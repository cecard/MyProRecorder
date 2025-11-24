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

# 引入 Windows API 库 (Boldly introduced!)
import win32gui
import win32con
import win32api

# --- Windows DPI 适配 ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# --- 生成程序内部用的图标 (窗口左上角和托盘) ---
# 注意：EXE文件的图标由 Build 脚本中的 Base64 决定，这里是运行时图标
def create_eye_icon(size=64, style="normal"):
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # 绘制更精致的图标
    draw.ellipse((2, 2, size-2, size-2), fill=(240, 240, 240), outline=(180, 180, 180))
    # 虹膜
    iris_color = (0, 120, 212) if style == "normal" else (220, 50, 50)
    c = size / 2
    r_iris = size * 0.28
    draw.ellipse((c-r_iris, c-r_iris, c+r_iris, c+r_iris), fill=iris_color)
    # 瞳孔
    r_pupil = size * 0.12
    draw.ellipse((c-r_pupil, c-r_pupil, c+r_pupil, c+r_pupil), fill=(20, 20, 20))
    # 高光
    r_hl = size * 0.08
    draw.ellipse((c+r_iris*0.3, c-r_iris*0.5, c+r_iris*0.3+r_hl, c-r_iris*0.5+r_hl), fill=(255, 255, 255, 240))
    return image

class ProfessionalRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("全能录屏 Pro")
        self.root.geometry("520x450")
        self.root.configure(bg="#1e1e1e")
        self.root.overrideredirect(True) # 无边框
        
        # 核心变量
        self.is_recording = False
        self.is_mini_mode = False
        self.process = None
        self.audio_thread = None
        self.region = None 
        self.ffmpeg_path = resource_path("ffmpeg.exe")
        self.tray_icon = None
        self.record_cursor_var = tk.BooleanVar(value=True)
        self.last_geometry = "520x450+300+300"
        
        # 图标资源
        self.icon_img = create_eye_icon(64, "normal")
        self.rec_icon_img = create_eye_icon(64, "record")
        self.tk_icon = ImageTk.PhotoImage(self.icon_img)
        self.root.iconphoto(True, self.tk_icon)

        # 初始化UI
        self.setup_ui() 
        self.setup_tray()
        
        # === 核心：启用 Windows 原生窗口拖拽 hook ===
        self.root.after(100, self.hook_window)
        
        if not os.path.exists(self.ffmpeg_path):
            messagebox.showerror("致命错误", f"找不到内核文件: {self.ffmpeg_path}")

    # ========================================================
    # Windows Native Resizing (The "Browser-like" Magic)
    # ========================================================
    def hook_window(self):
        # 获取 Tkinter 窗口句柄
        self.hwnd = win32gui.GetParent(self.root.winfo_id())
        # 替换窗口过程函数 (Window Procedure)
        self.old_wnd_proc = win32gui.SetWindowLong(self.hwnd, win32con.GWL_WNDPROC, self.wnd_proc)

    def wnd_proc(self, hwnd, msg, wparam, lparam):
        # 处理 WM_NCHITTEST 消息 (告诉 Windows 鼠标点在了窗口的哪里)
        if msg == win32con.WM_NCHITTEST:
            # 获取鼠标位置
            x = win32api.LOWORD(lparam)
            y = win32api.HIWORD(lparam)
            
            # 将屏幕坐标转换为窗口相对坐标
            window_rect = win32gui.GetWindowRect(hwnd)
            win_x, win_y = window_rect[0], window_rect[1]
            win_w = window_rect[2] - win_x
            win_h = window_rect[3] - win_y
            
            # 边框判定范围 (像素)
            border_width = 8 
            
            rel_x = x - win_x
            rel_y = y - win_y
            
            # Mini 模式下禁止调整大小，只允许拖动标题栏
            if self.is_mini_mode:
                return win32con.HTCAPTION

            # 判定顺序：角落 -> 边缘 -> 标题栏 -> 客户区
            if rel_x < border_width and rel_y < border_width: return win32con.HTTOPLEFT
            if rel_x > win_w - border_width and rel_y < border_width: return win32con.HTTOPRIGHT
            if rel_x < border_width and rel_y > win_h - border_width: return win32con.HTBOTTOMLEFT
            if rel_x > win_w - border_width and rel_y > win_h - border_width: return win32con.HTBOTTOMRIGHT
            
            if rel_x < border_width: return win32con.HTLEFT
            if rel_x > win_w - border_width: return win32con.HTRIGHT
            if rel_y < border_width: return win32con.HTTOP
            if rel_y > win_h - border_width: return win32con.HTBOTTOM
            
            # 标题栏区域判定 (高度35像素，排除右上角按钮区)
            if rel_y < 35 and rel_x < win_w - 120:
                return win32con.HTCAPTION
            
            return win32con.HTCLIENT

        # 其他消息交给默认处理程序
        return win32gui.CallWindowProc(self.old_wnd_proc, hwnd, msg, wparam, lparam)

    # ==========================
    # 模式切换
    # ==========================
    def toggle_mini_mode(self):
        if not self.is_mini_mode:
            # === 切换到 Mini ===
            self.is_mini_mode = True
            self.last_geometry = self.root.geometry()
            
            # 屏幕左下角 (State bar above taskbar)
            screen_h = self.root.winfo_screenheight()
            target_y = screen_h - 90 
            target_x = 20
            
            self.normal_frame.pack_forget()
            self.mini_frame.pack(fill=tk.BOTH, expand=True)
            self.root.geometry(f"380x40+{target_x}+{target_y}") # 紧凑的长条
            self.root.attributes('-topmost', True)
        else:
            # === 恢复正常 ===
            self.is_mini_mode = False
            self.mini_frame.pack_forget()
            self.normal_frame.pack(fill=tk.BOTH, expand=True)
            try:
                # 恢复记忆的尺寸和位置
                geo = self.last_geometry.replace('x', '+').split('+')
                self.root.geometry(f"{geo[0]}x{geo[1]}+{geo[2]}+{geo[3]}")
            except:
                self.root.geometry("520x450+300+300")
            self.root.attributes('-topmost', False)

    # ==========================
    # UI 构建
    # ==========================
    def setup_ui(self):
        self.bg_color = "#1e1e1e"
        self.title_bg = "#2d2d2d"
        
        # 普通界面容器
        self.normal_frame = tk.Frame(self.root, bg=self.bg_color)
        self.normal_frame.pack(fill=tk.BOTH, expand=True)
        self.build_normal_ui(self.normal_frame)
        
        # Mini界面容器
        self.mini_frame = tk.Frame(self.root, bg="#333333", highlightthickness=1, highlightbackground="#555555")
        self.build_mini_ui(self.mini_frame)

    def build_mini_ui(self, parent):
        # Mini 模式包含所有功能按钮
        # 布局：[还原] | [框选] [鼠标] || [状态文字(拖动)] || [停止] [开始]
        btn_opts = {"bd": 0, "width": 4, "font": ("Arial", 10)}
        
        # 还原
        tk.Button(parent, text="⤢", bg="#444444", fg="white", command=self.toggle_mini_mode, **btn_opts).pack(side=tk.LEFT, fill=tk.Y, padx=1)
        
        # 框选
        tk.Button(parent, text="⛶", bg="#333333", fg="white", command=self.select_area, **btn_opts).pack(side=tk.LEFT, fill=tk.Y, padx=1)
        
        # 鼠标开关 (动态颜色)
        self.btn_mini_cursor = tk.Button(parent, text="🖱️", bg="#333333", fg="#00ff00", command=self.toggle_cursor_mini, **btn_opts)
        self.btn_mini_cursor.pack(side=tk.LEFT, fill=tk.Y, padx=1)
        
        # 拖动区
        spacer = tk.Label(parent, text="Mini Bar", bg="#333333", fg="#777777", font=("Segoe UI", 8))
        spacer.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        # 注意：因为用了 native hook，这里的拖动会被 WM_NCHITTEST 接管为 HTCAPTION，所以无需 bind
        
        # 停止
        self.btn_mini_stop = tk.Button(parent, text="⬛", command=self.stop_recording, bg="#d13438", fg="white", state=tk.DISABLED, **btn_opts)
        self.btn_mini_stop.pack(side=tk.RIGHT, fill=tk.Y, padx=1)
        
        # 开始
        self.btn_mini_start = tk.Button(parent, text="▶", command=self.start_recording, bg="#0078d4", fg="white", **btn_opts)
        self.btn_mini_start.pack(side=tk.RIGHT, fill=tk.Y, padx=1)

    def toggle_cursor_mini(self):
        cur = self.record_cursor_var.get()
        self.record_cursor_var.set(not cur)
        self.btn_mini_cursor.config(fg="#00ff00" if not cur else "#555555")

    def build_normal_ui(self, parent):
        # 1. 顶部标题栏 (Native Hook 会识别这个区域为 Caption)
        title_bar = tk.Frame(parent, bg=self.title_bg, height=35)
        title_bar.pack(side=tk.TOP, fill=tk.X)
        title_bar.pack_propagate(False)

        lbl_icon = tk.Label(title_bar, image=self.tk_icon, bg=self.title_bg, bd=0)
        lbl_icon.pack(side=tk.LEFT, padx=(10, 5))
        tk.Label(title_bar, text="全能录屏 Pro", bg=self.title_bg, fg="#dddddd", font=("Segoe UI", 10)).pack(side=tk.LEFT)

        # 窗口控制按钮 (右上角)
        btn_ctrl = {"bd": 0, "font": ("Arial", 11), "width": 4}
        # 关闭
        tk.Button(title_bar, text="✕", bg=self.title_bg, fg="#aaaaaa", activebackground="#e81123", activeforeground="white", command=self.kill_app, **btn_ctrl).pack(side=tk.RIGHT, fill=tk.Y)
        # 切换Mini
        tk.Button(title_bar, text="⤢", bg=self.title_bg, fg="#aaaaaa", activebackground="#444444", activeforeground="white", command=self.toggle_mini_mode, **btn_ctrl).pack(side=tk.RIGHT, fill=tk.Y)
        # 最小化
        tk.Button(title_bar, text="─", bg=self.title_bg, fg="#aaaaaa", activebackground="#444444", activeforeground="white", command=self.minimize_to_tray, **btn_ctrl).pack(side=tk.RIGHT, fill=tk.Y)

        # 2. 中间信息区 (自适应)
        content_frame = tk.Frame(parent, bg=self.bg_color)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        info_container = tk.Frame(content_frame, bg=self.bg_color)
        info_container.place(relx=0.5, rely=0.4, anchor=tk.CENTER)
        
        self.lbl_info = tk.Label(info_container, text="Ready to Record", font=("Segoe UI", 18), bg=self.bg_color, fg="#666666")
        self.lbl_info.pack(pady=10)
        tk.Label(info_container, text="High Performance • System Audio • Native UI", font=("Segoe UI", 9), bg=self.bg_color, fg="#444444").pack()

        # 3. 底部控制栏 (固定在底部，按钮不随窗口拉伸变形)
        # 使用 Frame 容器，pack side=BOTTOM
        bottom_area = tk.Frame(content_frame, bg=self.bg_color, height=80)
        bottom_area.pack(side=tk.BOTTOM, fill=tk.X, pady=20)
        
        # 按钮居中容器
        btn_row = tk.Frame(bottom_area, bg=self.bg_color)
        btn_row.pack(anchor=tk.CENTER)

        # 框选
        tk.Button(btn_row, text="⛶ 框选", command=self.select_area, bg="#333333", fg="white", font=("Segoe UI", 10), bd=0, padx=15, pady=8).pack(side=tk.LEFT, padx=8)
        
        # 开始
        self.btn_start = tk.Button(btn_row, text="▶ 开始录制", command=self.start_recording, bg="#0078d4", fg="white", font=("Segoe UI", 10, "bold"), bd=0, padx=20, pady=8)
        self.btn_start.pack(side=tk.LEFT, padx=8)
        
        # 停止
        self.btn_stop = tk.Button(btn_row, text="⬛ 停止", command=self.stop_recording, bg="#d13438", fg="white", font=("Segoe UI", 10), bd=0, padx=20, pady=8, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=8)
        
        # 鼠标开关
        chk = tk.Checkbutton(btn_row, text="录制鼠标", variable=self.record_cursor_var, bg=self.bg_color, fg="#dddddd", selectcolor="#333333", activebackground=self.bg_color, activeforeground="#ffffff", font=("Segoe UI", 10))
        chk.pack(side=tk.LEFT, padx=8)

        # 装饰性细边框
        tk.Frame(parent, bg="#444444", width=1).pack(side=tk.LEFT, fill=tk.Y)
        tk.Frame(parent, bg="#444444", width=1).pack(side=tk.RIGHT, fill=tk.Y)
        tk.Frame(parent, bg="#444444", height=1).pack(side=tk.BOTTOM, fill=tk.X)

    # ==========================
    # 逻辑功能 (保持不变)
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
                self.lbl_info.config(text=f"Selected Region: {w}x{h}")
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
