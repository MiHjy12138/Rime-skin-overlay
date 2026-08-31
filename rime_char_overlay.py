# -*- coding: utf-8 -*-
"""
rime_char_overlay.py —— Rime 皮肤外挂 v0.7
让小狼毫 (Rime/Weasel) 输入时，候选框旁边跟随显示图片。

v0.7 配置向导（所见即所得）：
  ① 选择图片（png/jpg/webp/gif/bmp）
  ② 预览区实时显示「候选框 + 图片」组合样式（按候选框类型变化）
  ③ 可一键「读取当前 Rime 候选框配置」自动识别布局类型
  ④ 候选框类型：单行横排 / 双行横排 / 竖排
  ⑤ 贴边方向：左 / 右
  ⑥ 缩放、水平微调、垂直微调 三滑块实时预览
  配置保存到 config.json，下次启动直接生效

原理：小狼毫候选框是 TSF 框架窗口（类名 ATL: 前缀），脚本每 50ms 枚举
可见窗口找到候选框，把透明置顶小窗贴到其左/右侧；无候选框自动隐藏。
皮肤联动：每 2 秒读 weasel.custom.yaml，光环颜色跟随当前皮肤主色调。

用法:
  双击 exe / python rime_char_overlay.py   → 有配置直接跑，无配置弹向导
  RimeSkinOverlay.exe 图片.png right        → 命令行模式（兼容）
  RimeSkinOverlay.exe --install/--uninstall → 自启管理

依赖: 主程序仅 Python 标准库；预览/光环需 Pillow（可选）
快捷键: Ctrl+Alt+C 隐藏/显示 | Ctrl+Alt+Q 退出 | 拖动微调 | 滚轮缩放 | 右键菜单
"""
import sys, os, json, time, threading
import tkinter as tk
from tkinter import filedialog, messagebox
import ctypes
from ctypes import wintypes

# ============ 单例检测（防重复启动）============
import ctypes as _ct
LOCK_NAME = 'RimeSkinOverlay_SingleInstance'
_mutex_handle = None  # 模块级保存，防 GC 释放互斥体

def _already_running():
    """用命名互斥体检测是否已有实例在跑（跨进程可靠）"""
    global _mutex_handle
    try:
        h = _ct.windll.kernel32.CreateMutexW(None, False, LOCK_NAME)
        err = _ct.windll.kernel32.GetLastError()
        if err == 183:  # ERROR_ALREADY_EXISTS → 已有实例
            _ct.windll.kernel32.CloseHandle(h)
            return True
        _mutex_handle = h  # 首次创建，保存句柄
        return False
    except Exception:
        return False

def _warn_already_running():
    """已有实例 → 弹窗提示"""
    try:
        import tkinter.messagebox as _mb
        r = tk.Tk()
        r.withdraw()
        _mb.showwarning('Rime 皮肤外挂',
                        '外挂已在运行中！\n\n'
                        '请勿重复启动。如需重启：\n'
                        '先关闭已运行的外挂（Ctrl+Alt+Q 或任务管理器结束 RimeSkinOverlay），\n'
                        '再双击本程序。')
        r.destroy()
    except Exception:
        pass

def _kill_existing():
    """杀掉所有已运行的 RimeSkinOverlay 实例（排除当前进程）"""
    import subprocess
    my_pid = os.getpid()
    killed = 0
    try:
        out = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             f"Get-CimInstance Win32_Process -Filter \"Name='RimeSkinOverlay.exe'\" | "
             f"Where-Object {{ $_.ProcessId -ne {my_pid} }} | "
             f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $_.ProcessId }}"],
            capture_output=True, text=True, timeout=15)
        if out.stdout and out.stdout.strip():
            killed = len([x for x in out.stdout.strip().split() if x.isdigit()])
    except Exception:
        pass
    return killed

# ============ 自启管理 ============
APP_NAME = 'RimeSkinOverlay'
VERSION = 'v1.2'

def _exe_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _icon_path(name):
    """图标文件路径：打包后从 _MEIPASS 取，源码模式取项目目录"""
    if getattr(sys, 'frozen', False):
        base = getattr(sys, '_MEIPASS', _exe_dir())
    else:
        base = _exe_dir()
    return os.path.join(base, name)


def set_window_icon(root, PIL=None):
    """设置窗口/任务栏图标为专属羽毛图标（替换 tkinter 默认 Tcl/Tk 图标）"""
    try:
        if PIL is None:
            from PIL import Image, ImageTk as _Tk
            PIL = (Image, _Tk)
        Image, ImageTk = PIL
        p = _icon_path('icon.png')
        if os.path.exists(p):
            img = ImageTk.PhotoImage(Image.open(p).resize((64, 64), Image.LANCZOS))
            root.iconphoto(True, img)
            root._icon_ref = img  # 防 GC 回收
    except Exception:
        pass

HERE = _exe_dir()
CONFIG_PATH = os.path.join(HERE, 'config.json')
RIME_DIR = os.path.join(os.environ.get('APPDATA', ''), 'Rime')
WEASEL_CUSTOM = os.path.join(RIME_DIR, 'weasel.custom.yaml')
WEASEL_BASE = os.path.join(RIME_DIR, 'weasel.yaml')

def _startup_lnk():
    return os.path.join(os.environ.get('APPDATA', ''),
                        r'Microsoft\Windows\Start Menu\Programs\Startup',
                        f'{APP_NAME}.lnk')

def install_autostart():
    import subprocess, tempfile
    exe = sys.argv[0]
    if not exe.lower().endswith('.exe'):
        print('自启仅支持 exe 版（请使用 RimeSkinOverlay.exe --install）')
        return 1
    lnk = _startup_lnk()
    vbs = os.path.join(tempfile.gettempdir(), '_skov_mklnk.vbs')
    with open(vbs, 'w', encoding='gbk') as f:
        f.write(
            'Set ws = CreateObject("WScript.Shell")\n'
            f'Set sc = ws.CreateShortcut("{lnk}")\n'
            f'sc.TargetPath = "{exe}"\n'
            'sc.WorkingDirectory = "' + HERE + '"\n'
            'sc.WindowStyle = 7\n'
            'sc.Description = "Rime Skin Overlay"\n'
            'sc.Save()\n'
        )
    try:
        subprocess.run(['cscript', '//nologo', vbs], check=True, timeout=15)
        print(f'已安装开机自启: {lnk}')
        return 0
    except Exception as e:
        print(f'安装自启失败: {e}')
        return 1
    finally:
        try:
            os.remove(vbs)
        except OSError:
            pass

def uninstall_autostart():
    lnk = _startup_lnk()
    if os.path.exists(lnk):
        os.remove(lnk)
        print(f'已移除开机自启: {lnk}')
    else:
        print('未找到自启项（可能未安装）')
    return 0

if '--install' in sys.argv:
    sys.exit(install_autostart())
if '--uninstall' in sys.argv:
    sys.exit(uninstall_autostart())

