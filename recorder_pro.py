import tkinter as tk
from tkinter import messagebox, Toplevel, Canvas
import subprocess
import threading
import time
import sys
import os
import pyaudiowpatch as pyaudio
from screeninfo import get_monitors

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

class ProfessionalRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("全能录屏 (免配置版)")
        self.root.geometry("450x320")
        self.root.configure(bg="#1e1e1e")
        self.is_recording = False
        self.process = None
        self.audio_thread = None
        self.region = None 
        self.ffmpeg_path = resource_path("ffmpeg.exe")
        self.setup_ui()
        if not os.path.exists(self.ffmpeg_path):
            messagebox.showerror("错误", f"找不到内核文件: {self.ffmpeg_path}")

    def setup_ui(self):
        bg_color = "#1e1e1e"
        btn_color = "#0078d4"
        tk.Label(self.root, text="🔴 高清系统内录工具", font=("Segoe UI", 16, "bold"), bg=bg_color, fg="#ffffff").pack(pady=20)
        self.lbl_info = tk.Label(self.root, text="状态: 就绪 (默认录制全屏)", font=("Segoe UI", 10), bg=bg_color, fg="#aaaaaa")
        self.lbl_info.pack(pady=5)
        btn_frame = tk.Frame(self.root, bg=bg_color)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="⛶ 框选区域", command=self.select_area, bg="#333333", fg="white", font=("Segoe UI", 11), bd=0, padx=15, pady=8).grid(row=0, column=0, padx=10)
        self.btn_start = tk.Button(btn_frame, text="▶ 开始录制", command=self.start_recording, bg=btn_color, fg="white", font=("Segoe UI", 11, "bold"), bd=0, padx=20, pady=8)
        self.btn_start.grid(row=0, column=1, padx=10)
        self.btn_stop = tk.Button(self.root, text="⬛ 停止并保存", command=self.stop_recording, bg="#d13438", fg="white", font=("Segoe UI", 11), bd=0, padx=30, pady=5, state=tk.DISABLED)
        self.btn_stop.pack(pady=10)
        tk.Label(self.root, text="无需立体声混音 · 自动同步 · CRF18无损级", bg=bg_color, fg="#666666", font=("Segoe UI", 8)).pack(side=tk.BOTTOM, pady=10)

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
        filename = f"Capture_{int(time.time())}.mp4"
        p = pyaudio.PyAudio()
        loopback_dev = self.get_default_loopback_device(p)
        audio_args = []
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
        if loopback_dev:
            self.audio_thread = threading.Thread(target=self.audio_pipe_worker, args=(stream, self.process))
            self.audio_thread.start()

    def stop_recording(self):
        self.is_recording = False
        if self.process:
            try: self.process.stdin.close(); self.process.wait(timeout=3)
            except: self.process.kill()
        self.btn_start.config(state=tk.NORMAL, bg="#0078d4"); self.btn_stop.config(state=tk.DISABLED)
        messagebox.showinfo("完成", "录制已保存！")

if __name__ == "__main__":
    root = tk.Tk()
    app = ProfessionalRecorder(root)
    root.mainloop()
