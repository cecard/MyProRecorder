import tkinter as tk
from tkinter import messagebox, Toplevel, Canvas
import threading
import time
import sys
import os
import wave
import ctypes
import subprocess
import numpy as np
import cv2
import mss
import pyaudiowpatch as pyaudio
from PIL import Image, ImageDraw, ImageTk
import pystray
from pystray import MenuItem as item

# --- 系统设置 ---
myappid = 'mycompany.recorder.av.v1'
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception: pass
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception: pass

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class AudioRecorder(threading.Thread):
    """ 独立的音频录制线程 """
    def __init__(self, filename):
        super().__init__()
        self.filename = filename
        self.recording = False
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.error = None

    def run(self):
        self.recording = True
        try:
            # 寻找 Loopback 设备 (系统内录)
            wasapi = self.p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = self.p.get_device_info_by_index(wasapi["defaultOutputDevice"])
            
            target_device = default_speakers
            if not default_speakers["isLoopbackDevice"]:
                for loopback in self.p.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]:
                        target_device = loopback
                        break
            
            channels = int(target_device["maxInputChannels"])
            rate = int(target_device["defaultSampleRate"])
            
            # 打开 WAV 文件
            wf = wave.open(self.filename, 'wb')
            wf.setnchannels(channels)
            wf.setsampwidth(self.p.get_sample_size(pyaudio.paInt16))
            wf.setframerate(rate)
            
            def callback(in_data, frame_count, time_info, status):
                wf.writeframes(in_data)
                return (in_data, pyaudio.paContinue)
            
            self.stream = self.p.open(format=pyaudio.paInt16,
                                      channels=channels,
                                      rate=rate,
                                      frames_per_buffer=1024,
                                      input=True,
                                      input_device_index=target_device["index"],
                                      stream_callback=callback)
            
            self.stream.start_stream()
            
            # 等待停止信号
            while self.recording:
                time.sleep(0.1)
                
            self.stream.stop_stream()
            self.stream.close()
            wf.close()
            
        except Exception as e:
            self.error = str(e)
            print(f"Audio Error: {e}")
        finally:
            self.p.terminate()

    def stop(self):
        self.recording = False

class ProfessionalRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("Recorder (AV Mux Mode)")
        self.root.configure(bg="#1e1e1e")
        self.root.overrideredirect(True)

        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        w, h = 540, 480
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        
        self.is_recording = False
        self.is_mini_mode = False
        self.start_time = 0
        self.region = None
        
        # 路径管理
        self.ffmpeg_path = resource_path("ffmpeg.exe")
        self.temp_video = ""
        self.temp_audio = ""
        self.final_output = ""
        
        self.audio_thread = None
        
        self.record_cursor_var = tk.BooleanVar(value=True)
        self.border_windows = []
        self._drag_data = {"x": 0, "y": 0, "mode": None}
        self.resize_margin = 10

        # 图标
        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            self.icon_img = Image.open(icon_path)
            self.root.iconbitmap(icon_path)
        else:
            self.icon_img = self.create_internal_icon(64, (234, 51, 35))
        self.tk_icon = ImageTk.PhotoImage(self.icon_img)
        self.root.iconphoto(True, self.tk_icon)
        self.rec_icon_img = self.create_internal_icon(64, (255, 0, 0))

        self.setup_ui()
        self.setup_tray()

        self.root.bind("<Motion>", self.check_cursor)
        self.root.bind("<ButtonPress-1>", self.start_action)
        self.root.bind("<ButtonRelease-1>", self.stop_action)
        self.root.bind("<B1-Motion>", self.do_action)

    def create_internal_icon(self, size, color):
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((2, 2, size-2, size-2), fill=(255, 255, 255))
        c = size / 2
        draw.ellipse((c-size*0.3, c-size*0.3, c+size*0.3, c+size*0.3), fill=color)
        return image

    # --- 窗口操作 (省略重复代码，保持功能一致) ---
    def check_cursor(self, event):
        if self.is_mini_mode: return
        x, y, w, h = event.x, event.y, self.root.winfo_width(), self.root.winfo_height()
        m = self.resize_margin
        cursor, mode = "", None
        if x < m and y < m: cursor, mode = "sb_h_double_arrow", "nw"
        elif x > w-m and y > h-m: cursor, mode = "sb_h_double_arrow", "se"
        elif x < m: cursor, mode = "sb_h_double_arrow", "w"
        elif x > w-m: cursor, mode = "sb_h_double_arrow", "e"
        elif y < m: cursor, mode = "sb_v_double_arrow", "n"
        elif y > h-m: cursor, mode = "sb_v_double_arrow", "s"
        else: cursor, mode = "arrow", None
        if self.root.cget("cursor") != cursor: self.root.config(cursor=cursor)
        self._drag_data["hover_mode"] = mode

    def start_action(self, event):
        self._drag_data["start_x"] = event.x_root
        self._drag_data["start_y"] = event.y_root
        self._drag_data["win_x"] = self.root.winfo_x()
        self._drag_data["win_y"] = self.root.winfo_y()
        self._drag_data["start_w"] = self.root.winfo_width()
        self._drag_data["start_h"] = self.root.winfo_height()
        if self.is_mini_mode or event.y < 40: self._drag_data["mode"] = "move"
        else: self._drag_data["mode"] = self._drag_data.get("hover_mode")

    def stop_action(self, event):
        self._drag_data["mode"] = None
        self.root.config(cursor="arrow")

    def do_action(self, event):
        mode = self._drag_data.get("mode")
        if not mode: return
        dx = event.x_root - self._drag_data["start_x"]
        dy = event.y_root - self._drag_data["start_y"]
        if mode == "move":
            self.root.geometry(f"+{self._drag_data['win_x'] + dx}+{self._drag_data['win_y'] + dy}")
        else:
            w = max(400, self._drag_data["start_w"] + (dx if "e" in mode else -dx if "w" in mode else 0))
            h = max(300, self._drag_data["start_h"] + (dy if "s" in mode else -dy if "n" in mode else 0))
            self.root.geometry(f"{w}x{h}+{self._drag_data['win_x']}+{self._drag_data['win_y']}")

    def toggle_mini_mode(self):
        if not self.is_mini_mode:
            self.is_mini_mode = True
            self.last_geometry = self.root.geometry()
            self.normal_frame.pack_forget()
            self.mini_frame.pack(fill=tk.BOTH, expand=True)
            self.root.geometry(f"420x50+50+{self.root.winfo_screenheight()-150}")
            self.root.attributes('-topmost', True)
        else:
            self.is_mini_mode = False
            self.mini_frame.pack_forget()
            self.normal_frame.pack(fill=tk.BOTH, expand=True)
            self.root.geometry(self.last_geometry)
            self.root.attributes('-topmost', False)

    def update_timer(self):
        if self.is_recording:
            elapsed = int(time.time() - self.start_time)
            h, r = divmod(elapsed, 3600)
            m, s = divmod(r, 60)
            time_str = f"{h:02}:{m:02}:{s:02}"
            try:
                self.lbl_main_timer.config(text=time_str, fg="#d32f2f")
                self.lbl_mini_timer.config(text=f"REC {time_str}", fg="#d32f2f")
            except: pass
            self.root.after(1000, self.update_timer)

    def select_area(self):
        self.clear_borders()
        top = Toplevel(self.root)
        top.attributes('-fullscreen', True)
        top.attributes('-topmost', True)
        top.attributes('-alpha', 0.3)
        top.config(bg='white', cursor='cross')
        canvas = Canvas(top, bg="white", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        self.sel_start = [0, 0]
        def on_down(e): self.sel_start = [e.x, e.y]
        def on_drag(e):
            canvas.delete("rect"); canvas.delete("txt")
            canvas.create_rectangle(self.sel_start[0], self.sel_start[1], e.x, e.y, outline="red", width=3, tags="rect")
            canvas.create_text(e.x+20, e.y+20, text=f"{abs(e.x-self.sel_start[0])}x{abs(e.y-self.sel_start[1])}", fill="red", font=("Arial", 14), tags="txt")
        def on_up(e):
            x1, y1 = min(self.sel_start[0], e.x), min(self.sel_start[1], e.y)
            w, h = abs(self.sel_start[0]-e.x), abs(self.sel_start[1]-e.y)
            if w % 2 != 0: w -= 1
            if h % 2 != 0: h -= 1
            if w > 50 and h > 50:
                self.region = {'top': y1, 'left': x1, 'width': w, 'height': h}
                self.lbl_info.config(text=f"Region: {w}x{h} (Ready)")
                self.draw_permanent_border(x1, y1, w, h)
            top.destroy()
            self.root.deiconify()
        canvas.bind("<Button-1>", on_down); canvas.bind("<B1-Motion>", on_drag); canvas.bind("<ButtonRelease-1>", on_up)
        top.bind("<Escape>", lambda e: top.destroy())

    def clear_borders(self):
        for win in self.border_windows: win.destroy()
        self.border_windows = []
    
    def draw_permanent_border(self, x, y, w, h):
        self.clear_borders()
        for g in [(x, y, w, 3), (x, y+h-3, w, 3), (x, y, 3, h), (x+w-3, y, 3, h)]:
            tw = Toplevel(self.root); tw.overrideredirect(True); tw.attributes('-topmost', True); tw.config(bg="red")
            tw.geometry(f"{g[2]}x{g[3]}+{g[0]}+{g[1]}")
            self.border_windows.append(tw)

    # --- 录制核心 (音画分离 + 自动合并) ---
    def start_recording(self):
        self.btn_start.config(state=tk.DISABLED, text="Init...")
        self.btn_stop.config(state=tk.DISABLED)
        
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.exists(desktop): desktop = os.path.expanduser("~")
        
        ts = int(time.time())
        # 1. 临时文件
        self.temp_video = os.path.join(desktop, f"temp_v_{ts}.mp4")
        self.temp_audio = os.path.join(desktop, f"temp_a_{ts}.wav")
        self.final_output = os.path.join(desktop, f"Rec_{ts}.mp4")
        
        threading.Thread(target=self._recording_controller, daemon=True).start()

    def _recording_controller(self):
        self.is_recording = True
        self.start_time = time.time()
        
        # 更新 UI
        self.root.after(0, lambda: self.btn_start.config(text="▶ Recording", bg="#555"))
        self.root.after(0, lambda: self.btn_stop.config(state=tk.NORMAL))
        self.root.after(0, lambda: self.btn_mini_start.config(state=tk.DISABLED))
        self.root.after(0, lambda: self.btn_mini_stop.config(state=tk.NORMAL))
        self.root.after(0, self.update_timer)
        if self.tray_icon: self.tray_icon.icon = self.rec_icon_img

        # 1. 启动音频线程
        self.audio_thread = AudioRecorder(self.temp_audio)
        self.audio_thread.start()
        
        # 2. 启动视频录制 (主线程阻塞)
        self._record_video_loop()

    def _record_video_loop(self):
        try:
            with mss.mss() as sct:
                if self.region:
                    monitor = self.region
                else:
                    monitor = sct.monitors[1]
                
                width = monitor['width']
                height = monitor['height']

                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                fps = 20.0
                out = cv2.VideoWriter(self.temp_video, fourcc, fps, (width, height))

                while self.is_recording:
                    loop_start = time.time()
                    
                    img = sct.grab(monitor)
                    frame = np.array(img)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    
                    # 绘制光标 (可选)
                    # 如果你需要录制光标，这里需要额外代码获取光标位置并画圆
                    # 暂时保持纯净画面
                    
                    out.write(frame)

                    elapsed = time.time() - loop_start
                    wait_time = (1.0 / fps) - elapsed
                    if wait_time > 0:
                        time.sleep(wait_time)
                
                out.release()
                
                # 停止音频
                if self.audio_thread:
                    self.audio_thread.stop()
                    self.audio_thread.join()
                
                self.root.after(0, self._start_merge)

        except Exception as e:
            print(f"Video Error: {e}")
            self.is_recording = False
            if self.audio_thread: self.audio_thread.stop()
            self.root.after(0, self._reset_ui)

    def stop_recording(self):
        self.btn_stop.config(text="Merging...", state=tk.DISABLED)
        self.is_recording = False

    def _start_merge(self):
        # 合并音视频
        threading.Thread(target=self._merge_worker, daemon=True).start()

    def _merge_worker(self):
        # 如果音频录制失败，直接重命名视频文件
        if not os.path.exists(self.temp_audio) or os.path.getsize(self.temp_audio) < 100:
            if os.path.exists(self.temp_video):
                os.rename(self.temp_video, self.final_output)
                self.root.after(0, lambda: messagebox.showinfo("Done", "Saved Video Only (Audio failed or silent)."))
        else:
            # 使用 FFmpeg 合并
            # -i video -i audio -c:v copy (视频不重编码，秒级完成) -c:a aac (音频转aac)
            cmd = [
                self.ffmpeg_path, '-y',
                '-i', self.temp_video,
                '-i', self.temp_audio,
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-shortest', # 以最短的流为准
                self.final_output
            ]
            
            # 隐藏黑框
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            try:
                subprocess.run(cmd, startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                # 清理临时文件
                try: os.remove(self.temp_video)
                except: pass
                try: os.remove(self.temp_audio)
                except: pass
                
                self.root.after(0, lambda: messagebox.showinfo("Success", "Video & Audio Saved!"))
                
            except Exception as e:
                 self.root.after(0, lambda: messagebox.showerror("Merge Failed", f"Could not merge:\n{e}\nTemp files kept on desktop."))

        self.root.after(0, self._finish_all)

    def _finish_all(self):
        if self.tray_icon: self.tray_icon.icon = self.icon_img
        self._reset_ui()
        if os.path.exists(self.final_output):
            try: subprocess.run(f'explorer /select,"{self.final_output}"')
            except: pass

    def _reset_ui(self):
        self.btn_start.config(text="▶ Start", state=tk.NORMAL, bg="#1976d2")
        self.btn_stop.config(text="⬛ Stop", state=tk.DISABLED)
        self.btn_mini_start.config(state=tk.NORMAL, bg="#1976d2")
        self.btn_mini_stop.config(state=tk.DISABLED)
        self.lbl_main_timer.config(text="00:00:00", fg="#555")
        self.lbl_mini_timer.config(text="00:00:00", fg="#bbb")

    # --- UI Setup (保持不变) ---
    def setup_ui(self):
        self.bg_color = "#1e1e1e"
        self.title_bg = "#2d2d2d"
        self.normal_frame = tk.Frame(self.root, bg=self.bg_color)
        self.normal_frame.pack(fill=tk.BOTH, expand=True)
        self.mini_frame = tk.Frame(self.root, bg="#333", highlightthickness=1, highlightbackground="#555")
        self.build_normal_ui()
        self.build_mini_ui()

    def build_mini_ui(self):
        p = self.mini_frame
        btn_s = {"bd": 0, "width": 4, "font": ("Arial", 10)}
        tk.Button(p, text="⤢", bg="#444", fg="white", command=self.toggle_mini_mode, **btn_s).pack(side=tk.LEFT, fill=tk.Y, padx=1)
        tk.Button(p, text="⛶", bg="#333", fg="white", command=self.select_area, **btn_s).pack(side=tk.LEFT, fill=tk.Y, padx=1)
        self.btn_mini_cur = tk.Button(p, text="🖱️", bg="#333", fg="#0f0", command=self.toggle_cursor_mini, **btn_s)
        self.btn_mini_cur.pack(side=tk.LEFT, fill=tk.Y, padx=1)
        self.lbl_mini_timer = tk.Label(p, text="00:00:00", bg="#333", fg="#bbb", font=("Consolas", 10))
        self.lbl_mini_timer.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        self.btn_mini_stop = tk.Button(p, text="⬛", bg="#d32f2f", fg="white", command=self.stop_recording, state=tk.DISABLED, **btn_s)
        self.btn_mini_stop.pack(side=tk.RIGHT, fill=tk.Y, padx=1)
        self.btn_mini_start = tk.Button(p, text="▶", bg="#1976d2", fg="white", command=self.start_recording, **btn_s)
        self.btn_mini_start.pack(side=tk.RIGHT, fill=tk.Y, padx=1)

    def toggle_cursor_mini(self):
        v = self.record_cursor_var.get()
        self.record_cursor_var.set(not v)
        self.btn_mini_cur.config(fg="#0f0" if not v else "#555")

    def build_normal_ui(self):
        p = self.normal_frame
        t_bar = tk.Frame(p, bg=self.title_bg, height=40)
        t_bar.pack(side=tk.TOP, fill=tk.X)
        t_bar.pack_propagate(False)
        t_bar.bind("<ButtonPress-1>", self.start_action)
        
        lbl = tk.Label(t_bar, image=self.tk_icon, bg=self.title_bg, bd=0)
        lbl.pack(side=tk.LEFT, padx=10)
        tk.Label(t_bar, text="Pro Recorder", bg=self.title_bg, fg="#eee", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        
        btn_s = {"bd": 0, "width": 4, "font": ("Arial", 11)}
        tk.Button(t_bar, text="✕", bg=self.title_bg, fg="#aaa", activebackground="red", command=self.kill_app, **btn_s).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Button(t_bar, text="⤢", bg=self.title_bg, fg="#aaa", command=self.toggle_mini_mode, **btn_s).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Button(t_bar, text="─", bg=self.title_bg, fg="#aaa", command=self.minimize_to_tray, **btn_s).pack(side=tk.RIGHT, fill=tk.Y)
        
        c_frame = tk.Frame(p, bg=self.bg_color)
        c_frame.pack(fill=tk.BOTH, expand=True)
        self.lbl_main_timer = tk.Label(c_frame, text="00:00:00", font=("Segoe UI", 36), bg=self.bg_color, fg="#555")
        self.lbl_main_timer.place(relx=0.5, rely=0.4, anchor=tk.CENTER)
        self.lbl_info = tk.Label(c_frame, text="Ready", font=("Segoe UI", 10), bg=self.bg_color, fg="#777")
        self.lbl_info.place(relx=0.5, rely=0.55, anchor=tk.CENTER)
        
        b_frame = tk.Frame(c_frame, bg=self.bg_color, height=90)
        b_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=20)
        row = tk.Frame(b_frame, bg=self.bg_color)
        row.pack(anchor=tk.CENTER)
        
        tk.Button(row, text="⛶ Area", command=self.select_area, bg="#333", fg="white", bd=0, padx=15, pady=8).pack(side=tk.LEFT, padx=5)
        self.btn_start = tk.Button(row, text="▶ Start", command=self.start_recording, bg="#1976d2", fg="white", bd=0, padx=20, pady=8)
        self.btn_start.pack(side=tk.LEFT, padx=5)
        self.btn_stop = tk.Button(row, text="⬛ Stop", command=self.stop_recording, bg="#d32f2f", fg="white", bd=0, padx=20, pady=8, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=5)
        tk.Checkbutton(row, text="Cursor", variable=self.record_cursor_var, bg=self.bg_color, fg="#ddd", selectcolor="#333", activebackground=self.bg_color, font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=10)
        
        tk.Frame(p, bg="#444", width=1).pack(side=tk.LEFT, fill=tk.Y)
        tk.Frame(p, bg="#444", width=1).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Frame(p, bg="#444", height=1).pack(side=tk.BOTTOM, fill=tk.X)

    def setup_tray(self):
        def show_window(icon, item):
            self.root.deiconify()
            self.root.lift()
        def quit_app(icon, item):
            self.root.after(0, self.kill_app)
        menu = (item('Show', show_window, default=True), item('Exit', quit_app))
        self.tray_icon = pystray.Icon("Recorder", self.icon_img, "Pro Recorder", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def minimize_to_tray(self):
        self.root.withdraw()

    def kill_app(self):
        self.is_recording = False
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()
        sys.exit(0)

if __name__ == "__main__":
    root = tk.Tk()
    app = ProfessionalRecorder(root)
    root.mainloop()
