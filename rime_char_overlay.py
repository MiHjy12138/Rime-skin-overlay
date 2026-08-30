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
import sys, os, json
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

# ============ 自启管理 ============
APP_NAME = 'RimeSkinOverlay'
VERSION = 'v1.0'

def _exe_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

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
        self._build_ui()

    def _build_ui(self):
        pad = {'padx': 12, 'pady': 4}
        frm = tk.Frame(self.root)
        frm.pack(**pad)

        # 顶部提示：支持格式 + 建议分辨率
        tk.Label(frm,
                 text='支持格式: PNG / JPG / WEBP / GIF / BMP    建议: 透明底 PNG，竖版 2:3（如 500x750）',
                 fg='#e67e22', font=('Microsoft YaHei', 9)).pack(anchor='w', pady=(0, 4))

        # ① 图片选择
        row1 = tk.Frame(frm)
        row1.pack(fill='x', pady=3)
        tk.Label(row1, text='① 图片:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.btn_img = tk.Button(row1, text='选择图片...', command=self._pick_image,
                                 font=('Microsoft YaHei', 10))
        self.btn_img.pack(side='left', padx=6)
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
        self._update_preview()

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

        # 图片（贴候选框侧边，应用缩放+微调；自适应缩放到预览框可见全貌）
        if self.cfg.get('image') and self.PIL:
            try:
                img = self._Image.open(self.cfg['image']).convert('RGBA')
                # 先自适应缩放：保证完整显示在预览区（宽 760 高 380，留边）
                # 候选框可能占大部分宽度，图片自适应到不超过预览区高度的一半
                max_pw, max_ph = 300, 170
                fit = min(max_pw / img.width, max_ph / img.height, 1.0)
                if fit < 1.0:
                    img = img.resize((max(1, int(img.width * fit)),
                                      max(1, int(img.height * fit))), self._Image.LANCZOS)
                # 再应用用户缩放
                if scale != 1.0:
                    img = img.resize((max(1, int(img.width * scale)),
                                      max(1, int(img.height * scale))), self._Image.LANCZOS)
                new_w, new_h = img.size
                # 贴边
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
        self.root.destroy()
        sys.exit(0)

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
        self.root.withdraw()
        self.off_x, self.off_y = 0, 0
        self.poll_ms = 50
        self.skin_ms = 2000

    def load_char(self):
        img_path = self.cfg['image']
        if self.PIL:
            img = self._Image.open(img_path).convert('RGBA')
            base_h = self.cfg.get('base_height', 300) * self.cfg.get('scale', 1.0)
            if img.height > 0:
                ratio = base_h / img.height
                new_w = max(1, int(img.width * ratio))
                img = img.resize((new_w, max(1, int(base_h))), self._Image.LANCZOS)
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
        self.visible = not self.visible
        if self.visible:
            self.root.deiconify()
        else:
            self.root.withdraw()

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
                if self.visible:
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
            # 选「重新配置」→ 走向导（向导保存后覆盖 config.json 并启动）
            def start(cfg2):
                # 重新配置保存后：检查单例再启动
                if _already_running():
                    _warn_already_running()
                    return
                FollowOverlay(cfg2).run()
            ConfigWizard(on_done=start).root.mainloop()
            return

        # 无配置 → 直接弹向导（单例检查在保存后）
        def start(cfg):
            if _already_running():
                _warn_already_running()
                return
            FollowOverlay(cfg).run()
        ConfigWizard(on_done=start).root.mainloop()
    except Exception as e:
        import traceback
        _write_log(f'[异常] {e}\n{traceback.format_exc()}')
        raise

if __name__ == '__main__':
    main()
