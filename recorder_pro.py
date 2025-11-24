import tkinter as tk
from tkinter import messagebox, Toplevel, Canvas
import subprocess
import threading
import time
import sys
import os
import ctypes
from PIL import Image, ImageDraw, ImageTk # 绘图库
import pystray # 托盘库
from pystray import MenuItem as item
import pyaudiowpatch as pyaudio
from screeninfo import get_monitors

# --- 1. 开启 Windows 高清屏适配 (解决界面模糊问题) ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# --- 2. 自动生成“大眼球”图标算法 (无需外部图片文件) ---
def create_eye_icon(size=64, style="normal"):
    # 创建透明背景图片
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # 配色方案
    sclera_color = (240, 240, 240) # 眼白
    iris_color = (0, 120, 212) if style == "normal" else (209, 52, 56) # 虹膜(蓝/红)
    pupil_color = (20, 20, 20) # 瞳孔
    
    # 画眼白 (圆形)
    draw.ellipse((2, 2, size-2, size-2), fill=sclera_color, outline=(200, 200, 200))
    # 画虹膜
    iris_size = size * 0.55
    iris_offset = (size - iris_size) / 2
    draw.ellipse((iris_offset, iris_offset, iris_offset+iris_size, iris_offset+iris_size), fill=iris_color)
    # 画瞳孔
    pupil_size = size * 0.25
    pupil_offset = (size - pupil_size) / 2
    draw.ellipse((pupil_offset, pupil_offset, pupil_offset+pupil_size, pupil_offset+pupil_size), fill=pupil_color)
    # 画高光 (点睛之笔)
    highlight_size = size * 0.1
    draw.ellipse((size*0.6, size*0.3, size*0.6+highlight_size, size*0.3+highlight_size), fill=(255, 255, 255, 230))
    
    return image

class ProfessionalRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("全能录屏 Pro")
        self.root.geometry("500x380")
        self.root.configure(bg="#1e1e1e")
        
        # 核心变量
        self.is_recording = False
        self.process = None
        self.audio_thread = None
        self.region = None 
        self.ffmpeg_path = resource_path("ffmpeg.exe")
        self.tray_icon = None

        # 生成应用图标
        self.icon_img = create_eye_icon(64, "normal")
        self.rec_icon_img = create_eye_icon(64, "record") # 录制时的红眼图标
        
        # 设置窗口图标 (Tkinter需要特定格式)
        self.tk_icon = ImageTk.PhotoImage(self.icon_img)
        self.root.iconphoto(True, self.tk_icon)

        # 启动系统托盘 (在独立线程运行)
        self.setup_tray()
        
        # 拦截关闭事件，确保清理干净
        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)
        
        self.setup_ui()
        
        if not os.path.exists(self.ffmpeg_path):
            messagebox.showerror("致命错误", f"找不到内核文件: {self.ffmpeg_path}")

    def setup_tray(self):
        def show_window(icon, item):
            self.root.deiconify()
            self.root.lift()

        def quit_app(icon, item):
            self.root.after(0, self.on_exit) # 回到主线程退出

        # 托盘菜单
        menu = (item('显示主界面', show_window, default=True), item('退出', quit_app))
        self.tray_icon = pystray.Icon("name", self.icon_img, "录屏助手 - 待机", menu)
        
        # 线程启动
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def setup_ui(self):
        bg_color = "#1e1e1e"
        btn_color = "#0078d4"
        
        # 顶部标题栏
        header_frame = tk.Frame(self.root, bg=bg_color)
        header_frame.pack(pady=20)
        # 标题左侧放个小图标
        self.lbl_header_icon = tk.Label(header_frame, image=self.tk_icon, bg=bg_color, bd=0)
        self.lbl_header_icon.pack(side=tk.LEFT, padx=10)
        tk.Label(header_frame, text="全能录屏 Pro", font=("Segoe UI", 18, "bold"), bg=bg_color, fg="#ffffff").pack(side=tk.LEFT)
        
        self.lbl_info = tk.Label(self.root, text="状态: 就绪 (默认录制全屏)", font=("Segoe UI", 10), bg=bg_color, fg="#aaaaaa")
        self.lbl_info.pack(pady=5)
        
        btn_frame = tk.Frame(self.root, bg=bg_color)
        btn_frame.pack(pady=25)

        tk.Button(btn_frame, text="⛶ 框选区域", command=self.select_area, bg="#333333", fg="white", font=("Segoe UI", 11), bd=0, padx=15, pady=8).grid(row=0, column=0, padx=10)
        
        self.btn_start = tk.Button(btn_frame, text="▶ 开始录制", command=self.start_recording, bg=btn_color, fg="white", font=("Segoe UI", 11, "bold"), bd=0, padx=20, pady=8)
        self.btn_start.grid(row=0, column=1, padx=10)
        
        self.btn_stop = tk.Button(self.root, text="⬛ 停止并保存", command=self.stop_recording, bg="#d13438", fg="white", font=("Segoe UI", 11), bd=0, padx=30, pady=5, state=tk.DISABLED)
        self.btn_stop.pack(pady=10)
        
        tk.Label(self.root, text="System Loopback Audio · FFmpeg x264 · Tray Supported", bg=bg_color, fg="#555555", font=("Segoe UI", 8)).pack(side=tk.BOTTOM, pady=10)

    def select_area(self):
        self.root.iconify()
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
            self.root.deiconify()
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
        
        # 更新托盘图标状态
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
        
        video_args = ['-f', 'gdigrab', '-framerate', '30', '-draw_mouse', '1']
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
        
        # 恢复托盘图标
        if self.tray_icon:
            self.tray_icon.icon = self.icon_img
            self.tray_icon.title = "录屏助手 - 待机"

        if self.process:
            try: self.process.stdin.close(); self.process.wait(timeout=3)
            except: self.process.kill()
        
        self.btn_start.config(state=tk.NORMAL, bg="#0078d4")
        self.btn_stop.config(state=tk.DISABLED)
        messagebox.showinfo("完成", "录制已保存！")

    def on_exit(self):
        # 安全退出逻辑
        if self.is_recording:
            if messagebox.askyesno("确认", "正在录制中，确定要停止并退出吗？"):
                self.stop_recording()
            else:
                return
        if self.tray_icon:
            self.tray_icon.stop() # 停止托盘线程
        self.root.destroy() # 销毁窗口

if __name__ == "__main__":
    root = tk.Tk()
    app = ProfessionalRecorder(root)
    root.mainloop()
