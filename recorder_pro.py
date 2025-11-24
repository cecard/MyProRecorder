import tkinter as tk
from tkinter import messagebox, Toplevel, Canvas
import threading
import time
import sys
import os
import ctypes
import numpy as np
import cv2
import mss
from PIL import Image, ImageDraw, ImageTk
import pystray
from pystray import MenuItem as item

# --- 系统设置 ---
myappid = 'mycompany.recorder.native.v1'
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

class ProfessionalRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("Recorder (Native Engine)")
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

        self.is_recording = False
        self.is_mini_mode = False
        self.start_time = 0
        self.region = None
        self.current_output_file = ""

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

    # --- 窗口拖拽逻辑 (不变) ---
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

    # --- 计时器 ---
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

    # --- 选区逻辑 ---
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
            # 强制偶数
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

    # --- 核心录制 (MSS + OpenCV) ---
    def start_recording(self):
        self.btn_start.config(state=tk.DISABLED, text="Init...")
        self.btn_stop.config(state=tk.DISABLED)
        
        # 保存路径
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.exists(desktop): desktop = os.path.expanduser("~")
        self.current_output_file = os.path.join(desktop, f"Rec_{int(time.time())}.mp4")
        
        threading.Thread(target=self._recording_loop, daemon=True).start()

    def _recording_loop(self):
        self.is_recording = True
        self.start_time = time.time()
        
        # UI 更新
        self.root.after(0, lambda: self.btn_start.config(text="▶ Recording", bg="#555"))
        self.root.after(0, lambda: self.btn_stop.config(state=tk.NORMAL))
        self.root.after(0, lambda: self.btn_mini_start.config(state=tk.DISABLED))
        self.root.after(0, lambda: self.btn_mini_stop.config(state=tk.NORMAL))
        self.root.after(0, self.update_timer)
        if self.tray_icon: self.tray_icon.icon = self.rec_icon_img

        # --- 初始化录制 ---
        try:
            with mss.mss() as sct:
                # 确定录制区域
                if self.region:
                    monitor = self.region
                else:
                    # 全屏：获取主显示器
                    monitor = sct.monitors[1] # monitors[1] 是主屏，monitors[0] 是所有屏组合
                
                width = monitor['width']
                height = monitor['height']

                # OpenCV VideoWriter 设置
                # mp4v 编码器是 Windows 兼容性最好的内置编码器之一
                fourcc = cv2.VideoWriter_fourcc(*'mp4v') 
                # FPS 设为 20 保证性能流畅
                fps = 20.0
                out = cv2.VideoWriter(self.current_output_file, fourcc, fps, (width, height))

                if not out.isOpened():
                    raise Exception("Could not open video writer. Try installing 'opencv-python'.")

                print(f"Recording started: {width}x{height} @ {fps}fps")

                # 循环抓屏
                while self.is_recording:
                    loop_start = time.time()

                    # 1. 极速抓屏
                    img = sct.grab(monitor)
                    
                    # 2. 转换为 Numpy 数组 (OpenCV 格式)
                    frame = np.array(img)
                    
                    # 3. 颜色空间转换 (MSS 是 BGRA, OpenCV 需要 BGR)
                    # 这一步极其高效，几乎不耗时
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                    # 4. 写入视频帧
                    out.write(frame)

                    # 5. 帧率控制
                    elapsed = time.time() - loop_start
                    wait_time = (1.0 / fps) - elapsed
                    if wait_time > 0:
                        time.sleep(wait_time)

                # 结束清理
                out.release()
                print("Recording stopped.")
                
                self.root.after(0, self._finish_success)

        except Exception as e:
            print(f"Error: {e}")
            self.root.after(0, lambda: messagebox.showerror("Error", f"Native Recording Failed:\n{e}"))
            self.root.after(0, self._reset_ui)

    def stop_recording(self):
        self.btn_stop.config(text="Saving...", state=tk.DISABLED)
        self.is_recording = False # 这会触发循环结束

    def _finish_success(self):
        if self.tray_icon: self.tray_icon.icon = self.icon_img
        self._reset_ui()
        
        if os.path.exists(self.current_output_file):
            try: subprocess.run(f'explorer /select,"{self.current_output_file}"')
            except: pass
            messagebox.showinfo("Success", "Video Saved!\n(Using MSS+OpenCV Engine)")

    def _reset_ui(self):
        self.btn_start.config(text="▶ Start", state=tk.NORMAL, bg="#1976d2")
        self.btn_stop.config(text="⬛ Stop", state=tk.DISABLED)
        self.btn_mini_start.config(state=tk.NORMAL, bg="#1976d2")
        self.btn_mini_stop.config(state=tk.DISABLED)
        self.lbl_main_timer.config(text="00:00:00", fg="#555")
        self.lbl_mini_timer.config(text="00:00:00", fg="#bbb")

    # --- UI Setup (不变) ---
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