# ============ 配置 ============
DEFAULT_CONFIG = {
    'image': '',
    'layout': 'horizontal_double',  # horizontal_single / horizontal_double / vertical
    'side': 'right',
    'scale': 1.0,      # 0.2 ~ 2.0，基准高度 300px
    'offset_x': 0,     # 水平微调
    'offset_y': 0,     # 垂直微调
    'base_height': 300,
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding='utf-8') as f:
                cfg = json.load(f)
            if cfg.get('image') and os.path.exists(cfg['image']):
                return cfg
        except Exception:
            pass
    return None

def save_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def read_rime_layout():
    """
    读取当前 Rime 的候选框布局配置，返回：
      'horizontal_single' / 'horizontal_double' / 'vertical' / None(读取失败)
    判断逻辑：
      horizontal=false  → 竖排
      inline_preedit=false → 双行（候选窗内有编码行）
      否则 → 单行
    """
    def parse_file(path):
        data = {}
        if not os.path.exists(path):
            return data
        try:
            with open(path, encoding='utf-8') as f:
                for ln in f:
                    s = ln.strip()
                    if s.startswith('"') and ':' in s:
                        key, _, val = s.partition(':')
                        data[key.strip().strip('"')] = val.strip()
        except Exception:
            pass
        return data

    custom = parse_file(WEASEL_CUSTOM)
    base = parse_file(WEASEL_BASE)

    def get(flat_key):
        if flat_key in custom:
            return custom[flat_key]
        # base 是嵌套 yaml，这里只做简单查找
        for k, v in base.items():
            if k.endswith(flat_key):
                return v
        return None

    horizontal = get('style/horizontal')
    inline_preedit = get('style/inline_preedit')

    if horizontal is not None and str(horizontal).strip().lower() == 'false':
        return 'vertical'
    if inline_preedit is not None and str(inline_preedit).strip().lower() == 'false':
        return 'horizontal_double'
    return 'horizontal_single'

# ============ 皮肤联动 ============
def get_rime_accent():
    default = (0, 240, 255)
    try:
        with open(WEASEL_CUSTOM, encoding='utf-8') as f:
            cfg = {}
            for ln in f:
                s = ln.strip()
                if s.startswith('"') and ':' in s:
                    key, _, val = s.partition(':')
                    cfg[key.strip().strip('"')] = val.strip()
        scheme = cfg.get('style/color_scheme') or 'mint_fresh'
        color = cfg.get(f'preset_color_schemes/{scheme}/hilited_candidate_back_color')
        if color is None:
            color = cfg.get(f'preset_color_schemes/{scheme}/hilited_back_color')
        if color:
            v = int(color, 16) & 0xFFFFFF
            return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)
    except Exception:
        pass
    return default

def _flatten_alpha_for_tk(img_rgba, Image=None):
    """tkinter 显示用：把 RGBA 转成「品红抠色」图。

    tkinter 的 PhotoImage 不支持每像素 alpha，透明像素会露窗口底色；
    而 -transparentcolor 只精确匹配 #FF00FF。所以：
      1) alpha 二值化（>=128 不透明，<128 透明）——消除半透明像素（紫边根源）
      2) 透明区域填精确品红 (255,0,255) —— 让 transparentcolor 抠干净
      3) 输出 alpha 恒为 255（不保留原 alpha，避免 composite 泄漏半透明）
    注意：图内不能有纯品红像素（已知限制）。
    """
    if Image is None:
        from PIL import Image as _I
        Image = _I
    alpha = img_rgba.split()[3].point(lambda a: 255 if a >= 128 else 0)
    rgb = img_rgba.convert('RGB')  # 丢弃原 alpha，只保留颜色
    magenta = Image.new('RGB', img_rgba.size, (255, 0, 255))
    out = Image.composite(rgb, magenta, alpha)
    return out.convert('RGBA')  # alpha 全 255，无半透明


def add_glow(img_rgba, accent, radius_ratio=0.35, alpha=90):
    try:
        from PIL import ImageDraw
        w, h = img_rgba.size
        glow_h = int(h * 0.16)
        draw = ImageDraw.Draw(img_rgba)
        r, g, b = accent
        margin = int(w * (1 - radius_ratio) / 2)
        draw.ellipse((margin, h - glow_h, w - margin, h + int(glow_h * 0.4)),
                     fill=(r, g, b, alpha))
        draw.ellipse((int(w * 0.3), h - int(glow_h * 0.7), int(w * 0.7), h + int(glow_h * 0.15)),
                     fill=(r, g, b, min(255, alpha + 60)))
    except Exception:
        pass
    return img_rgba

# ============ 候选框检测 ============
user32 = ctypes.windll.user32

def find_candidate_window(layout='horizontal_double'):
    found = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value.startswith('ATL:'):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if 0 < w < 1300 and 0 < h < 1000 and h < w * 4:
                found.append((hwnd, rect))
        return True
    user32.EnumWindows(cb, 0)
    if found:
        found.sort(key=lambda f: f[1].top)
        return found[-1]
    return None

