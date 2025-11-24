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

# --- 图标生成 ---
def create_eye_icon(size=64, style="normal"):
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # 画一个简单的眼睛
    draw.ellipse((2, 2, size-2, size-2), fill=(240, 240, 240), outline=(200, 200, 200))
    iris_color = (0, 120, 212) if style == "normal" else (209, 52, 56)
    c = size / 2
    r_iris = size * 0.28
    draw.ellipse((c-r_iris, c-r_iris, c+r_iris, c+r_iris), fill=iris_color)
    r_pupil = size * 0.12
    draw.ellipse((c-r_pupil, c-r_pupil, c+r_pupil, c+r_pupil), fill=(20, 20, 20))
    return image

class ProfessionalRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("全能录屏 Pro")
        self.root.geometry("500x400")
        self.root.configure(bg="#1e1e1e")
        self.root.overrideredirect(True) # 无边框
        
        self.is_recording = False
        self.is_mini_mode = False
        self.process = None
        self.audio_thread = None
        self.region = None 
        self.ffmpeg_path = resource_path("ffmpeg.exe")
        self.tray_icon = None
        self.record_cursor_var = tk.BooleanVar(value=True)
        
        # 窗口拖动和缩放变量
        self.last_geometry = "500x400+300+300"
        self._drag_data = {"x": 0, "y": 0, "mode": None}
        
        # 边缘检测距离
        self.resize_margin = 8 

        # 图标资源
        self.icon_img = create_eye_icon(64, "normal")
        self.rec_icon_img = create_eye_icon(64, "record")
        self.tk_icon = ImageTk.PhotoImage(self.icon_img)
        self.root.iconphoto(True, self.tk_icon)

        self.setup_ui() 
        self.setup_tray()
        
        # 绑定全局鼠标事件用于边缘检测
        self.root.bind("<Motion>", self.check_cursor_style)
        self.root.bind("<ButtonPress-1>", self.start_drag_or_resize)
        self.root.bind("<ButtonRelease-1>", self.stop_drag_or_resize)
        self.root.bind("<B1-Motion>", self.do_drag_or_resize)
        
        if not os.path.exists(self.ffmpeg_path):
            messagebox.showerror("致命错误", f"找不到内核文件: {self.ffmpeg_path}")

    # ==========================
    # 核心逻辑：8方向窗口拉伸
    # ==========================
    def check_cursor_style(self, event):
        if self.is_mini_mode: return # Mini模式不处理
        
        x, y = event.x, event.y
        w, h = self.root.winfo_width(), self.root.winfo_height()
        m = self.resize_margin
        
        cursor = ""
        mode = ""

        # 判定区域
        on_left = x < m
        on_right = x > w - m
        on_top = y < m
        on_bottom = y > h - m

        if on_top and on_left: cursor, mode = "sb_h_double_arrow", "nw" # 实际上是斜向，tk用通用图标
        elif on_top and on_right: cursor, mode = "sb_h_double_arrow", "ne"
        elif on_bottom and on_left: cursor, mode = "sb_h_double_arrow", "sw"
        elif on_bottom and on_right: cursor, mode = "sb_h_double_arrow", "se"
        elif on_top: cursor, mode = "sb_v_double_arrow", "n"
        elif on_bottom: cursor, mode = "sb_v_double_arrow", "s"
        elif on_left: cursor, mode = "sb_h_double_arrow", "w"
        elif on_right: cursor, mode = "sb_h_double_arrow", "e"
        else: cursor, mode = "arrow", None

        # 只有当在普通界面且非拖动标题栏时才改变鼠标
        if self.root.cget("cursor") != cursor:
            self.root.config(cursor=cursor)
            
        self._drag_data["hover_mode"] = mode

    def start_drag_or_resize(self, event):
        if self.is_mini_mode: return
        
        mode = self._drag_data.get("hover_mode")
        if mode:
            # 开始调整大小
            self._drag_data["mode"] = mode
            self._drag_data["start_x"] = event.x_root
            self._drag_data["start_y"] = event.y_root
            self._drag_data["start_w"] = self.root.winfo_width()
            self._drag_data["start_h"] = self.root.winfo_height()
            self._drag_data["start_geo_x"] = self.root.winfo_x()
            self._drag_data["start_geo_y"] = self.root.winfo_y()
        else:
            # 检查是否点击了标题栏区域 (假设高度35)
            # 这里做个简单的区域判断，如果是通过Frame绑定的拖动会由Frame处理
            # 这里处理的是点击了背景的情况
            pass

    def stop_drag_or_resize(self, event):
        self._drag_data["mode"] = None
        self.root.config(cursor="arrow")

    def do_drag_or_resize(self, event):
        mode = self._drag_data.get("mode")
        if not mode: return

        dx = event.x_root - self._drag_data["start_x"]
        dy = event.y_root - self._drag_data["start_y"]
        
        x, y = self._drag_data["start_geo_x"], self._drag_data["start_geo_y"]
        w, h = self._drag_data["start_w"], self._drag_data["start_h"]
        
        new_x, new_y, new_w, new_h = x, y, w, h
        
        # 计算新坐标和尺寸
        if "n" in mode: 
            new_y += dy; new_h -= dy
        if "s" in mode: 
            new_h += dy
        if "w" in mode: 
            new_x += dx; new_w -= dx
        if "e" in mode: 
            new_w += dx

        # 最小尺寸限制
        if new_w < 350: new_w = 350
        if new_h < 300: new_h = 300
        
        # 应用
        self.root.geometry(f"{new_w}x{new_h}+{new_x}+{new_y}")

    # ==========================
    # 标题栏拖动 (独立逻辑)
    # ==========================
    def start_move(self, event):
        self._drag_data["win_x"] = event.x
        self._drag_data["win_y"] = event.y

    def do_move(self, event):
        x = self.root.winfo_x() + event.x - self._drag_data["win_x"]
        y = self.root.winfo_y() + event.y - self._drag_data["win_y"]
        self.root.geometry(f"+{x}+{y}")

    # ==========================
    # Mini 模式切换
    # ==========================
    def toggle_mini_mode(self):
        if not self.is_mini_mode:
            self.is_mini_mode = True
            self.last_geometry = self.root.geometry()
            
            # 屏幕左下角
            screen_h = self.root.winfo_screenheight()
            target_y = screen_h - 90 # 状态栏上方
            target_x = 20
            
            self.normal_frame.pack_forget()
            self.mini_frame.pack(fill=tk.BOTH, expand=True)
            self.root.geometry(f"420x50+{target_x}+{target_y}")
            self.root.attributes('-topmost', True)
        else:
            self.is_mini_mode = False
            self.mini_frame.pack_forget()
            self.normal_frame.pack(fill=tk.BOTH, expand=True)
            # 恢复位置
            try:
                # 简单的解析，防止 geometry 出错
                parts = self.last_geometry.replace('x', '+').split('+')
                self.root.geometry(f"{parts[0]}x{parts[1]}+{parts[2]}+{parts[3]}")
            except:
                self.root.geometry("500x400+300+300")
            self.root.attributes('-topmost', False)

    # ==========================
    # UI 构建
    # ==========================
    def setup_ui(self):
        self.bg_color = "#1e1e1e"
        self.title_bg = "#2d2d2d"
        
        # 1. 正常界面
        self.normal_frame = tk.Frame(self.root, bg=self.bg_color)
        self.normal_frame.pack(fill=tk.BOTH, expand=True)
        self.build_normal_ui(self.normal_frame)
        
        # 2. Mini 界面
        self.mini_frame = tk.Frame(self.root, bg="#333333", highlightthickness=1, highlightbackground="#555555")
        self.build_mini_ui(self.mini_frame)

    def build_mini_ui(self, parent):
        # 绑定拖动
        parent.bind("<Button-1>", self.start_move)
        parent.bind("<B1-Motion>", self.do_move)
        
        # 布局：左侧还原 -> 框选 -> 鼠标 -> (空白拖动区) -> 停止 -> 开始
        # 使用 pack(side=LEFT/RIGHT) 保证排列整齐
        
        btn_opts = {"bd": 0, "width": 4, "font": ("Arial", 10)}
        
        # 左侧功能区
        tk.Button(parent, text="⤢", bg="#444444", fg="white", command=self.toggle_mini_mode, **btn_opts).pack(side=tk.LEFT, padx=1, fill=tk.Y)
        tk.Button(parent, text="⛶", bg="#333333", fg="white", command=self.select_area, **btn_opts).pack(side=tk.LEFT, padx=1, fill=tk.Y)
        
        # 鼠标开关 (Mini版用颜色区分状态)
        self.btn_mini_cursor = tk.Button(parent, text="🖱️", bg="#333333", fg="#00ff00", command=self.toggle_cursor_mini, **btn_opts)
        self.btn_mini_cursor.pack(side=tk.LEFT, padx=1, fill=tk.Y)
        
        # 中间空白区 (用于拖动)
        spacer = tk.Label(parent, text="Mini Mode", bg="#333333", fg="#666666", font=("Segoe UI", 8))
        spacer.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        spacer.bind("<Button-1>", self.start_move)
        spacer.bind("<B1-Motion>", self.do_move)

        # 右侧控制区
        self.btn_mini_stop = tk.Button(parent, text="⬛", command=self.stop_recording, bg="#d13438", fg="white", state=tk.DISABLED, **btn_opts)
        self.btn_mini_stop.pack(side=tk.RIGHT, padx=1, fill=tk.Y)
        
        self.btn_mini_start = tk.Button(parent, text="▶", command=self.start_recording, bg="#0078d4", fg="white", **btn_opts)
        self.btn_mini_start.pack(side=tk.RIGHT, padx=1, fill=tk.Y)

    def toggle_cursor_mini(self):
        # Mini模式下的鼠标开关逻辑
        current = self.record_cursor_var.get()
        self.record_cursor_var.set(not current)
        color = "#00ff00" if not current else "#555555" # 绿色开启，灰色关闭
        self.btn_mini_cursor.config(fg=color)
        # 同步更新主界面的 Checkbutton (如果需要)

    def build_normal_ui(self, parent):
        # 标题栏 (固定高度)
        title_bar = tk.Frame(parent, bg=self.title_bg, height=35)
        title_bar.pack(side=tk.TOP, fill=tk.X)
        title_bar.pack_propagate(False)
        title_bar.bind("<Button-1>", self.start_move)
        title_bar.bind("<B1-Motion>", self.do_move)

        lbl_icon = tk.Label(title_bar, image=self.tk_icon, bg=self.title_bg, bd=0)
        lbl_icon.pack(side=tk.LEFT, padx=(10, 5))
        tk.Label(title_bar, text="全能录屏 Pro", bg=self.title_bg, fg="#dddddd", font=("Segoe UI", 10)).pack(side=tk.LEFT)

        btn_opts = {"bd": 0, "font": ("Arial", 11), "width": 4}
        tk.Button(title_bar, text="✕", bg=self.title_bg, fg="#aaaaaa", activebackground="#e81123", activeforeground="white", command=self.kill_app, **btn_opts).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Button(title_bar, text="⤢", bg=self.title_bg, fg="#aaaaaa", activebackground="#444444", activeforeground="white", command=self.toggle_mini_mode, **btn_opts).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Button(title_bar, text="─", bg=self.title_bg, fg="#aaaaaa", activebackground="#444444", activeforeground="white", command=self.minimize_to_tray, **btn_opts).pack(side=tk.RIGHT, fill=tk.Y)

        # 内容区 (弹性)
        content_frame = tk.Frame(parent, bg=self.bg_color)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 信息区 (居中)
        info_frame = tk.Frame(content_frame, bg=self.bg_color)
        info_frame.pack(expand=True)
        self.lbl_info = tk.Label(info_frame, text="Ready to Record", font=("Segoe UI", 16), bg=self.bg_color, fg="#666666")
        self.lbl_info.pack()

        # 底部控制栏 (固定高度，防止按钮变形)
        # 使用 pack(side=BOTTOM) 让它始终吸附底部
        bottom_bar = tk.Frame(content_frame, bg=self.bg_color, height=100)
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=20)
        
        # 按钮容器 (居中)
        btn_container = tk.Frame(bottom_bar, bg=self.bg_color)
        btn_container.pack(anchor=tk.CENTER)

        tk.Button(btn_container, text="⛶ 框选", command=self.select_area, bg="#333333", fg="white", font=("Segoe UI", 10), bd=0, padx=15, pady=8).pack(side=tk.LEFT, padx=10)
        
        self.btn_start = tk.Button(btn_container, text="▶ 开始", command=self.start_recording, bg="#0078d4", fg="white", font=("Segoe UI", 10, "bold"), bd=0, padx=20, pady=8)
        self.btn_start.pack(side=tk.LEFT, padx=10)
        
        self.btn_stop = tk.Button(btn_container, text="⬛ 停止", command=self.stop_recording, bg="#d13438", fg="white", font=("Segoe UI", 10), bd=0, padx=20, pady=8, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=10)

        # 鼠标开关
        chk_cursor = tk.Checkbutton(btn_container, text="录制鼠标", variable=self.record_cursor_var, bg=self.bg_color, fg="#dddddd", selectcolor="#333333", activebackground=self.bg_color, activeforeground="#ffffff", font=("Segoe UI", 10))
        chk_cursor.pack(side=tk.LEFT, padx=10)

        # 细边框
        tk.Frame(parent, bg="#444444", width=1).pack(side=tk.LEFT, fill=tk.Y)
        tk.Frame(parent, bg="#444444", width=1).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Frame(parent, bg="#444444", height=1).pack(side=tk.BOTTOM, fill=tk.X)

    # ==========================
    # 通用功能 (复用)
    # ==========================
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
                self.lbl_info.config(text=f"Region: {w}x{h}")
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
        
        if self.tray_icon:
            self.tray_icon.icon = self.rec_icon_img
            self.tray_icon.title = "Recording..."
        
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
            self.tray_icon.title = "Ready"
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
