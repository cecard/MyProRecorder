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

# --- 1. 开启 Windows 高清屏适配 ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# --- 2. 自动生成图标算法 ---
def create_eye_icon(size=64, style="normal"):
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    sclera_color = (240, 240, 240)
    iris_color = (0, 120, 212) if style == "normal" else (209, 52, 56)
    pupil_color = (20, 20, 20)
    draw.ellipse((2, 2, size-2, size-2), fill=sclera_color, outline=(200, 200, 200))
    iris_size = size * 0.55
    iris_offset = (size - iris_size) / 2
    draw.ellipse((iris_offset, iris_offset, iris_offset+iris_size, iris_offset+iris_size), fill=iris_color)
    pupil_size = size * 0.25
    pupil_offset = (size - pupil_size) / 2
    draw.ellipse((pupil_offset, pupil_offset, pupil_offset+pupil_size, pupil_offset+pupil_size), fill=pupil_color)
    highlight_size = size * 0.1
    draw.ellipse((size*0.6, size*0.3, size*0.6+highlight_size, size*0.3+highlight_size), fill=(255, 255, 255, 230))
    return image

class ProfessionalRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("全能录屏 Pro")
        self.root.geometry("500x420")
        self.root.configure(bg="#1e1e1e")
        
        # --- 核心修改：无边框模式 (去白边) ---
        self.root.overrideredirect(True) 
        # ----------------------------------
        
        self.is_recording = False
        self.process = None
        self.audio_thread = None
        self.region = None 
        self.ffmpeg_path = resource_path("ffmpeg.exe")
        self.tray_icon = None
        self.record_cursor_var = tk.BooleanVar(value=True)
        
        # 窗口拖动变量
        self.offset_x = 0
        self.offset_y = 0

        # 生成图标
        self.icon_img = create_eye_icon(64, "normal")
        self.rec_icon_img = create_eye_icon(64, "record")
        self.tk_icon = ImageTk.PhotoImage(self.icon_img)
        self.root.iconphoto(True, self.tk_icon)

        # 启动顺序：先UI(含自定义标题栏) -> 再托盘
        self.setup_ui() 
        self.setup_tray()
        
        # 检查FFmpeg
        if not os.path.exists(self.ffmpeg_path):
            messagebox.showerror("致命错误", f"找不到内核文件: {self.ffmpeg_path}")

    # --- 自定义标题栏拖动逻辑 ---
    def start_move(self, event):
        self.offset_x = event.x
        self.offset_y = event.y

    def do_move(self, event):
        x = self.root.winfo_x() + event.x - self.offset_x
        y = self.root.winfo_y() + event.y - self.offset_y
        self.root.geometry(f"+{x}+{y}")
    # --------------------------

    def setup_tray(self):
        def show_window(icon, item):
            self.root.deiconify()
            self.root.lift()
        def quit_app(icon, item):
            self.root.after(0, self.kill_app) # 强制退出
        menu = (item('显示主界面', show_window, default=True), item('退出', quit_app))
        self.tray_icon = pystray.Icon("name", self.icon_img, "录屏助手 - 待机", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def minimize_to_tray(self):
        # 最小化时隐藏窗口
        self.root.withdraw()
        # 此时只能通过托盘恢复，或者添加气泡提示（可选）

    def kill_app(self):
        # 彻底退出的逻辑
        if self.is_recording:
             if not messagebox.askyesno("确认", "正在录制中，强制退出将停止录制。", parent=self.root):
                 return
             self.stop_recording()
        
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()
        os._exit(0) # 确保所有线程被杀掉

    def setup_ui(self):
        bg_color = "#1e1e1e"
        title_bg = "#2d2d2d"
        btn_color = "#0078d4"
        text_color = "#ffffff"
        
        # --- 自定义标题栏 (替代系统白边) ---
        title_bar = tk.Frame(self.root, bg=title_bg, relief="flat", height=35)
        title_bar.pack(side=tk.TOP, fill=tk.X)
        title_bar.pack_propagate(False) # 固定高度
        
        # 绑定拖动事件到标题栏背景和标题文字
        title_bar.bind("<Button-1>", self.start_move)
        title_bar.bind("<B1-Motion>", self.do_move)

        # 标题栏图标
        lbl_icon = tk.Label(title_bar, image=self.tk_icon, bg=title_bg, bd=0)
        lbl_icon.pack(side=tk.LEFT, padx=(10, 5))
        lbl_icon.bind("<Button-1>", self.start_move)
        
        # 标题栏文字
        lbl_title = tk.Label(title_bar, text="全能录屏 Pro", bg=title_bg, fg="#dddddd", font=("Segoe UI", 10))
        lbl_title.pack(side=tk.LEFT)
        lbl_title.bind("<Button-1>", self.start_move)
        
        # 自定义关闭按钮 (X)
        btn_close = tk.Button(title_bar, text="✕", bg=title_bg, fg="#aaaaaa", activebackground="#e81123", activeforeground="white", bd=0, font=("Arial", 11), width=4, command=self.kill_app)
        btn_close.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 自定义最小化按钮 (-)
        btn_min = tk.Button(title_bar, text="─", bg=title_bg, fg="#aaaaaa", activebackground="#444444", activeforeground="white", bd=0, font=("Arial", 11), width=4, command=self.minimize_to_tray)
        btn_min.pack(side=tk.RIGHT, fill=tk.Y)
        # --------------------------------

        # 内容区域
        content_frame = tk.Frame(self.root, bg=bg_color)
        content_frame.pack(fill=tk.BOTH, expand=True)

        self.lbl_info = tk.Label(content_frame, text="状态: 就绪 (默认录制全屏)", font=("Segoe UI", 10), bg=bg_color, fg="#aaaaaa")
        self.lbl_info.pack(pady=(20, 10))
        
        ctrl_frame = tk.Frame(content_frame, bg=bg_color)
        ctrl_frame.pack(pady=10)

        tk.Button(ctrl_frame, text="⛶ 框选区域", command=self.select_area, bg="#333333", fg="white", font=("Segoe UI", 11), bd=0, padx=15, pady=8).grid(row=0, column=0, padx=10)
        
        self.btn_start = tk.Button(ctrl_frame, text="▶ 开始录制", command=self.start_recording, bg=btn_color, fg="white", font=("Segoe UI", 11, "bold"), bd=0, padx=20, pady=8)
        self.btn_start.grid(row=0, column=1, padx=10)

        # 鼠标录制开关
        chk_cursor = tk.Checkbutton(content_frame, text="录制鼠标光标", variable=self.record_cursor_var, 
                                    bg=bg_color, fg="#dddddd", selectcolor="#333333", activebackground=bg_color, activeforeground="#ffffff",
                                    font=("Segoe UI", 10))
        chk_cursor.pack(pady=5)
        
        self.btn_stop = tk.Button(content_frame, text="⬛ 停止并保存", command=self.stop_recording, bg="#d13438", fg="white", font=("Segoe UI", 11), bd=0, padx=30, pady=5, state=tk.DISABLED)
        self.btn_stop.pack(pady=15)
        
        tk.Label(content_frame, text="System Loopback Audio · FFmpeg x264 · Frameless UI", bg=bg_color, fg="#555555", font=("Segoe UI", 8)).pack(side=tk.BOTTOM, pady=10)

        # 绘制边框 (因为去掉了系统边框，加一圈细线比较好看)
        tk.Frame(self.root, bg="#333333", width=1).pack(side=tk.LEFT, fill=tk.Y)
        tk.Frame(self.root, bg="#333333", width=1).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Frame(self.root, bg="#333333", height=1).pack(side=tk.BOTTOM, fill=tk.X)

    def select_area(self):
        self.root.iconify() # 最小化
        # 这里因为是无边框窗口，iconify可能表现不同，但withdraw会导致无法恢复，所以用iconify
        time.sleep(0.2)
        top = Toplevel(self.root)
        top.attributes('-fullscreen', True, '-alpha', 0.3)
        top.config(bg='black', cursor='cross')
        canvas = Canvas(top, bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        start_pos = [None, None]
        def on_down(e): start_pos[:] = [e.x, e.y]
        def on_drag(e):
            canvas.delete("rect")
            canvas.create_rectangle(start_pos[0], start_pos[1], e.x, e.y, outline="red", width=3, tags="rect")
        def on_up(e):
            x1, y1 = min(start_pos[0], e.x), min(start_pos[1], e.y)
            w, h = abs(start_pos[0] - e.x), abs(start_pos[1] - e.y)
            if w % 2 != 0: w -= 1
            if h % 2 != 0: h -= 1
            if w > 50 and h > 50:
                self.region = (x1, y1, w, h)
                self.lbl_info.config(text=f"选区: {w}x{h} @ ({x1},{y1})")
            top.destroy()
            self.root.deiconify() # 恢复
        canvas.bind("<Button-1>", on_down); canvas.bind("<B1-Motion>", on_drag); canvas.bind("<ButtonRelease-1>", on_up)
        top.bind("<Escape>", lambda e: [top.destroy(), self.root.deiconify()])

    def get_default_loopback_device(self, p):
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            if not default_speakers["isLoopbackDevice"]:
                for loopback in p.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]: return loopback
            else: return default_speakers
        except: return None

    def audio_pipe_worker(self, stream, ffmpeg_process):
        try:
            while self.is_recording: ffmpeg_process.stdin.write(stream.read(1024))
        except: pass

    def start_recording(self):
        self.is_recording = True
        self.btn_start.config(state=tk.DISABLED, bg="#555555")
        self.btn_stop.config(state=tk.NORMAL)
        
        if self.tray_icon:
            self.tray_icon.icon = self.rec_icon_img
            self.tray_icon.title = "录屏中..."
        
        filename = f"Capture_{int(time.time())}.mp4"
        p = pyaudio.PyAudio()
        loopback_dev = self.get_default_loopback_device(p)
        audio_args = []
        stream = None
        
        if loopback_dev:
            stream = p.open(format=pyaudio.paInt16, channels=loopback_dev["maxInputChannels"], rate=int(loopback_dev["defaultSampleRate"]), frames_per_buffer=1024, input=True, input_device_index=loopback_dev["index"])
            audio_args = ['-f', 's16le', '-ar', str(int(loopback_dev["defaultSampleRate"])), '-ac', str(loopback_dev["maxInputChannels"]), '-i', 'pipe:0']
        
        mouse_flag = '1' if self.record_cursor_var.get() else '0'
        video_args = ['-f', 'gdigrab', '-framerate', '30', '-draw_mouse', mouse_flag]
        if self.region:
            x, y, w, h = self.region
            video_args.extend(['-offset_x', str(x), '-offset_y', str(y), '-video_size', f"{w}x{h}"])
        video_args.extend(['-i', 'desktop'])
        
        cmd = [self.ffmpeg_path, '-y'] + audio_args + video_args + ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-c:a', 'aac', '-b:a', '192k', '-pix_fmt', 'yuv420p', filename]
        
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        
        if stream:
            self.audio_thread = threading.Thread(target=self.audio_pipe_worker, args=(stream, self.process))
            self.audio_thread.start()

    def stop_recording(self):
        self.is_recording = False
        if self.tray_icon:
            self.tray_icon.icon = self.icon_img
            self.tray_icon.title = "录屏助手 - 待机"
        if self.process:
            try: self.process.stdin.close(); self.process.wait(timeout=3)
            except: self.process.kill()
        self.btn_start.config(state=tk.NORMAL, bg="#0078d4")
        self.btn_stop.config(state=tk.DISABLED)
        messagebox.showinfo("完成", "录制已保存！")

if __name__ == "__main__":
    root = tk.Tk()
    app = ProfessionalRecorder(root)
    root.mainloop()
