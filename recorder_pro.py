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
myappid = 'mycompany.recorder.final.cursorfix'
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception: pass
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception: pass

# 定义鼠标坐标结构体 (用于获取全局鼠标位置)
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class AudioRecorder(threading.Thread):
    def __init__(self, filename):
        super().__init__()
        self.filename = filename
        self.recording = False
        self.p = pyaudio.PyAudio()
        self.stream = None

    def run(self):
        self.recording = True
        try:
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
            while self.recording:
                time.sleep(0.1)
                
            self.stream.stop_stream()
            self.stream.close()
            wf.close()
        except Exception as e:
            print(f"Audio Error: {e}")
        finally:
            self.p.terminate()

    def stop(self):
        self.recording = False

class ProfessionalRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("Pro Recorder")
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
        
        self.ffmpeg_path = resource_path("ffmpeg.exe")
        self.temp_video = ""
        self.temp_audio = ""
        self.final_output = ""
        self.audio_thread = None
        self.is_screenshot_mode = False

        self.record_cursor_var = tk.BooleanVar(value=True) # 默认开启录制鼠标
        self.border_visible = True
        self.border_windows = []
        self._drag_data = {"x": 0, "y": 0, "mode": None}
        self.resize_margin = 10

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
        draw.ellipse((c-size*0.35, c-size*0.35, c+size*0.35, c+size*0.35), fill=color)
        return image

    def get_output_folder(self):
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        folder = os.path.join(desktop, "ProRecorder_Files")
        if not os.path.exists(folder):
            os.makedirs(folder)
        return folder

    def get_timestamp_filename(self, ext):
        folder = self.get_output_folder()
        ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        return os.path.join(folder, f"{ts}.{ext}")

    # --- 截屏 ---
    def screenshot_full(self):
        try:
            filename = self.get_timestamp_filename("png")
            with mss.mss() as sct:
                sct.shot(mon=-1, output=filename)
            self.flash_feedback("Snapshot Saved!")
            subprocess.run(f'explorer /select,"{filename}"')
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def screenshot_area_mode(self):
        self.is_screenshot_mode = True
        self.select_area()

    def perform_area_screenshot(self, region):
        try:
            filename = self.get_timestamp_filename("png")
            with mss.mss() as sct:
                img = sct.grab(region)
                mss.tools.to_png(img.rgb, img.size, output=filename)
            self.flash_feedback("Area Captured!")
            subprocess.run(f'explorer /select,"{filename}"')
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            self.is_screenshot_mode = False

    def flash_feedback(self, text):
        try:
            original_text = self.lbl_info.cget("text")
            self.lbl_info.config(text=text, fg="#0f0")
            self.root.after(2000, lambda: self.lbl_info.config(text=original_text, fg="#777"))
        except: pass

    # --- 选区 ---
    def select_area(self):
        self.clear_borders()
        self.root.withdraw()
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
            canvas.create_rectangle(self.sel_start[0], self.sel_start[1], e.x, e.y, outline="red", width=2, tags="rect")
            w, h = abs(e.x - self.sel_start[0]), abs(e.y - self.sel_start[1])
            canvas.create_text(e.x+30, e.y+20, text=f"{w}x{h}", fill="red", font=("Arial", 12, "bold"), tags="txt")
        def on_up(e):
            x1, y1 = min(self.sel_start[0], e.x), min(self.sel_start[1], e.y)
            w, h = abs(self.sel_start[0]-e.x), abs(self.sel_start[1]-e.y)
            top.destroy()
            self.root.deiconify()
            if w < 10 or h < 10: return
            region = {'top': y1, 'left': x1, 'width': w, 'height': h}
            if self.is_screenshot_mode:
                self.perform_area_screenshot(region)
            else:
                if w % 2 != 0: w -= 1
                if h % 2 != 0: h -= 1
                region['width'] = w; region['height'] = h
                self.region = region
                self.lbl_info.config(text=f"Region: {w}x{h} (Ready)")
                if self.border_visible: self.draw_permanent_border(x1, y1, w, h)

        canvas.bind("<Button-1>", on_down)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_up)
        def cancel(e):
            top.destroy()
            self.root.deiconify()
            self.is_screenshot_mode = False
        top.bind("<Button-3>", cancel); top.bind("<Escape>", cancel)

    # --- 红框 ---
    def clear_borders(self):
        for win in self.border_windows: 
            try: win.destroy()
            except: pass
        self.border_windows = []
    
    def toggle_border(self):
        self.border_visible = not self.border_visible
        color = "#0f0" if self.border_visible else "#555"
        try:
            self.btn_border_mini.config(fg=color)
            self.btn_border_normal.config(fg=color)
        except: pass
        if self.border_visible and self.region:
            r = self.region
            self.draw_permanent_border(r['left'], r['top'], r['width'], r['height'])
        else:
            self.clear_borders()

    def draw_permanent_border(self, x, y, w, h):
        self.clear_borders()
        if not self.border_visible: return
        thickness = 3; color = "red"
        geoms = [
            (x - thickness, y - thickness, w + 2*thickness, thickness),
            (x - thickness, y + h, w + 2*thickness, thickness),
            (x - thickness, y, thickness, h),
            (x + w, y, thickness, h)
        ]
        for gx, gy, gw, gh in geoms:
            tw = Toplevel(self.root)
            tw.overrideredirect(True)
            tw.attributes('-topmost', True)
            try: tw.attributes('-alpha', 0.8)
            except: pass
            tw.config(bg=color)
            tw.geometry(f"{gw}x{gh}+{gx}+{gy}")
            self.border_windows.append(tw)

    # --- 录制逻辑 (含鼠标绘制) ---
    def start_recording(self):
        self.btn_start.config(state=tk.DISABLED, text="Init...")
        self.btn_stop.config(state=tk.DISABLED)
        
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        ts = int(time.time())
        self.temp_video = os.path.join(desktop, f"temp_v_{ts}.mp4")
        self.temp_audio = os.path.join(desktop, f"temp_a_{ts}.wav")
        self.final_output = self.get_timestamp_filename("mp4")
        
        threading.Thread(target=self._recording_controller, daemon=True).start()

    def _recording_controller(self):
        self.is_recording = True
        self.start_time = time.time()
        
        self.root.after(0, lambda: self.btn_start.config(text="▶ Recording", bg="#555"))
        self.root.after(0, lambda: self.btn_stop.config(state=tk.NORMAL))
        self.root.after(0, lambda: self.btn_mini_start.config(state=tk.DISABLED))
        self.root.after(0, lambda: self.btn_mini_stop.config(state=tk.NORMAL))
        self.root.after(0, self.update_timer)
        if self.tray_icon: self.tray_icon.icon = self.rec_icon_img

        self.audio_thread = AudioRecorder(self.temp_audio)
        self.audio_thread.start()
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
                top_offset = monitor['top']
                left_offset = monitor['left']

                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                fps = 20.0
                out = cv2.VideoWriter(self.temp_video, fourcc, fps, (width, height))
                
                # 预先定义鼠标点结构
                pt = POINT()

                while self.is_recording:
                    loop_start = time.time()
                    
                    # 1. 抓图
                    img = sct.grab(monitor)
                    frame = np.array(img)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    
                    # 2. 绘制鼠标 (如果开启)
                    if self.record_cursor_var.get():
                        # 获取全局鼠标位置
                        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                        # 转换为相对录制区域的坐标
                        mx = pt.x - left_offset
                        my = pt.y - top_offset
                        
                        # 如果鼠标在画面内，画一个小圆点
                        if 0 <= mx < width and 0 <= my < height:
                            # 白色圆心，黑色描边，保证在任何背景下可见
                            cv2.circle(frame, (mx, my), 5, (255, 255, 255), -1) 
                            cv2.circle(frame, (mx, my), 5, (0, 0, 0), 1)

                    out.write(frame)

                    elapsed = time.time() - loop_start
                    wait_time = (1.0 / fps) - elapsed
                    if wait_time > 0:
                        time.sleep(wait_time)
                
                out.release()
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
        threading.Thread(target=self._merge_worker, daemon=True).start()

    def _merge_worker(self):
        if not os.path.exists(self.temp_audio) or os.path.getsize(self.temp_audio) < 100:
            if os.path.exists(self.temp_video):
                os.rename(self.temp_video, self.final_output)
                self.root.after(0, lambda: messagebox.showinfo("Done", "Saved Video (No Audio)."))
        else:
            cmd = [
                self.ffmpeg_path, '-y',
                '-i', self.temp_video, '-i', self.temp_audio,
                '-c:v', 'copy', '-c:a', 'aac', '-shortest',
                self.final_output
            ]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            try:
                subprocess.run(cmd, startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try: os.remove(self.temp_video); os.remove(self.temp_audio)
                except: pass
                self.root.after(0, lambda: messagebox.showinfo("Success", "Video & Audio Saved!"))
            except Exception as e:
                 self.root.after(0, lambda: messagebox.showerror("Merge Failed", f"{e}"))
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

    # --- UI Setup ---
    def setup_ui(self):
        self.bg_color = "#1e1e1e"
        self.title_bg = "#2d2d2d"
        self.normal_frame = tk.Frame(self.root, bg=self.bg_color)
        self.normal_frame.pack(fill=tk.BOTH, expand=True)
        self.mini_frame = tk.Frame(self.root, bg="#333", highlightthickness=1, highlightbackground="#555")
        self.build_normal_ui()
        self.build_mini_ui()

    # 窗口拖拽 (重复代码省略，保持不变)
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

    def build_mini_ui(self):
        p = self.mini_frame
        btn_s = {"bd": 0, "width": 4, "font": ("Arial", 10)}
        tk.Button(p, text="⤢", bg="#444", fg="white", command=self.toggle_mini_mode, **btn_s).pack(side=tk.LEFT, fill=tk.Y, padx=1)
        tk.Button(p, text="📷", bg="#333", fg="cyan", command=self.screenshot_area_mode, **btn_s).pack(side=tk.LEFT, fill=tk.Y, padx=1)
        tk.Button(p, text="⛶", bg="#333", fg="white", command=self.select_area, **btn_s).pack(side=tk.LEFT, fill=tk.Y, padx=1)
        self.btn_border_mini = tk.Button(p, text="🔲", bg="#333", fg="#0f0", command=self.toggle_border, **btn_s)
        self.btn_border_mini.pack(side=tk.LEFT, fill=tk.Y, padx=1)
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
        tk.Button(row, text="📷 Full", command=self.screenshot_full, bg="#333", fg="cyan", bd=0, padx=10, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(row, text="📷 Area", command=self.screenshot_area_mode, bg="#333", fg="cyan", bd=0, padx=10, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Frame(row, width=15, bg=self.bg_color).pack(side=tk.LEFT)
        tk.Button(row, text="⛶ Rec Area", command=self.select_area, bg="#333", fg="white", bd=0, padx=10, pady=8).pack(side=tk.LEFT, padx=5)
        self.btn_start = tk.Button(row, text="▶ Start", command=self.start_recording, bg="#1976d2", fg="white", bd=0, padx=20, pady=8)
        self.btn_start.pack(side=tk.LEFT, padx=5)
        self.btn_stop = tk.Button(row, text="⬛ Stop", command=self.stop_recording, bg="#d32f2f", fg="white", bd=0, padx=20, pady=8, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=5)
        self.btn_border_normal = tk.Button(row, text="🔲 Border", command=self.toggle_border, bg=self.bg_color, fg="#0f0", bd=0, font=("Segoe UI", 9))
        self.btn_border_normal.pack(side=tk.LEFT, padx=10)
        
        # 【关键修复】把 Cursor 复选框加回来了
        tk.Checkbutton(row, text="Cursor", variable=self.record_cursor_var, bg=self.bg_color, fg="#ddd", selectcolor="#333", activebackground=self.bg_color, font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=5)
        
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
