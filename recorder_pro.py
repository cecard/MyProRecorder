import tkinter as tk
from tkinter import messagebox, Toplevel, Canvas
import subprocess
import threading
import time
import sys
import os
import ctypes
from PIL import Image, ImageDraw, ImageTk
import pystray
from pystray import MenuItem as item
import pyaudiowpatch as pyaudio
from screeninfo import get_monitors

# --- 1. 高清屏适配 ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def create_internal_icon(size=64):
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((2, 2, size-2, size-2), fill=(255, 255, 255), outline=(200, 200, 200))
    c = size / 2
    draw.ellipse((c-size*0.3, c-size*0.3, c+size*0.3, c+size*0.3), fill=(234, 51, 35))
    return image

class ProfessionalRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("Pro Recorder")
        self.root.configure(bg="#1e1e1e")
        self.root.overrideredirect(True)
        
        # 居中
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        w, h = 540, 480
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.last_geometry = f"{w}x{h}+{x}+{y}"
        
        # 变量
        self.is_recording = False
        self.is_mini_mode = False
        self.start_time = 0 # 录制开始时间
        self.process = None
        self.audio_thread = None
        self.region = None 
        self.ffmpeg_path = resource_path("ffmpeg.exe")
        self.tray_icon = None
        self.record_cursor_var = tk.BooleanVar(value=True)
        
        # 拖拽
        self._drag_data = {"x": 0, "y": 0, "mode": None}
        self.resize_margin = 10 
        
        # 图标
        self.icon_img = create_internal_icon(64)
        self.rec_icon_img = create_internal_icon(64)
        self.tk_icon = ImageTk.PhotoImage(self.icon_img)
        self.root.iconphoto(True, self.tk_icon)

        self.setup_ui() 
        self.setup_tray()
        
        # 绑定
        self.root.bind("<Motion>", self.check_cursor)
        self.root.bind("<ButtonPress-1>", self.start_action)
        self.root.bind("<ButtonRelease-1>", self.stop_action)
        self.root.bind("<B1-Motion>", self.do_action)
        
        if not os.path.exists(self.ffmpeg_path):
            messagebox.showerror("Error", f"Kernel missing: {self.ffmpeg_path}")

    # ==========================
    # 物理引擎 (拖拽/拉伸)
    # ==========================
    def check_cursor(self, event):
        if self.is_mini_mode: return
        x, y = event.x, event.y
        w, h = self.root.winfo_width(), self.root.winfo_height()
        m = self.resize_margin
        cursor, mode = "", None

        if x < m and y < m: cursor, mode = "sb_h_double_arrow", "nw"
        elif x > w - m and y < m: cursor, mode = "sb_h_double_arrow", "ne"
        elif x < m and y > h - m: cursor, mode = "sb_h_double_arrow", "sw"
        elif x > w - m and y > h - m: cursor, mode = "sb_h_double_arrow", "se"
        elif y < m: cursor, mode = "sb_v_double_arrow", "n"
        elif y > h - m: cursor, mode = "sb_v_double_arrow", "s"
        elif x < m: cursor, mode = "sb_h_double_arrow", "w"
        elif x > w - m: cursor, mode = "sb_h_double_arrow", "e"
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

        if self.is_mini_mode: 
            self._drag_data["mode"] = "move"
            return
        mode = self._drag_data.get("hover_mode")
        if mode: self._drag_data["mode"] = mode
        elif event.y < 40: self._drag_data["mode"] = "move"

    def stop_action(self, event):
        self._drag_data["mode"] = None
        self.root.config(cursor="arrow")

    def do_action(self, event):
        mode = self._drag_data.get("mode")
        if not mode: return
        dx = event.x_root - self._drag_data["start_x"]
        dy = event.y_root - self._drag_data["start_y"]

        if mode == "move":
            x = self._drag_data["win_x"] + dx
            y = self._drag_data["win_y"] + dy
            self.root.geometry(f"+{x}+{y}")
        else:
            x, y = self._drag_data["win_x"], self._drag_data["win_y"]
            w, h = self._drag_data["start_w"], self._drag_data["start_h"]
            if "n" in mode: y += dy; h -= dy
            if "s" in mode: h += dy
            if "w" in mode: x += dx; w -= dx
            if "e" in mode: w += dx
            w, h = max(400, w), max(300, h)
            self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ==========================
    # 模式切换
    # ==========================
    def toggle_mini_mode(self):
        if not self.is_mini_mode:
            self.is_mini_mode = True
            self.last_geometry = self.root.geometry()
            screen_h = self.root.winfo_screenheight()
            target_y = screen_h - 150 
            target_x = 50
            self.normal_frame.pack_forget()
            self.mini_frame.pack(fill=tk.BOTH, expand=True)
            self.root.geometry(f"420x50+{target_x}+{target_y}")
            self.root.attributes('-topmost', True)
        else:
            self.is_mini_mode = False
            self.mini_frame.pack_forget()
            self.normal_frame.pack(fill=tk.BOTH, expand=True)
            try: self.root.geometry(self.last_geometry)
            except: self.root.geometry("540x480+300+300")
            self.root.attributes('-topmost', False)

    # ==========================
    # UI 构建
    # ==========================
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
        
        # 计时器/拖动区 (Mini)
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
        # 标题栏
        t_bar = tk.Frame(p, bg=self.title_bg, height=40)
        t_bar.pack(side=tk.TOP, fill=tk.X)
        t_bar.pack_propagate(False)
        t_bar.bind("<ButtonPress-1>", self.start_action) # 确保可拖动
        
        lbl = tk.Label(t_bar, image=self.tk_icon, bg=self.title_bg, bd=0)
        lbl.pack(side=tk.LEFT, padx=10)
        tk.Label(t_bar, text="Pro Recorder", bg=self.title_bg, fg="#eee", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        
        btn_s = {"bd": 0, "width": 4, "font": ("Arial", 11)}
        tk.Button(t_bar, text="✕", bg=self.title_bg, fg="#aaa", activebackground="red", command=self.kill_app, **btn_s).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Button(t_bar, text="⤢", bg=self.title_bg, fg="#aaa", command=self.toggle_mini_mode, **btn_s).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Button(t_bar, text="─", bg=self.title_bg, fg="#aaa", command=self.minimize_to_tray, **btn_s).pack(side=tk.RIGHT, fill=tk.Y)

        # 内容区
        c_frame = tk.Frame(p, bg=self.bg_color)
        c_frame.pack(fill=tk.BOTH, expand=True)
        
        # 计时器 (Normal)
        self.lbl_main_timer = tk.Label(c_frame, text="00:00:00", font=("Segoe UI", 36), bg=self.bg_color, fg="#555")
        self.lbl_main_timer.place(relx=0.5, rely=0.4, anchor=tk.CENTER)
        self.lbl_info = tk.Label(c_frame, text="Ready", font=("Segoe UI", 10), bg=self.bg_color, fg="#777")
        self.lbl_info.place(relx=0.5, rely=0.55, anchor=tk.CENTER)

        # 底部栏
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

    # ==========================
    # 计时器逻辑
    # ==========================
    def update_timer(self):
        if self.is_recording:
            elapsed = int(time.time() - self.start_time)
            h = elapsed // 3600
            m = (elapsed % 3600) // 60
            s = elapsed % 60
            time_str = f"{h:02}:{m:02}:{s:02}"
            
            # 更新两个界面的时间
            self.lbl_main_timer.config(text=time_str, fg="#d32f2f") # 录制时变红
            self.lbl_mini_timer.config(text=f"REC {time_str}", fg="#d32f2f")
            
            self.root.after(1000, self.update_timer)

    # ==========================
    # 选区逻辑 (修复点击无效)
    # ==========================
    def select_area(self):
        # 不要最小化，否则用户可能觉得程序消失了
        # self.root.iconify() 
        
        top = Toplevel(self.root)
        top.attributes('-fullscreen', True)
        top.attributes('-topmost', True) # 强制置顶！
        top.attributes('-alpha', 0.4)    # 稍微不那么透明，更容易看见
        top.config(bg='white', cursor='cross') # 用白色背景，对比度更高
        
        canvas = Canvas(top, bg="white", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        
        self.sel_start = [0, 0]
        
        def on_down(e):
            self.sel_start = [e.x, e.y]

        def on_drag(e):
            canvas.delete("rect")
            # 画一个显眼的红框
            canvas.create_rectangle(self.sel_start[0], self.sel_start[1], e.x, e.y, outline="red", width=3, tags="rect")
            # 显示实时尺寸
            w, h = abs(e.x - self.sel_start[0]), abs(e.y - self.sel_start[1])
            canvas.delete("txt")
            canvas.create_text(e.x + 20, e.y + 20, text=f"{w}x{h}", fill="red", font=("Arial", 14, "bold"), tags="txt")

        def on_up(e):
            x1, y1 = min(self.sel_start[0], e.x), min(self.sel_start[1], e.y)
            w, h = abs(self.sel_start[0] - e.x), abs(self.sel_start[1] - e.y)
            
            # --- 核心修复：强制偶数分辨率 ---
            # FFmpeg x264 要求分辨率必须是 2 的倍数
            if w % 2 != 0: w -= 1
            if h % 2 != 0: h -= 1
            if x1 % 2 != 0: x1 -= 1 # 某些旧版ffmpeg对offset也有偶数要求
            if y1 % 2 != 0: y1 -= 1
            
            if w > 50 and h > 50:
                self.region = (x1, y1, w, h)
                self.lbl_info.config(text=f"Region: {w}x{h} (Ready)")
            
            top.destroy()
            self.root.deiconify() # 确保主界面回来

        canvas.bind("<Button-1>", on_down)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_up)
        # 右键或ESC取消
        top.bind("<Button-3>", lambda e: top.destroy()) 
        top.bind("<Escape>", lambda e: top.destroy())

    # ==========================
    # 音频设备 (带容错)
    # ==========================
    def get_default_loopback_device(self, p):
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            if not default_speakers["isLoopbackDevice"]:
                for loopback in p.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]: return loopback
            else: return default_speakers
        except Exception as e:
            print(f"Audio Error: {e}") # 打印错误但不崩溃
            return None

    def audio_pipe_worker(self, stream, ffmpeg_process):
        try:
            while self.is_recording: ffmpeg_process.stdin.write(stream.read(1024))
        except: pass

    # ==========================
    # 录制逻辑 (修复损坏文件)
    # ==========================
    def start_recording(self):
        self.is_recording = True
        self.start_time = time.time()
        self.update_timer() # 启动计时器
        
        # 按钮状态
        self.btn_start.config(state=tk.DISABLED, bg="#555")
        self.btn_stop.config(state=tk.NORMAL)
        self.btn_mini_start.config(state=tk.DISABLED, bg="#555")
        self.btn_mini_stop.config(state=tk.NORMAL)
        if self.tray_icon: self.tray_icon.icon = self.rec_icon_img
        
        filename = f"Capture_{int(time.time())}.mp4"
        
        # --- 音频容错处理 ---
        audio_args = []
        stream = None
        p = None
        try:
            p = pyaudio.PyAudio()
            loopback_dev = self.get_default_loopback_device(p)
            if loopback_dev:
                stream = p.open(format=pyaudio.paInt16, channels=loopback_dev["maxInputChannels"], 
                                rate=int(loopback_dev["defaultSampleRate"]), frames_per_buffer=1024, 
                                input=True, input_device_index=loopback_dev["index"])
                audio_args = ['-f', 's16le', '-ar', str(int(loopback_dev["defaultSampleRate"])), 
                              '-ac', str(loopback_dev["maxInputChannels"]), '-i', 'pipe:0']
            else:
                self.lbl_info.config(text="No Audio (Video Only)")
        except Exception:
            self.lbl_info.config(text="Audio Error (Video Only)")
            audio_args = [] # 确保即使音频失败，也重置为空，只录视频
        
        # 视频参数
        mouse_flag = '1' if self.record_cursor_var.get() else '0'
        video_args = ['-f', 'gdigrab', '-framerate', '30', '-draw_mouse', mouse_flag]
        
        if self.region:
            x, y, w, h = self.region
            video_args.extend(['-offset_x', str(x), '-offset_y', str(y), '-video_size', f"{w}x{h}"])
        video_args.extend(['-i', 'desktop'])
        
        # 组合命令
        cmd = [self.ffmpeg_path, '-y'] + audio_args + video_args + \
              ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p']
        
        if audio_args:
            cmd.extend(['-c:a', 'aac', '-b:a', '192k'])
        
        cmd.append(filename)
        
        # 启动
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        # 使用 stdin=subprocess.PIPE 仅当有音频时，否则给 DEVNULL 防止 ffmpeg 等待输入
        stdin_stream = subprocess.PIPE if audio_args else subprocess.DEVNULL
        
        self.process = subprocess.Popen(cmd, stdin=stdin_stream, stdout=subprocess.PIPE, 
                                        stderr=subprocess.PIPE, startupinfo=startupinfo, 
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        
        if stream:
            self.audio_thread = threading.Thread(target=self.audio_pipe_worker, args=(stream, self.process))
            self.audio_thread.start()

    def stop_recording(self):
        self.is_recording = False
        if self.tray_icon: self.tray_icon.icon = self.icon_img
        
        if self.process:
            try: 
                if self.process.stdin: self.process.stdin.close()
                self.process.wait(timeout=3)
            except: 
                self.process.kill()
        
        # 恢复界面
        self.btn_start.config(state=tk.NORMAL, bg="#1976d2")
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_mini_start.config(state=tk.NORMAL, bg="#1976d2")
        self.btn_mini_stop.config(state=tk.DISABLED)
        
        self.lbl_main_timer.config(text="00:00:00", fg="#555")
        self.lbl_mini_timer.config(text="00:00:00", fg="#bbb")
        
        messagebox.showinfo("Done", f"Saved!")

    # ... (Tray and Kill logic remains same) ...
    def setup_tray(self):
        def show_window(icon, item):
            self.root.deiconify()
            self.root.lift()
        def quit_app(icon, item):
            self.root.after(0, self.kill_app)
        menu = (item('Open', show_window, default=True), item('Exit', quit_app))
        self.tray_icon = pystray.Icon("name", self.icon_img, "Recorder", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def minimize_to_tray(self):
        self.root.withdraw()

    def kill_app(self):
        if self.is_recording:
             if not messagebox.askyesno("Confirm", "Stop recording?", parent=self.root):
                 return
             self.stop_recording()
        if self.tray_icon: self.tray_icon.stop()
        self.root.destroy()
        os._exit(0)

if __name__ == "__main__":
    root = tk.Tk()
    app = ProfessionalRecorder(root)
    root.mainloop()
