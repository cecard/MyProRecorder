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
    """ 获取资源绝对路径 """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# --- 2. 内部运行时图标 (用于托盘和窗口左上角) ---
def create_internal_icon(size=64):
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # 简单的红点图标
    draw.ellipse((0, 0, size, size), fill=(255, 255, 255))
    margin = size * 0.2
    draw.ellipse((margin, margin, size-margin, size-margin), fill=(234, 51, 35))
    return image

class ProfessionalRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("Pro Recorder")
        self.root.configure(bg="#1e1e1e")
        self.root.overrideredirect(True) # 无边框模式
        
        # --- 窗口居中初始化 ---
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        w, h = 520, 460
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.last_geometry = f"{w}x{h}+{x}+{y}"
        
        # 核心变量
        self.is_recording = False
        self.is_mini_mode = False
        self.process = None
        self.audio_thread = None
        self.region = None 
        self.ffmpeg_path = resource_path("ffmpeg.exe")
        self.tray_icon = None
        self.record_cursor_var = tk.BooleanVar(value=True)
        
        # 拖拽相关
        self._drag_data = {"x": 0, "y": 0, "mode": None}
        self.resize_margin = 10 # 边缘检测范围 (像素)
        
        # 图标资源
        self.icon_img = create_internal_icon(64)
        self.rec_icon_img = create_internal_icon(64) # 录制中也是红点，可根据需要改颜色
        self.tk_icon = ImageTk.PhotoImage(self.icon_img)
        self.root.iconphoto(True, self.tk_icon)

        # 构建界面
        self.setup_ui() 
        self.setup_tray()
        
        # 绑定鼠标事件 (核心：实现拖动和拉伸)
        self.root.bind("<Motion>", self.check_cursor)
        self.root.bind("<ButtonPress-1>", self.start_action)
        self.root.bind("<ButtonRelease-1>", self.stop_action)
        self.root.bind("<B1-Motion>", self.do_action)
        
        if not os.path.exists(self.ffmpeg_path):
            messagebox.showerror("Error", f"Kernel not found: {self.ffmpeg_path}")

    # ==========================
    # 边缘检测与光标变换
    # ==========================
    def check_cursor(self, event):
        if self.is_mini_mode: return
        
        x, y = event.x, event.y
        w, h = self.root.winfo_width(), self.root.winfo_height()
        m = self.resize_margin
        
        cursor = ""
        mode = None

        # 判定鼠标位置
        on_left = x < m
        on_right = x > w - m
        on_top = y < m
        on_bottom = y > h - m

        if on_top and on_left: cursor, mode = "sb_h_double_arrow", "nw"
        elif on_top and on_right: cursor, mode = "sb_h_double_arrow", "ne"
        elif on_bottom and on_left: cursor, mode = "sb_h_double_arrow", "sw"
        elif on_bottom and on_right: cursor, mode = "sb_h_double_arrow", "se"
        elif on_top: cursor, mode = "sb_v_double_arrow", "n"
        elif on_bottom: cursor, mode = "sb_v_double_arrow", "s"
        elif on_left: cursor, mode = "sb_h_double_arrow", "w"
        elif on_right: cursor, mode = "sb_h_double_arrow", "e"
        else: cursor, mode = "arrow", None

        # 只有在光标样式改变时才更新，防止闪烁
        if self.root.cget("cursor") != cursor:
            self.root.config(cursor=cursor)
            
        self._drag_data["hover_mode"] = mode

    # ==========================
    # 动作开始 (点击)
    # ==========================
    def start_action(self, event):
        # 记录起始坐标和窗口状态
        self._drag_data["start_x"] = event.x_root
        self._drag_data["start_y"] = event.y_root
        self._drag_data["win_x"] = self.root.winfo_x()
        self._drag_data["win_y"] = self.root.winfo_y()
        self._drag_data["start_w"] = self.root.winfo_width()
        self._drag_data["start_h"] = self.root.winfo_height()

        if self.is_mini_mode: 
            # Mini 模式只能移动
            self._drag_data["mode"] = "move"
            return

        mode = self._drag_data.get("hover_mode")
        if mode:
            # 如果在边缘，则是拉伸模式
            self._drag_data["mode"] = mode
        elif event.y < 40: # 点击了顶部标题栏区域
            # 移动模式
            self._drag_data["mode"] = "move"

    # ==========================
    # 动作结束 (释放)
    # ==========================
    def stop_action(self, event):
        self._drag_data["mode"] = None
        self.root.config(cursor="arrow")

    # ==========================
    # 动作执行 (拖拽中)
    # ==========================
    def do_action(self, event):
        mode = self._drag_data.get("mode")
        if not mode: return

        # 计算鼠标移动量
        dx = event.x_root - self._drag_data["start_x"]
        dy = event.y_root - self._drag_data["start_y"]

        if mode == "move":
            new_x = self._drag_data["win_x"] + dx
            new_y = self._drag_data["win_y"] + dy
            self.root.geometry(f"+{new_x}+{new_y}")
        else:
            # 拉伸计算
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
            
            # 最小尺寸限制
            w = max(400, w)
            h = max(300, h)
            
            self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ==========================
    # 模式切换逻辑
    # ==========================
    def toggle_mini_mode(self):
        if not self.is_mini_mode:
            # -> 切换到 Mini
            self.is_mini_mode = True
            self.last_geometry = self.root.geometry()
            
            # 计算左下角位置
            screen_h = self.root.winfo_screenheight()
            target_y = screen_h - 130 # 留出任务栏高度 + 一点间隙
            target_x = 20
            
            self.normal_frame.pack_forget()
            self.mini_frame.pack(fill=tk.BOTH, expand=True)
            self.root.geometry(f"380x50+{target_x}+{target_y}")
            self.root.attributes('-topmost', True)
        else:
            # -> 恢复正常
            self.is_mini_mode = False
            self.mini_frame.pack_forget()
            self.normal_frame.pack(fill=tk.BOTH, expand=True)
            
            try:
                self.root.geometry(self.last_geometry)
            except:
                self.root.geometry("520x460+300+300")
            self.root.attributes('-topmost', False)

    # ==========================
    # 界面构建
    # ==========================
    def setup_ui(self):
        self.bg_color = "#1e1e1e"
        self.title_bg = "#2d2d2d"
        
        # 正常界面
        self.normal_frame = tk.Frame(self.root, bg=self.bg_color)
        self.normal_frame.pack(fill=tk.BOTH, expand=True)
        self.build_normal_ui()
        
        # Mini 界面
        self.mini_frame = tk.Frame(self.root, bg="#333333", highlightthickness=1, highlightbackground="#555555")
        self.build_mini_ui()

    def build_mini_ui(self):
        p = self.mini_frame
        btn_s = {"bd": 0, "width": 4, "font": ("Arial", 10)}
        
        # Mini 栏按钮
        tk.Button(p, text="⤢", bg="#444", fg="white", command=self.toggle_mini_mode, **btn_s).pack(side=tk.LEFT, fill=tk.Y, padx=1)
        tk.Button(p, text="⛶", bg="#333", fg="white", command=self.select_area, **btn_s).pack(side=tk.LEFT, fill=tk.Y, padx=1)
        self.btn_mini_cur = tk.Button(p, text="🖱️", bg="#333", fg="#0f0", command=self.toggle_cursor_mini, **btn_s)
        self.btn_mini_cur.pack(side=tk.LEFT, fill=tk.Y, padx=1)
        
        # 拖动区
        tk.Label(p, text="Mini Mode", bg="#333", fg="#777").pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        
        # 控制区
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
        
        # 1. 标题栏
        t_bar = tk.Frame(p, bg=self.title_bg, height=40)
        t_bar.pack(side=tk.TOP, fill=tk.X)
        t_bar.pack_propagate(False)
        
        # 标题栏点击事件 (用于拖动)
        # 注意：这里我们依靠 root 的 bind 处理，所以 label 设为 transparent 感觉更好，或者让事件穿透
        # 简单起见，只要点击上方 40px 区域都会触发 move，无需给组件单独绑定
        
        icon_lbl = tk.Label(t_bar, image=self.tk_icon, bg=self.title_bg, bd=0)
        icon_lbl.pack(side=tk.LEFT, padx=10)
        tk.Label(t_bar, text="Pro Recorder", bg=self.title_bg, fg="#eee", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        
        btn_s = {"bd": 0, "width": 4, "font": ("Arial", 11)}
        tk.Button(t_bar, text="✕", bg=self.title_bg, fg="#aaa", activebackground="red", command=self.kill_app, **btn_s).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Button(t_bar, text="⤢", bg=self.title_bg, fg="#aaa", command=self.toggle_mini_mode, **btn_s).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Button(t_bar, text="─", bg=self.title_bg, fg="#aaa", command=self.minimize_to_tray, **btn_s).pack(side=tk.RIGHT, fill=tk.Y)

        # 2. 内容区
        c_frame = tk.Frame(p, bg=self.bg_color)
        c_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(c_frame, text="Ready to Record", font=("Segoe UI", 20), bg=self.bg_color, fg="#555").place(relx=0.5, rely=0.4, anchor=tk.CENTER)
        
        # 3. 底部固定控制栏
        b_frame = tk.Frame(c_frame, bg=self.bg_color, height=90)
        b_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=20)
        
        # 按钮行
        row = tk.Frame(b_frame, bg=self.bg_color)
        row.pack(anchor=tk.CENTER)
        
        tk.Button(row, text="⛶ Area", command=self.select_area, bg="#333", fg="white", bd=0, padx=15, pady=8).pack(side=tk.LEFT, padx=5)
        self.btn_start = tk.Button(row, text="▶ Start", command=self.start_recording, bg="#1976d2", fg="white", bd=0, padx=20, pady=8)
        self.btn_start.pack(side=tk.LEFT, padx=5)
        self.btn_stop = tk.Button(row, text="⬛ Stop", command=self.stop_recording, bg="#d32f2f", fg="white", bd=0, padx=20, pady=8, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=5)
        
        # 鼠标开关 (大号)
        tk.Checkbutton(row, text="Cursor", variable=self.record_cursor_var, bg=self.bg_color, fg="#ddd", selectcolor="#333", activebackground=self.bg_color, font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=10)
        
        # 装饰边框
        tk.Frame(p, bg="#444", width=1).pack(side=tk.LEFT, fill=tk.Y)
        tk.Frame(p, bg="#444", width=1).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Frame(p, bg="#444", height=1).pack(side=tk.BOTTOM, fill=tk.X)

    # ==========================
    # 核心功能函数 (必须保留)
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

    def start_recording(self):
        self.is_recording = True
        self.btn_start.config(state=tk.DISABLED, bg="#555")
        self.btn_stop.config(state=tk.NORMAL)
        self.btn_mini_start.config(state=tk.DISABLED, bg="#555")
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
        
        self.btn_start.config(state=tk.NORMAL, bg="#1976d2")
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_mini_start.config(state=tk.NORMAL, bg="#1976d2")
        self.btn_mini_stop.config(state=tk.DISABLED)
        messagebox.showinfo("Done", f"Saved!")

if __name__ == "__main__":
    root = tk.Tk()
    app = ProfessionalRecorder(root)
    root.mainloop()
