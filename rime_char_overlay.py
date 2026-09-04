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

原理：小狼毫候选框是 TSF 框架窗口（类名 ATL: 前缀）。脚本用 WinEventHook
（LOCATIONCHANGE/DESTROY/SHOW/HIDE）事件驱动定位：后台守护线程监听事件，
只对缓存候选框句柄置位；主线程消费后 O(1) GetWindowRect + SetWindowPos
把透明置顶小窗贴到其左/右侧；无候选框自动隐藏（带 150ms 去抖防闪烁）。
候选框销毁重建由 SHOW 事件/低频全扫自愈；hook 不可用时退化为心跳低频全扫。
皮肤联动：每 2 秒读 weasel.custom.yaml，光环颜色跟随当前皮肤主色调。

用法:
  双击 exe / python rime_char_overlay.py   → 有配置直接跑，无配置弹向导
  RimeSkinOverlay.exe 图片.png right        → 命令行模式（兼容）
  RimeSkinOverlay.exe --install/--uninstall → 自启管理

依赖: 主程序仅 Python 标准库；预览/光环需 Pillow（可选）
快捷键: Ctrl+Alt+C 隐藏/显示 | Ctrl+Alt+Q 退出 | 拖动微调 | 滚轮缩放 | 右键菜单
"""
import sys, os, json, time, threading, re, queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog
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
VERSION = 'v1.5'

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
            img = ImageTk.PhotoImage(Image.open(p).resize((64, 64), Image.LANCZOS), master=root)
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
    'layer': 'above',  # 图层：above=图片在候选框上方 / below=候选框压住图片（仅 贴边=中间 重叠时生效）
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


# ============ 多皮肤管理 ============
# 皮肤档案 = 图片 + 全套参数，存 exe 同目录 skins/<皮肤名>/（image.<ext> + skin.json）
SKINS_DIR = os.path.join(HERE, 'skins')


def _valid_skin_name(name):
    """皮肤名合法性：1-40 字符，中英文/数字/空格/横线/下划线；防路径穿越"""
    if not name or len(name) > 40:
        return False
    import re as _re
    return bool(_re.fullmatch(r'[\w\u4e00-\u9fff][\w\u4e00-\u9fff \-]{0,39}', name))


def list_skins():
    """列出所有已保存皮肤：返回 [(名称, cfg), ...] 按名称排序；损坏条目跳过"""
    if not os.path.isdir(SKINS_DIR):
        return []
    out = []
    for d in sorted(os.listdir(SKINS_DIR)):
        p = os.path.join(SKINS_DIR, d)
        j = os.path.join(p, 'skin.json')
        if not (os.path.isdir(p) and os.path.exists(j)):
            continue
        try:
            with open(j, encoding='utf-8') as f:
                cfg = json.load(f)
            cfg['name'] = d
            img = cfg.get('image')
            if img and os.path.exists(img):
                out.append((d, cfg))
        except Exception:
            continue
    return out


def save_skin(name, cfg):
    """把当前配置 + 图片副本保存为皮肤档案；返回保存后的 cfg（含 name），失败抛异常"""
    if not _valid_skin_name(name):
        raise ValueError('皮肤名称限 1-40 字符（中文/字母/数字/空格/横线）')
    src = cfg.get('image')
    if not src or not os.path.exists(src):
        raise ValueError('图片不存在，无法保存皮肤')
    d = os.path.join(SKINS_DIR, name)
    os.makedirs(d, exist_ok=True)
    ext = os.path.splitext(src)[1].lower() or '.png'
    dst_img = os.path.join(d, 'image' + ext)
    if os.path.normpath(src) != os.path.normpath(dst_img):
        import shutil
        shutil.copy2(src, dst_img)
    scfg = dict(cfg)
    scfg['image'] = dst_img
    scfg['name'] = name
    with open(os.path.join(d, 'skin.json'), 'w', encoding='utf-8') as f:
        json.dump(scfg, f, ensure_ascii=False, indent=2)
    return scfg


def delete_skin(name):
    """删除皮肤档案；返回是否删除成功（带路径前缀防护）"""
    d = os.path.join(SKINS_DIR, name)
    base = os.path.normpath(SKINS_DIR) + os.sep
    if os.path.isdir(d) and os.path.normpath(d).startswith(base):
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        return not os.path.exists(d)
    return False


def find_skin(name):
    """按名称查皮肤 cfg；不存在返回 None"""
    for n, cfg in list_skins():
        if n == name:
            return cfg
    return None

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

# 默认抠色键 = 品红（-transparentcolor 最稳的基准色）
MAGENTA = (255, 0, 255)


def _key_hex(rgb):
    """RGB 三元组 → '#RRGGBB'（tkinter transparentcolor 格式）"""
    return '#%02X%02X%02X' % rgb


def _release_photo(photo):
    """主动释放 PhotoImage 的 tcl 端 image（不等 Python GC 的 __del__）。

    高频创建 PhotoImage（滑块/皮肤切换/预处理对话框）时，被 pop 的旧对象若只靠
    GC 触发 image delete，时机不确定且会堆积 tcl image table；显式同步删除
    （str(photo) 返回 pyimageN，公开行为）让生命周期可预测。PIL __del__ 有兜底，
    重复 delete 无噪音。
    """
    try:
        if photo is not None:
            photo.tk.call('image', 'delete', str(photo))
    except Exception:
        pass


def pick_key_color(images, Image=None, preferred=MAGENTA):
    """动态颜色键：从一组 RGBA 图统计颜色并集，选一个图中完全不存在的颜色当抠色键。

    品红优先；若图中含品红 → 沿 RGB 空间步进扫描找空缺色（256³ 空间几乎总能找到）。
    images 支持单张图或帧列表（动图取所有帧并集，为升级一动图支持预留）。
    统计用缩小图（最长边 256）+ getcolors 全量枚举，一次加载开销可忽略。
    """
    if Image is None:
        from PIL import Image as _I
        Image = _I
    colors = set()
    for img in images:
        small = img
        longest = max(img.size)
        # 阈值看最长边和面积：1000×1000 自然图全量 getcolors 实测 3s/118MB（B3），
        # 超限用 NEAREST 缩小（不产生混合色，避免插值稀释导致品红漏检）
        if longest > 1024 or img.width * img.height > 1_048_576:
            s = min(1024.0 / longest, 1.0)
            small = img.resize((max(1, int(img.width * s)),
                                max(1, int(img.height * s))), Image.NEAREST)
        try:
            cnt = small.getcolors(small.width * small.height)
        except Exception:
            cnt = None
        if cnt:
            for _n, c in cnt:
                colors.add(c[:3])
        else:
            # 异常兜底：逐像素采样
            px = small.load()
            step = max(1, small.width // 120, small.height // 120)
            for y in range(0, small.height, step):
                for x in range(0, small.width, step):
                    colors.add(px[x, y][:3])
    if preferred not in colors:
        return preferred
    # 品红被占用 → 从品红出发沿 RGB 立方体步进扫描（步长递增，优先近距离替代色）
    r0, g0, b0 = preferred
    for step in (1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233):
        for d in range(step, 256, step):
            for r, g, b in (
                ((r0 + d) % 256, g0, b0),
                (r0, (g0 + d) % 256, b0),
                (r0, g0, (b0 + d) % 256),
                ((r0 - d) % 256, g0, b0),
                (r0, (g0 - d) % 256, b0),
                (r0, g0, (b0 - d) % 256),
            ):
                if (r, g, b) not in colors:
                    return (r, g, b)
    # 理论到不了的兜底：线性扫描
    for v in range(256):
        for u in range(256):
            c = ((r0 + v) % 256, (g0 + u) % 256, (b0 + v + u) % 256)
            if c not in colors:
                return c
    return (0, 0, 1)


def _flatten_alpha_for_tk(img_rgba, Image=None, key=MAGENTA):
    """tkinter 显示用：把 RGBA 转成「键色抠色」图。

    tkinter 的 PhotoImage 不支持每像素 alpha，透明像素会露窗口底色；
    而 -transparentcolor 只精确匹配键色（默认品红 #FF00FF）。所以：
      1) alpha 二值化（>=128 不透明，<128 透明）——消除半透明像素（紫边根源）
      2) 透明区域填精确键色 —— 让 transparentcolor 抠干净
      3) 输出 alpha 恒为 255（不保留原 alpha，避免 composite 泄漏半透明）
    key 为动态颜色键：见 pick_key_color，图中不含该色即不会误抠。
    """
    if Image is None:
        from PIL import Image as _I
        Image = _I
    alpha = img_rgba.split()[3].point(lambda a: 255 if a >= 128 else 0)
    rgb = img_rgba.convert('RGB')  # 丢弃原 alpha，只保留颜色
    key_img = Image.new('RGB', img_rgba.size, key)
    out = Image.composite(rgb, key_img, alpha)
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
kernel32 = ctypes.windll.kernel32
# ctypes 64 位进程必须显式声明 Win32 API 签名，否则句柄参数被截断导致调用失败
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]                            
user32.GetWindowLongW.restype = ctypes.c_long                                              
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]                          
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t                                        
user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]                               
user32.GetAncestor.restype = wintypes.HWND                                                 
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

# ============ 事件驱动（路径 B）WinEventHook 绑定 ============
# 仅在已 import 的 user32/kernel32 基础上补充；全部显式声明签名
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetWindow.restype = wintypes.HWND
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL
user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.DWORD]
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
user32.UnhookWinEvent.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_long
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = ctypes.c_longlong
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

# WinEventHook 事件常量
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
WINEVENT_OUTOFCONTEXT = 0x0002
WINEVENT_SKIPOWNPROCESS = 0x0004
OBJID_WINDOW = 0
CHILDID_SELF = 0
WM_QUIT = 0x0012
GW_HWNDPREV = 3
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

# 小狼毫相关进程名（候选框窗口可能属于这些进程——旧版架构/独立候选窗）
_WEASEL_PROCESSES = ('weaselserver.exe', 'weaseltsf.exe', 'weaselime.exe', 'weasel.exe')

# TSF 候选框窗口样式特征（小狼毫 0.17.x 候选框=TSF 注入应用进程，属 msedge 等，不能用进程名过滤）
_WS_POPUP = 0x80000000
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
# 图层（below）用：候选框是否置顶探测（WS_EX_TOPMOST）+ GWL_EXSTYLE 偏移
WS_EX_TOPMOST = 0x00000008
GWL_EXSTYLE = -20

def _is_tsf_candidate_style(hwnd):
    """TSF 候选框样式识别：POPUP + TOOLWINDOW + NOACTIVATE（无标题、不抢焦点）。
    火绒等普通弹窗通常是 CAPTION/激活型窗口，不满足此组合，不会被误判。"""
    try:
        style = user32.GetWindowLongPtrW(hwnd, -16)   # GWL_STYLE
        exstyle = user32.GetWindowLongPtrW(hwnd, -20)  # GWL_EXSTYLE
        return bool(style & _WS_POPUP) and bool(exstyle & _WS_EX_TOOLWINDOW) and bool(exstyle & _WS_EX_NOACTIVATE)
    except Exception:
        return False

def _window_belongs_to_weasel(hwnd):
    """校验窗口所属进程是否为小狼毫（兼容旧版候选窗架构的兜底条件）。"""
    try:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False
        h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = os.path.basename(buf.value).lower()
                return name in _WEASEL_PROCESSES
            return False
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return False

# ---- EnumWindows 回调：模块级单例（改造后仅低频重扫才调用，一次创建反复使用，
#      避免旧版每 50ms 重建 WINFUNCTYPE 闭包的浪费；结果放模块级缓冲 + 锁防重入）----
_find_results = []
_find_lock = threading.Lock()


@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def _find_enum_proc(hwnd, lparam):
    """EnumWindows 回调：收集类名 ATL: 前缀 + 尺寸 + TSF 样式/weasel 进程判定的候选框。"""
    try:
        if not user32.IsWindowVisible(hwnd):
            return True
        _find_cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, _find_cls, 256)
        if _find_cls.value.startswith('ATL:'):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if 0 < w < 1300 and 0 < h < 1000 and h < w * 4:
                # 候选框判定：TSF 样式为主，小狼毫进程兜底（兼容旧架构）；
                # 普通弹窗（火绒等）不满足样式组合且非 weasel 进程 → 排除
                if not (_is_tsf_candidate_style(hwnd) or _window_belongs_to_weasel(hwnd)):
                    return True
                _find_results.append((hwnd, rect))
    except Exception:
        pass
    return True


def find_candidate_window(layout='horizontal_double'):
    """低频兜底全扫：枚举可见窗口找候选框，返回 (hwnd, rect) 或 None。
    （事件驱动主路径失效/缓存被销毁时才调用，受 FollowOverlay 节流控制。）
    多候选框排序说明：EnumWindows 自 z-order 顶向下枚举，此处按原行为
    取 rect.top 最大（最靠下）的一个 —— 单候选框场景无差异，见 B_AUDIT 清单 8。"""
    global _find_results
    with _find_lock:
        _find_results = []
        try:
            user32.EnumWindows(_find_enum_proc, 0)
        except Exception:
            pass
        found = list(_find_results)
    if found:
        found.sort(key=lambda f: f[1].top)
        return found[-1]
    return None


# ============ 事件驱动（路径 B）：WinEventHook 后台线程 ============
# 替代「每 50ms EnumWindows 全桌扫描」：
#   · 守护线程 SetWinEventHook(OUTOFCONTEXT) + GetMessageW 消息循环
#   · 回调只做极轻工作：hwnd 与缓存句柄比较，匹配才置标志（不调任何重 API）
#   · 主线程（Tk）16ms 消费标志 → 立即重定位；200ms 心跳兜底校验缓存
# 回调与主线程之间用「单调时钟时间戳」通信（GIL 保证 int/float 赋值原子，
# 免锁免队列满问题；事件风暴时天然只保留「最近一次」，与去抖语义吻合）。
_EVT_CACHE_HWND = 0        # 主线程维护的候选框句柄缓存（回调线程只读）
# 事件信号：严格递增序号（int）+ 时间戳。用序号而非时间戳比较 ——
# 系统时间戳精度可能 1ms，两次事件若同戳会被误判「已消费」而丢事件；
# 单调递增计数则永不丢（慢 tick 会合并多次置位为一次处理，语义=只关心最新位置）。
_EVT_MOVE_CNT = 0          # 候选框移动/显示 事件计数
_EVT_GONE_CNT = 0          # 候选框销毁/隐藏 事件计数
_EVT_SHOW_CNT = 0          # 任意窗口 SHOW 事件计数（缓存失效自愈重扫用）
_EVT_MOVE_TS = 0.0         # 最近一次 MOVE 事件时刻（monotonic，perf 用）
_EVT_GONE_TS = 0.0         # 最近一次 GONE 事件时刻
_EVT_SHOW_TS = 0.0         # 最近一次 SHOW 事件时刻
_EVT_SHOW_HWND = 0         # 与最近 SHOW 对应的窗口句柄（供主线程免全扫直挂候选）
_EVT_HOOK = None           # WinEventHook 句柄
_EVT_THREAD = None         # 事件线程
_EVT_TID = 0               # 事件线程 id（退出用 PostThreadMessage）
_EVT_REFS = 0              # 引用计数：多实例/重建（open_wizard）交错时避免误停线程
_WIN_EVENT_PROC = None     # 保存 WINFUNCTYPE 实例引用，防 GC 导致回调失效


@ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                    ctypes.c_long, ctypes.c_long, wintypes.DWORD, wintypes.DWORD)
def _win_event_proc(hook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
    """WinEventHook 回调（事件线程上下文执行）：
    只做 hwnd 比对 + 递增序号/置时间戳，绝不调用窗口查询/Tk 等重 API。"""
    global _EVT_MOVE_CNT, _EVT_GONE_CNT, _EVT_SHOW_CNT
    global _EVT_MOVE_TS, _EVT_GONE_TS, _EVT_SHOW_TS, _EVT_SHOW_HWND
    try:
        if not hwnd or idObject != OBJID_WINDOW or idChild != CHILDID_SELF:
            return
        if event == EVENT_OBJECT_SHOW:
            # 任何窗口显示都可能包含重建后的候选框 → 置位供主线程按需低频重扫
            _EVT_SHOW_CNT += 1
            _EVT_SHOW_TS = time.monotonic()
            _EVT_SHOW_HWND = int(hwnd)
            return
        if hwnd != _EVT_CACHE_HWND:
            return
        if event == EVENT_OBJECT_LOCATIONCHANGE:
            _EVT_MOVE_CNT += 1
            _EVT_MOVE_TS = time.monotonic()
        elif event in (EVENT_OBJECT_DESTROY, EVENT_OBJECT_HIDE):
            _EVT_GONE_CNT += 1
            _EVT_GONE_TS = time.monotonic()
    except Exception:
        pass  # 回调必须零失败，任何异常都吞掉


def set_candidate_hwnd(hwnd):
    """主线程在缓存更新时调用：让事件回调只关心当前候选框句柄。"""
    global _EVT_CACHE_HWND
    _EVT_CACHE_HWND = hwnd or 0


def _ensure_event_thread():
    """幂等启动事件守护线程（引用计数 +1）；返回是否已启动/存活。"""
    global _EVT_THREAD, _EVT_TID, _EVT_HOOK, _WIN_EVENT_PROC, _EVT_REFS
    _EVT_REFS += 1
    if _EVT_THREAD is not None and _EVT_THREAD.is_alive():
        return True
    _EVT_TID = 0
    _EVT_HOOK = None
    # 必须在有消息循环的线程调用 SetWinEventHook（OUTOFCONTEXT 回调由系统投递到该线程）
    _WIN_EVENT_PROC = _win_event_proc  # 模块级持有，防 GC
    _EVT_THREAD = threading.Thread(target=_event_thread_main,
                                   name='rime-win-event-hook', daemon=True)
    _EVT_THREAD.start()
    return True


def _release_event_thread():
    """引用计数 -1；归零才真正停止事件线程（open_wizard 重建时新旧实例交错）。"""
    global _EVT_REFS
    if _EVT_REFS > 0:
        _EVT_REFS -= 1
    if _EVT_REFS == 0:
        stop_event_thread()


def _event_thread_main():
    """事件线程：注册钩子 + GetMessageW 消息循环；收到 WM_QUIT 退出。"""
    global _EVT_HOOK, _EVT_TID, _WIN_EVENT_PROC
    try:
        _EVT_TID = kernel32.GetCurrentThreadId()
        # 确保本线程已有消息队列（GetMessage 前的 Peek 即可创建）
        _m = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(_m), 0, 0, 0, 0)
        hook = user32.SetWinEventHook(
            EVENT_OBJECT_DESTROY, EVENT_OBJECT_LOCATIONCHANGE,   # 0x8001..0x800B
            0, _WIN_EVENT_PROC, 0, 0,
            WINEVENT_OUTOFCONTEXT)  # 不加 SKIPOWNPROCESS：回调内已按缓存句柄过滤，自身窗口事件可忽略
        if not hook:
            _write_log('[event] SetWinEventHook 失败，将退化为心跳全扫兜底')
            _EVT_HOOK = None
            return
        _EVT_HOOK = hook
        while True:
            r = user32.GetMessageW(ctypes.byref(_m), 0, 0, 0)
            if r <= 0:  # 0=WM_QUIT, -1=错误
                break
            # OUTOFCONTEXT 回调以消息形式投递到本线程，必须 Translate+Dispatch 派发才会触发
            user32.TranslateMessage(ctypes.byref(_m))
            user32.DispatchMessageW(ctypes.byref(_m))
    except Exception as e:
        try:
            import traceback as _tb
            _write_log(f'[event] 事件线程异常: {e}\n{_tb.format_exc()}')
        except Exception:
            pass
    finally:
        # 退出清理：卸载钩子 + 释放回调引用
        try:
            if _EVT_HOOK:
                user32.UnhookWinEvent(_EVT_HOOK)
        except Exception:
            pass
        _EVT_HOOK = None
        _WIN_EVENT_PROC = None


def stop_event_thread():
    """停止事件线程：UnhookWinEvent + 向线程队列投递 WM_QUIT。幂等，可重复调用。"""
    global _EVT_HOOK, _EVT_TID, _EVT_THREAD
    try:
        if _EVT_HOOK:
            user32.UnhookWinEvent(_EVT_HOOK)
    except Exception:
        pass
    _EVT_HOOK = None
    if _EVT_TID:
        try:
            user32.PostThreadMessageW(_EVT_TID, WM_QUIT, 0, 0)
        except Exception:
            pass
        _EVT_TID = 0
    t = _EVT_THREAD
    _EVT_THREAD = None
    if t is not None and t.is_alive():
        t.join(timeout=1.0)


def event_hook_alive():
    """事件钩子是否正常工作中（供心跳判断是否需退化全扫兜底）。"""
    return bool(_EVT_HOOK) and _EVT_THREAD is not None and _EVT_THREAD.is_alive()


# ============ 性能日志（路径 B，任务 G：默认关，常量控制）============
# 设为 1 打开：记录 事件到达→SetWindowPos 完成 延迟 / EnumWindows 次数 / 心跳次数，
# 写入 exe 同目录 perf.log（与 error.log 分开，便于单独分析）
PERF_LOG_ENABLED = os.environ.get('RIME_OVERLAY_PERF', '') == '1'
_PERF_START = time.time()


def _perf_log(msg):
    """性能日志（perf.log）；开关关闭时零开销（一层布尔判断）。"""
    if not PERF_LOG_ENABLED:
        return
    try:
        with open(os.path.join(HERE, 'perf.log'), 'a', encoding='utf-8') as f:
            f.write(f'{time.time() - _PERF_START:8.3f}s | {msg}\n')
    except Exception:
        pass


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
        # 性能优化：交互基于缩略图（最长边 1200px），应用时映射回原图。
        # 大图（如 3MB）不再每次拖拽/调容差时处理全分辨率，顺滑度大幅提升。
        longest = max(self.orig.size)
        self.scale = min(1.0, 1200.0 / longest)
        if self.scale < 1.0:
            self.work = self.orig.resize(
                (max(1, int(self.orig.width * self.scale)),
                 max(1, int(self.orig.height * self.scale))), self._Image.LANCZOS)
        else:
            self.work = self.orig.copy()
        self.flipped = False
        self.crop = (0, 0, self.work.width, self.work.height)  # 缩略图坐标 (x0,y0,x1,y1)
        self.lock_ratio = None             # None=原图比例 / 'free'=自由 / float=锁定宽高比
        self.use_key = tk.BooleanVar(master=master, value=True)
        self.tol_var = tk.IntVar(master=master, value=20)
        self.bg_color = None               # 抠图背景色 (r,g,b)，None=未检测
        self.drag = None                   # 拖拽状态 (mode, ...)
        self.tk_img = None
        self._photo_refs = []              # PhotoImage 引用保留，防 GC

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
        self.var_ratio = tk.IntVar(master=self.master, value=0)
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
        self.tk_img = self._ImageTk.PhotoImage(disp_s, master=self.root)
        self._photo_refs.append(self.tk_img)
        if len(self._photo_refs) > 3:
            _release_photo(self._photo_refs.pop(0))
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
        # 恢复为缩略图（大图时避免全分辨率交互）
        if self.scale < 1.0:
            self.work = self.orig.resize(
                (max(1, int(self.orig.width * self.scale)),
                 max(1, int(self.orig.height * self.scale))), self._Image.LANCZOS)
        else:
            self.work = self.orig.copy()
        self.flipped = False
        self.crop = (0, 0, self.work.width, self.work.height)
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
            # 缩略图坐标 → 原图坐标
            if self.scale < 1.0:
                inv = 1.0 / self.scale
                ox0 = int(x0 * inv)
                oy0 = int(y0 * inv)
                ox1 = int(min(self.orig.width, x1 * inv))
                oy1 = int(min(self.orig.height, y1 * inv))
            else:
                ox0, oy0, ox1, oy1 = x0, y0, x1, y1
            out = self.orig.crop((ox0, oy0, ox1, oy1))
            if self.flipped:
                out = out.transpose(self._Image.FLIP_LEFT_RIGHT)
            if self.use_key.get() and self.bg_color:
                out = self._chroma_key(out, self.bg_color, self.tol_var.get())
            out_path = os.path.join(HERE, f'preprocessed_{int(time.time() * 1000)}.png')
            out.save(out_path, 'PNG')
            self.result_path = out_path
            for p in self._photo_refs:
                _release_photo(p)
            self._photo_refs.clear()
            self.root.destroy()
        except Exception as e:
            messagebox.showerror('处理失败', str(e), parent=self.root)

    def _cancel(self):
        self.result_path = None
        for p in self._photo_refs:
            _release_photo(p)
        self._photo_refs.clear()
        self.root.destroy()


# ============ 配置向导（所见即所得）============
class ConfigWizard:
    LAYOUT_INFO = {
        'horizontal_single': ('单行横排', 460, 42),
        'horizontal_double': ('双行横排', 460, 84),
        'vertical': ('竖排', 96, 320),
    }

    def __init__(self, on_done, overlay=None):
        self.on_done = on_done
        self.overlay = overlay   # 运行中的外挂实例（托盘重配时传入，选中皮肤立即应用）
        self.cfg = dict(DEFAULT_CONFIG)
        self.PIL = False
        try:
            from PIL import Image, ImageTk
            self._Image, self._ImageTk = Image, ImageTk
            self.PIL = True
        except ImportError:
            pass
        self.tk_img = None
        self._cache = None   # 预览图片缓存 (path, mtime, Image)
        self._photo_refs = []  # PhotoImage 引用保留，防 GC 回收导致 image doesn't exist

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
                 text='支持格式: PNG / JPG / WEBP / GIF / BMP    建议: 竖版 2:3，图片 ≤ 2000×2000（约 2MB 内）\n💡 可选「图片预处理」：裁剪 / 镜像反转 / 纯色背景一键抠图',
                 fg='#e67e22', font=('Microsoft YaHei', 9), justify='left').pack(anchor='w', pady=(0, 2))
        # 品红冲突提示（动态抠色键）：图片含品红时显示，提示已自动切换
        self.lbl_keyhint = tk.Label(frm, text='', fg='#e67e22', font=('Microsoft YaHei', 9), justify='left')
        self.lbl_keyhint.pack(anchor='w', pady=(0, 2))

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

        # ② 候选框类型（读取 Rime 配置按钮放这一行）
        row3 = tk.Frame(frm)
        row3.pack(fill='x', pady=3)
        tk.Label(row3, text='② 候选框类型:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.var_layout = tk.StringVar(master=self.root, value='horizontal_double')
        for text, val in [('单行横排', 'horizontal_single'),
                          ('双行横排', 'horizontal_double'),
                          ('竖排', 'vertical')]:
            tk.Radiobutton(row3, text=text, variable=self.var_layout, value=val,
                           font=('Microsoft YaHei', 9),
                           command=self._update_preview).pack(side='left', padx=4)
        tk.Button(row3, text='读取当前Rime配置(可选)', command=self._read_rime,
                  font=('Microsoft YaHei', 9)).pack(side='left', padx=12)

        # ③ 贴边方向
        row4 = tk.Frame(frm)
        row4.pack(fill='x', pady=3)
        tk.Label(row4, text='③ 贴边方向:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.var_side = tk.StringVar(master=self.root, value='right')
        for text, val in [('右侧', 'right'), ('左侧', 'left'), ('中间', 'center')]:
            tk.Radiobutton(row4, text=text, variable=self.var_side, value=val,
                           font=('Microsoft YaHei', 9),
                           command=self._update_preview).pack(side='left', padx=4)

        # ④ 图层（图片相对候选框层级；v1.5 自 v1.2 恢复，事件驱动下重建可自愈）
        row_layer = tk.Frame(frm)
        row_layer.pack(fill='x', pady=3)
        tk.Label(row_layer, text='④ 图层:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.var_layer = tk.StringVar(master=self.root, value='above')
        for text, val in [('候选框上方', 'above'), ('候选框下方', 'below')]:
            tk.Radiobutton(row_layer, text=text, variable=self.var_layer, value=val,
                           font=('Microsoft YaHei', 9),
                           command=self._update_preview).pack(side='left', padx=4)
        # below 提示行（随 图层/贴边 选择动态更新；v1.3 教训：below 仅 贴边=中间 重叠时可见）
        self.lbl_layer_hint = tk.Label(frm, text='', fg='#888', font=('Microsoft YaHei', 8),
                                       justify='left')
        self.lbl_layer_hint.pack(anchor='w', pady=(0, 2))

        # ⑤ 缩放（独立一行）
        row5 = tk.Frame(frm)
        row5.pack(fill='x', pady=3)
        tk.Label(row5, text='⑤ 缩放:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.var_scale = tk.DoubleVar(master=self.root, value=1.0)
        tk.Scale(row5, from_=0.2, to=2.0, resolution=0.1, orient='horizontal',
                 variable=self.var_scale, length=220,
                 command=lambda _: self._update_preview(),
                 font=('Microsoft YaHei', 8)).pack(side='left', padx=4)
        self.lbl_scale = tk.Label(row5, text='1.0x', fg='#888', font=('Microsoft YaHei', 9))
        self.lbl_scale.pack(side='left')

        # ⑥ 水平微调（独立一行）
        row6 = tk.Frame(frm)
        row6.pack(fill='x', pady=3)
        tk.Label(row6, text='⑥ 水平微调:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.var_offx = tk.IntVar(master=self.root, value=0)
        tk.Scale(row6, from_=-200, to=200, orient='horizontal',
                 variable=self.var_offx, length=220,
                 command=lambda _: self._update_preview(),
                 font=('Microsoft YaHei', 8)).pack(side='left', padx=4)
        self.lbl_offx = tk.Label(row6, text='0px', fg='#888', font=('Microsoft YaHei', 9))
        self.lbl_offx.pack(side='left')

        # ⑦ 垂直微调（独立一行）
        row7 = tk.Frame(frm)
        row7.pack(fill='x', pady=3)
        tk.Label(row7, text='⑦ 垂直微调:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.var_offy = tk.IntVar(master=self.root, value=0)
        tk.Scale(row7, from_=-150, to=150, orient='horizontal',
                 variable=self.var_offy, length=220,
                 command=lambda _: self._update_preview(),
                 font=('Microsoft YaHei', 8)).pack(side='left', padx=4)
        self.lbl_offy = tk.Label(row7, text='0px', fg='#888', font=('Microsoft YaHei', 9))
        self.lbl_offy.pack(side='left')

        # ⑧ 预览区（候选框 + 图片 组合）
        tk.Label(frm, text='预览（候选框 + 图片组合样式，图片已自适应缩放）:',
                 font=('Microsoft YaHei', 9), fg='#555').pack(anchor='w', pady=(4, 0))
        self.canvas = tk.Canvas(frm, width=760, height=380, bg='#ffffff',
                                highlightthickness=1, highlightbackground='#ccc')
        self.canvas.pack(pady=4)

        # ⑨ 皮肤管理（独立分区，图片 + 全套参数整套切换）
        skin_box = tk.LabelFrame(frm, text='💾 皮肤管理（图片 + 全套参数，选中即应用）',
                                 font=('Microsoft YaHei', 9), fg='#555', padx=8, pady=4)
        skin_box.pack(fill='x', pady=(2, 0))
        self.skin_var = tk.StringVar(master=self.root)
        self.skin_cb = ttk.Combobox(skin_box, textvariable=self.skin_var, state='readonly',
                                    width=18, font=('Microsoft YaHei', 9))
        self.skin_cb.pack(side='left', padx=(0, 4))
        # 选中即应用：预览 + 立即切换到运行中的外挂（若有）
        self.skin_cb.bind('<<ComboboxSelected>>', lambda _e: self._apply_skin_to_wizard())
        tk.Button(skin_box, text='💾 保存当前为皮肤…', command=self._save_as_skin,
                  font=('Microsoft YaHei', 9)).pack(side='left', padx=2)
        tk.Button(skin_box, text='🗑 删除…', command=self._delete_skin,
                  font=('Microsoft YaHei', 9)).pack(side='left', padx=2)
        self.lbl_skin_hint = tk.Label(skin_box, text='选中即应用（含正在运行的外挂），可随时整套切换',
                                      fg='#999', font=('Microsoft YaHei', 8))
        self.lbl_skin_hint.pack(side='left', padx=6)
        self._refresh_skin_list()

        # ⑩ 按钮
        row8 = tk.Frame(frm)
        row8.pack(fill='x', pady=6)
        tk.Button(row8, text='保存并启动', command=self._save_and_start,
                  bg='#4CAF50', fg='white', font=('Microsoft YaHei', 10, 'bold')).pack(side='left', padx=4)
        tk.Button(row8, text='取消', command=self._on_cancel,
                  font=('Microsoft YaHei', 10)).pack(side='left', padx=4)
        tk.Label(row8, text='💡 保存后启动；下次双击可重新配置',
                 fg='#e67e22', font=('Microsoft YaHei', 11, 'bold')).pack(side='right')

    def _get_preview_img(self):
        """预览图片缓存：文件未变时复用已打开的图，避免每次滑块都重开大图"""
        path = self.cfg.get('image')
        if not path or not self.PIL:
            return None
        try:
            mtime = os.path.getmtime(path)
            if self._cache and self._cache[0] == path and self._cache[1] == mtime:
                return self._cache[2]
            img = self._Image.open(path).convert('RGBA')
            # 大图先缩到最长边 1600，减少后续预览缩放开销
            longest = max(img.size)
            if longest > 1600:
                s = 1600.0 / longest
                img = img.resize((max(1, int(img.width * s)),
                                  max(1, int(img.height * s))), self._Image.LANCZOS)
            self._cache = (path, mtime, img)
            return img
        except Exception:
            return None

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
        self._update_key_hint()

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
                self._update_key_hint()
        except Exception as e:
            messagebox.showerror('预处理失败', str(e))

    # ---------- 动态抠色键提示 ----------
    def _update_key_hint(self):
        """检测图片是否含品红 → 提示运行时已自动切换抠色键"""
        path = self.cfg.get('image')
        if not path or not self.PIL:
            self.lbl_keyhint.config(text='')
            return
        try:
            img = self._get_preview_img()
            if img is None:
                self.lbl_keyhint.config(text='')
                return
            key = pick_key_color([img], self._Image)
            if key != MAGENTA:
                self.lbl_keyhint.config(
                    text=f'⚠ 检测到图片含品红像素，运行时抠色键已自动切换为 {_key_hex(key)}（避免被抠穿）')
            else:
                self.lbl_keyhint.config(text='')
        except Exception:
            self.lbl_keyhint.config(text='')

    # ---------- 皮肤管理 ----------
    def _refresh_skin_list(self):
        """刷新皮肤下拉框；保留当前选中（若还在）"""
        skins = list_skins()
        names = [n for n, _ in skins]
        self.skin_cb['values'] = names
        if self.skin_var.get() not in names:
            self.skin_var.set('')

    def _apply_skin_to_wizard(self):
        """应用选中皮肤：整套参数恢复到向导"""
        name = self.skin_var.get()
        if not name:
            messagebox.showwarning('提示', '请先在下拉框选择皮肤')
            return
        cfg = find_skin(name)
        if not cfg:
            messagebox.showwarning('提示', '皮肤档案不存在或已损坏')
            self._refresh_skin_list()
            return
        # 应用前清预览缓存 + 显式释放旧 PhotoImage（避免新旧图片切换时 tcl 端 image 竞争）
        self._cache = None
        if self.tk_img is not None:
            _release_photo(self.tk_img)
            self.tk_img = None
        for p in self._photo_refs:
            _release_photo(p)
        self._photo_refs.clear()
        self.cfg.update(cfg)
        self.var_layout.set(cfg.get('layout', 'horizontal_double'))
        self.var_side.set(cfg.get('side', 'right'))
        self.var_layer.set(cfg.get('layer', 'above'))
        self.var_scale.set(cfg.get('scale', 1.0))
        self.var_offx.set(cfg.get('offset_x', 0))
        self.var_offy.set(cfg.get('offset_y', 0))
        img = cfg.get('image', '')
        self.lbl_img.config(text=os.path.basename(img) + f'（皮肤: {name}）', fg='#2e7d32')
        self.btn_prep.config(state='normal' if img else 'disabled')
        self._update_preview()
        self._update_key_hint()
        # 选中即应用：若外挂正在运行，立即切换皮肤（托盘菜单选中态同步）
        if self.overlay is not None:
            try:
                self.overlay.apply_skin(name)
            except Exception:
                pass

    def _save_as_skin(self):
        """把当前向导参数保存为皮肤档案"""
        if not self.cfg.get('image'):
            messagebox.showwarning('提示', '请先选择图片！')
            return
        name = simpledialog.askstring('保存皮肤',
                                      '皮肤名称（保存图片 + 全套参数，\n保存后可在托盘「皮肤选择」随时切换）：',
                                      parent=self.root)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        # 同名覆盖确认
        existing = [n for n, _ in list_skins() if n.lower() == name.lower()]
        if existing:
            if not messagebox.askyesno('覆盖确认',
                                       f'皮肤「{existing[0]}」已存在，覆盖？',
                                       parent=self.root):
                return
            name = existing[0]
        tcfg = dict(self.cfg)
        tcfg['layout'] = self.var_layout.get()
        tcfg['side'] = self.var_side.get()
        tcfg['layer'] = self.var_layer.get()
        tcfg['scale'] = round(float(self.var_scale.get()), 2)
        tcfg['offset_x'] = int(self.var_offx.get())
        tcfg['offset_y'] = int(self.var_offy.get())
        try:
            save_skin(name, tcfg)
        except ValueError as e:
            messagebox.showwarning('无法保存', str(e), parent=self.root)
            return
        except Exception as e:
            messagebox.showerror('保存失败', str(e), parent=self.root)
            return
        self._refresh_skin_list()
        self.skin_var.set(name)
        messagebox.showinfo('已保存', f'皮肤「{name}」已保存。\n托盘「皮肤选择」可随时切换。',
                            parent=self.root)

    def _delete_skin(self):
        """删除选中皮肤（仅删档案，不影响当前运行中的外挂）"""
        name = self.skin_var.get()
        if not name:
            messagebox.showwarning('提示', '请先在下拉框选择要删除的皮肤')
            return
        if not messagebox.askyesno('删除皮肤',
                                   f'确定删除皮肤「{name}」？\n（仅删除皮肤档案，不影响当前运行中的外挂）',
                                   parent=self.root):
            return
        delete_skin(name)
        self._refresh_skin_list()
        messagebox.showinfo('已删除', f'皮肤「{name}」已删除。', parent=self.root)

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

        # 候选框（居中于画布）——先算几何，实际绘制按图层顺序统一进行
        cw, ch = self.LAYOUT_INFO[layout][1], self.LAYOUT_INFO[layout][2]
        base_x = (760 - cw) // 2
        base_y = (360 - ch) // 2
        # 候选框配色（用 Rime 皮肤主色，简单示意）
        accent = get_rime_accent() if self.PIL else (0, 137, 123)
        hex_acc = '#%02x%02x%02x' % accent

        # 图片（贴候选框侧边；缩放逻辑与运行时一致：高度 = base_height×scale）
        img = None
        new_w = new_h = 0
        ix = iy = 0
        if self.cfg.get('image') and self.PIL:
            try:
                img = self._get_preview_img()
                if img is None:
                    raise ValueError('图片加载失败')
                # 与 FollowOverlay.load_char 完全相同的缩放逻辑
                base_h = 300 * scale
                if img.height > 0:
                    ratio = base_h / img.height
                    img = img.resize((max(1, int(img.width * ratio)),
                                      max(1, int(base_h))), self._Image.BILINEAR)
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
                        cw, ch = int(cw * fit_all), int(ch * fit_all)
                        base_x = (cv_w - cw) // 2
                        base_y = (cv_h - ch) // 2
                # 贴边（偏移量与运行时一致）
                gap = 8
                if side == 'right':
                    ix = base_x + cw + gap + offx
                elif side == 'left':
                    ix = base_x - new_w - gap + offx
                else:  # center：水平居中于候选框（配合图层叠放）
                    ix = base_x + (cw - new_w) // 2 + offx
                iy = base_y + (ch - new_h) // 2 + offy
                # 预览不加光环（实际运行时有皮肤联动光环）
                self.tk_img = self._ImageTk.PhotoImage(img, master=self.root)
                self._photo_refs.append(self.tk_img)
                if len(self._photo_refs) > 3:
                    _release_photo(self._photo_refs.pop(0))
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                cv.create_text(380, 180, text=f'图片加载失败: {e}', fill='red',
                               font=('Microsoft YaHei', 9))
                img = None
                try:
                    # 诊断 dump：关键验证 tk_img 与 canvas 是否同一 tcl 解释器
                    tk_img_info = 'None'
                    try:
                        if self.tk_img is not None:
                            tk_img_info = (f'{str(self.tk_img)} '
                                           f'same_interp={self.tk_img.tk is cv.tk}')
                    except Exception:
                        pass
                    try:
                        import tkinter as _tk
                        dr = getattr(_tk, '_default_root', None)
                        dr_info = 'None'
                        if dr is not None:
                            try:
                                dr_info = f'{dr} alive={bool(dr.tk.call("info", "exists", "."))}'
                            except Exception:
                                dr_info = f'{dr} (tk不可用)'
                    except Exception:
                        dr_info = '?'
                    _write_log('[_update_preview] 图片加载失败:\n'
                               f'{tb}'
                               f'err={e!r}\n'
                               f'tk_img={tk_img_info}\n'
                               f'cfg[image]={self.cfg.get("image")!r}\n'
                               f'_photo_refs={len(self._photo_refs)}\n'
                               f'canvas_tk={cv.tk}\n'
                               f'default_root={dr_info}')
                except Exception:
                    pass

        # 绘制顺序按图层直观表现（v1.5）：
        #   above            → 候选框在下、图片在上（重叠区图片盖候选框，现状）
        #   below + 中间重叠 → 图片在下、候选框在上（候选框不透明背景压住图片重叠区）
        #   below + 侧贴边   → 不重叠不生效，保持置顶语义 = 图片在上（同 above 顺序）
        layer = self.var_layer.get()
        below_overlap = (layer == 'below' and side == 'center')

        def _draw_img_layer():
            if img is not None:
                cv.create_image(ix, iy, anchor='nw', image=self.tk_img)
                cv.create_rectangle(ix, iy, ix + new_w, iy + new_h,
                                    outline='#ff6a00', dash=(4, 2))

        if below_overlap:
            _draw_img_layer()  # 下层：图片（虚线框被候选框盖住部分自然不可见，更真实）
            self._draw_candidate(cv, layout, base_x, base_y, cw, ch, hex_acc)  # 上层：候选框压图
        else:
            self._draw_candidate(cv, layout, base_x, base_y, cw, ch, hex_acc)
            _draw_img_layer()
        # 图层提示行随 图层/贴边 变化刷新
        self._update_layer_hint()

    def _update_layer_hint(self):
        """图层提示行：below 选中时提示适用条件（v1.3 教训文案）；
        当前 贴边≠中间 时额外提示该组合不会生效、将自动保持置顶。"""
        if not hasattr(self, 'lbl_layer_hint'):
            return
        layer = self.var_layer.get()
        if layer == 'above':
            self.lbl_layer_hint.config(text='')
        else:
            side = self.var_side.get()
            if side == 'center':
                self.lbl_layer_hint.config(
                    text='💡 下方效果仅在 贴边=中间(重叠) 时可见；左/右贴边时自动保持置顶',
                    fg='#888')
            else:
                side_txt = {'left': '左', 'right': '右'}.get(side, side)
                self.lbl_layer_hint.config(
                    text=f'⚠ 当前 贴边={side_txt}侧（不与候选框重叠），「下方」不生效，将自动保持置顶；'
                         f'切到 中间 才可见下方效果',
                    fg='#e67e22')

    def _draw_candidate(self, cv, layout, base_x, base_y, cw, ch, hex_acc):
        """画预览候选框（主体 + 编码行 + 候选文字 + 类型名）。
        与图片绘制分离，供图层顺序（above 候选框在下层 / below 候选框压住图片）复用。
        """
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

    def _save_and_start(self):
        self.cfg['layout'] = self.var_layout.get()
        self.cfg['side'] = self.var_side.get()
        self.cfg['layer'] = self.var_layer.get()
        self.cfg['scale'] = round(float(self.var_scale.get()), 2)
        self.cfg['offset_x'] = int(self.var_offx.get())
        self.cfg['offset_y'] = int(self.var_offy.get())
        if not self.cfg.get('image'):
            messagebox.showwarning('提示', '请先选择图片！')
            return
        # 预处理产物持久化（B1 修复）：preprocessed_*.png 是易变临时文件（下次预处理会生成新文件），
        # 但 config.json 若指向它，重新预处理 + 取消向导后内容会与配置语义脱节。
        # 保存时复制成 cfg_image_<ts> 独立副本，config.json 指向副本，内容不再被后续操作静默改变。
        img = self.cfg.get('image')
        if (img and os.path.dirname(os.path.normpath(img)) == os.path.normpath(HERE)
                and os.path.basename(img).startswith('preprocessed_')):
            import shutil
            new_path = os.path.join(HERE, f'cfg_image_{int(time.time() * 1000)}'
                                    f'{os.path.splitext(img)[1] or ".png"}')
            try:
                shutil.copy2(img, new_path)
                self.cfg['image'] = new_path
                # 清理旧预处理临时文件（保存动作已发生，旧的 preprocessed_* 不再被引用）
                for old in os.listdir(HERE):
                    if old.startswith('preprocessed_') and os.path.isfile(os.path.join(HERE, old)):
                        try:
                            os.remove(os.path.join(HERE, old))
                        except OSError:
                            pass
            except Exception:
                pass
        save_config(self.cfg)
        self.root.destroy()
        self.on_done(self.cfg)

    def _on_cancel(self):
        # 只销毁窗口，让 mainloop 自然返回（不要 sys.exit，否则 Tk 清理会卡住）
        # 顺带显式释放全部 PhotoImage（tcl 端 image table 同步清理）
        for p in self._photo_refs:
            _release_photo(p)
        self._photo_refs.clear()
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
        self._cur_name = overlay.cfg.get('name', '')  # 当前皮肤名缓存（pystray 线程读，避免跨线程碰主线程 cfg）

    def start(self):
        try:
            import pystray
            from PIL import Image
            icon_path = _icon_path('icon.png')
            if not os.path.exists(icon_path):
                return
            img = Image.open(icon_path).resize((64, 64), Image.LANCZOS)
            menu = pystray.Menu(
                pystray.MenuItem('重新配置…', self._reconfig, default=True),
                pystray.MenuItem('皮肤选择', pystray.Menu(self._skin_items)),
                pystray.MenuItem('退出 (Ctrl+Alt+Q)', self._quit),
            )
            self.icon = pystray.Icon('RimeSkinOverlay', img, 'Rime 皮肤外挂', menu)
            self._thread = threading.Thread(target=self.icon.run, daemon=True)
            self._thread.start()
        except Exception:
            pass

    def _skin_items(self):
        """动态皮肤子菜单：每次打开菜单时重新生成（新增/删除皮肤实时可见）"""
        try:
            import pystray
        except Exception:
            return iter(())
        skins = list_skins()
        cur_name = self._cur_name
        if not skins:
            yield pystray.MenuItem('（暂无已保存皮肤）', None, enabled=False)
        else:
            for name, _cfg in skins:
                yield pystray.MenuItem(
                    name, self._switch_skin, radio=True,
                    checked=lambda item, n=name: bool(cur_name == n))
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem('保存当前为皮肤…', self._save_skin_from_tray)

    def _switch_skin(self, icon, item):
        """切换皮肤（托盘线程 → Tk 主线程执行）"""
        try:
            self.overlay.root.after(0, lambda: self.overlay.apply_skin(item.text))
        except Exception:
            pass

    def _save_skin_from_tray(self, icon, item):
        """保存当前为皮肤（托盘线程 → Tk 主线程执行）"""
        try:
            self.overlay.root.after(0, self.overlay.save_current_skin)
        except Exception:
            pass

    def _reconfig(self, icon, item):
        """重新配置：打开配置向导（托盘与后台全程保持，取消关闭不影响）"""
        try:
            self.overlay.root.after(0, self.overlay.open_wizard)
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
        self.root.attributes('-transparentcolor', '#FF00FF')  # 默认品红，load_char 后按实际键色覆盖
        self.root.configure(bg='#FF00FF')
        if self.PIL:
            set_window_icon(self.root, (self._Image, self._ImageTk))

        self.raw_img = None
        self.cur_accent = None
        self.img_mtime = None
        self.key_rgb = MAGENTA          # 当前抠色键（动态，随图片变化）
        self.layer = self.cfg.get('layer', 'above')  # 图层：above=图片置顶 / below=候选框压图（v1.5）
        self.load_char()

        self.label = tk.Label(self.root, image=self.img, bg=_key_hex(self.key_rgb), cursor='fleur')
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
        # ===== 路径 B：事件驱动状态（替代 50ms 全桌轮询）=====
        self.event_ms = 16        # 事件消费节拍（只读标志位，开销可忽略）
        self.heartbeat_ms = 200   # 兜底心跳：缓存有效性校验 + 位置脏检查（不做 EnumWindows）
        self.skin_ms = 2000       # 图片热重载（保持原 2s）
        self._cached_hwnd = 0     # 候选框句柄缓存（有效 → 定位 O(1) GetWindowRect）
        self._x, self._y = 0, 0   # 镜像坐标：SetWindowPos/geometry 后的权威窗口位置
        self._hide_since = None   # 候选框消失起始时刻（None=未消失）；<150ms 复现不 withdraw
        self._need_rescan = False # 需要低频重扫（缓存被 DESTROY/SHOW 失效后置位）
        self._last_scan_ts = 0.0  # 上次 EnumWindows 时刻（重扫节流）
        self._rescan_min = 0.4    # 两次全扫最小间隔（秒），事件驱动下 EnumWindows 仅低频
        self._pos_dirty = False   # 位置脏标志（收到移动事件后置位）
        self._below_log_ts = 0.0  # below 保底(候选框非置顶)日志节流时间戳（monotonic）
        # 事件消费游标：只处理快照之后的新事件（序号递增，永不丢事件）
        self._last_move_cnt = _EVT_MOVE_CNT
        self._last_gone_cnt = _EVT_GONE_CNT
        self._last_show_cnt = _EVT_SHOW_CNT
        self._last_move_ts = _EVT_MOVE_TS  # 镜像（仅 perf/诊断）
        self._top_hwnd_cache = None  # 顶层窗口句柄缓存（SetWindowPos 目标）
        self._n_scans = 0            # EnumWindows 全扫计数（perf/诊断）
        self._n_heartbeats = 0       # 心跳计数（perf/诊断）
        set_candidate_hwnd(0)        # 让事件回调忽略旧句柄
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
            # 动态颜色键：统计颜色并集，选图中不存在的颜色当抠色键（消灭「图含品红被误抠」）
            key = pick_key_color([img], self._Image)
            self.key_rgb = key
            # 修复紫边：缩放后 alpha 二值化 + 透明区填键色（配合 transparentcolor 抠色）
            img = _flatten_alpha_for_tk(img, self._Image, key)
            self.raw_img = img.copy()
            self.img_mtime = os.path.getmtime(img_path)
            # 不画光环（纯图片）
            self.cur_accent = None
            old = getattr(self, 'img', None)
            self.img = self._ImageTk.PhotoImage(img, master=self.root)
            if old is not None:
                _release_photo(old)  # 显式释放旧 tcl image（热重载/切皮肤同步清理）
            # 窗口透明色 / 背景 / Label 底色全部跟随动态键色
            key_hex = _key_hex(key)
            try:
                self.root.attributes('-transparentcolor', key_hex)
            except Exception:
                pass
            try:
                self.root.configure(bg=key_hex)
            except Exception:
                pass
            if hasattr(self, 'label'):
                try:
                    self.label.configure(image=self.img, bg=key_hex)
                except Exception:
                    pass
        else:
            self.img = tk.PhotoImage(file=img_path, master=self.root)
        self.w, self.h = self.img.width(), self.img.height()
        self.layer = self.cfg.get('layer', 'above')  # 热重载/切皮肤/缩放重载后同步图层配置

    # ---------- 多皮肤 ----------
    def apply_skin(self, name):
        """切换皮肤：整套参数（图片/布局/贴边/缩放/偏移）恢复，保持当前位置"""
        cfg = find_skin(name)
        if not cfg:
            return False
        self.cfg = cfg
        self.load_char()
        self._sync_tk_geometry()  # 尺寸变化：低频 geometry 同步镜像坐标（与 SetWindowPos 镜像一致）
        # 图层同步：切皮肤后候选框在场 → 重插层级（layer/side 可能已随皮肤变化）
        self._sync_layer_with_candidate()
        # S1 修复：切换后持久化，重启仍用当前皮肤
        try:
            save_config(self.cfg)
        except Exception:
            pass
        # S3 修复：同步托盘菜单选中态缓存（pystray 线程读，不直接碰主线程 cfg）
        try:
            if self.tray:
                self.tray._cur_name = name
        except Exception:
            pass
        return True

    def save_current_skin(self):
        """把当前配置保存为皮肤档案（托盘菜单用，走 Tk 主线程）"""
        from tkinter import simpledialog
        try:
            name = simpledialog.askstring('保存皮肤',
                                          '皮肤名称（保存图片 + 全套参数，\n可在托盘「皮肤选择」随时切换）：',
                                          parent=self.root)
            if not name:
                return
            name = name.strip()
            if not name:
                return
            try:
                save_skin(name, self.cfg)
            except ValueError as e:
                messagebox.showwarning('无法保存', str(e), parent=self.root)
                return
            messagebox.showinfo('已保存', f'皮肤「{name}」已保存。\n托盘「皮肤选择」可随时切换。',
                                parent=self.root)
        except Exception:
            pass

    def check_skin(self):
        if self.PIL:
            try:
                mtime = os.path.getmtime(self.cfg['image'])
            except OSError:
                mtime = None
            if mtime != self.img_mtime:
                try:
                    self.load_char()
                    self.label.configure(image=self.img)
                    self._sync_tk_geometry()  # 热重载尺寸变化：低频 geometry 同步镜像
                    # 热重载后候选框在场 → 补一次图层同步（图片尺寸变化可能影响叠放观感）
                    self._sync_layer_with_candidate()
                except Exception as e:
                    # 图片被删/损坏时不能崩主线程（B2 修复）：记录日志后继续轮询
                    try:
                        _write_log(f'[check_skin] 图片加载失败: {e} (image={self.cfg.get("image")})')
                    except Exception:
                        pass
        self.root.after(self.skin_ms, self.check_skin)

    def on_press(self, e):
        # 基准用镜像坐标（SetWindowPos 直移后 Tk 的 winfo_x/y 可能过时）
        self._dx, self._dy = e.x_root - self._x, e.y_root - self._y

    def on_drag(self, e):
        # 拖拽低频 → 仍用 geometry 移动，但同步镜像，避免与事件定位两套坐标打架
        nx, ny = e.x_root - self._dx, e.y_root - self._dy
        self.root.geometry(f'+{nx}+{ny}')
        self._x, self._y = nx, ny
        # 手动拖拽后候选框在场 → 同步图层（below 时保持候选框压图，避免拖完层级漂移）
        self._sync_layer_with_candidate()

    def on_wheel(self, e):
        """滚轮缩放：修改缩放因子后重走加载管线。

        PIL 的 ImageTk.PhotoImage 没有 zoom/subsample 方法（v1.2 起滚轮缩放实际会抛
        AttributeError，既有 bug）；改为调整 cfg['scale'] 后 load_char 统一重载，
        顺带动态键色/尺寸同步，所见即所得。
        """
        delta = 0.1 if e.delta > 0 else -0.1
        cur = self.cfg.get('scale', 1.0)
        new_scale = round(min(2.0, max(0.2, cur + delta)), 2)
        if new_scale == cur:
            return
        self.cfg['scale'] = new_scale
        try:
            self.load_char()
            self.label.configure(image=self.img)
            self._sync_tk_geometry()  # 缩放后尺寸变化：低频 geometry 同步镜像
        except Exception:
            pass

    def on_right_click(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    def toggle(self):
        """手动切换显示/隐藏（托盘菜单 / Ctrl+Alt+C）。
        手动显示后 pinned=True，不再因无候选框自动隐藏；再次切换恢复自动模式。
        """
        self.pinned = not self.pinned
        if self.pinned:
            self.root.deiconify()
            self.visible = True
            try:
                # S4 语义保持：手动显示立即定位（允许低频重扫找候选框）
                self._hide_since = None
                self._position_once(allow_scan=True)
            except Exception:
                pass
        else:
            self.root.withdraw()
            self.visible = False

    def open_wizard(self):
        """打开配置向导（托盘与后台全程保持）。

        向导作为独立窗口打开（双 Tk 嵌套 mainloop，overlay 的跟随/托盘不受影响）：
        - 保存新配置 → 替换当前实例（停托盘、关窗口、启动新配置的 overlay）
        - 取消/关闭向导 → 什么都不动，外挂继续后台运行
        """
        def start(cfg2):
            try:
                self.tray.stop()
            except Exception:
                pass
            try:
                self.root.destroy()
            except Exception:
                pass
            if _already_running():
                _kill_existing()
                time.sleep(1)
            FollowOverlay(cfg2).run()
        try:
            wizard = ConfigWizard(on_done=start, overlay=self)
            wizard.root.mainloop()
        except Exception:
            pass

    # ---------- 路径 B：事件驱动定位（替代 50ms 全桌轮询）----------
    def _top_hwnd(self):
        """取 Tk 窗口的真实顶层 HWND（SetWindowPos 目标）。
        winfo_id 返回的是 TkChild 子窗口句柄，SetWindowPos 必须作用在真正的
        顶层 TkTopLevel 上（否则只移动子窗口、父窗不动，层级插序失效）。
        沿 GetParent 链向上取到 parent=0 的窗口即顶层；窗口未 map（withdraw）
        时 GetParent 可能返回 0 → 退回 winfo_id（此时不可见，无碍）。
        缓存仅保存「非 winfo_id 的真实顶层」，避免把子窗口句柄缓存死。"""
        try:
            my = self.root.winfo_id()
            if not my:
                return self._top_hwnd_cache or None
            if (self._top_hwnd_cache and self._top_hwnd_cache != my
                    and user32.IsWindow(self._top_hwnd_cache)):
                return self._top_hwnd_cache
            top = my
            while True:
                p = user32.GetParent(top)
                if not p:
                    break
                top = p
            if top != my:
                self._top_hwnd_cache = top
            return top
        except Exception:
            return self._top_hwnd_cache or None

    def _sync_tk_geometry(self):
        """低频（尺寸变化/手动交互后）把镜像坐标同步回 Tk：
        SetWindowPos 直移后 Tk 内部 winfo_x/y 可能过时，凡 w/h 变化
        （切皮肤/滚轮缩放/热重载）都必须用一次 geometry 校正，否则 Tk
        下次布局/update 会把窗口拉回旧位置，与事件定位打架。
        geometry 仅在此类低频路径使用；高频跟随一律 SetWindowPos。"""
        try:
            self.root.geometry(f'{self.w}x{self.h}+{int(self._x)}+{int(self._y)}')
        except Exception:
            pass

    def _cached_hwnd_ok(self):
        """缓存句柄仍有效：窗口存在且可见（O(1)，无枚举）。"""
        try:
            return bool(self._cached_hwnd) and bool(user32.IsWindow(self._cached_hwnd)) \
                and bool(user32.IsWindowVisible(self._cached_hwnd))
        except Exception:
            return False

    def _calc_target(self, rect):
        """候选框 rect → 贴边目标 (x, y)（逻辑与改造前一致，含用户微调偏移）。"""
        cw, ch = rect.right - rect.left, rect.bottom - rect.top
        side = self.cfg.get('side', 'right')
        gap = 8
        if side == 'left':
            x = rect.left - self.w - gap + self.off_x + self.cfg.get('offset_x', 0)
        elif side == 'right':
            x = rect.right + gap + self.off_x + self.cfg.get('offset_x', 0)
        else:  # center：水平居中于候选框（配合图层叠放）
            x = rect.left + (cw - self.w) // 2 + self.off_x + self.cfg.get('offset_x', 0)
        y = rect.top + (ch - self.h) // 2 + self.off_y + self.cfg.get('offset_y', 0)
        return int(x), int(y)

    def _move_to(self, x, y):
        """主定位路径：SetWindowPos 一次完成「移动 + HWND_TOPMOST」，
        顺带 SWP_NOACTIVATE。窗口显示/隐藏统一由 deiconify/withdraw 管理
        （避免 Tk withdraw 状态与 SWP_SHOWWINDOW 状态机打架）。
        维护 _x/_y 镜像（Tk 的 winfo 在此之后可能过时，以镜像为准）。"""
        top = self._top_hwnd()
        if not top:
            return False
        try:
            ok = user32.SetWindowPos(top, HWND_TOPMOST, int(x), int(y), 0, 0,
                                     SWP_NOACTIVATE | SWP_NOSIZE)
        except Exception:
            return False
        if ok:
            self._x, self._y = int(x), int(y)
        return bool(ok)

    def _read_cached_rect(self):
        """O(1) 读取缓存候选框的矩形；失败返回 None。"""
        try:
            if not self._cached_hwnd:
                return None
            rect = wintypes.RECT()
            if user32.GetWindowRect(self._cached_hwnd, ctypes.byref(rect)):
                return rect
        except Exception:
            pass
        return None

    def _position_once(self, allow_scan=False):
        """事件驱动单次定位：
        · 缓存句柄有效 → 只 GetWindowRect(缓存) O(1) → 死区判断 → SetWindowPos；
        · 缓存失效 → 仅当 allow_scan/需要时低频全扫重建缓存。
        返回 True=已贴到候选框 / False=当前无可用候选框。"""
        try:
            if self._cached_hwnd_ok():
                rect = self._read_cached_rect()
                if rect is not None:
                    cw = rect.right - rect.left
                    ch = rect.bottom - rect.top
                    if cw > 0 and ch > 0 and ch < cw * 4 and cw < 1300 and ch < 1000:
                        x, y = self._calc_target(rect)
                        # 死区：窗口已显示且位置变化 <2px 不移动（省一次系统调用与重绘）
                        if self.visible and abs(x - self._x) < 2 and abs(y - self._y) < 2:
                            self._apply_layer(self._cached_hwnd)  # 成功定位后同步图层（事件驱动，频率低）
                            return True
                        moved = self._move_to(x, y)
                        self._pos_dirty = False
                        if not self.visible:
                            self.root.deiconify()
                            self.visible = True
                        if PERF_LOG_ENABLED and moved:
                            _perf_log(f'  ├ SetWindowPos -> ({x},{y})')
                        self._apply_layer(self._cached_hwnd)  # 移动/首显后同步图层（above=无操作）
                        return True
                    # 矩形异常（非候选框尺寸）→ 缓存失效
                    self._cached_hwnd = 0
                    set_candidate_hwnd(0)
                else:
                    self._cached_hwnd = 0
                    set_candidate_hwnd(0)
            # 缓存失效：低频兜底重扫（受 _rescan_min 节流，不随 tick 全扫）
            if allow_scan and time.time() - self._last_scan_ts >= self._rescan_min:
                return self._rescan_candidate()
            return False
        except Exception as e:
            try:
                _write_log(f'[_position_once] 定位异常: {e}')
            except Exception:
                pass
            return False

    def _try_attach_show_hwnd(self, hwnd):
        """SHOW 事件候选句柄直挂（免全扫）：校验可见 + TSF 样式 + 尺寸合理后缓存并定位。"""
        try:
            if not hwnd or not user32.IsWindowVisible(hwnd):
                return False
            if not _is_tsf_candidate_style(hwnd) and not _window_belongs_to_weasel(hwnd):
                return False
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return False
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if not (0 < w < 1300 and 0 < h < 1000 and h < w * 4):
                return False
            self._cached_hwnd = hwnd
            set_candidate_hwnd(hwnd)
            self._hide_since = None
            self._pos_dirty = True
            self._position_once()
            # SHOW 直挂后补一次图层插序：候选框重建自愈（v1.4 相对 v1.2 的关键优势）
            if self.visible:
                self._apply_layer(hwnd)
            return True
        except Exception:
            return False

    def _rescan_candidate(self):
        """低频兜底全扫：find_candidate_window + 命中即缓存并定位。返回是否命中。"""
        now = time.time()
        if now - self._last_scan_ts < self._rescan_min:
            return False
        self._last_scan_ts = now
        self._n_scans += 1
        if PERF_LOG_ENABLED:
            _perf_log(f'EnumWindows scan #{self._n_scans}')
        try:
            win = find_candidate_window(self.cfg.get('layout', 'horizontal_double'))
        except Exception as e:
            try:
                _write_log(f'[_rescan_candidate] 扫描异常: {e}')
            except Exception:
                pass
            return False
        if not win:
            return False
        hwnd, _rect = win
        if hwnd != self._cached_hwnd:
            self._cached_hwnd = hwnd
            set_candidate_hwnd(hwnd)
        self._hide_since = None
        self._need_rescan = False
        self._position_once()
        return True

    # ---------- 图层（v1.5：自 v1.2 恢复，事件驱动下候选框重建可自愈）----------
    def _apply_layer(self, cand_hwnd):
        """图层层级（事件驱动调用，频率低，不再每拍无条件执行）：
        above：移动路径已自带 HWND_TOPMOST = 天然在候选框上方，不做任何额外动作；
        below：仅在 贴边=中间（图片与候选框重叠）时有意义（v1.3 教训）：
          - 候选框是置顶(WS_EX_TOPMOST) → 把图片窗插到其正下方（已紧贴则不重插）；
          - 候选框非置顶 → below 不可用，保持图片窗 topmost 保底可见（节流记日志）。
        左/右贴边（与候选框不重叠）时执行任何插序都是纯副作用 → 保持 topmost。"""
        try:
            if self.layer != 'below':
                return  # above：回归 v1.4，无任何额外 z-order 操作
            if self.cfg.get('side', 'right') != 'center':
                return  # 侧贴边不重叠：below 无意义，保持 topmost
            if not cand_hwnd or not self.visible:
                return
            top = self._top_hwnd()
            if not top:
                return
            # 探测候选框是否置顶（GWL_EXSTYLE & WS_EX_TOPMOST）
            ex = user32.GetWindowLongPtrW(cand_hwnd, GWL_EXSTYLE)
            if not (ex & WS_EX_TOPMOST):
                # 候选框非置顶：插序无法稳定生效且会让图片被活动窗口盖住 → 保底置顶
                self._log_below_unavailable(cand_hwnd)
                return
            # 已紧贴候选框正下方（图片窗上方第一窗 == 候选框）→ 无需重复插序
            if user32.GetWindow(top, GW_HWNDPREV) == cand_hwnd:
                return
            user32.SetWindowPos(top, cand_hwnd, 0, 0, 0, 0,
                                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        except Exception:
            pass

    def _log_below_unavailable(self, cand_hwnd):
        """节流日志：below+center 但候选框非置顶 → below 不可用，保持置顶。
        事件驱动下定位调用较频繁，同一状态 5s 内最多记一条，避免刷屏 error.log。"""
        try:
            now = time.monotonic()
            if now - self._below_log_ts < 5.0:
                return
            self._below_log_ts = now
            _write_log(f'[layer] below 不可用：候选框(0x{cand_hwnd:X})非置顶，'
                       f'保持图片窗 topmost 保底可见')
        except Exception:
            pass

    def _sync_layer_with_candidate(self):
        """切皮肤/手动拖拽/热重载后的图层补同步：候选框在场且图片可见才重插层级。"""
        try:
            if self.visible and self._cached_hwnd_ok():
                self._apply_layer(self._cached_hwnd)
        except Exception:
            pass

    def _ensure_topmost_if_needed(self):
        """低频 z-order 兜底（心跳调用，不做任何枚举）：
        · layer=above 或 侧贴边：维持 v1.4 语义 —— 仅当被候选框压住
          （GetWindow 向上找 24 层内出现缓存句柄）才补一次 HWND_TOPMOST；
        · layer=below 且 贴边=中间：改检「图片窗是否仍紧贴候选框正下方」，
          漂了才由 _apply_layer 重插，绝不补 topmost（否则破坏 below 插序）。"""
        try:
            if not self._cached_hwnd or not self.visible:
                return
            top = self._top_hwnd()
            if not top:
                return
            if self.layer == 'below' and self.cfg.get('side', 'right') == 'center':
                # below+center：只维护「紧贴候选框下方」，不把图片拉回 topmost
                self._apply_layer(self._cached_hwnd)
                return
            w = user32.GetWindow(top, GW_HWNDPREV)  # 向 z-order 上方走
            steps = 0
            while w and steps < 24:
                if w == self._cached_hwnd:
                    user32.SetWindowPos(top, HWND_TOPMOST, 0, 0, 0, 0,
                                        SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
                    return
                w = user32.GetWindow(w, GW_HWNDPREV)
                steps += 1
        except Exception:
            pass

    def _hide_if_gone(self, now):
        """候选框消失去抖：_hide_since 起 150ms 内复现则不 withdraw（防闪烁）；
        超阈值且非 pinned 才隐藏。"""
        if self._hide_since is None or self.pinned or not self.visible:
            return
        if now - self._hide_since >= 0.150:
            self.root.withdraw()
            self.visible = False
            self._hide_since = None
            if PERF_LOG_ENABLED:
                _perf_log('hide (gone>150ms)')

    def _event_tick(self):
        """事件消费节拍（~16ms）：读取线程安全序号，仅在有新事件时做事。"""
        try:
            now = time.time()
            # 1) 候选框销毁/隐藏事件 → 清缓存 + 去抖计时（重建由 SHOW/心跳自愈）
            if _EVT_GONE_CNT > self._last_gone_cnt:
                self._last_gone_cnt = _EVT_GONE_CNT
                if self._cached_hwnd:
                    if PERF_LOG_ENABLED:
                        _perf_log(f'GONE hwnd=0x{self._cached_hwnd:X}')
                    self._cached_hwnd = 0
                    set_candidate_hwnd(0)
                if self.visible and not self.pinned:
                    self._hide_since = now
                self._need_rescan = True
            # 2) 候选框移动事件 → 立即定位（无延迟）
            if _EVT_MOVE_CNT > self._last_move_cnt:
                self._last_move_cnt = _EVT_MOVE_CNT
                self._last_move_ts = _EVT_MOVE_TS
                if self._cached_hwnd_ok():
                    if PERF_LOG_ENABLED:
                        _perf_log(f'MOVE hwnd=0x{self._cached_hwnd:X}')
                    t_lat = _EVT_MOVE_TS
                    self._position_once()
                    if PERF_LOG_ENABLED:
                        # 事件到达 → 定位完成 的端到端延迟（含本 tick 调度等待）
                        _perf_log(f'  ├ follow latency {(time.monotonic() - t_lat) * 1000:.1f} ms')
            # 3) SHOW 事件 → 无缓存时优先直挂候选句柄，失败再低频全扫
            if _EVT_SHOW_CNT > self._last_show_cnt:
                self._last_show_cnt = _EVT_SHOW_CNT
                if not self._cached_hwnd:
                    if _EVT_SHOW_HWND and self._try_attach_show_hwnd(_EVT_SHOW_HWND):
                        self._hide_since = None
                    else:
                        self._need_rescan = True
            # 4) 需要重扫（缓存曾失效）→ 低频全扫自愈（受节流）
            if self._need_rescan and not self._cached_hwnd:
                self._rescan_candidate()
            # 5) 消失去抖隐藏（150ms 复现保护）
            self._hide_if_gone(now)
        except Exception as e:
            try:
                _write_log(f'[_event_tick] 异常: {e}')
            except Exception:
                pass
        try:
            self.root.after(self.event_ms, self._event_tick)
        except Exception:
            pass  # root 已销毁（open_wizard 重建场景），停止节拍

    def _heartbeat(self):
        """200ms 兜底心跳：只做轻量校验，不做 EnumWindows——
        · 缓存有效性（IsWindow/IsWindowVisible O(1)）；失效→标记重扫（交给低频全扫）
        · 缓存有效但位置脏 → 只用缓存 rect 补一次定位（事件丢失兜底）
        · 极低频 z-order 兜底置顶
        例外：事件钩子安装失败时（SetWinEventHook 不可用）退化本模式 ——
        心跳充当低频全扫（受 _rescan_min 节流），保证「已有功能不坏」。"""
        try:
            now = time.time()
            self._n_heartbeats += 1
            if not event_hook_alive():
                # 退化：事件驱动不可用 → 心跳低频全扫定位（≈0.4s 一次，CPU 可接受）
                if self._cached_hwnd and not self._cached_hwnd_ok():
                    self._cached_hwnd = 0
                    set_candidate_hwnd(0)
                self._rescan_candidate()
                self._hide_if_gone(now)
                return
            if self._cached_hwnd and not self._cached_hwnd_ok():
                if PERF_LOG_ENABLED:
                    _perf_log(f'heartbeat: cache 失效 0x{self._cached_hwnd:X}')
                self._cached_hwnd = 0
                set_candidate_hwnd(0)
                self._need_rescan = True
                if self.visible and not self.pinned:
                    self._hide_since = now
            if self._cached_hwnd_ok():
                if self._pos_dirty:
                    self._position_once()
                    self._pos_dirty = False
                self._ensure_topmost_if_needed()
            elif self._need_rescan:
                # 兜底：心跳允许在「缓存失效待重扫」时低频触发全扫（受节流）
                self._rescan_candidate()
            self._hide_if_gone(now)
        except Exception as e:
            try:
                _write_log(f'[_heartbeat] 异常: {e}')
            except Exception:
                pass
        try:
            self.root.after(self.heartbeat_ms, self._heartbeat)
        except Exception:
            pass  # root 已销毁，停止心跳

    def run(self):
        """启动事件守护线程 + 三个定时循环：事件 tick（16ms）/ 心跳（200ms）/
        皮肤热重载（2s，保持）。mainloop 结束（退出/重建）时清理事件线程。"""
        _ensure_event_thread()
        # 启动先做一次定位：候选框可能已在屏幕上（事件线程就绪前的窗口不丢）
        try:
            self._rescan_candidate()
        except Exception:
            pass
        self.root.after(self.event_ms, self._event_tick)
        self.root.after(self.heartbeat_ms, self._heartbeat)
        self.root.after(self.skin_ms, self.check_skin)
        try:
            self.root.mainloop()
        finally:
            _release_event_thread()

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
        # 启动即写日志（诊断用：任何路径都留痕，含 cwd/exe/python 版本）
        try:
            _write_log(f'[启动] v{VERSION} cwd={os.getcwd()} exe={sys.argv[0]} '
                       f'frozen={getattr(sys, "frozen", False)} python={sys.version.split()[0]}')
        except Exception:
            pass
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
