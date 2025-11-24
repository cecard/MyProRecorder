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

# --- Windows DPI 适配 ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def create_eye_icon(size=64, style="normal"):
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # 绘制图标
    draw.ellipse((2, 2, size-2, size-2), fill=(255, 255, 255), outline=(200, 200, 200))
    iris_color = (0, 120, 212) if style == "normal" else (220, 50, 50)
    c = size / 2
    r_iris = size * 0.3
    draw.ellipse((c-r_iris, c-r_iris, c+r_iris, c+r_iris), fill=iris_color)
    return image

class ProfessionalRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("Pro Recorder")
        self.root.configure(bg="#1e1e1e")
        self.root.overrideredirect(True) # 无边框
        
        # 1. 窗口初始化：居中显示
        w, h = 520, 450
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        
        # 核心变量
        self.is_recording = False
        self.is_mini_mode = False
        self.process = None
        self.audio_thread = None
        self.region = None 
        self.ffmpeg_path = resource_path("ffmpeg.exe")
        self.tray_icon = None
        self.record_cursor_var = tk.BooleanVar(value=True)
        self.last_geometry = f"{w}x{h}+{x}+{y}"
        
        # 拖拽相关
        self._drag_data = {"x": 0, "y": 0, "mode": None}
        self.resize_margin = 8 # 边缘检测宽度
        
        # 图标资源
        self.icon_img = create_eye_icon(64, "normal")
        self.rec_icon_img = create_eye_icon(64, "record")
        self.tk_icon = ImageTk.PhotoImage(self.icon_img)
        self.root.iconphoto(True, self.tk_icon)

        self.setup_ui() 
        self.setup_tray()
        
        # 绑定事件实现拉伸和拖拽
        self.root.bind("<Motion>", self.check_cursor)
        self.root.bind("<ButtonPress-1>", self.start_action)
        self.root.bind("<ButtonRelease-1>", self.stop_action)
        self.root.bind("<B1-Motion>", self.do_action)
        
        if not os.path.exists(self.ffmpeg_path):
            messagebox.showerror("Error", f"Missing ffmpeg: {self.ffmpeg_path}")

    # ==========================
    # 纯 Python 实现的窗口操作
    # ==========================
    def check_cursor(self, event):
        if self.is_mini_mode: return
        
        x, y = event.x, event.y
        w, h = self.root.winfo_width(), self.root.winfo_height()
        m = self.resize_margin
        
        cursor = ""
        mode = None

        # 检测边缘
        if x < m and y < m: cursor, mode = "sb_h_double_arrow", "nw"
        elif x > w - m and y < m: cursor, mode = "sb_h_double_arrow", "ne"
        elif x < m and y > h - m: cursor, mode = "sb_h_double_arrow", "sw"
        elif x > w - m and y > h - m: cursor, mode = "sb_h_double_arrow", "se"
        elif y < m: cursor, mode = "sb_v_double_arrow", "n"
        elif y > h - m: cursor, mode = "sb_v_double_arrow", "s"
        elif x < m: cursor, mode = "sb_h_double_arrow", "w"
        elif x > w - m: cursor, mode = "sb_h_double_arrow", "e"
        else: cursor, mode = "arrow", None

        if self.root.cget("cursor") != cursor:
            self.root.config(cursor=cursor)
            
        self._drag_data["hover_mode"] = mode

    def start_action(self, event):
        if self.is_mini_mode: 
            # Mini模式下只能拖动
            self._drag_data["mode"] = "move"
            self._drag_data["start_x"] = event.x_root
            self._drag_data["start_y"] = event.y_root
            self._drag_data["win_x"] = self.root.winfo_x()
            self._drag_data["win_y"] = self.root.winfo_y()
            return

        mode = self._drag_data.get("hover_mode")
        if mode:
            # 边缘拉伸
            self._drag_data["mode"] = mode
            self._drag_data["start_x"] = event.x_root
            self._drag_data["start_y"] = event.y_root
            self._drag_data["start_w"] = self.root.winfo_width()
            self._drag_data["start_h"] = self.root.winfo_height()
            self._drag_data["win_x"] = self.root.winfo_x()
            self._drag_data["win_y"] = self.root.winfo_y()
        elif event.y < 35: # 标题栏高度
            # 标题栏移动
            self._drag_data["mode"] = "move"
            self._drag_data["start_x"] = event.x_root
            self._drag_data["start_y"] = event.y_root
            self._drag_data["win_x"] = self.root.winfo_x()
            self._drag_data["win_y"] = self.root.winfo_y()

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
            # 拉伸逻辑
            x, y = self._drag_data["win_x"], self._drag_data["win_y"]
            w, h = self._drag_data["start_w"], self._drag_data["start_h"]
            
            if "n" in mode: 
                y += dy; h -= dy
            if "s" in mode: 
                h += dy
            if "w" in mode: 
                x += dx; w -= dx
            if "e" in mode: 
                w += dx
            
            # 限制最小尺寸
            if w < 400: w = 400
            if h < 300: h = 300
            
            self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ==========================
    # 模式切换
    # ==========================
    def toggle_mini_mode(self):
        if not self.is_mini_mode:
            # === 切换到 Mini ===
            self.is_mini_mode = True
            self.last_geometry = self.root.geometry()
            
            # 安全的左下角计算
            screen_h = self.root.winfo_screenheight()
            # 留出 120px 避开任务栏
            target_y = screen_h - 120 
            target_x = 20
            
            self.normal_frame.pack_forget()
            self.mini_frame.pack(fill=tk.BOTH, expand=True)
            self.root.geometry(f"380x45+{target_x}+{target_y}")
            self.root.attributes('-topmost', True)
        else:
            # === 恢复正常 ===
            self.is_mini_mode = False
            self.mini_frame.pack_forget()
            self.normal_frame.pack(fill=tk.BOTH, expand=True)
            try:
                # 恢复之前的位置
                self.root.geometry(self.last_geometry)
            except:
                self.root.geometry("520x450+300+300")
            self.root.attributes('-topmost', False)

    # ==========================
    # UI 构建
    # ==========================
    def setup_ui(self):
        self.bg_color = "#1e1e1e"
        self.title_bg = "#2d2d2d"
        
        # 容器
        self.normal_frame = tk.Frame(self.root, bg=self.bg_color)
        self.normal_frame.pack(fill=tk.BOTH, expand=True)
        
        self.mini_frame = tk.Frame(self.root, bg="#333333", highlightthickness=1, highlightbackground="#555555")
        
        self.build_normal_ui()
        self.build_mini_ui()

    def build_mini_ui(self):
        # 简单的 Mini 栏
        p = self.mini_frame
        btn_opts = {"bd": 0, "width": 4, "font": ("Arial", 10)}
        
        tk.Button(p, text="⤢", bg="#444444", fg="white", command=self.toggle_mini_mode, **btn_opts).pack(side=tk.LEFT, fill=tk.Y, padx=1)
        tk.Button(p, text="⛶", bg="#333333", fg="white", command=self.select_area, **btn_opts).pack(side=tk.LEFT, fill=tk.Y, padx=1)
        self.btn_mini_cursor = tk.Button(p, text="🖱️", bg="#333333", fg="#00ff00", command=self.toggle_cursor_mini, **btn_opts)
        self.btn_mini_cursor.pack(side=tk.LEFT, fill=tk.Y, padx=1)
        
        # 拖拽把手
        tk.Label(p, text="Mini Mode", bg="#333333", fg="#777777").pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        
        self.btn_mini_stop = tk.Button(p, text="⬛", command=self.stop_recording, bg="#d13438", fg="white", state=tk.DISABLED, **btn_opts)
        self.btn_mini_stop.pack(side=tk.RIGHT, fill=tk.Y, padx=1)
        self.btn_mini_start = tk.Button(p, text="▶", command=self.start_recording, bg="#0078d4", fg="white", **btn_opts)
        self.btn_mini_start.pack(side=tk.RIGHT, fill=tk.Y, padx=1)

    def toggle_cursor_mini(self):
        v = self.record_cursor_var.get()
        self.record_cursor_var.set(not v)
        self.btn_mini_cursor.config(fg="#00ff00" if not v else "#555555")

    def build_normal_ui(self):
        p = self.normal_frame
        
        # 标题栏
        t_bar = tk.Frame(p, bg=self.title_bg, height=35)
        t_bar.pack(side=tk.TOP, fill=tk.X)
        t_bar.pack_propagate(False) # 锁定高度
        
        # 标题栏虽然有事件绑定在root上，但这里再加一层防止被组件遮挡
        t_bar.bind("<ButtonPress-1>", self.start_action)
        t_bar.bind("<B1-Motion>", self.do_action)
        
        lbl = tk.Label(t_bar, image=self.tk_icon, bg=self.title_bg, bd=0)
        lbl.pack(side=tk.LEFT, padx=(10,5))
        lbl.bind("<ButtonPress-1>", self.start_action) # 确保点击图标也能拖动
        
        tk.Label(t_bar, text="Pro Recorder", bg=self.title_bg, fg="#ddd", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        
        b_sty = {"bd": 0, "width": 4, "font": ("Arial", 11)}
        tk.Button(t_bar, text="✕", bg=self.title_bg, fg="#aaa", activebackground="red", command=self.kill_app, **b_sty).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Button(t_bar, text="⤢", bg=self.title_bg, fg="#aaa", command=self.toggle_mini_mode, **b_sty).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Button(t_bar, text="─", bg=self.title_bg, fg="#aaa", command=self.minimize_to_tray, **b_sty).pack(side=tk.RIGHT, fill=tk.Y)

        # 内容
        c_frame = tk.Frame(p, bg=self.bg_color)
        c_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(c_frame, text="Ready to Record", font=("Segoe UI", 20), bg=self.bg_color, fg="#555").place(relx=0.5, rely=0.4, anchor=tk.CENTER)
        
        # 底部栏
        b_frame = tk.Frame(c_frame, bg=self.bg_color, height=80)
        b_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=20)
        
        row = tk.Frame(b_frame, bg=self.bg_color)
        row.pack(anchor=tk.CENTER)
        
        tk.Button(row, text="⛶ Area", command=self.select_area, bg="#333", fg="white", bd=0, padx=15, pady=8).pack(side=tk.LEFT, padx=5)
        self.btn_start = tk.Button(row, text="▶ Start", command=self.start_recording, bg="#0078d4", fg="white", bd=0, padx=20, pady=8)
        self.btn_start.pack(side=tk.LEFT, padx=5)
        self.btn_stop = tk.Button(row, text="⬛ Stop", command=self.stop_recording, bg="#d13438", fg="white", bd=0, padx=20, pady=8, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=5)
        tk.Checkbutton(row, text="Cursor", variable=self.record_cursor_var, bg=self.bg_color, fg="#ddd", selectcolor="#333", activebackground=self.bg_color).pack(side=tk.LEFT, padx=5)
        
        # 边框
        tk.Frame(p, bg="#444", width=1).pack(side=tk.LEFT, fill=tk.Y)
        tk.Frame(p, bg="#444", width=1).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Frame(p, bg="#444", height=1).pack(side=tk.BOTTOM, fill=tk.X)

    # ... (保持 select_area, get_default_loopback_device, audio_pipe_worker, setup_tray, minimize_to_tray, kill_app, start_recording, stop_recording 不变，请直接复制之前的实现) ...
    # 为了防止你复制漏了，我这里补上关键的 select_area 和其他函数，确保这是完整可运行的文件
    
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

    def setup_tray(self):
        def show_window(icon, item):
            self.root.deiconify()
            self.root.lift()
        def quit_app(icon, item):
            self.root.after(0, self.kill_app)
        menu = (item('显示主界面', show_window, default=True), item('退出', quit_app))
        self.tray_icon = pystray.Icon("name", self.icon_img, "录屏助手", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def minimize_to_tray(self):
        self.root.withdraw()

    def kill_app(self):
        if self.is_recording:
             if not messagebox.askyesno("Confirm", "Stop recording and exit?", parent=self.root):
                 return
             self.stop_recording()
        if self.tray_icon: self.tray_icon.stop()
        self.root.destroy()
        os._exit(0)

    def start_recording(self):
        self.is_recording = True
        self.btn_start.config(state=tk.DISABLED, bg="#555555")
        self.btn_stop.config(state=tk.NORMAL)
        self.btn_mini_start.config(state=tk.DISABLED, bg="#555555")
        self.btn_mini_stop.config(state=tk.NORMAL)
        if self.tray_icon: self.tray_icon.icon = self.rec_icon_img
        
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
        if self.tray_icon: self.tray_icon.icon = self.icon_img
        if self.process:
            try: self.process.stdin.close(); self.process.wait(timeout=3)
            except: self.process.kill()
        
        self.btn_start.config(state=tk.NORMAL, bg="#0078d4")
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_mini_start.config(state=tk.NORMAL, bg="#0078d4")
        self.btn_mini_stop.config(state=tk.DISABLED)
        messagebox.showinfo("Done", f"Saved!")

if __name__ == "__main__":
    root = tk.Tk()
    app = ProfessionalRecorder(root)
    root.mainloop()