# ============ 图片预处理（裁剪 / 镜像 / 抠图）============
class ImagePreprocessDialog:
    """图片预处理窗口：裁剪 / 镜像反转 / 纯色背景抠图。

    应用后把处理结果保存为 exe 同目录 preprocessed.png，
    self.result_path 返回该路径；取消则为 None。
    交互：
      - 裁剪框可整体拖动、拖四角调整；右侧可锁定比例（1:1 / 2:3 / 3:4 / 9:16）
      - 镜像反转 = 水平翻转，实时预览
      - 抠图：自动检测四角背景色，或点击图片上任意背景区域手动指定；容差滑块微调
    """
    PRESETS = [
        ('原图', None),      # 初始 = 全图
        ('自由', 'free'),    # 任意比例
        ('1:1', 1.0),
        ('2:3', 2.0 / 3),
        ('3:4', 3.0 / 4),
        ('9:16', 9.0 / 16),
    ]

    def __init__(self, master, image_path):
        self.master = master
        self.src_path = image_path
        self.result_path = None
        try:
            from PIL import Image, ImageTk, ImageChops
        except ImportError:
            messagebox.showerror('缺少依赖', '图片预处理需要 Pillow 库，当前环境未安装。')
            raise
        self._Image, self._ImageTk = Image, ImageTk
        self._Chops = ImageChops

        self.orig = self._Image.open(image_path).convert('RGBA')
        self.work = self.orig.copy()       # 当前工作图（应用镜像后的状态）
        self.flipped = False
        self.crop = (0, 0, self.orig.width, self.orig.height)  # 原图坐标 (x0,y0,x1,y1)
        self.lock_ratio = None             # None=原图比例 / 'free'=自由 / float=锁定宽高比
        self.use_key = tk.BooleanVar(value=True)
        self.tol_var = tk.IntVar(value=20)
        self.bg_color = None               # 抠图背景色 (r,g,b)，None=未检测
        self.drag = None                   # 拖拽状态 (mode, ...)
        self.tk_img = None

        self.root = tk.Toplevel(master)
        self.root.title('图片预处理 - 裁剪 / 镜像 / 抠图')
        self.root.resizable(False, False)
        self.root.transient(master)
        self.root.protocol('WM_DELETE_WINDOW', self._cancel)
        self._build_ui()
        self._auto_detect_bg()
        self._auto_crop()
        self._draw()

    # ---------- UI ----------
    def _build_ui(self):
        main = tk.Frame(self.root)
        main.pack(fill='both', expand=True, padx=10, pady=8)

        # 左：画布
        self.cv = tk.Canvas(main, width=640, height=600, bg='#2b2b2b',
                            highlightthickness=1, highlightbackground='#666')
        self.cv.pack(side='left')
        self.cv.bind('<ButtonPress-1>', self._on_press)
        self.cv.bind('<B1-Motion>', self._on_drag)
        self.cv.bind('<ButtonRelease-1>', self._on_release)

        # 右：控制面板
        panel = tk.Frame(main, width=240)
        panel.pack(side='right', fill='y', padx=(10, 0))
        panel.pack_propagate(False)

        tk.Label(panel, text=f'原图 {self.orig.width}×{self.orig.height}',
                 font=('Microsoft YaHei', 9), fg='#888').pack(anchor='w')

        # ① 裁剪比例
        tk.Label(panel, text='① 裁剪比例:', font=('Microsoft YaHei', 10)).pack(anchor='w', pady=(8, 2))
        self.var_ratio = tk.IntVar(value=0)
        for i, (txt, _) in enumerate(self.PRESETS):
            tk.Radiobutton(panel, text=txt, variable=self.var_ratio, value=i,
                           font=('Microsoft YaHei', 9),
                           command=self._on_ratio).pack(anchor='w')
        self.lbl_crop = tk.Label(panel, text='裁剪: 全图', fg='#888',
                                 font=('Microsoft YaHei', 9))
        self.lbl_crop.pack(anchor='w', pady=(4, 0))
        tk.Button(panel, text='✂ 自动裁剪到内容', command=self._auto_crop,
                  font=('Microsoft YaHei', 9)).pack(anchor='w', pady=(4, 0))

        # ② 镜像反转
        tk.Label(panel, text='② 镜像反转:', font=('Microsoft YaHei', 10)).pack(anchor='w', pady=(10, 2))
        self.btn_flip = tk.Button(panel, text='水平翻转（当前: 否）', command=self._toggle_flip,
                                  font=('Microsoft YaHei', 9))
        self.btn_flip.pack(anchor='w', fill='x')

        # ③ 纯色背景抠图
        tk.Label(panel, text='③ 纯色背景抠图:', font=('Microsoft YaHei', 10)).pack(anchor='w', pady=(10, 2))
        tk.Checkbutton(panel, text='启用抠图（背景变透明）', variable=self.use_key,
                       font=('Microsoft YaHei', 9), command=self._draw).pack(anchor='w')
        row_tol = tk.Frame(panel)
        row_tol.pack(anchor='w', fill='x')
        tk.Label(row_tol, text='容差', font=('Microsoft YaHei', 9)).pack(side='left')
        tk.Scale(row_tol, from_=0, to=100, orient='horizontal', variable=self.tol_var,
                 command=lambda _: self._draw(), length=130,
                 font=('Microsoft YaHei', 8)).pack(side='left')
        self.bg_box = tk.Label(panel, text='背景色: 未检测', bg='#eee', fg='#666',
                               font=('Microsoft YaHei', 9), anchor='w')
        self.bg_box.pack(anchor='w', fill='x', pady=(2, 0))
        tk.Button(panel, text='重新自动检测', command=self._auto_detect_bg,
                  font=('Microsoft YaHei', 9)).pack(anchor='w', pady=2)
        tk.Label(panel, text='💡 也可点击图片上的背景区域\n手动指定背景色', fg='#e67e22',
                 font=('Microsoft YaHei', 9)).pack(anchor='w')

        # 按钮
        btns = tk.Frame(panel)
        btns.pack(anchor='w', fill='x', pady=(14, 0))
        tk.Button(btns, text='应用', command=self._apply, bg='#4CAF50', fg='white',
                  font=('Microsoft YaHei', 10, 'bold')).pack(side='left', padx=2)
        tk.Button(btns, text='重置', command=self._reset,
                  font=('Microsoft YaHei', 10)).pack(side='left', padx=2)
        tk.Button(btns, text='取消', command=self._cancel,
                  font=('Microsoft YaHei', 10)).pack(side='left', padx=2)

    # ---------- 坐标换算 ----------
    def _fit(self):
        """返回 (缩放比, 画布偏移ox, 画布偏移oy)：工作图 fit 到画布"""
        cw, ch = 640, 600
        iw, ih = self.work.size
        s = min(cw / iw, ch / ih)
        ox, oy = (cw - iw * s) / 2, (ch - ih * s) / 2
        return s, ox, oy

    def _to_canvas(self, x, y):
        s, ox, oy = self._fit()
        return ox + x * s, oy + y * s

    def _to_img(self, cx, cy):
        s, ox, oy = self._fit()
        return (cx - ox) / s, (cy - oy) / s

    # ---------- 绘制 ----------
    def _draw_checker(self, cv, ox, oy, w, h):
        """透明棋盘格背景（画在图下层）"""
        cell = 16
        c = '#4a4a4a'
        for i in range(int(w // cell) + 1):
            for j in range(int(h // cell) + 1):
                if (i + j) % 2 == 0:
                    cv.create_rectangle(ox + i * cell, oy + j * cell,
                                        ox + min((i + 1) * cell, w),
                                        oy + min((j + 1) * cell, h),
                                        fill=c, outline='')

    def _draw(self):
        cv = self.cv
        cv.delete('all')
        s, ox, oy = self._fit()
        disp_w, disp_h = self.work.width * s, self.work.height * s

        # 棋盘格 + 图片
        self._draw_checker(cv, ox, oy, disp_w, disp_h)
        disp = self.work
        if self.use_key.get() and self.bg_color:
            disp = self._chroma_key(self.work, self.bg_color, self.tol_var.get())
        disp_s = disp.resize((max(1, int(disp.width * s)), max(1, int(disp.height * s))),
                             self._Image.LANCZOS)
        self.tk_img = self._ImageTk.PhotoImage(disp_s)
        cv.create_image(ox, oy, anchor='nw', image=self.tk_img)

        # 裁剪框
        x0, y0, x1, y1 = self.crop
        cx0, cy0 = self._to_canvas(x0, y0)
        cx1, cy1 = self._to_canvas(x1, y1)
        # 框外遮罩（四块半透明黑）
        mask = '#000000'
        cv.create_rectangle(ox, oy, ox + disp_w, cy0, fill=mask, stipple='gray50', outline='')
        cv.create_rectangle(ox, cy1, ox + disp_w, oy + disp_h, fill=mask, stipple='gray50', outline='')
        cv.create_rectangle(ox, cy0, cx0, cy1, fill=mask, stipple='gray50', outline='')
        cv.create_rectangle(cx1, cy0, ox + disp_w, cy1, fill=mask, stipple='gray50', outline='')
        # 框线 + 四角手柄
        cv.create_rectangle(cx0, cy0, cx1, cy1, outline='#ffb300', width=2)
        for hx, hy in [(cx0, cy0), (cx1, cy0), (cx0, cy1), (cx1, cy1)]:
            cv.create_rectangle(hx - 5, hy - 5, hx + 5, hy + 5, fill='#ffb300', outline='white')
        # 信息
        cw, chh = int(x1 - x0), int(y1 - y0)
        self.lbl_crop.config(text=f'裁剪: {cw}×{chh}')

    # ---------- 裁剪交互 ----------
    def _on_press(self, e):
        x, y = self._to_img(e.x, e.y)
        x0, y0, x1, y1 = self.crop
        s, _, _ = self._fit()
        handle = 12 / s  # 命中区（原图单位）
        corners = {'tl': (x0, y0), 'tr': (x1, y0), 'bl': (x0, y1), 'br': (x1, y1)}
        for name, (cx, cy) in corners.items():
            if abs(x - cx) < handle and abs(y - cy) < handle:
                self.drag = ('corner', name)
                return
        if x0 <= x <= x1 and y0 <= y <= y1:
            self.drag = ('move', x, y)
            return
        # 框外点击：若启用抠图 → 手动指定背景色
        if self.use_key.get():
            ix, iy = int(x), int(y)
            if 0 <= ix < self.work.width and 0 <= iy < self.work.height:
                self.bg_color = self.work.getpixel((ix, iy))[:3]
                self._update_bg_box()
                self._draw()

    def _on_drag(self, e):
        if not self.drag:
            return
        x, y = self._to_img(e.x, e.y)
        W, H = self.work.size
        mode = self.drag[0]
        if mode == 'move':
            _, dx, dy = self.drag
            x0, y0, x1, y1 = self.crop
            mx, my = x - dx, y - dy
            nx0, ny0 = x0 + mx, y0 + my
            nx1, ny1 = x1 + mx, y1 + my
            if nx0 < 0:
                nx1 -= nx0; nx0 = 0
            if ny0 < 0:
                ny1 -= ny0; ny0 = 0
            if nx1 > W:
                nx0 -= nx1 - W; nx1 = W
            if ny1 > H:
                ny0 -= ny1 - H; ny1 = H
            self.crop = (int(nx0), int(ny0), int(nx1), int(ny1))
        elif mode == 'corner':
            name = self.drag[1]
            # 锚点 = 对角
            x0, y0, x1, y1 = self.crop
            ax, ay = {
                'tl': (x1, y1), 'tr': (x0, y1),
                'bl': (x1, y0), 'br': (x0, y0),
            }[name]
            self._set_crop_by_anchor(ax, ay, x, y, name)
        self._draw()

    def _on_release(self, _e):
        self.drag = None

    def _set_crop_by_anchor(self, ax, ay, cx, cy, name):
        """锚点 (ax,ay) 固定，拖动点 (cx,cy)，按锁定比例计算新裁剪框"""
        W, H = self.work.size
        cx = min(max(cx, 0.0), float(W))
        cy = min(max(cy, 0.0), float(H))
        w = abs(cx - ax)
        h = abs(cy - ay)
        r = self.lock_ratio
        if isinstance(r, float):
            # 保持宽高比：优先以宽度为准，超界则回退以高度为准（最多两轮修正）
            for _ in range(2):
                h = w / r
                if ay + h > H or ay - h < 0:
                    h = abs(cy - ay)
                    w = h * r
                    if ax + w > W or ax - w < 0:
                        w = abs(cx - ax)
                        h = w / r
                        break
                else:
                    break
            cx = ax + w if cx >= ax else ax - w
            cy = ay + h if cy >= ay else ay - h
        x0, x1 = (ax, cx) if ax < cx else (cx, ax)
        y0, y1 = (ay, cy) if ay < cy else (cy, ay)
        self.crop = (int(x0), int(y0), int(x1), int(y1))

    # ---------- 控件动作 ----------
    def _on_ratio(self):
        i = self.var_ratio.get()
        _, r = self.PRESETS[i]
        W, H = self.work.size
        if r is None:  # 原图
            self.lock_ratio = None
            self.crop = (0, 0, W, H)
        elif r == 'free':
            self.lock_ratio = 'free'
        else:
            self.lock_ratio = r
            # 以当前框中心为锚，调整为该比例（取图内最大内接）
            x0, y0, x1, y1 = self.crop
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            w = min(float(W), float(H) * r)
            h = w / r
            if h > H:
                h = float(H)
                w = h * r
            nx0, ny0 = cx - w / 2, cy - h / 2
            nx1, ny1 = cx + w / 2, cy + h / 2
            if nx0 < 0:
                nx1 -= nx0; nx0 = 0
            if ny0 < 0:
                ny1 -= ny0; ny0 = 0
            if nx1 > W:
                nx0 -= nx1 - W; nx1 = W
            if ny1 > H:
                ny0 -= ny1 - H; ny1 = H
            self.crop = (int(nx0), int(ny0), int(nx1), int(ny1))
        self._draw()

    def _toggle_flip(self):
        self.work = self.work.transpose(self._Image.FLIP_LEFT_RIGHT)
        self.flipped = not self.flipped
        self.btn_flip.config(text=f'水平翻转（当前: {"是" if self.flipped else "否"}）')
        # 裁剪框随镜像映射
        W = self.work.width
        x0, y0, x1, y1 = self.crop
        self.crop = (W - x1, y0, W - x0, y1)
        self._draw()

    # ---------- 抠图 ----------
    def _detect_bg(self, img):
        """取四角 5×5 区域平均色作为背景色"""
        w, h = img.size
        px = img.load()
        pts = [(4, 4), (w - 5, 4), (4, h - 5), (w - 5, h - 5)]
        r = g = b = n = 0
        for x, y in pts:
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    pr, pg, pb, _ = px[x + dx, y + dy]
                    r += pr; g += pg; b += pb; n += 1
        return (r // n, g // n, b // n)

    def _content_bbox(self, tol=24):
        """检测与背景色差异明显的内容包围盒 (left, top, right, bottom)；纯背景返回 None"""
        img = self.work
        r, g, b = img.split()[:3]
        L = self._Image.new
        bg = self.bg_color or (0, 0, 0)
        dr = self._Chops.difference(r, L('L', img.size, bg[0]))
        dg = self._Chops.difference(g, L('L', img.size, bg[1]))
        db = self._Chops.difference(b, L('L', img.size, bg[2]))
        dist = self._Chops.lighter(self._Chops.lighter(dr, dg), db)
        m = dist.point(lambda d, t=tol: 255 if d > t else 0)
        return m.getbbox()

    def _auto_crop(self):
        """自动裁剪：内容包围盒 + 3% 留白；内容占图超 95% 则保持全图"""
        W, H = self.work.size
        bbox = self._content_bbox()
        if not bbox:
            self.crop = (0, 0, W, H)
            self._draw()
            return
        l, t, r, b = bbox
        # 内容占比
        area_ratio = ((r - l) * (b - t)) / (W * H)
        if area_ratio > 0.95:
            self.crop = (0, 0, W, H)
            self._draw()
            return
        # 3% 留白
        pad_w, pad_h = int((r - l) * 0.03), int((b - t) * 0.03)
        x0 = max(0, l - pad_w)
        y0 = max(0, t - pad_h)
        x1 = min(W, r + pad_w)
        y1 = min(H, b + pad_h)
        self.crop = (x0, y0, x1, y1)
        self._draw()

    def _auto_detect_bg(self):
        self.bg_color = self._detect_bg(self.work)
        self._update_bg_box()
        self._draw()

    def _update_bg_box(self):
        if self.bg_color:
            r, g, b = self.bg_color
            self.bg_box.config(text=f'背景色: RGB({r},{g},{b})', bg='#%02x%02x%02x' % (r, g, b),
                               fg='white' if (r * 0.299 + g * 0.587 + b * 0.114) < 140 else '#222')
        else:
            self.bg_box.config(text='背景色: 未检测', bg='#eee', fg='#666')

    def _chroma_key(self, img, bg, tol):
        """色键抠图：与背景色距离 < lo 的像素变全透明，> hi 保持不透明，中间渐变过渡"""
        r, g, b = img.split()[:3]
        L = self._Image.new
        dr = self._Chops.difference(r, L('L', img.size, bg[0]))
        dg = self._Chops.difference(g, L('L', img.size, bg[1]))
        db = self._Chops.difference(b, L('L', img.size, bg[2]))
        dist = self._Chops.lighter(self._Chops.lighter(dr, dg), db)  # 逐像素 max
        lo = max(1, int(tol * 0.7))
        hi = max(lo + 1, int(tol * 1.4))
        alpha = dist.point(
            lambda d, lo=lo, hi=hi: 0 if d < lo else (255 if d > hi else int((d - lo) * 255 / (hi - lo))))
        out = img.copy()
        out.putalpha(alpha)
        return out

    # ---------- 结果 ----------
    def _reset(self):
        self.work = self.orig.copy()
        self.flipped = False
        self.crop = (0, 0, self.orig.width, self.orig.height)
        self.var_ratio.set(0)
        self.lock_ratio = None
        self.tol_var.set(20)
        self.use_key.set(True)
        self.btn_flip.config(text='水平翻转（当前: 否）')
        self._auto_detect_bg()
        self._auto_crop()

    def _apply(self):
        try:
            x0, y0, x1, y1 = [int(v) for v in self.crop]
            w, h = x1 - x0, y1 - y0
            if w < 2 or h < 2:
                messagebox.showwarning('提示', '裁剪区域太小！', parent=self.root)
                return
            out = self.work.crop((x0, y0, x1, y1))
            if self.use_key.get() and self.bg_color:
                out = self._chroma_key(out, self.bg_color, self.tol_var.get())
            out_path = os.path.join(HERE, 'preprocessed.png')
            out.save(out_path, 'PNG')
            self.result_path = out_path
            self.root.destroy()
        except Exception as e:
            messagebox.showerror('处理失败', str(e), parent=self.root)

    def _cancel(self):
        self.result_path = None
        self.root.destroy()


# ============ 配置向导（所见即所得）============
class ConfigWizard:
    LAYOUT_INFO = {
        'horizontal_single': ('单行横排', 460, 42),
        'horizontal_double': ('双行横排', 460, 84),
        'vertical': ('竖排', 96, 320),
    }

    def __init__(self, on_done):
        self.on_done = on_done
        self.cfg = dict(DEFAULT_CONFIG)
        self.PIL = False
        try:
            from PIL import Image, ImageTk
            self._Image, self._ImageTk = Image, ImageTk
            self.PIL = True
        except ImportError:
            pass
        self.tk_img = None

        self.root = tk.Tk()
        self.root.title(f'Rime 皮肤外挂 {VERSION} - 配置')
        self.root.resizable(False, False)
        self.root.protocol('WM_DELETE_WINDOW', self._on_cancel)
        if self.PIL:
            set_window_icon(self.root, (self._Image, self._ImageTk))
        self._build_ui()

    def _build_ui(self):
        pad = {'padx': 12, 'pady': 4}
        frm = tk.Frame(self.root)
        frm.pack(**pad)

        # 顶部提示：支持格式 + 建议分辨率
        tk.Label(frm,
                 text='支持格式: PNG / JPG / WEBP / GIF / BMP    建议: 竖版 2:3（如 500x750）\n💡 可选「图片预处理」：裁剪 / 镜像反转 / 纯色背景一键抠图',
                 fg='#e67e22', font=('Microsoft YaHei', 9), justify='left').pack(anchor='w', pady=(0, 4))

        # ① 图片选择
        row1 = tk.Frame(frm)
        row1.pack(fill='x', pady=3)
        tk.Label(row1, text='① 图片:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.btn_img = tk.Button(row1, text='选择图片...', command=self._pick_image,
                                 font=('Microsoft YaHei', 10))
        self.btn_img.pack(side='left', padx=6)
        self.btn_prep = tk.Button(row1, text='图片预处理', command=self._preprocess_image,
                                  font=('Microsoft YaHei', 10), state='disabled')
        self.btn_prep.pack(side='left', padx=2)
        self.lbl_img = tk.Label(row1, text='未选择', fg='#888', font=('Microsoft YaHei', 9))
        self.lbl_img.pack(side='left')

        # ② 预览区（候选框 + 图片 组合）
        tk.Label(frm, text='预览（候选框 + 图片组合样式，图片已自适应缩放）:',
                 font=('Microsoft YaHei', 9), fg='#555').pack(anchor='w', pady=(4, 0))
        self.canvas = tk.Canvas(frm, width=760, height=380, bg='#ffffff',
                                highlightthickness=1, highlightbackground='#ccc')
        self.canvas.pack(pady=4)

        # ③ 候选框类型（读取 Rime 配置按钮放这一行）
        row3 = tk.Frame(frm)
        row3.pack(fill='x', pady=3)
        tk.Label(row3, text='② 候选框类型:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.var_layout = tk.StringVar(value='horizontal_double')
        for text, val in [('单行横排', 'horizontal_single'),
                          ('双行横排', 'horizontal_double'),
                          ('竖排', 'vertical')]:
            tk.Radiobutton(row3, text=text, variable=self.var_layout, value=val,
                           font=('Microsoft YaHei', 9),
                           command=self._update_preview).pack(side='left', padx=4)
        tk.Button(row3, text='读取当前Rime配置(可选)', command=self._read_rime,
                  font=('Microsoft YaHei', 9)).pack(side='left', padx=12)

        # ④ 贴边方向
        row4 = tk.Frame(frm)
        row4.pack(fill='x', pady=3)
        tk.Label(row4, text='③ 贴边方向:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.var_side = tk.StringVar(value='right')
        for text, val in [('右侧', 'right'), ('左侧', 'left')]:
            tk.Radiobutton(row4, text=text, variable=self.var_side, value=val,
                           font=('Microsoft YaHei', 9),
                           command=self._update_preview).pack(side='left', padx=4)

        # ⑤ 缩放（独立一行）
        row5 = tk.Frame(frm)
        row5.pack(fill='x', pady=3)
        tk.Label(row5, text='④ 缩放:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.var_scale = tk.DoubleVar(value=1.0)
        tk.Scale(row5, from_=0.2, to=2.0, resolution=0.1, orient='horizontal',
                 variable=self.var_scale, length=220,
                 command=lambda _: self._update_preview(),
                 font=('Microsoft YaHei', 8)).pack(side='left', padx=4)
        self.lbl_scale = tk.Label(row5, text='1.0x', fg='#888', font=('Microsoft YaHei', 9))
        self.lbl_scale.pack(side='left')

        # ⑥ 水平微调（独立一行）
        row6 = tk.Frame(frm)
        row6.pack(fill='x', pady=3)
        tk.Label(row6, text='⑤ 水平微调:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.var_offx = tk.IntVar(value=0)
        tk.Scale(row6, from_=-200, to=200, orient='horizontal',
                 variable=self.var_offx, length=220,
                 command=lambda _: self._update_preview(),
                 font=('Microsoft YaHei', 8)).pack(side='left', padx=4)
        self.lbl_offx = tk.Label(row6, text='0px', fg='#888', font=('Microsoft YaHei', 9))
        self.lbl_offx.pack(side='left')

        # ⑦ 垂直微调（独立一行）
        row7 = tk.Frame(frm)
        row7.pack(fill='x', pady=3)
        tk.Label(row7, text='⑥ 垂直微调:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.var_offy = tk.IntVar(value=0)
        tk.Scale(row7, from_=-150, to=150, orient='horizontal',
                 variable=self.var_offy, length=220,
                 command=lambda _: self._update_preview(),
                 font=('Microsoft YaHei', 8)).pack(side='left', padx=4)
        self.lbl_offy = tk.Label(row7, text='0px', fg='#888', font=('Microsoft YaHei', 9))
        self.lbl_offy.pack(side='left')

        # ⑧ 按钮
        row8 = tk.Frame(frm)
        row8.pack(fill='x', pady=6)
        tk.Button(row8, text='保存并启动', command=self._save_and_start,
                  bg='#4CAF50', fg='white', font=('Microsoft YaHei', 10, 'bold')).pack(side='left', padx=4)
        tk.Button(row8, text='取消', command=self._on_cancel,
                  font=('Microsoft YaHei', 10)).pack(side='left', padx=4)
        tk.Label(row8, text='💡 保存后启动；下次双击可重新配置',
                 fg='#e67e22', font=('Microsoft YaHei', 11, 'bold')).pack(side='right')

    def _pick_image(self):
        path = filedialog.askopenfilename(
            title='选择图片',
            filetypes=[('图片文件', '*.png *.jpg *.jpeg *.webp *.gif *.bmp'),
                       ('所有文件', '*.*')])
        if not path:
            return
        self.cfg['image'] = path
        self.lbl_img.config(text=os.path.basename(path), fg='#333')
        self.btn_prep.config(state='normal')
        self._update_preview()

    def _preprocess_image(self):
        """打开图片预处理窗口：裁剪 / 镜像反转 / 纯色抠图"""
        if not self.cfg.get('image'):
            messagebox.showwarning('提示', '请先选择图片！')
            return
        if not self.PIL:
            messagebox.showerror('缺少依赖', '图片预处理需要 Pillow 库，当前环境未安装。')
            return
        try:
            dlg = ImagePreprocessDialog(self.root, self.cfg['image'])
            self.root.wait_window(dlg.root)
            if dlg.result_path:
                self.cfg['image'] = dlg.result_path
                self.lbl_img.config(text=os.path.basename(dlg.result_path) + '（已预处理）', fg='#2e7d32')
                self._update_preview()
        except Exception as e:
            messagebox.showerror('预处理失败', str(e))

    def _read_rime(self):
        """读取当前 Rime 候选框配置并应用到向导"""
        layout = read_rime_layout()
        if layout:
            self.var_layout.set(layout)
            msg = f'已读取当前 Rime 配置：{self.LAYOUT_INFO[layout][0]}'
            # 也尝试读皮肤高亮色，把预览候选框上色
            try:
                accent = get_rime_accent()
                msg += f'\n皮肤主色 RGB{accent}'
            except Exception:
                pass
            self._update_preview()
            messagebox.showinfo('读取成功', msg)
        else:
            messagebox.showwarning('读取失败', '未找到 Rime 配置文件，请手动选择候选框类型')

    def _update_preview(self):
        cv = self.canvas
        cv.delete('all')
        # 更新滑块数值显示
        if hasattr(self, 'lbl_scale'):
            self.lbl_scale.config(text=f'{float(self.var_scale.get()):.1f}x')
        if hasattr(self, 'lbl_offx'):
            self.lbl_offx.config(text=f'{int(self.var_offx.get())}px')
        if hasattr(self, 'lbl_offy'):
            self.lbl_offy.config(text=f'{int(self.var_offy.get())}px')
        layout = self.var_layout.get()
        side = self.var_side.get()
        scale = float(self.var_scale.get())
        offx = int(self.var_offx.get())
        offy = int(self.var_offy.get())

        # 候选框（居中于画布）
        cw, ch = self.LAYOUT_INFO[layout][1], self.LAYOUT_INFO[layout][2]
        base_x = (760 - cw) // 2
        base_y = (360 - ch) // 2
        # 候选框配色（用 Rime 皮肤主色，简单示意）
        accent = get_rime_accent() if self.PIL else (0, 137, 123)
        hex_acc = '#%02x%02x%02x' % accent
        # 候选框主体
        cv.create_rectangle(base_x, base_y, base_x + cw, base_y + ch,
                            fill='#f5f5f5', outline=hex_acc, width=2)
        # 候选框内的编码行 + 候选文字示意
        if layout == 'vertical':
            # 竖排：顶部高亮块 + 竖排候选
            cv.create_rectangle(base_x + 4, base_y + 4, base_x + cw - 4, base_y + 26,
                                fill=hex_acc)
            cv.create_text(base_x + cw // 2, base_y + 16, text='拼音', fill='white',
                           font=('Microsoft YaHei', 8))
            for i, wd in enumerate(['候选一', '候选二', '候选三', '候选四']):
                ty = base_y + 44 + i * 64
                cv.create_text(base_x + cw // 2, ty, text=wd,
                               font=('Microsoft YaHei', 9))
        else:
            # 横排：顶部编码行（双行才有）+ 底部候选
            if layout == 'horizontal_double':
                cv.create_rectangle(base_x + 4, base_y + 4, base_x + cw - 4, base_y + 30,
                                    fill=hex_acc)
                cv.create_text(base_x + 12, base_y + 17, text='拼音编码', anchor='w',
                               fill='white', font=('Microsoft YaHei', 8))
                cand_y = base_y + ch - 20
            else:
                cand_y = base_y + ch // 2
            # 候选文字 + 高亮第一个
            for i, wd in enumerate(['候选一', '候选二', '候选三', '候选四', '候选五']):
                cx = base_x + 14 + i * 88
                if i == 0:
                    cv.create_rectangle(cx - 4, cand_y - 14, cx + 74, cand_y + 14,
                                        fill=hex_acc)
                    cv.create_text(cx + 35, cand_y, text=wd, fill='white',
                                   font=('Microsoft YaHei', 9))
                else:
                    cv.create_text(cx + 35, cand_y, text=wd, fill='#333',
                                   font=('Microsoft YaHei', 9))
        cv.create_text(base_x + cw // 2, base_y + ch + 16,
                       text=self.LAYOUT_INFO[layout][0], fill='#888',
                       font=('Microsoft YaHei', 8))

        # 图片（贴候选框侧边；缩放逻辑与运行时一致：高度 = base_height×scale）
        if self.cfg.get('image') and self.PIL:
            try:
                img = self._Image.open(self.cfg['image']).convert('RGBA')
                # 与 FollowOverlay.load_char 完全相同的缩放逻辑
                base_h = 300 * scale
                if img.height > 0:
                    ratio = base_h / img.height
                    img = img.resize((max(1, int(img.width * ratio)),
                                      max(1, int(base_h))), self._Image.LANCZOS)
                new_w, new_h = img.size
                # 若图片+候选框超出画布，整体等比缩小（保持相对位置比例）
                total_w = new_w + 8 + cw
                total_h = max(new_h, ch)
                cv_w, cv_h = 760, 380
                if total_w > cv_w - 30 or total_h > cv_h - 30:
                    fit_all = min((cv_w - 30) / total_w, (cv_h - 30) / total_h, 1.0)
                    if fit_all < 1.0:
                        img = img.resize((max(1, int(new_w * fit_all)),
                                          max(1, int(new_h * fit_all))), self._Image.LANCZOS)
                        new_w, new_h = img.size
                        cw_s, ch_s = int(cw * fit_all), int(ch * fit_all)
                        base_x = (cv_w - cw_s) // 2
                        base_y = (cv_h - ch_s) // 2
                        cw, ch = cw_s, ch_s
                        # 重画候选框（缩小后的尺寸）
                        cv.delete('all')
                        cv.create_rectangle(base_x, base_y, base_x + cw, base_y + ch,
                                            fill='#f5f5f5', outline=hex_acc, width=2)
                        if layout == 'vertical':
                            cv.create_rectangle(base_x + 4, base_y + 4, base_x + cw - 4, base_y + 26,
                                                fill=hex_acc)
                            cv.create_text(base_x + cw // 2, base_y + 16, text='拼音', fill='white',
                                           font=('Microsoft YaHei', 8))
                        else:
                            if layout == 'horizontal_double':
                                cv.create_rectangle(base_x + 4, base_y + 4, base_x + cw - 4, base_y + 30,
                                                    fill=hex_acc)
                                cv.create_text(base_x + 12, base_y + 17, text='拼音编码', anchor='w',
                                               fill='white', font=('Microsoft YaHei', 8))
                # 贴边（偏移量与运行时一致）
                gap = 8
                if side == 'right':
                    ix = base_x + cw + gap + offx
                else:
                    ix = base_x - new_w - gap + offx
                iy = base_y + (ch - new_h) // 2 + offy
                # 预览不加光环（实际运行时有皮肤联动光环）
                self.tk_img = self._ImageTk.PhotoImage(img)
                cv.create_image(ix, iy, anchor='nw', image=self.tk_img)
                cv.create_rectangle(ix, iy, ix + new_w, iy + new_h,
                                    outline='#ff6a00', dash=(4, 2))
            except Exception as e:
                cv.create_text(380, 180, text=f'图片加载失败: {e}', fill='red',
                               font=('Microsoft YaHei', 9))

    def _save_and_start(self):
        self.cfg['layout'] = self.var_layout.get()
        self.cfg['side'] = self.var_side.get()
        self.cfg['scale'] = round(float(self.var_scale.get()), 2)
        self.cfg['offset_x'] = int(self.var_offx.get())
        self.cfg['offset_y'] = int(self.var_offy.get())
        if not self.cfg.get('image'):
            messagebox.showwarning('提示', '请先选择图片！')
            return
        save_config(self.cfg)
        self.root.destroy()
        self.on_done(self.cfg)

    def _on_cancel(self):
        # 只销毁窗口，让 mainloop 自然返回（不要 sys.exit，否则 Tk 清理会卡住）
        self.root.destroy()

# ============ 系统托盘 ============
class TrayIcon:
    """系统托盘图标：右键菜单 显示/隐藏、退出。

    解决无边框透明窗口不好关闭的问题（不用再进任务管理器）。
    图标用专属羽毛 icon.png，pystray 后台线程跑。
    """
    def __init__(self, overlay):
        self.overlay = overlay
        self.icon = None
        self._thread = None

    def start(self):
        try:
            import pystray
            from PIL import Image
            icon_path = _icon_path('icon.png')
            if not os.path.exists(icon_path):
                return
            img = Image.open(icon_path).resize((64, 64), Image.LANCZOS)
            menu = pystray.Menu(
                pystray.MenuItem('显示 / 隐藏 (Ctrl+Alt+C)', self._toggle, default=True),
                pystray.MenuItem('退出 (Ctrl+Alt+Q)', self._quit),
            )
            self.icon = pystray.Icon('RimeSkinOverlay', img, 'Rime 皮肤外挂', menu)
            self._thread = threading.Thread(target=self.icon.run, daemon=True)
            self._thread.start()
        except Exception:
            pass

    def _toggle(self, icon, item):
        try:
            self.overlay.toggle()
        except Exception:
            pass

    def _quit(self, icon, item):
        try:
            icon.stop()
        except Exception:
            pass
        try:
            self.overlay.root.after(0, self.overlay.root.destroy)
        except Exception:
            pass

    def stop(self):
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass


# ============ 主窗口 ============
class FollowOverlay:
    def __init__(self, cfg):
        self.cfg = cfg
        self.PIL = False
        try:
            from PIL import Image, ImageDraw, ImageTk
            self._Image, self._ImageTk = Image, ImageTk
            self.PIL = True
        except ImportError:
            pass

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-transparentcolor', '#FF00FF')
        self.root.configure(bg='#FF00FF')
        if self.PIL:
            set_window_icon(self.root, (self._Image, self._ImageTk))

        self.raw_img = None
        self.cur_accent = None
        self.img_mtime = None
        self.load_char()

        self.label = tk.Label(self.root, image=self.img, bg='#FF00FF', cursor='fleur')
        self.label.pack()

        self.label.bind('<ButtonPress-1>', self.on_press)
        self.label.bind('<B1-Motion>', self.on_drag)
        self.label.bind('<MouseWheel>', self.on_wheel)
        self.label.bind('<Button-3>', self.on_right_click)
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label='隐藏/显示 Ctrl+Alt+C', command=self.toggle)
        self.menu.add_command(label='退出 Ctrl+Alt+Q', command=self.root.destroy)
        self.root.bind('<Control-Alt-Key-c>', lambda e: self.toggle())
        self.root.bind('<Control-Alt-Key-q>', lambda e: self.root.destroy())

        self.visible = False
        self.pinned = False   # 手动固定显示（托盘/快捷键切换，不受候选框有无影响）
        self.root.withdraw()
        self.off_x, self.off_y = 0, 0
        self.poll_ms = 50
        self.skin_ms = 2000
        # 系统托盘（方便退出，不用进任务管理器）
        self.tray = TrayIcon(self)
        self.tray.start()

    def load_char(self):
        img_path = self.cfg['image']
        if self.PIL:
            img = self._Image.open(img_path).convert('RGBA')
            base_h = self.cfg.get('base_height', 300) * self.cfg.get('scale', 1.0)
            if img.height > 0:
                ratio = base_h / img.height
                new_w = max(1, int(img.width * ratio))
                img = img.resize((new_w, max(1, int(base_h))), self._Image.LANCZOS)
            # 修复紫边：缩放后 alpha 二值化 + 透明区填品红（配合 transparentcolor 抠色）
            img = _flatten_alpha_for_tk(img, self._Image)
            self.raw_img = img.copy()
            self.img_mtime = os.path.getmtime(img_path)
            # 不画光环（纯图片）
            self.cur_accent = None
            self.img = self._ImageTk.PhotoImage(img)
        else:
            self.img = tk.PhotoImage(file=img_path)
        self.w, self.h = self.img.width(), self.img.height()

    def check_skin(self):
        if self.PIL:
            try:
                mtime = os.path.getmtime(self.cfg['image'])
            except OSError:
                mtime = None
            if mtime != self.img_mtime:
                self.load_char()
                self.label.configure(image=self.img)
                self.root.geometry(f'{self.w}x{self.h}+{self.root.winfo_x()}+{self.root.winfo_y()}')
        self.root.after(self.skin_ms, self.check_skin)

    def on_press(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def on_drag(self, e):
        self.root.geometry(f'+{e.x_root - self._dx}+{e.y_root - self._dy}')

    def on_wheel(self, e):
        if e.delta > 0:
            self.img = self.img.zoom(2, 2)
        else:
            self.img = self.img.subsample(2, 2)
        self.w, self.h = self.img.width(), self.img.height()
        self.label.configure(image=self.img)
        self.root.geometry(f'{self.w}x{self.h}+{self.root.winfo_x()}+{self.root.winfo_y()}')

    def on_right_click(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    def toggle(self):
        """手动切换显示/隐藏（托盘菜单 / Ctrl+Alt+C）。
        手动显示后 pinned=True，poll 不再因无候选框自动隐藏；再次切换恢复自动模式。
        """
        self.pinned = not self.pinned
        if self.pinned:
            self.root.deiconify()
            self.visible = True
        else:
            self.root.withdraw()
            self.visible = False

    def poll(self):
        try:
            win = find_candidate_window(self.cfg.get('layout', 'horizontal_double'))
            if win:
                hwnd, rect = win
                cw, ch = rect.right - rect.left, rect.bottom - rect.top
                side = self.cfg.get('side', 'right')
                gap = 8
                if side == 'left':
                    x = rect.left - self.w - gap + self.off_x + self.cfg.get('offset_x', 0)
                else:
                    x = rect.right + gap + self.off_x + self.cfg.get('offset_x', 0)
                y = rect.top + (ch - self.h) // 2 + self.off_y + self.cfg.get('offset_y', 0)
                self.root.geometry(f'+{x}+{y}')
                if not self.visible:
                    self.root.deiconify()
                    self.visible = True
            else:
                # 无候选框：仅在非手动固定（pinned）时自动隐藏
                if not self.pinned and self.visible:
                    self.root.withdraw()
                    self.visible = False
        except Exception:
            pass
        self.root.after(self.poll_ms, self.poll)

    def run(self):
        self.root.after(self.poll_ms, self.poll)
        self.root.after(self.skin_ms, self.check_skin)
        self.root.mainloop()

# ============ 入口 ============
def _write_log(msg):
    """写运行日志到 exe 同目录 error.log（排查用）"""
    try:
        with open(os.path.join(HERE, 'error.log'), 'a', encoding='utf-8') as f:
            f.write(f'{msg}\n')
    except Exception:
        pass

def _ask_action():
    """弹选择框：直接启动 / 重新配置"""
    import tkinter.messagebox as _mb
    r = tk.Tk()
    r.withdraw()
    r.attributes('-topmost', True)
    ans = _mb.askyesno(
        'Rime 皮肤外挂',
        '检测到已保存的配置。\n\n'
        '选「是」= 直接启动外挂（使用现有配置）\n'
        '选「否」= 重新配置（打开配置向导）\n\n'
        '提示：选「否」后如未保存新配置，下次启动仍会用旧配置。',
        icon='question')
    r.destroy()
    return ans  # True=直接启动, False=重新配置

def main():
    try:
        argv = [a for a in sys.argv if not a.startswith('--')]
        if len(argv) >= 2 and not argv[1].startswith('-'):
            # 命令行模式（临时指定图片），单例检查
            if _already_running():
                _warn_already_running()
                return
            cfg = dict(DEFAULT_CONFIG)
            cfg['image'] = argv[1]
            if len(argv) >= 3:
                cfg['side'] = argv[2]
            FollowOverlay(cfg).run()
            return

        cfg = load_config()
        if cfg:
            # 有配置 → 先弹选择框（单例检查在这之后）
            try:
                start_now = _ask_action()
            except Exception:
                start_now = True
            if start_now:
                # 选「直接启动」→ 才检查单例
                if _already_running():
                    _warn_already_running()
                    return
                _write_log(f'[启动] 使用现有配置: {cfg}')
                FollowOverlay(cfg).run()
                return
            # 选「重新配置」→ 走向导（保存后杀掉旧实例，用新配置启动）
            def start(cfg2):
                # 用户主动重新配置：保存后替换旧实例
                if _already_running():
                    _kill_existing()
                    time.sleep(1)
                FollowOverlay(cfg2).run()
            ConfigWizard(on_done=start).root.mainloop()
            return

        # 无配置 → 直接弹向导（保存后若已有实例则替换）
        def start(cfg):
            if _already_running():
                _kill_existing()
                time.sleep(1)
            FollowOverlay(cfg).run()
        ConfigWizard(on_done=start).root.mainloop()
    except Exception as e:
        import traceback
        _write_log(f'[异常] {e}\n{traceback.format_exc()}')
        raise

if __name__ == '__main__':
    main()
