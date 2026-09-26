# -*- coding: utf-8 -*-
"""
rime_char_overlay.py —— Rime 皮肤外挂 v0.7
让小狼毫 (Rime/Weasel) 输入时，候选框旁边跟随显示图片。

v0.7 配置向导（所见即所得）：
  ① 选择图片（png/jpg/webp/gif/bmp，GIF/动图WebP/APNG 支持动图播放）
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
  RimeSkinOverlay.exe --install/--uninstall → 自启管理（CLI；也可在向导勾选/托盘开关）

依赖: 主程序仅 Python 标准库；预览/光环需 Pillow（可选）
快捷键: Ctrl+Alt+C 隐藏/显示 | Ctrl+Alt+Q 退出 | 拖动微调 | 滚轮缩放 | 右键菜单

v2.0-③ 选图自动生成候选框配色（升级四）：
  向导「🎨 生成候选框配色…」→ 从当前图片（动图取所有帧的颜色并集）提主色/强调色/背景色
  → 生成 21 字段配色方案（亮 color_scheme + 暗 color_scheme_dark，自动对比度校正）
  → 备份 weasel.custom.yaml.bak-<时间戳> 后按 patch 扁平键合并注入 → WeaselDeployer 重部署。
  皮肤档案记录配色名，切皮肤时图/参数/配色整套恢复（光环经 get_rime_accent 自动联动）。
  未生成过配色（配置里无 rime_scheme）时全链路静默跳过 —— 老用户零感知。

v2.0-①a 渲染层收口（升级一，第二步）：
  config.json 增 render_mode：compat（默认，v1.6 键色抠色路径）/ alpha（真 alpha 分层窗）。
  FollowOverlay.load_char 里「RGBA → 抠色 → PhotoImage → Label + 窗口透明色」整段收口成
  Renderer 接口，两个实现：CompatRenderer（老逻辑原样承载）/ LayeredRenderer（真 alpha）。
  缺键与非法值一律按 compat（resolve_render_mode）；回滚：改回 compat 即恢复。

v2.0-①b 真 alpha 分层窗实装（升级一，第三步）：
  LayeredRenderer = Tk 窗 + WS_EX_LAYERED + UpdateLayeredWindow 推 32bpp 预乘 BGRA 位图
  （PIL 向量化预乘，无逐像素 Python 循环；biHeight 取负=自上而下）。效果：逐像素 alpha
  真渐变（圆角/羽化边缘不再硬边）、含品红的图不再被抠穿、透明区点击穿透。
  推送时机：动图跟 _anim_tick 每帧推；静态图只在首次显示/移动/缩放/换图/特效变化推一次。
  向导 ⑪ 渲染模式可一键切换（兼容/增强）；alpha 下不放 Label 贴图，交互事件照旧挂 Tk 窗。

v2.0-② 套层皮肤（升级二，多图层）：
  一个皮肤 = 多个图片图层（默认 1 层 = 老行为）。皮肤档案升级为
  {schema:2, layers:[{image, anchor, offset_x, offset_y, scale, flip, effects, z,
  follow_width_ratio}], 全套 v1.6 旧字段}；老单图档案读进来自动包成单元素图层列表，
  单层时布局与 v1.6 逐位一致（plan_layer_layout 单层退化 = 原 _calc_target 公式）。
  锚点 left_edge / right_edge / center + offset 微调；follow_width_ratio 按候选框宽度
  比例分摊 → 候选框随打字变宽时两侧图层自动拉开、变窄收拢。
  渲染走「单窗多图」：compose_layers 把各层合成一张 RGBA 画布（各层自身 alpha 保留），
  只开一个窗口 —— 合成结果交给 ① 的 Renderer（compat 抠色贴 Label / alpha 推分层位图），
  compat 与 alpha 两条路都能跑多图层；绝不按层开窗（z-order 漂移是历史高发坑）。
  顶层旧字段（image/side/scale/offset_x/offset_y/flip_h/圆角/羽化）始终是第 0 层（主层）
  的权威值，layers[0] 只存额外量 —— 老代码读顶层键、老版本程序读该档案都不会跑偏。
  向导 ⑫ 图层区：图层列表 + 每层可选中调参（贴左/贴右/居中、左右上下微调、这层大小、
  水平翻转、随候选框变宽往外让 %），预览画布多层绘制（_draw_candidate 层级关系不破）。
"""
import sys, os, json, time, threading, re, queue, collections
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

def _enum_other_instance_windows(my_pid, exe_name='rimeskinoverlay.exe'):
    """枚举顶层窗口，返回属于「同名 exe 的其他进程」的 (hwnd, pid) 列表（S8）。

    纯 ctypes 实现（GetWindowThreadProcessId + OpenProcess/QueryFullProcessImageNameW），
    不 spawn powershell —— 这是 WM_CLOSE 精确投递的目标来源。
    """
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        try:
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value or pid.value == my_pid or pid.value in (0, 4):
                return True
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if not h:
                return True
            try:
                buf = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(buf))
                if (k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
                        and os.path.basename(buf.value).lower() == exe_name):
                    found.append((int(hwnd), int(pid.value)))
            finally:
                k32.CloseHandle(h)
        except Exception:
            pass
        return True

    try:
        u32.EnumWindows(_cb, 0)
    except Exception:
        pass
    return found


def _pid_alive(pid):
    """进程是否真在运行（GetExitCodeProcess == STILL_ACTIVE）。

    只用 OpenProcess 判句柄是不够的：已退出但句柄未释放的进程（我们持有
    Popen 句柄时）OpenProcess 仍会成功。用退出码区分，等待循环才不会被
    "僵尸"拖满 timeout。"""
    STILL_ACTIVE = 259
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            if k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            k32.CloseHandle(h)
    except Exception:
        return True


def _terminate_pid(pid):
    """强杀兜底：TerminateProcess（纯 ctypes，比 powershell 强杀快得多）"""
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x0001, False, int(pid))  # PROCESS_TERMINATE
        if not h:
            return False
        try:
            ctypes.windll.kernel32.TerminateProcess(h, 1)
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:
        return False


def _kill_existing(timeout=3.0):
    """关掉已运行的旧实例（排除当前进程）：先 WM_CLOSE 请它自己退，超时才强杀（S8）。

    历史：powershell Get-CimInstance + Stop-Process 强杀，实测 5-15s 且进程被硬切。
    现在：
      1) 纯 ctypes 枚举同名进程的顶层窗口（顺带拿到 pid）；
      2) 每个窗口 PostMessage(WM_CLOSE)：新版本注册了 WM_DELETE_WINDOW 协议，
         Tk 收到后正常走 mainloop 退出 + 释放 WinEventHook 线程 / 托盘图标；
         （旧版本没注册协议：窗口会被销毁但进程可能残留 → 第 3 步兜底）
      3) 等 timeout 秒，仍存活的 pid 用 TerminateProcess 强杀，
         保证「旧实例一定会被换掉」的既有语义不变。
    返回：本次处理的目标进程数（0 = 没有别的实例）。
    """
    my_pid = os.getpid()
    targets = _enum_other_instance_windows(my_pid)
    if not targets:
        return 0
    pids = sorted({pid for _hwnd, pid in targets})
    u32 = ctypes.windll.user32
    WM_CLOSE = 0x0010
    for hwnd, _pid in targets:
        try:
            u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        except Exception:
            pass
    deadline = time.time() + max(0.0, timeout)
    while time.time() < deadline:
        if not any(_pid_alive(p) for p in pids):
            break
        time.sleep(0.15)
    for p in pids:
        if _pid_alive(p):
            _terminate_pid(p)
    return len(pids)

# ============ 自启管理 ============
APP_NAME = 'RimeSkinOverlay'
VERSION = 'v2.0'

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


def _autostart_target():
    """自启目标三元组 (target, arguments, workdir)。

    exe 版：直接用自己；源码版：用同目录 pythonw.exe（无控制台窗口）+ 脚本路径，
    这样开发时也能试自启（旧版直接拒绝源码模式，只支持 exe）。
    """
    if getattr(sys, 'frozen', False):
        return os.path.abspath(sys.executable), '--tray', HERE
    script = os.path.abspath(__file__)
    pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    exe = pyw if os.path.exists(pyw) else sys.executable
    return exe, f'"{script}" --tray', HERE


def autostart_installed():
    """启动文件夹里是否存在本程序的自启快捷方式（GUI/托盘勾选态的唯一真相）"""
    return os.path.exists(_startup_lnk())


def install_autostart(quiet=False):
    import subprocess, tempfile
    target, args, wd = _autostart_target()
    lnk = _startup_lnk()
    vbs = os.path.join(tempfile.gettempdir(), '_skov_mklnk.vbs')
    with open(vbs, 'w', encoding='gbk') as f:
        f.write(
            'Set ws = CreateObject("WScript.Shell")\n'
            f'Set sc = ws.CreateShortcut("{lnk}")\n'
            f'sc.TargetPath = "{target}"\n'
            f'sc.Arguments = "{args}"\n'
            f'sc.WorkingDirectory = "{wd}"\n'
            'sc.WindowStyle = 7\n'
            'sc.Description = "Rime Skin Overlay"\n'
            'sc.Save()\n'
        )
    try:
        subprocess.run(['cscript', '//nologo', vbs], check=True, timeout=15)
        if not quiet:
            print(f'已安装开机自启: {lnk}')
        return 0
    except Exception as e:
        if not quiet:
            print(f'安装自启失败: {e}')
        return 1
    finally:
        try:
            os.remove(vbs)
        except OSError:
            pass


def uninstall_autostart(quiet=False):
    lnk = _startup_lnk()
    if os.path.exists(lnk):
        try:
            os.remove(lnk)
        except OSError as e:
            if not quiet:
                print(f'移除自启失败: {e}')
            return 1
        if not quiet:
            print(f'已移除开机自启: {lnk}')
        return 0
    if not quiet:
        print('未找到自启项（可能未安装）')
    return 0


def set_autostart(enabled, quiet=True, force=False):
    """GUI/托盘用开关（幂等）：返回 (ok, msg)。只动启动文件夹快捷方式，
    不碰 config.json（配置写入由调用方负责，避免半截配置覆盖）。
    """
    try:
        cur = autostart_installed()
        if enabled and ((not cur) or force):
            ok = install_autostart(quiet=quiet) == 0
        elif (not enabled) and cur:
            ok = uninstall_autostart(quiet=quiet) == 0
        else:
            ok = True
        _write_log(f'[自启] {"开启" if enabled else "关闭"} ok={ok} '
                   f'（已装={cur} force={force}）')
    except Exception as e:
        return False, f'操作异常: {e}'
    if not ok:
        return False, '操作失败（启动文件夹可能被安全软件拦截，可手动检查）'
    return True, ('已开启开机自启' if enabled else '已关闭开机自启')

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
    'autostart': False,  # 开机自启意图（真相为启动文件夹快捷方式是否存在，见 autostart_installed）
    'flip_h': False,     # 水平翻转（显示期，不修改图片文件；动图同样生效）
    # 显示期特效（只影响外挂显示，不改图片文件本身；皮肤档案一并保存）
    'corner_enabled': False,   # 圆角
    'corner_radius': 24,       # 圆角半径（px，按缩放后的显示尺寸）
    'feather_enabled': False,  # 点阵羽化（边缘 alpha 用有序抖动近似成渐变）
    'feather_radius': 24,      # 羽化带宽（px，0~80）
    # ③ 候选框配色绑定（升级四）：空 = 未生成/未绑定 → 全链路静默跳过（老用户零感知）
    'rime_scheme': '',         # 亮套 Rime 配色方案名（生成后写入；切皮肤时整套恢复）
    'rime_scheme_dark': '',    # 暗套 Rime 配色方案名
    # ① 渲染模式（升级一）：compat=老键色抠色路径（v1.6 行为，默认）/ alpha=真 alpha 分层窗
    # 缺键与非法值一律按 compat 处理（resolve_render_mode），老用户零感知；见 Renderer 抽象
    'render_mode': 'compat',
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


# ============ ② 套层皮肤：多图层档案（v2.0）============
# 手册 ② 步 1/2/3：一个皮肤 = 多个图片图层，每层可锚到候选框左/右/边缘并按 offset 微调，
# 可选 follow_width_ratio 按候选框宽度比例分摊 —— 候选框随打字变宽时两侧图层自动拉开/收拢。
#
# 档案形态（写盘）：
#   {"schema": 2, "layers": [{image, anchor, offset_x, offset_y, scale, flip, effects,
#                             z, follow_width_ratio}, ...], <全套 v1.6 旧字段>}
# 兼容口径（硬要求）：
#   · 老单图 skin.json（无 schema / 无 layers）读进来 → 自动包成**单元素**图层列表；
#   · 单图层时布局与 v1.6 逐位一致（见 plan_layer_layout：单层退化为老 _calc_target 公式）；
#   · 顶层旧字段（image / side / scale / offset_x / offset_y / flip_h / 圆角 / 羽化）继续是
#     第 0 层（主层）的**权威值**，layers[0] 里这些键只存"额外量"，避免两处翻倍。
LAYER_SCHEMA = 2
LAYER_ANCHORS = ('left_edge', 'right_edge', 'center')
LAYER_KEYS = ('image', 'anchor', 'offset_x', 'offset_y', 'scale', 'flip',
              'effects', 'z', 'follow_width_ratio')
MAX_LAYERS = 6                  # 图层数上限（防呆：画布宽度随层数线性增长）
DEFAULT_LAYER_GAP = 8           # 图层与候选框边缘的间距（与 v1.6 的 gap=8 同口径）


def anchor_from_side(side):
    """旧字段 side（left/right/center）→ 图层锚点"""
    s = str(side or '').strip().lower()
    if s == 'left':
        return 'left_edge'
    if s == 'center':
        return 'center'
    return 'right_edge'


def side_from_anchor(anchor):
    """图层锚点 → 旧字段 side（保证老键始终可读）"""
    a = str(anchor or '').strip().lower()
    if a == 'left_edge':
        return 'left'
    if a == 'center':
        return 'center'
    return 'right'


def _as_int(v, default=0, lo=None, hi=None):
    try:
        n = int(round(float(v)))
    except Exception:
        n = int(default)
    if lo is not None and n < lo:
        n = lo
    if hi is not None and n > hi:
        n = hi
    return n


def _as_float(v, default=0.0, lo=None, hi=None):
    try:
        f = float(v)
    except Exception:
        f = float(default)
    if lo is not None and f < lo:
        f = lo
    if hi is not None and f > hi:
        f = hi
    return f


def normalize_layer(ld, skin_dir=None):
    """单个图层 → 规范形态（键齐全、类型正确、越界值夹紧）。非法输入不抛异常。"""
    d = ld if isinstance(ld, dict) else {}
    img = str(d.get('image') or '').strip()
    if img and skin_dir and not os.path.isabs(img):
        img = os.path.normpath(os.path.join(skin_dir, img))
    anc = str(d.get('anchor') or '').strip().lower()
    eff = d.get('effects') if isinstance(d.get('effects'), dict) else {}
    return {
        'image': img,
        'anchor': anc if anc in LAYER_ANCHORS else 'right_edge',
        'offset_x': _as_int(d.get('offset_x'), 0, -1000, 1000),
        'offset_y': _as_int(d.get('offset_y'), 0, -1000, 1000),
        'scale': _as_float(d.get('scale'), 1.0, 0.2, 2.0),
        'flip': bool(d.get('flip')),
        'effects': {
            'corner_enabled': bool(eff.get('corner_enabled')),
            'corner_radius': _as_int(eff.get('corner_radius'), 24, 0, 120),
            'feather_enabled': bool(eff.get('feather_enabled')),
            'feather_radius': _as_int(eff.get('feather_radius'), 24, 0, 80),
        },
        'z': _as_int(d.get('z'), 0, -99, 99),
        'follow_width_ratio': _as_float(d.get('follow_width_ratio'), 0.0, -1.0, 1.0),
    }


def make_layer_from_cfg(cfg, skin_dir=None):
    """老单图 cfg（顶层字段）→ 第 0 层（主层）。

    offset_x/offset_y 一律归零：顶层 cfg 的 offset 才是权威（否则两处相加翻倍）。
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    return normalize_layer({
        'image': cfg.get('image') or '',
        'anchor': anchor_from_side(cfg.get('side')),
        'offset_x': 0, 'offset_y': 0,
        'scale': cfg.get('scale', 1.0),
        'flip': cfg.get('flip_h', False),
        'effects': {
            'corner_enabled': cfg.get('corner_enabled', False),
            'corner_radius': cfg.get('corner_radius', 24),
            'feather_enabled': cfg.get('feather_enabled', False),
            'feather_radius': cfg.get('feather_radius', 24),
        },
        'z': 0, 'follow_width_ratio': 0.0,
    }, skin_dir=skin_dir)


def resolve_layers(cfg, skin_dir=None):
    """cfg → 运行时图层列表（每个元素键齐全）。

    · 老配置/老档案（无 layers 键）→ 单元素列表，**且必须继续走下面的主层合并分支**
      —— 顶层 offset_x/offset_y 是用户微调偏移的唯一权威（出厂 config.json 就是
      offset -132/-132），提前 return 会让老配置的微调偏移在启动路径上整体丢掉
      （F-V1：图片窗位移 132~162 px；皮肤路径因 list_skins 会 migrate 才侥幸正常）
    · 第 0 层（主层）：anchor/scale/flip/effects/offset 一律以顶层兼容字段为权威，
      layers[0] 里的同名字段**不参与计算**（F-V3：避免"顶层 offset + 层内 offset"双计；
      存盘时该字段本就归零，只有手改档案才可能非零，语义上以顶层为准）
    · 其它层（i>0）：完全用自己的字段
    · 按 z 稳定升序（画布从下往上叠）
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    raw = cfg.get('layers')
    layers = []
    if isinstance(raw, list) and raw:
        for x in raw:
            l = normalize_layer(x, skin_dir=skin_dir)
            if l.get('image'):
                layers.append(l)
    if not layers:
        # 老配置：补出主层，然后与有 layers 的情况走**同一条**合并分支（勿提前 return）
        layers = [make_layer_from_cfg(cfg, skin_dir=skin_dir)]
    layers = layers[:MAX_LAYERS]
    layers.sort(key=lambda l: l.get('z', 0))
    main = make_layer_from_cfg(cfg, skin_dir=skin_dir)
    l0 = dict(layers[0])
    # 第 0 层（主层）：锚点/缩放/翻转/特效一律以顶层兼容字段为权威 —— 向导的
    # ③ 贴边方向 / ④ 缩放 / 水平翻转 / ⑨ 特效 编辑的就是主层，滚轮缩放改的也是顶层 scale
    l0['anchor'] = main['anchor']
    l0['scale'] = main['scale']
    l0['flip'] = main['flip']
    l0['effects'] = main['effects']
    if not l0.get('image'):
        l0['image'] = main['image']
    # 顶层 offset 就是第 0 层的 offset（单一权威，F-V3：不再叠加层内值 → 绝无双计）
    l0['offset_x'] = _as_int(cfg.get('offset_x'), 0, -1000, 1000)
    l0['offset_y'] = _as_int(cfg.get('offset_y'), 0, -1000, 1000)
    layers[0] = l0
    return layers


def save_layers_into_cfg(cfg, layers=None):
    """把图层写回档案形态：schema 2 + layers + 顶层兼容字段同步（原地改并返回 cfg）。

    单向权威（F-V3 的延伸）：顶层兼容字段是**第 0 层（主层）的权威来源**，所以这里
    是「顶层 → 主层」回填 + 主层 offset 归零，而不是拿 layers[0] 的历史值覆盖顶层。

    为什么必须单向：向导打开时 cfg 来自 config.json（顶层 scale=0.9），而 cfg['layers']
    可能是更早存档里遗留的主层（scale 字段是历史值 1.0）。若用后者覆盖前者，用户保存时
    顶层参数会被静默改掉（实测 R01：0.9 被写成 1.0）。反过来，用户在向导里改主层参数时
    _layer_set_params 已经**同时**写了顶层与层内，所以回填不会丢东西。
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    layers = layers if layers is not None else resolve_layers(cfg)
    layers = [normalize_layer(x) for x in layers if isinstance(x, dict) and x.get('image')]
    if not layers:
        layers = [make_layer_from_cfg(cfg)]
    layers = layers[:MAX_LAYERS]
    arch = [dict(x, effects=dict(x.get('effects') or {})) for x in layers]
    # ---- 顶层 → 主层回填（顶层权威；只回填配置里真的存在的键）----
    if 'scale' in cfg:
        arch[0]['scale'] = _as_float(cfg.get('scale'), arch[0]['scale'], 0.2, 2.0)
    if 'flip_h' in cfg:
        arch[0]['flip'] = bool(cfg.get('flip_h'))
    if 'side' in cfg:
        arch[0]['anchor'] = anchor_from_side(cfg.get('side'))
    _eff_keys = ('corner_enabled', 'corner_radius', 'feather_enabled', 'feather_radius')
    if any(k in cfg for k in _eff_keys):
        e = arch[0]['effects']
        if 'corner_enabled' in cfg:
            e['corner_enabled'] = bool(cfg.get('corner_enabled'))
        if 'corner_radius' in cfg:
            e['corner_radius'] = _as_int(cfg.get('corner_radius'), 24, 0, 120)
        if 'feather_enabled' in cfg:
            e['feather_enabled'] = bool(cfg.get('feather_enabled'))
        if 'feather_radius' in cfg:
            e['feather_radius'] = _as_int(cfg.get('feather_radius'), 24, 0, 80)
    arch[0]['offset_x'] = 0
    arch[0]['offset_y'] = 0
    cfg['schema'] = LAYER_SCHEMA
    cfg['layers'] = arch
    cfg['image'] = arch[0]['image']
    cfg['side'] = side_from_anchor(arch[0]['anchor'])
    cfg['scale'] = arch[0]['scale']
    cfg['flip_h'] = bool(arch[0]['flip'])
    eff = arch[0]['effects']
    cfg['corner_enabled'] = bool(eff.get('corner_enabled'))
    cfg['corner_radius'] = _as_int(eff.get('corner_radius'), 24, 0, 120)
    cfg['feather_enabled'] = bool(eff.get('feather_enabled'))
    cfg['feather_radius'] = _as_int(eff.get('feather_radius'), 24, 0, 80)
    return cfg


def migrate_skin_cfg(cfg, skin_dir=None):
    """老/新皮肤档案 → 统一档案形态（schema 2 + 单元素或多元图层列表）。

    纯函数：不改入参；幂等；旧字段一个不丢（只多不少）。
    """
    out = dict(cfg or {})
    raw = out.get('layers')
    if isinstance(raw, list) and raw:
        layers = []
        for x in raw:
            l = normalize_layer(x, skin_dir=skin_dir)
            if l.get('image'):
                layers.append(l)
        if not layers:
            layers = [make_layer_from_cfg(out, skin_dir=skin_dir)]
    else:
        layers = [make_layer_from_cfg(out, skin_dir=skin_dir)]
    layers = sorted(layers, key=lambda l: l.get('z', 0))[:MAX_LAYERS]
    layers[0] = dict(layers[0])
    layers[0]['offset_x'] = 0       # 顶层 offset 是权威（档案形态里主层不再重复存）
    layers[0]['offset_y'] = 0
    out['schema'] = LAYER_SCHEMA
    out['layers'] = layers
    return out


def _rect_tuple(rect):
    """候选框矩形 → (left, top, right, bottom)；支持 wintypes.RECT 或 4 元组"""
    if rect is None:
        return 0, 0, 0, 0
    try:
        if hasattr(rect, 'left'):
            return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
        l, t, r, b = rect
        return int(l), int(t), int(r), int(b)
    except Exception:
        return 0, 0, 0, 0


def plan_layer_layout(layers, sizes, rect, gap=DEFAULT_LAYER_GAP, main_off=(0, 0)):
    """② 步 3：一次算出全部图层的目标坐标（纯函数、无状态、可预览可单测）。

    返回 (win_x, win_y, win_w, win_h, placements)：
      · win_*  = 合成画布（= 唯一的那个透明窗）的屏幕位置与尺寸（各层的包围盒）
      · placements = [(层号, 画布内 dx, 画布内 dy), ...] —— 与 layers 一一对应

    锚点规则（手册 ② 步 2）：
      left_edge  → 候选框左边缘外侧：left - 层宽 - gap
      right_edge → 候选框右边缘外侧：right + gap
      center     → 水平居中于候选框：(cw - 层宽) / 2
    follow_width_ratio（可选）额外按候选框宽度比例把该层继续向外推（左右同步拉开/收拢）。
    单图层 + ratio=0 时逐位退化为 v1.6 的 _calc_target 公式（兼容硬要求）。
    """
    left, top, right, bottom = _rect_tuple(rect)
    cw, ch = right - left, bottom - top
    places, boxes = [], []
    mo_x = _as_int((main_off or (0, 0))[0], 0)
    mo_y = _as_int((main_off or (0, 0))[1], 0)
    for i, ld in enumerate(layers or []):
        if i >= len(sizes or []):
            break
        try:
            lw, lh = int(sizes[i][0]), int(sizes[i][1])
        except Exception:
            continue
        if lw <= 0 or lh <= 0:
            continue
        d = ld if isinstance(ld, dict) else {}
        anc = d.get('anchor', 'right_edge')
        ox = _as_int(d.get('offset_x'), 0)
        oy = _as_int(d.get('offset_y'), 0)
        if i == 0:
            ox += mo_x
            oy += mo_y
        if anc == 'left_edge':
            lx = left - lw - gap + ox
        elif anc == 'center':
            lx = left + (cw - lw) // 2 + ox
        else:
            lx = right + gap + ox
        ratio = _as_float(d.get('follow_width_ratio'), 0.0)
        if ratio:
            spread = int(round(cw * ratio))
            lx += -spread if anc == 'left_edge' else spread
        ly = top + (ch - lh) // 2 + oy
        boxes.append((i, lx, ly, lw, lh))
    if not boxes:
        return 0, 0, 0, 0, []
    wx = min(b[1] for b in boxes)
    wy = min(b[2] for b in boxes)
    ww = max(b[1] + b[3] for b in boxes) - wx
    wh = max(b[2] + b[4] for b in boxes) - wy
    places = [(i, lx - wx, ly - wy) for (i, lx, ly, _lw, _lh) in boxes]
    return int(wx), int(wy), int(ww), int(wh), places


def compose_layers(frames, size, placements, Image=None):
    """② 步 4「单窗多图」：把各层帧合成到一张画布（各层自身 alpha 原样保留）。

    frames     : 与图层同序的 RGBA 帧（None 表示该层跳过）
    size       : (w, h) 画布尺寸
    placements : plan_layer_layout 的产出（层号 → 画布内 dx/dy）
    越界/负偏移一律按交集裁剪，绝不抛异常。
    """
    if Image is None:
        Image = _pil()[0]
    w = max(0, int((size or (0, 0))[0]))
    h = max(0, int((size or (0, 0))[1]))
    canvas = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    if w <= 0 or h <= 0:
        return canvas
    pos = {}
    for item in (placements or []):
        try:
            pos[int(item[0])] = (int(item[1]), int(item[2]))
        except Exception:
            continue
    for idx, fr in enumerate(frames or []):
        if fr is None:
            continue
        try:
            src = fr if fr.mode == 'RGBA' else fr.convert('RGBA')
        except Exception:
            continue
        dx, dy = pos.get(idx, (0, 0))
        sw, sh = src.size
        x0, y0 = max(0, dx), max(0, dy)
        x1, y1 = min(w, dx + sw), min(h, dy + sh)
        if x1 <= x0 or y1 <= y0:
            continue
        crop = src.crop((x0 - dx, y0 - dy, x1 - dx, y1 - dy))
        canvas.alpha_composite(crop, (x0, y0))
    return canvas


def _valid_skin_name(name):
    """皮肤名合法性：1-40 字符，中英文/数字/空格/横线/下划线；防路径穿越"""
    if not name or len(name) > 40:
        return False
    import re as _re
    return bool(_re.fullmatch(r'[\w\u4e00-\u9fff][\w\u4e00-\u9fff \-]{0,39}', name))


def list_skins():
    """列出所有已保存皮肤：返回 [(名称, cfg), ...] 按名称排序；损坏条目跳过。

    v2.0-②：读到的档案一律过 migrate_skin_cfg —— 老单图档案在此自动包成单元素图层
    列表（schema 2），调用方拿到的永远是统一形态；图片缺失的档案照旧跳过。
    """
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
            cfg = migrate_skin_cfg(cfg, skin_dir=p)
            cfg['name'] = d
            img = cfg.get('image')
            if img and os.path.exists(img):
                out.append((d, cfg))
        except Exception:
            continue
    return out


def save_skin(name, cfg):
    """把当前配置 + 图片副本保存为皮肤档案；返回保存后的 cfg（含 name），失败抛异常。

    v2.0-②：档案升级为 {schema:2, layers:[...], 兼容旧字段}。每层图片都以
    image.<ext> / layer1.<ext> / layer2.<ext> … 复制进 skins/<名>/，顶层旧字段
    与第 0 层（主层）保持同步 —— 老版本程序读这个档案仍能正常显示主图。
    """
    if not _valid_skin_name(name):
        raise ValueError('皮肤名称限 1-40 字符（中文/字母/数字/空格/横线）')
    src = cfg.get('image')
    if not src or not os.path.exists(src):
        raise ValueError('图片不存在，无法保存皮肤')
    d = os.path.join(SKINS_DIR, name)
    os.makedirs(d, exist_ok=True)
    layers = resolve_layers(cfg)
    new_layers = []
    for i, ld in enumerate(layers):
        s = ld.get('image')
        if not s or not os.path.exists(s):
            if i == 0:
                raise ValueError('图片不存在，无法保存皮肤')
            continue                      # 缺图的从层直接丢弃（不写坏档案）
        ext = os.path.splitext(s)[1].lower() or '.png'
        dst_img = os.path.join(d, ('image' if i == 0 else f'layer{i}') + ext)
        if os.path.normpath(s) != os.path.normpath(dst_img):
            import shutil
            shutil.copy2(s, dst_img)
        nl = dict(ld)
        nl['image'] = dst_img
        new_layers.append(nl)
    if not new_layers:
        raise ValueError('图片不存在，无法保存皮肤')
    scfg = dict(cfg)
    save_layers_into_cfg(scfg, new_layers)
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
        # 统一走模块级解析（口径与 ③ 配色注入一致：只认 "扁平键": 值 行）
        return parse_flat_yaml(path)

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


# ============ ③ Rime 候选框配色自动生成与安全注入（升级四）============
# 管线：选图 → 提主色/强调色/背景色（动图取所有帧的颜色并集）→ 生成 21 字段配色方案
# （亮 color_scheme + 暗 color_scheme_dark）→ 自动对比度校正 → 备份后按 patch 扁平键
# 合并进 weasel.custom.yaml → 调 WeaselDeployer 重部署 → 皮肤档案记配色名（切皮肤整套恢复）。
# 字段名以本机 weasel.custom.yaml 现成先例（furina_aqua / furina_night / yuzu_orange /
# spring_bloom 等；其中 21 键的 6 套为基准）为准，一字不差：无遗漏、无多余。
# 默认不动作：皮肤/配置里没有 rime_scheme 键时，全链路静默跳过（老用户零感知）。
SCHEME_FIELDS = (
    'name', 'author', 'color_format',
    'back_color', 'border_color', 'shadow_color',
    'text_color', 'label_color', 'comment_text_color',
    'candidate_text_color', 'candidate_back_color',
    'hilited_text_color', 'hilited_back_color',
    'hilited_candidate_text_color', 'hilited_candidate_back_color',
    'hilited_candidate_border_color', 'hilited_label_color',
    'hilited_comment_text_color', 'hilited_candidate_shadow_color',
    'nextpage_color', 'prevpage_color',
)   # 恰好 21 个字段
SCHEME_AUTHOR = 'RimeSkinOverlay'
SCHEME_SCAN_EDGE = 256           # 颜色统计前把帧缩到最长边（NEAREST，不引入混合色）
SCHEME_MAX_SCAN_FRAMES = 240     # 帧数上限（GIF 通常 <100 帧；超过才均匀采样）
SCHEME_MIN_DELTA_MAIN = 100      # 主文字与所在背景的亮度差下限（0-255 luma，手册口径）
SCHEME_MIN_DELTA_SUB = 70        # 次级文字（序号/注释/翻页箭头）亮度差下限
SCHEME_MIN_DELTA_ACCENT_BG = 40  # 强调色与候选栏底色的亮度差下限
SCHEME_MIN_DELTA_BORDER = 30     # 边框/选中边框与所在底色的亮度差下限
SCHEME_BG_LIGHT_MIN_LUMA = 215   # 亮套候选栏底色亮度下限（保证浅底深字）
SCHEME_BG_DARK_MAX_LUMA = 70     # 暗套候选栏底色亮度上限（保证深底浅字）
SCHEME_TEXT_FLIP_LUMA = 140      # 高亮块亮度 ≥ 此值 → 用深色文字（否则浅色）
SCHEME_DEPLOY_TIMEOUT = 30.0     # WeaselDeployer 等待上限（秒）；超时明确报错不静默
SCHEME_DEPLOY_HINT = '可手动部署：右键小狼毫托盘图标 →「重新部署」'
SCHEME_MANIFEST = os.path.join(HERE, 'rime_schemes.json')  # 本工具生成过的方案记录（清残留用）

# 扁平键行：  "preset_color_schemes/<方案>/<字段>": <值>
_SCHEME_LINE_RE = re.compile(r'''^(\s*)["']?preset_color_schemes/([^/"']+)/([^"']+?)["']?\s*:\s*(.*?)\s*$''')
# 当前配色行：  "style/color_scheme" / "style/color_scheme_dark"
_ACTIVE_LINE_RE = re.compile(r'''^(\s*)["']?(style/color_scheme(?:_dark)?)["']?\s*:\s*(.*?)\s*$''')
_PATCH_LINE_RE = re.compile(r'^(\s*)patch\s*:\s*$')
# R5：本工具写的分节标题注释行（`# ===== 某皮肤 =====`，与用户文件里现成写法同形）
_SCHEME_HEADER_RE = re.compile(r'^\s*#\s*={3,}\s*.+?\s*={3,}\s*$')


def _clamp8(v):
    return 0 if v < 0 else (255 if v > 255 else int(round(v)))


def _luma255(rgb):
    """感知亮度（手册口径 L = 0.299R + 0.587G + 0.114B，0-255 标度）"""
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _contrast_ratio(c1, c2):
    """WCAG 对比度（1~21，附带参考；主判定用 _luma255 差）"""
    def _lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    l1 = 0.2126 * _lin(c1[0]) + 0.7152 * _lin(c1[1]) + 0.0722 * _lin(c1[2])
    l2 = 0.2126 * _lin(c2[0]) + 0.7152 * _lin(c2[1]) + 0.0722 * _lin(c2[2])
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


def _mix(c1, c2, t):
    """线性混色（t=0 取 c1，t=1 取 c2）"""
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return (_clamp8(c1[0] + (c2[0] - c1[0]) * t),
            _clamp8(c1[1] + (c2[1] - c1[1]) * t),
            _clamp8(c1[2] + (c2[2] - c1[2]) * t))


def _saturation(rgb):
    """饱和度（max-min，0-255）"""
    return max(rgb[:3]) - min(rgb[:3])


def _color_dist(c1, c2):
    """RGB 欧氏距离（0-441）"""
    return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2) ** 0.5


def _vivid(rgb, amount=1.2):
    """提饱和：把颜色往远离其灰度等值线的方向拉（保持亮度）"""
    gray = _luma255(rgb)
    return tuple(_clamp8(gray + (v - gray) * amount) for v in rgb[:3])


def _push_luma(rgb, min_luma=None, max_luma=None):
    """把颜色亮度推到达标区间（保持色相，往白/黑插值）；已在区间内则原样返回"""
    l = _luma255(rgb)
    if min_luma is not None and l < min_luma:
        target = (255, 255, 255)
    elif max_luma is not None and l > max_luma:
        target = (0, 0, 0)
    else:
        return tuple(rgb[:3])
    for i in range(1, 41):
        c = _mix(rgb, target, i / 40.0)
        if min_luma is not None and _luma255(c) >= min_luma:
            return c
        if max_luma is not None and _luma255(c) <= max_luma:
            return c
    return tuple(target)


def _ensure_delta(fg, bg, min_delta, prefer=None):
    """保证 fg 与 bg 的 luma 差 ≥ min_delta（保持色相：往黑/白方向最小步插值）。

    prefer='dark'/'light' 指定优先方向（浅底压深 / 深底提亮）；首选方向到不了上限就换另一方向。
    返回「最接近原色且达标」的颜色——这就是自动对比度校正的核心。
    """
    lb = _luma255(bg)
    if abs(_luma255(fg) - lb) >= min_delta:
        return tuple(fg[:3])
    if prefer not in ('dark', 'light'):
        prefer = 'dark' if lb >= 128 else 'light'
    order = [('dark', (0, 0, 0)), ('light', (255, 255, 255))]
    if prefer == 'light':
        order.reverse()
    best = tuple(fg[:3])
    for _tag, target in order:
        for i in range(1, 41):
            c = _mix(fg, target, i / 40.0)
            if abs(_luma255(c) - lb) >= min_delta:
                return c
            best = c
    return best


def _text_on(bg, light_src, dark_src, min_delta):
    """在底色 bg（通常是高亮块）上选文字色：块亮→深字、块暗→浅字，再保证 luma 差达标"""
    if _luma255(bg) >= SCHEME_TEXT_FLIP_LUMA:
        return _ensure_delta(dark_src, bg, min_delta, prefer='dark')
    return _ensure_delta(light_src, bg, min_delta, prefer='light')


def _hex6(rgb):
    """0xRRGGBB（Rime 配色标准写法，与 weasel.custom.yaml 先例一致）"""
    return '0x%02X%02X%02X' % (rgb[0], rgb[1], rgb[2])


def _hex8(rgb, alpha):
    """0xAARRGGBB（带透明度：边框/投影用；alpha 为 'AA'/'1A' 之类 2 位十六进制）"""
    return '0x%s%02X%02X%02X' % (str(alpha).upper().zfill(2), rgb[0], rgb[1], rgb[2])


def _parse_hex_color(s):
    """'0xDCE2F0' / '0x4A6FA599' / '#RRGGBB' → (r,g,b)；失败返回 None"""
    try:
        t = str(s).strip().strip('"').strip("'")
        if t.lower().startswith('0x'):
            v = int(t[2:], 16)
        elif t.startswith('#'):
            v = int(t[1:], 16)
        else:
            return None
        if v > 0xFFFFFF:      # 带 alpha（AARRGGBB）→ 丢弃 alpha，取颜色
            v &= 0xFFFFFF
        return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)
    except Exception:
        return None


# ---------- 颜色提取（单图 / 动图多帧并集）----------
def collect_scheme_frames(path, Image=None, max_frames=SCHEME_MAX_SCAN_FRAMES):
    """打开图片并返回 (帧列表, meta)。动图默认取**所有帧**的颜色并集（超上限才均匀采样）。"""
    if Image is None:
        from PIL import Image as _I
        Image = _I
    src = Image.open(path)
    try:
        n = int(getattr(src, 'n_frames', 1) or 1)
    except Exception:
        n = 1
    idxs = list(range(n))
    sampled = False
    if max_frames and n > max_frames:
        step = n / float(max_frames)
        idxs = sorted({min(n - 1, int(i * step)) for i in range(max_frames)} | {0, n - 1})
        sampled = True
    frames = []
    for i in idxs:
        try:
            src.seek(i)
            frames.append(src.convert('RGBA'))
        except Exception:
            break
    meta = {'n_frames': n, 'used': len(frames), 'sampled': sampled}
    try:
        src.seek(0)
    except Exception:
        pass
    return frames, meta


def _frame_color_stats(frames, Image=None, top_n=24):
    """多帧颜色统计：每帧缩到 ≤SCHEME_SCAN_EDGE → 4bit/通道量化累加（权重=像素数）。

    alpha<128 的像素不计入（透明底角色图的关键：背景不该污染配色）。
    返回 (色块列表[按权重降序, 每项 {'rgb','w','share'}], 参与统计的像素总数)。
    """
    if Image is None:
        from PIL import Image as _I
        Image = _I
    buckets = {}
    total = 0
    for img in frames or []:
        if img is None:
            continue
        try:
            small = img
            longest = max(img.size)
            if longest > SCHEME_SCAN_EDGE:
                s = SCHEME_SCAN_EDGE / float(longest)
                small = img.resize((max(1, int(img.width * s)),
                                    max(1, int(img.height * s))), Image.NEAREST)
            cnt = small.getcolors(max(1, small.width * small.height))
        except Exception:
            cnt = None
        if not cnt:
            continue
        for n, c in cnt:
            if not c:
                continue
            a = c[3] if len(c) > 3 else 255
            if a < 128:
                continue
            r, g, b = c[0], c[1], c[2]
            d = buckets.setdefault((r >> 4, g >> 4, b >> 4), [0, 0, 0, 0])
            d[0] += n
            d[1] += r * n
            d[2] += g * n
            d[3] += b * n
            total += n
    out = []
    for _k, d in buckets.items():
        w = d[0]
        if w <= 0:
            continue
        out.append({'rgb': (d[1] // w, d[2] // w, d[3] // w), 'w': w,
                    'share': (w / float(total)) if total else 0.0})
    out.sort(key=lambda s: -s['w'])
    return out[:max(1, top_n)], total


def extract_scheme_theme(frames, Image=None):
    """从（单图或多帧动图的）RGBA 图提取主题色，返回 dict：

      primary   主色（权重最高、且有彩色优先）
      accent    强调色（与主色距离够远、权重够大的次显著色；没有就由主色派生）
      bg_light  亮套候选栏底色（图里最亮显著色的浅化版，亮度 ≥ SCHEME_BG_LIGHT_MIN_LUMA）
      bg_dark   暗套候选栏底色（图里最暗显著色的深化版，亮度 ≤ SCHEME_BG_DARK_MAX_LUMA）
      is_dark   原图是否整体偏暗（向导提示用）
      swatches  色块统计明细（调试/测试用）
    """
    sw, _total = _frame_color_stats(frames, Image)
    if not sw:
        base = (90, 110, 140)
        return {'primary': base, 'accent': _vivid(base, 1.3),
                'bg_light': _push_luma(base, min_luma=SCHEME_BG_LIGHT_MIN_LUMA),
                'bg_dark': _push_luma(base, max_luma=SCHEME_BG_DARK_MAX_LUMA),
                'is_dark': False, 'swatches': []}
    sig = [s for s in sw if s['share'] >= 0.06] or sw[:6]
    colored = [s for s in sig if _saturation(s['rgb']) >= 24 and 18 <= _luma255(s['rgb']) <= 242]
    primary = (colored or sig)[0]['rgb']
    cands = [s for s in sw if _color_dist(s['rgb'], primary) >= 70 and s['share'] >= 0.02]
    if cands:
        accent = max(cands, key=lambda s: s['share'] *
                     (1.0 + _saturation(s['rgb']) / 255.0 * 1.6))['rgb']
    else:
        away = (255, 255, 255) if _luma255(primary) < 128 else (0, 0, 0)
        accent = _vivid(_mix(primary, away, 0.30), 1.25)
    sig2 = [s for s in sw if s['share'] >= 0.02] or sw
    bright = max(sig2, key=lambda s: _luma255(s['rgb']))['rgb']
    darkc = min(sig2, key=lambda s: _luma255(s['rgb']))['rgb']
    return {'primary': primary,
            'accent': accent,
            'bg_light': _push_luma(_mix(bright, (255, 255, 255), 0.62),
                                   min_luma=SCHEME_BG_LIGHT_MIN_LUMA),
            'bg_dark': _push_luma(_mix(darkc, (0, 0, 0), 0.62),
                                  max_luma=SCHEME_BG_DARK_MAX_LUMA),
            'is_dark': (_luma255(bright) < 118 or _luma255(primary) < 90),
            'swatches': sw[:8]}


def make_scheme_names(skin_name):
    """皮肤名 → (亮配色名, 暗配色名)。Rime 方案名只用 ASCII 安全字符；中文名走稳定哈希。"""
    s = ''.join(ch for ch in str(skin_name or '').lower() if ch.isascii() and ch.isalnum())[:28]
    if len(s) < 2:
        import zlib
        s = 'skin%08x' % (zlib.crc32(str(skin_name or '').encode('utf-8')) & 0xFFFFFFFF)
    base = 'rime_' + s
    return base, base + '_dark'


def build_scheme_fields(skin_name, theme, dark=False, scheme=None, author=SCHEME_AUTHOR):
    """按主题色生成**恰好 21 个字段**的 Rime 配色方案（值全为字符串）。

    dark=False 亮套（浅底深字）/ dark=True 暗套（深底浅字）。
    所有文字色都过 _ensure_delta 校正：与所在背景的 luma 差 ≥ SCHEME_MIN_DELTA_MAIN(100)，
    次级文字 ≥ SCHEME_MIN_DELTA_SUB(70)，强调色与候选栏底色差 ≥ SCHEME_MIN_DELTA_ACCENT_BG(40)。
    """
    name = scheme or make_scheme_names(skin_name)[1 if dark else 0]
    prim = theme['primary']
    bg = theme['bg_dark'] if dark else theme['bg_light']
    # 强调色：先与候选栏底色拉开亮度差（保证高亮块在候选栏上看得清）
    acc = _ensure_delta(theme['accent'], bg, SCHEME_MIN_DELTA_ACCENT_BG,
                        prefer='light' if dark else 'dark')
    if dark:
        text_src = _mix(prim, (255, 255, 255), 0.45)
        strong_src = _mix(prim, (255, 255, 255), 0.82)
        soft_src = _mix(theme['accent'], (255, 255, 255), 0.22)
        shadow_rgb, shadow_a, main_pref = (0, 0, 0), '40', 'light'
    else:
        text_src = _mix(prim, (0, 0, 0), 0.45)
        strong_src = _mix(prim, (0, 0, 0), 0.74)
        soft_src = _mix(theme['accent'], (0, 0, 0), 0.28)
        shadow_rgb, shadow_a, main_pref = _mix(theme['bg_dark'], (0, 0, 0), 0.40), '1A', 'dark'
    on_acc_light = _mix(theme['bg_light'], (255, 255, 255), 0.30)
    on_acc_dark = _mix(theme['bg_dark'], (0, 0, 0), 0.20)
    text_color = _ensure_delta(text_src, bg, SCHEME_MIN_DELTA_MAIN, main_pref)
    cand_text = _ensure_delta(strong_src, bg, SCHEME_MIN_DELTA_MAIN, main_pref)
    label = _ensure_delta(_mix(acc, bg, 0.30), bg, SCHEME_MIN_DELTA_SUB, main_pref)
    comment = _ensure_delta(_mix(soft_src, bg, 0.45), bg, SCHEME_MIN_DELTA_SUB, main_pref)
    hilited_text = _text_on(acc, on_acc_light, on_acc_dark, SCHEME_MIN_DELTA_MAIN)
    hilited_cand_text = _text_on(acc, on_acc_light, on_acc_dark, SCHEME_MIN_DELTA_MAIN)
    hilited_label = _text_on(acc, on_acc_light, on_acc_dark, SCHEME_MIN_DELTA_SUB)
    hilited_comment = _text_on(acc, on_acc_light, on_acc_dark, SCHEME_MIN_DELTA_SUB)
    border = _ensure_delta(_mix(acc, bg, 0.55), bg, SCHEME_MIN_DELTA_BORDER, main_pref)
    hi_border = _ensure_delta(_mix(acc, (255, 255, 255) if dark else (0, 0, 0), 0.45),
                              acc, SCHEME_MIN_DELTA_BORDER,
                              'light' if dark else 'dark')
    label_hex = _hex6(label)
    return {
        'name': '%s %s' % (skin_name or name, name),
        'author': author,
        'color_format': 'rgba',
        'back_color': _hex6(bg),
        'border_color': _hex8(border, 'AA'),
        'shadow_color': _hex8(shadow_rgb, shadow_a),
        'text_color': _hex6(text_color),
        'label_color': label_hex,
        'comment_text_color': _hex6(comment),
        'candidate_text_color': _hex6(cand_text),
        'candidate_back_color': _hex6(bg),
        'hilited_text_color': _hex6(hilited_text),
        'hilited_back_color': _hex6(acc),
        'hilited_candidate_text_color': _hex6(hilited_cand_text),
        'hilited_candidate_back_color': _hex6(acc),
        'hilited_candidate_border_color': _hex6(hi_border),
        'hilited_label_color': _hex6(hilited_label),
        'hilited_comment_text_color': _hex6(hilited_comment),
        'hilited_candidate_shadow_color': _hex8(acc, '30'),
        'nextpage_color': label_hex,
        'prevpage_color': label_hex,
    }


# ---------- weasel.custom.yaml 扁平键解析 / 合并（纯函数，dry-run 友好）----------
def parse_flat_yaml_text(text):
    """解析扁平键（口径与 read_rime_layout 原有实现一致：只认 "键": 值 行）"""
    data = {}
    for ln in (text or '').splitlines():
        s = ln.strip()
        if s.startswith('"') and ':' in s:
            key, _, val = s.partition(':')
            data[key.strip().strip('"')] = val.strip()
    return data


def parse_flat_yaml(path):
    """读文件并解析扁平键；文件不存在/读失败返回 {}（不抛异常）"""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return parse_flat_yaml_text(f.read())
    except Exception:
        return {}


def _flat_value(flat, key):
    """取扁平键值并去掉可能的引号/行尾注释（用于比较 style/color_scheme 等）"""
    v = flat.get(key)
    if v is None:
        return None
    body, _cmt = _split_line_comment(str(v))   # YAML 口径：空白后的 # 起是注释，不算值
    return body.strip().strip('"').strip("'")


def _format_scheme_line(scheme, field, value, indent='  '):
    """生成一行 patch 扁平键（name 值加双引号，与先例一致）"""
    val = '"%s"' % str(value) if field == 'name' else str(value)
    return '%s"preset_color_schemes/%s/%s": %s' % (indent, scheme, field, val)


def _scheme_section_title(skin, sname):
    """R5：新配色块的分节标题文本 —— 亮套 = 皮肤名，暗套 = 皮肤名 · 深色。

    皮肤名（写入方给的归属名）优先；为空时退化成方案名，保证标题里永远有可读文字
    （用户要在 weasel.custom.yaml 里靠这行认块）。
    """
    base = str(skin or '').strip() or str(sname or '').strip()
    if str(sname or '').endswith('_dark'):
        return '%s · 深色' % base
    return base


def _scheme_section_header(title, indent='  '):
    """R5：`# ===== <标题> =====` 分节标题注释行（对齐用户文件现成写法）"""
    return '%s# ===== %s =====' % (indent, title)


def _split_line_comment(line):
    """拆出行尾注释（引号外的 # 起）；返回 (主体, 注释串含其前空白)。用于改值时保留注释"""
    in_q = None
    for i, ch in enumerate(line):
        if in_q:
            if ch == in_q:
                in_q = None
        elif ch in '"\'':
            in_q = ch
        elif ch == '#':
            return line[:i].rstrip(), line[i:]
    return line, ''


def _patch_insert_index(lines):
    """patch 段末尾的插入位置（紧贴块内最后一个非空非注释行之后）"""
    pi = None
    for i, ln in enumerate(lines):
        if _PATCH_LINE_RE.match(ln):
            pi = i
            break
    if pi is None:
        return len(lines)
    last = pi
    for j in range(pi + 1, len(lines)):
        ln = lines[j]
        if not ln.strip() or ln.lstrip().startswith('#'):
            continue
        if (len(ln) - len(ln.lstrip())) == 0:
            break                      # 下一个顶级键 → patch 段结束
        last = j
    return last + 1


def merge_scheme_into_yaml(text, schemes, set_active=False, stale_schemes=(),
                           active_light=None, active_dark=None, skin=''):
    """把配色方案按 patch 扁平键合并进 weasel.custom.yaml 文本（纯函数，不落盘）。

    schemes: [(方案名, {字段: 值}), ...]；字段集合限定在 SCHEME_FIELDS 内（不写野字段）。
    skin   : 归属皮肤名（R5）—— 新块写前加 `# ===== <皮肤名> =====` 分节标题注释，
             并与上一块之间留 ≥1 个空行（用户反馈：新配色跟最后一个皮肤「并在一起」看不清）。
    规则：
      · 同名方案的同名字段 → 就地替换该行值（保留缩进）；新字段 → 追加到 patch 段末尾
      · 其它配色方案、注释、style/* 、用户自定义键：默认一字不动（set_active=False）
      · set_active=True 时只额外改 style/color_scheme(_dark) 两个键（用户确认「一并切换」时）
      · stale_schemes：本工具上次生成、本次改名后残留的方案 → 整段键行删除（不堆垃圾），
        连带删掉它头上本工具写的分节标题（不留孤儿注释）
      · 幂等：只有「该方案真有新增键」才写标题，且同一标题已存在就不重复写
    返回 (新文本, diff 行列表, 统计 dict)
    """
    nl = '\r\n' if '\r\n' in (text or '') else '\n'
    lines = (text or '').splitlines()
    existing_cmts = {ln.strip() for ln in lines if ln.strip().startswith('#')}
    want = {}
    for sname, fields in schemes or []:
        if not sname or not fields:
            continue
        for f in SCHEME_FIELDS:                    # 只认 21 个字段
            if f in fields:
                want[(sname, f)] = fields[f]
    stale = set(stale_schemes or ())
    out, diff = [], []
    hit, updated, removed = set(), 0, 0
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith('#'):
            m = _SCHEME_LINE_RE.match(ln)
            if m:
                sname, fname = m.group(2), m.group(3)
                if sname in stale:
                    # R5：连同本工具写的分节标题一起清掉（改名重注入不留孤儿标题）
                    if out and _SCHEME_HEADER_RE.match(out[-1]):
                        diff.append('- ' + out[-1].strip())
                        out.pop()
                    diff.append('- ' + s)
                    removed += 1
                    continue
                key = (sname, fname)
                if key in want:
                    newln = _format_scheme_line(sname, fname, want[key], m.group(1))
                    _body, _cmt = _split_line_comment(ln)
                    if _cmt:                       # 保留用户写的行尾注释
                        newln = newln + '  ' + _cmt
                    hit.add(key)
                    if newln.strip() != s:
                        diff.append('- ' + s)
                        diff.append('+ ' + newln.strip())
                        updated += 1
                    out.append(newln)
                    continue
            elif set_active:
                ma = _ACTIVE_LINE_RE.match(ln)
                if ma:
                    flat = ma.group(2)
                    newv = active_light if flat == 'style/color_scheme' else active_dark
                    if newv:
                        newln = '%s"%s": %s' % (ma.group(1), flat, newv)
                        _body, _cmt = _split_line_comment(ln)
                        if _cmt:
                            newln = newln + '  ' + _cmt
                        if newln.strip() != s:
                            diff.append('- ' + s)
                            diff.append('+ ' + newln.strip())
                            updated += 1
                        out.append(newln)
                        continue
        out.append(ln)
    add, has_header = [], False
    for sname, fields in schemes or []:
        if not sname or not fields:
            continue
        miss = [f for f in SCHEME_FIELDS if f in fields and (sname, f) not in hit]
        if not miss:
            continue                           # 没有新增键 → 不写标题（幂等的前提）
        hdr = _scheme_section_header(_scheme_section_title(skin, sname))
        if hdr.strip() not in existing_cmts:   # 标题已存在就不重复写
            add.append(hdr)
            has_header = True
        for f in miss:
            add.append(_format_scheme_line(sname, f, fields[f]))
    if set_active:
        present = set()
        for ln in out:
            ma = _ACTIVE_LINE_RE.match(ln)
            if ma:
                present.add(ma.group(2))
        if active_light and 'style/color_scheme' not in present:
            add.append('  "style/color_scheme": %s' % active_light)
        if active_dark and 'style/color_scheme_dark' not in present:
            add.append('  "style/color_scheme_dark": %s' % active_dark)
    if add:
        ins = _patch_insert_index(out)
        # R5：新块前留 1 个空行（否则会紧贴上一个皮肤的最后一行键）
        if has_header and ins > 0 and out[ins - 1].strip() != '':
            out.insert(ins, '')
            ins += 1
            diff.append('+ (空行)')
        for a in add:
            out.insert(ins, a)
            ins += 1
            diff.append('+ ' + a.strip())
        # R5：新块后也留 1 个空行（后面还有别的内容时，别和它贴在一起）
        if has_header and ins < len(out) and out[ins].strip() != '':
            out.insert(ins, '')
            diff.append('+ (空行)')
    new_text = nl.join(out)
    if text.endswith(('\n', '\r')) or not text:
        new_text += nl
    return new_text, diff, {'added': len(add), 'updated': updated, 'removed': removed}


def plan_scheme_injection(path=None, skin='', light=None, dark=None,
                          scheme_light=None, scheme_dark=None, set_active=False,
                          stale_schemes=(), dry_run=False):
    """规划一次配色注入：只读文件 + 纯计算，返回 plan（不落盘）。

    plan = {ok, msg, target, diff, stats, new_text, old_text, dry_run, created, ...}
    dry_run=True 的计划带 dry_run 标记，apply_scheme_injection 会拒绝落盘（双保险）。
    """
    tgt = path or WEASEL_CUSTOM
    res = {'ok': False, 'msg': '', 'target': tgt, 'skin': skin, 'dry_run': bool(dry_run),
           'set_active': bool(set_active), 'created': False, 'diff': [], 'stats': {},
           'new_text': '', 'old_text': '', 'scheme_light': scheme_light,
           'scheme_dark': scheme_dark}
    parent = os.path.dirname(os.path.abspath(tgt))
    if os.path.exists(tgt):
        try:
            # newline='' 保留原始换行（CRLF 文件写回仍是 CRLF，不改用户文件风格）
            with open(tgt, encoding='utf-8', newline='') as f:
                text = f.read()
        except Exception as e:
            res['msg'] = '读取 %s 失败：%s' % (tgt, e)
            return res
    else:
        if not os.path.isdir(parent):
            res['msg'] = '未找到 Rime 配置目录：%s（请先安装小狼毫 Weasel）' % parent
            return res
        text, res['created'] = '', True
    base_text = text if text.strip() else 'patch:%s' % ('\n')
    schemes = [(scheme_light, light or {}), (scheme_dark, dark or {})]
    new_text, diff, stats = merge_scheme_into_yaml(
        base_text, schemes, set_active=set_active, stale_schemes=stale_schemes,
        active_light=scheme_light, active_dark=scheme_dark, skin=skin)
    res.update(new_text=new_text, old_text=text, diff=diff, stats=stats, ok=True)
    res['msg'] = '计划：新增 %d 行 / 修改 %d 行 / 删除 %d 行' % (
        stats['added'], stats['updated'], stats['removed'])
    return res


def apply_scheme_injection(plan, ts=None):
    """执行注入：先备份 weasel.custom.yaml.bak-<时间戳>，再写合并结果。

    返回 {ok, msg, backup, path, bytes}。dry-run 计划 / 无变化 / 写入失败都不静默：
    msg 里带明确原因与备份路径。
    """
    res = {'ok': False, 'msg': '', 'backup': None, 'path': None, 'bytes': 0}
    if not plan or not plan.get('ok'):
        res['msg'] = (plan or {}).get('msg') or '没有可写入的配色计划'
        return res
    if plan.get('dry_run'):
        res['msg'] = 'dry-run 计划不落盘（未写入任何文件）'
        return res
    tgt = plan['target']
    res['path'] = tgt
    if not plan.get('diff'):
        res['ok'] = True
        res['msg'] = '内容与现状一致，无需写入（未落盘）'
        return res
    if os.path.exists(tgt):
        import shutil
        stamp = ts or time.strftime('%Y%m%d-%H%M%S')
        bak = '%s.bak-%s' % (tgt, stamp)
        n = 0
        while os.path.exists(bak):
            n += 1
            bak = '%s.bak-%s-%d' % (tgt, stamp, n)
        try:
            shutil.copy2(tgt, bak)
            res['backup'] = bak
        except Exception as e:
            res['msg'] = '备份失败（已中止写入）：%s' % e
            return res
    try:
        # 原子写：先写同目录临时文件再替换，避免写一半崩溃导致 yaml 损坏
        tmp_path = tgt + '.tmp-scheme-write'
        with open(tmp_path, 'w', encoding='utf-8', newline='') as f:
            f.write(plan['new_text'])
        os.replace(tmp_path, tgt)
    except Exception as e:
        try:
            if os.path.exists(tgt + '.tmp-scheme-write'):
                os.remove(tgt + '.tmp-scheme-write')
        except Exception:
            pass
        res['msg'] = '写入失败：%s%s' % (e, ('（原文件已备份：%s）' % res['backup']) if res['backup'] else '')
        return res
    res['ok'] = True
    res['bytes'] = len(plan['new_text'].encode('utf-8'))
    res['msg'] = '已写入 %s（%d 字节）%s' % (os.path.basename(tgt), res['bytes'],
                                        ('；备份：%s' % os.path.basename(res['backup']))
                                        if res['backup'] else '；新建文件（无旧文件可备份）')
    return res


def restore_weasel_backup(bak_path, target=None):
    """从 .bak 还原 weasel.custom.yaml（还原前把当前文件另存 .bak-restore-<时间戳>）"""
    res = {'ok': False, 'msg': '', 'backup_of_current': None}
    if not bak_path or not os.path.exists(bak_path):
        res['msg'] = '备份文件不存在：%s' % bak_path
        return res
    tgt = target or WEASEL_CUSTOM
    try:
        import shutil
        if os.path.exists(tgt):
            keep = '%s.bak-restore-%s' % (tgt, time.strftime('%Y%m%d-%H%M%S'))
            shutil.copy2(tgt, keep)
            res['backup_of_current'] = keep
        shutil.copy2(bak_path, tgt)
    except Exception as e:
        res['msg'] = '还原失败：%s' % e
        return res
    res['ok'] = True
    res['msg'] = '已从 %s 还原 %s' % (os.path.basename(bak_path), os.path.basename(tgt))
    return res


def find_latest_weasel_backup(path=None):
    """找最近的 weasel.custom.yaml.bak-* 备份（按修改时间）；没有返回 None。

    .bak-restore-* 是「还原动作」为保护当前文件生成的副本，不算可选还原源。
    """
    tgt = path or WEASEL_CUSTOM
    d = os.path.dirname(os.path.abspath(tgt))
    prefix = os.path.basename(tgt) + '.bak-'
    try:
        cands = [os.path.join(d, f) for f in os.listdir(d)
                 if f.startswith(prefix) and '.bak-restore-' not in f]
    except Exception:
        return None
    cands = [c for c in cands if os.path.isfile(c)]
    if not cands:
        return None
    try:
        return max(cands, key=lambda p: os.path.getmtime(p))
    except Exception:
        return cands[0]


# ---------- 小狼毫安装位置探测：注册表卸载项（任意盘符的自定义安装都能定位）----------
# 三个根：HKLM 64 位 / HKLM 32 位（WOW6432Node）/ HKCU —— 小狼毫常见写在 WOW6432Node 下
_WEASEL_UNINSTALL_ROOTS = (
    ('HKLM', r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
    ('HKLM', r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'),
    ('HKCU', r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
)
# DisplayName/路径匹配：小狼毫 / weasel / 独立单词 rime（不误伤 Primer 之类含 rime 的词）
_WEASEL_NAME_RE = re.compile(r'小狼毫|weasel|(^|[^a-z])rime([^a-z]|$)', re.IGNORECASE)
# 这些扩展名的注册表值视为「可执行文件/图标路径」→ 取所在目录；否则视为目录本身
_EXE_LIKE_EXT = ('.exe', '.ico', '.dll', '.bat', '.cmd', '.msi', '.lnk')


def _reg_hive(name):
    """hive 名 → HKEY 常量；winreg 不可用（非 Windows/受限环境）返回 None"""
    try:
        import winreg
    except Exception:
        return None
    return {'HKLM': winreg.HKEY_LOCAL_MACHINE,
            'HKCU': winreg.HKEY_CURRENT_USER}.get(name)


def _path_from_reg_value(value):
    """注册表里的路径值 → 纯路径：去引号、去启动参数、去图标索引（...,0）。

    例：'"D:\\Rime\\weasel-0.17.4\\uninstall.exe"' → 'D:\\Rime\\weasel-0.17.4\\uninstall.exe'
        'D:\\Rime\\weasel\\weasel.ico,0'          → 'D:\\Rime\\weasel\\weasel.ico'
        '"C:\\Rime\\uninstall.exe" /S'            → 'C:\\Rime\\uninstall.exe'
    解析失败/空值返回 None（绝不抛异常）。
    """
    if not value:
        return None
    s = str(value).split('\x00')[0].strip()      # 个别安装器的 REG_SZ 带尾随 NUL
    if not s:
        return None
    if ',' in s:                                  # DisplayIcon 常见形式 "...\weasel.ico,0"
        head, _, tail = s.rpartition(',')
        if head.strip() and tail.strip().isdigit():
            s = head.strip()
    if s.startswith('"'):
        end = s.find('"', 1)
        s = s[1:end] if end > 0 else s[1:]
    else:
        m = re.match(r'^(.*?\.(?:exe|ico|dll|bat|cmd|msi|lnk))(\s|$)', s, re.IGNORECASE)
        s = m.group(1) if m else s.split(' ')[0]
    s = s.strip().strip('"').strip()
    return s or None


def _dir_from_reg_path_value(value):
    """注册表值 → 安装目录：可执行/图标路径取所在目录，纯目录（InstallLocation）原样返回"""
    p = _path_from_reg_value(value)
    if not p:
        return None
    if p.lower().endswith(_EXE_LIKE_EXT):
        d = os.path.dirname(p)
        return os.path.normpath(d) if d else None
    return os.path.normpath(p)


def _looks_like_weasel_entry(name, uninstall_string='', display_icon='', install_location=''):
    """卸载项是否属于小狼毫/Rime/weasel（名称或任一路径字段命中即可）"""
    blob = ' '.join(str(x or '') for x in (name, uninstall_string, display_icon, install_location))
    return bool(_WEASEL_NAME_RE.search(blob))


def iter_uninstall_entries(lister=None, reader=None):
    """遍历三个卸载项根，返回各卸载项的值字典列表。

    lister(hive, subkey) → 子键名列表；reader(hive, full_subkey) → 值字典（两者可注入，便于单测）。
    默认用 winreg 实读；任何异常（权限/缺失/非 Windows）都被吞掉并继续，绝不抛异常。
    """
    if lister is None:
        def lister(hive_name, subkey):
            try:
                import winreg
            except Exception:
                return []
            hive = _reg_hive(hive_name)
            if hive is None:
                return []
            try:
                with winreg.OpenKey(hive, subkey) as k:
                    out, i = [], 0
                    while True:
                        try:
                            out.append(winreg.EnumKey(k, i))
                        except OSError:
                            break
                        i += 1
                    return out
            except Exception:
                return []
    if reader is None:
        def reader(hive_name, full_subkey):
            try:
                import winreg
            except Exception:
                return None
            hive = _reg_hive(hive_name)
            if hive is None:
                return None
            try:
                with winreg.OpenKey(hive, full_subkey) as k:
                    d, i = {}, 0
                    while True:
                        try:
                            n, v, _t = winreg.EnumValue(k, i)
                        except OSError:
                            break
                        d[n] = v
                        i += 1
                    return d
            except Exception:
                return None
    entries = []
    for hive_name, subkey in _WEASEL_UNINSTALL_ROOTS:
        try:
            children = lister(hive_name, subkey)
        except Exception:
            children = []
        for child in children or []:
            try:
                vals = reader(hive_name, subkey + '\\' + str(child))
            except Exception:
                vals = None
            if isinstance(vals, dict) and vals:
                entries.append(vals)
    return entries


def weasel_dirs_from_entries(entries):
    """从卸载项列表筛出小狼毫/Rime/weasel 的安装目录（去重保序）。

    目录来源：UninstallString → DisplayIcon → InstallLocation（任一能解析即可）。
    """
    out = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        un = e.get('UninstallString') or ''
        icon = e.get('DisplayIcon') or ''
        loc = e.get('InstallLocation') or ''
        if not _looks_like_weasel_entry(e.get('DisplayName') or e.get('name') or '', un, icon, loc):
            continue
        for v in (un, icon, loc):
            d = _dir_from_reg_path_value(v)
            if d and d not in out:
                out.append(d)
    return out


def registry_weasel_dirs():
    """真机：从注册表卸载项得到小狼毫安装目录列表（读失败返回 []，绝不抛异常）"""
    try:
        return weasel_dirs_from_entries(iter_uninstall_entries())
    except Exception:
        return []


# ---------- WeaselDeployer 定位与调用（缺失/失败/超时都给明确提示）----------
def find_weasel_deployer(extra=None):
    """定位 WeaselDeployer.exe。

    优先级：显式 extra > 环境变量 > PATH > 注册表卸载项（任意盘符自定义安装）> 常见安装目录。
    找不到返回 None —— 调用方会给「已写入但需手动重新部署」的明确提示，不静默。
    """
    import glob as _glob
    cands = []
    if extra:
        cands.append(extra)
    for env in ('WEASEL_DEPLOYER', 'RIME_WEASEL_DEPLOYER'):
        if os.environ.get(env):
            cands.append(os.environ[env])
    if os.environ.get('WEASEL_DIR'):
        cands.append(os.path.join(os.environ['WEASEL_DIR'], 'WeaselDeployer.exe'))
    try:
        import shutil
        for name in ('WeaselDeployer.exe', 'WeaselDeployer'):
            w = shutil.which(name)
            if w:
                cands.append(w)
    except Exception:
        pass
    # 注册表卸载项：小狼毫装在 D:\Rime\weasel-0.17.4 这类非标准路径时靠它定位
    for d in registry_weasel_dirs():
        cands.append(os.path.join(d, 'WeaselDeployer.exe'))
    roots = [os.environ.get('ProgramFiles', r'C:\Program Files'),
             os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
             os.environ.get('LOCALAPPDATA', '')]
    pats = ('Rime/weasel-*/WeaselDeployer.exe', 'Rime/WeaselDeployer.exe',
            'Rime/*/WeaselDeployer.exe', 'Rime/weasel/WeaselDeployer.exe')
    for root in roots:
        if not root:
            continue
        for pat in pats:
            try:
                cands.extend(sorted(_glob.glob(os.path.join(root, *pat.split('/'))), reverse=True))
            except Exception:
                pass
    seen = set()
    for c in cands:
        if not c:
            continue
        key = os.path.normcase(os.path.abspath(c))
        if key in seen:
            continue
        seen.add(key)
        if os.path.isfile(c):
            return c
    return None


def run_weasel_deployer(exe=None, timeout=None, runner=None, extra_dir=None):
    """调 WeaselDeployer 重部署。返回 {'ok','msg','exe','rc','timed_out'}。

    runner(cmd, timeout) → returncode，可注入（测试用假 runner，不真起进程）。
    缺失/超时/非 0 返回码/启动异常都返回 ok=False + 明确 msg（绝不静默吞错）。
    """
    timeout = SCHEME_DEPLOY_TIMEOUT if timeout is None else timeout
    res = {'ok': False, 'msg': '', 'exe': None, 'rc': None, 'timed_out': False}
    path = exe or find_weasel_deployer(extra_dir)
    res['exe'] = path
    if not path or not os.path.isfile(path):
        res['msg'] = ('未找到 WeaselDeployer.exe（小狼毫部署程序）；配色已写入 weasel.custom.yaml，'
                      '但尚未生效。%s' % SCHEME_DEPLOY_HINT)
        return res
    if runner is None:
        def runner(cmd, _timeout):
            import subprocess
            p = subprocess.run([cmd], timeout=_timeout, capture_output=True)
            return p.returncode
    try:
        rc = runner(path, timeout)
    except Exception as e:
        if 'Timeout' in type(e).__name__:
            res['timed_out'] = True
            res['msg'] = ('WeaselDeployer 超过 %.0f 秒未返回（已放弃等待）。%s'
                          % (timeout, SCHEME_DEPLOY_HINT))
        else:
            res['msg'] = ('调用 WeaselDeployer 失败：%s。%s' % (e, SCHEME_DEPLOY_HINT))
        return res
    res['rc'] = rc
    if rc == 0:
        res['ok'] = True
        res['msg'] = '已调用 WeaselDeployer 重新部署（%s）' % os.path.basename(path)
    else:
        res['msg'] = ('WeaselDeployer 返回码 %s（部署未成功）。%s' % (rc, SCHEME_DEPLOY_HINT))
    return res


def apply_rime_scheme_binding(cfg, path=None, runner=None, exe=None, timeout=None):
    """切皮肤时把该皮肤绑定的配色名写回 style/color_scheme(_dark) 并重部署。

    未绑定（cfg 里无 rime_scheme）→ 静默跳过，绝不写文件（新功能默认不动作）。
    返回 {'ok','msg','skipped','unchanged','backup','deploy'}。
    """
    res = {'ok': True, 'msg': '该皮肤未绑定 Rime 配色，跳过', 'skipped': True,
           'unchanged': False, 'backup': None, 'deploy': None}
    light = str(cfg.get('rime_scheme') or '').strip()
    if not light:
        return res
    dark = str(cfg.get('rime_scheme_dark') or '').strip()
    tgt = path or WEASEL_CUSTOM
    res['skipped'] = False
    try:
        if not os.path.exists(tgt):
            res['ok'] = False
            res['msg'] = '未找到 %s，无法切换候选框配色' % tgt
            return res
        with open(tgt, encoding='utf-8', newline='') as f:
            cur_text = f.read()
        flat = parse_flat_yaml_text(cur_text)
        if _flat_value(flat, 'style/color_scheme') == light and \
                (not dark or _flat_value(flat, 'style/color_scheme_dark') == dark):
            res['unchanged'] = True
            res['msg'] = '候选框配色已是 %s，无需重写' % light
            return res
        plan = plan_scheme_injection(tgt, skin=cfg.get('name') or light, light={}, dark={},
                                     scheme_light=light, scheme_dark=dark, set_active=True)
        if not plan['ok']:
            res['ok'] = False
            res['msg'] = plan['msg']
            return res
        wr = apply_scheme_injection(plan)
        res['backup'] = wr.get('backup')
        if not wr['ok']:
            res['ok'] = False
            res['msg'] = wr['msg']
            return res
        dep = run_weasel_deployer(exe=exe, runner=runner, timeout=timeout)
        res['deploy'] = dep
        res['msg'] = ('候选框配色已切到 %s%s；%s'
                      % (light, (' / %s' % dark) if dark else '', dep['msg']))
        if not dep['ok']:
            res['ok'] = False          # 文件已写、部署没成 → 明确报「部分完成」
            res['msg'] = '配色已写入但部署未成功：%s' % dep['msg']
        return res
    except Exception as e:
        res['ok'] = False
        res['msg'] = '切换候选框配色失败：%s' % e
        return res


# ---------- 生成记录（皮肤改名后清理残留，避免堆垃圾方案）----------
def load_scheme_manifest():
    """读本工具生成记录：{皮肤名: [亮方案名, 暗方案名]}；损坏则当空"""
    try:
        with open(SCHEME_MANIFEST, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_scheme_manifest(man):
    try:
        with open(SCHEME_MANIFEST, 'w', encoding='utf-8') as f:
            json.dump(man, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def bind_scheme_to_skin(name, light, dark=''):
    """R5：把配色名写进皮肤档案（只改这两个键，其它字段一字不动）。

    返回是否写入成功。切皮肤时 apply_rime_scheme_binding 读它们整套恢复（含光环联动）；
    皮肤档案不存在（未保存皮肤）→ 返回 False，调用方据此提示「先保存皮肤」。
    """
    n = str(name or '').strip()
    if not n:
        return False
    j = os.path.join(SKINS_DIR, n, 'skin.json')
    if not os.path.exists(j):
        return False
    try:
        with open(j, encoding='utf-8') as f:
            cfg = json.load(f)
        cfg['rime_scheme'] = str(light or '')
        cfg['rime_scheme_dark'] = str(dark or '')
        with open(j, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


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
                if len(c) > 3 and c[3] < 128:
                    continue   # 全透明像素的 RGB 不参与统计（最终会被键色覆盖）
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


# ============ 渲染层抽象（v2.0-①a：Renderer 接口 + CompatRenderer）============
# 手册 ① 步 1：config.json 增 render_mode —— compat（默认，v1.6 键色路径不动）/ alpha（真 alpha 分层窗）。
# 缺键与非法值一律按 compat 处理：老用户升级后零感知（渲染层纯收口，不改行为）。
RENDER_MODES = ('compat', 'alpha')
DEFAULT_RENDER_MODE = 'compat'
# 向导里的中文标签（不把 compat/alpha 术语摆给用户看）：(模式值, 显示文案)
# v2.0-R10：⑪ 单选组已删 —— 这对标签现在只供提示文案（_update_render_hint）取中文名，
# 不再是控件选项；保留常量以免动到既有测试/档案口径。
RENDER_MODE_CHOICES = (('compat', '兼容（默认）'), ('alpha', '增强（真·半透明）'))

# ---- 分层窗（真 alpha）所需的 GDI/USER32 常量与结构（v2.0-①b，对齐 spike_layered_alpha.py）----
gdi32 = ctypes.windll.gdi32      # user32/kernel32 在下方统一声明；gdi32 只有分层窗路径用得到
WS_EX_LAYERED = 0x00080000       # 分层窗口扩展样式
ULW_ALPHA = 0x00000002           # UpdateLayeredWindow：使用逐像素 alpha
AC_SRC_OVER, AC_SRC_ALPHA = 0x00, 0x01
DIB_RGB_COLORS = 0
LAYERED_BI_RGB = 0               # biCompression：32bpp 无压缩（ULW 只吃 BI_RGB）


class BITMAPINFOHEADER(ctypes.Structure):
    """CreateDIBSection 位图描述头（biHeight 取负数 = 自上而下，手册 ① 步 3）"""
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG),
                ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', wintypes.DWORD * 3)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [('BlendOp', ctypes.c_byte), ('BlendFlags', ctypes.c_byte),
                ('SourceConstantAlpha', ctypes.c_byte), ('AlphaFormat', ctypes.c_byte)]


class LAYER_POINT(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]


class LAYER_SIZE(ctypes.Structure):
    _fields_ = [('cx', wintypes.LONG), ('cy', wintypes.LONG)]


_win32_ready = False


def _prepare_win32():
    """一次性声明分层窗用到的 GDI/USER32 签名（首次推图时生效，之后只过一次布尔判断）。

    64 位下返回 HDC/HBITMAP 的调用若吃默认 c_int 会被截断（spike 靠句柄值小侥幸没炸），
    这里显式声明 restype，避免"有时成功有时黑屏"的偶发故障。
    """
    global _win32_ready
    if _win32_ready:
        return
    u32, g32 = user32, gdi32
    u32.GetDC.argtypes = [wintypes.HWND]
    u32.GetDC.restype = ctypes.c_void_p
    u32.ReleaseDC.argtypes = [wintypes.HWND, ctypes.c_void_p]
    u32.ReleaseDC.restype = ctypes.c_int
    u32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    u32.SetWindowLongW.restype = ctypes.c_long
    u32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, ctypes.c_void_p, ctypes.POINTER(LAYER_POINT), ctypes.POINTER(LAYER_SIZE),
        ctypes.c_void_p, ctypes.POINTER(LAYER_POINT), wintypes.DWORD,
        ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
    u32.UpdateLayeredWindow.restype = wintypes.BOOL
    u32.WindowFromPoint.argtypes = [LAYER_POINT]
    u32.WindowFromPoint.restype = wintypes.HWND
    g32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    g32.CreateCompatibleDC.restype = ctypes.c_void_p
    g32.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                     ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                     wintypes.DWORD]
    g32.CreateDIBSection.restype = ctypes.c_void_p
    g32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    g32.SelectObject.restype = ctypes.c_void_p
    g32.DeleteObject.argtypes = [ctypes.c_void_p]
    g32.DeleteObject.restype = wintypes.BOOL
    g32.DeleteDC.argtypes = [ctypes.c_void_p]
    g32.DeleteDC.restype = wintypes.BOOL
    _win32_ready = True


_PIL_MOD = None
_PIL_CHOPS = None


def _pil():
    """(PIL.Image, PIL.ImageChops)：延迟取一次后复用 —— 预乘是逐帧热路径，别每帧 import"""
    global _PIL_MOD, _PIL_CHOPS
    if _PIL_MOD is None:
        from PIL import Image as _I, ImageChops as _C
        _PIL_MOD, _PIL_CHOPS = _I, _C
    return _PIL_MOD, _PIL_CHOPS


def resolve_render_mode(cfg):
    """决定渲染模式：缺键 / 非字符串 / 拼写不对 → 一律回落 compat（手册 ① 步 1）。

    容忍前后空白与大小写（' Alpha ' 认作 alpha），但仅 compat/alpha 两个词合法 ——
    这样既不给老配置（无该键）添麻烦，也不会把 ['alpha']/True/1 之类脏值当成开关。
    """
    raw = None
    try:
        raw = cfg.get('render_mode', DEFAULT_RENDER_MODE)
    except AttributeError:          # cfg 为 None / 非映射
        return DEFAULT_RENDER_MODE
    if not isinstance(raw, str):
        return DEFAULT_RENDER_MODE
    v = raw.strip().lower()
    return v if v in RENDER_MODES else DEFAULT_RENDER_MODE


class Renderer:
    """渲染接口（手册 ① 步 2）：收口「RGBA → 屏幕上一帧」的整条链路。

    FollowOverlay 只通过这套方法出图，不再直接碰 _flatten_alpha_for_tk /
    ImageTk.PhotoImage / -transparentcolor / Label —— 换实现即换渲染模式。
    两个实现：
      · CompatRenderer  —— v1.6 老路径（键色抠色 + Tk Label），默认
      · LayeredRenderer —— 真 alpha 分层窗（①b/t3 实装；骨架期对外行为与 compat 等价）
    """

    mode = DEFAULT_RENDER_MODE
    uses_tk_label = True      # alpha 实装后为 False（手册 ① 步 5：该模式不再放 Label 贴图）

    def __init__(self, overlay, mode=None):
        self.overlay = overlay
        self.mode = mode or self.mode
        self.cfg = getattr(overlay, 'cfg', None) or {}

    @property
    def root(self):
        return getattr(self.overlay, 'root', None)

    # ---------- 管线三段：抠色 → 出帧 → 应用 ----------
    def pick_key(self, imgs, Image=None):
        """动态抠色键：选一个图中不存在的颜色（alpha 模式不需要，但接口保持一致）"""
        return pick_key_color(imgs, Image)

    def flatten(self, img_rgba, key=MAGENTA, Image=None):
        """RGBA → 显示帧（格式由实现决定：compat=键色抠色 RGB / alpha=原 RGBA）"""
        raise NotImplementedError

    def to_photo(self, img):
        """显示帧 → Tk PhotoImage（alpha 实装后改推分层位图，返回 None）"""
        raise NotImplementedError

    def prepare(self, img_rgba, key=MAGENTA, Image=None):
        """一步出图：flatten + to_photo（动图逐帧、静态图共用）"""
        return self.to_photo(self.flatten(img_rgba, key, Image))

    def make_label(self, parent, photo, key_rgb, cursor='fleur'):
        """造承载图片的 Label（拖动/滚轮/右键事件都绑在它身上）"""
        raise NotImplementedError

    def apply_window(self, key_rgb):
        """窗口级应用（透明色 / 底色 / 首推位图）→ 返回键色 '#RRGGBB'"""
        raise NotImplementedError

    def apply_label(self, label, photo, key_rgb):
        """把帧贴到 Label（图像 + 跟随键色的底色）"""
        raise NotImplementedError

    def apply_photo_only(self, label, photo):
        """只换图、不改底色（热重载 / 滚轮缩放 / 动图节拍共用）"""
        raise NotImplementedError

    def push_frame(self, img_rgba, key_rgb=None, x=None, y=None):
        """把一帧真正送达屏幕。compat：显示由 Tk Label 承担，这里无事可做；
        alpha：UpdateLayeredWindow 推预乘位图（①b/t3 实装）。"""
        return None

    def on_moved(self, x=None, y=None):
        """窗口移动/缩放/图层同步后（compat：无操作，Label 由系统带走；
        alpha：位图必须重推一次，手册 ① 步 6）。x/y 仅作诊断，实现在推图时自取窗口坐标。"""
        return None

    def on_shown(self):
        """窗口从隐藏恢复显示后（compat：无操作；alpha：重推，隐藏期间位图可能失效）。"""
        return None

    def release(self, photo):
        """释放 tcl image（同步，不等 GC 的 __del__）"""
        _release_photo(photo)

    def describe(self):
        return f'{type(self).__name__}(mode={self.mode})'


class CompatRenderer(Renderer):
    """v1.6 老路径原样承载：_flatten_alpha_for_tk → ImageTk.PhotoImage → Label + -transparentcolor。

    本类每个方法都是 v1.6 行为的一对一搬运（含 try/except 静默容错的边界条件），
    逐像素不变 —— 由 B_test_renderer.py 与既有 6 个回归脚本共同守住这条。
    """

    mode = 'compat'
    uses_tk_label = True

    def flatten(self, img_rgba, key=MAGENTA, Image=None):
        # 修复紫边：缩放后 alpha 二值化 + 透明区填键色（配合 transparentcolor 抠色）
        return _flatten_alpha_for_tk(img_rgba, Image, key if key is not None else MAGENTA)

    def to_photo(self, img):
        image_tk = getattr(self.overlay, '_ImageTk', None)
        return image_tk.PhotoImage(img, master=self.root)

    def make_label(self, parent, photo, key_rgb, cursor='fleur'):
        return tk.Label(parent, image=photo, bg=_key_hex(key_rgb), cursor=cursor)

    def apply_window(self, key_rgb):
        # 窗口透明色 / 背景色全部跟随动态键色
        key_hex = _key_hex(key_rgb)
        root = self.root
        if root is not None:
            try:
                root.attributes('-transparentcolor', key_hex)
            except Exception:
                pass
            try:
                root.configure(bg=key_hex)
            except Exception:
                pass
        return key_hex

    def apply_label(self, label, photo, key_rgb):
        if label is None:
            return
        try:
            label.configure(image=photo, bg=_key_hex(key_rgb))
        except Exception:
            pass

    def apply_photo_only(self, label, photo):
        if label is None:
            return
        try:
            label.configure(image=photo)
        except Exception:
            pass


class LayerFrame:
    """alpha 模式的「帧对象」：包住 PIL 图，向调用方提供与 PhotoImage 相同的取尺寸语义。

    load_char 里用 `self.img.width()/height()`（PhotoImage 是方法），而 PIL.Image 的
    width/height 是**属性** —— 直接返回 PIL 图会在 load_char 里炸 'int' object is not
    callable。所以统一包一层：对外 width()/height()，对内 .image 是真正的 RGBA 帧。
    """

    __slots__ = ('image',)

    def __init__(self, image):
        self.image = image

    def width(self):
        return int(self.image.size[0])

    def height(self):
        return int(self.image.size[1])

    def __repr__(self):
        return f'LayerFrame{tuple(self.image.size)}'


class LayeredRenderer(CompatRenderer):
    """真 alpha 分层窗渲染（手册 ① 步 2-6）：Tk 窗 + WS_EX_LAYERED + UpdateLayeredWindow。

    与 CompatRenderer 的差别（只影响 render_mode=alpha；compat 分支一行都不受影响）：
      · flatten 原样保留 RGBA：不抠键色、不做 alpha 二值化 → 逐像素 alpha 真渐变
      · 不经 Tk PhotoImage：帧本身就是显示数据源，UpdateLayeredWindow 推预乘 BGRA 位图
      · 不复用 -transparentcolor（窗口内容完全由位图决定），Label 只用来接鼠标事件
        （手册 ① 步 5；透明区天然点击穿透，见 Windows 对 ULW 窗口的 alpha 命中测试）
      · 推送时机（手册 ① 步 6）：动图跟 _anim_tick 每帧推；静态图只在「首次显示 / 移动 /
        缩放 / 换图 / 特效参数变」推一次 —— 由 FollowOverlay 在定位、拖动、尺寸校正、
        手动显示四处调 on_moved()/on_shown() 触发，不做 50ms 轮询硬推
      · 每次推图前重设 WS_EX_LAYERED（Tk 重设窗口属性会冲掉，手册 ① 步 4）

    性能（本机实测，手册基线）：PIL 向量化预乘 300x420 ≈2.8ms/帧、450x675 ≈6.3ms/帧；
    对照 spike 的逐像素 Python 循环 46ms/帧 —— 所以预乘只准用向量化实现。
    """

    mode = 'alpha'
    uses_tk_label = False      # 手册 ① 步 5：该模式不放贴图，内容完全由位图决定
    alpha_ready = True

    def __init__(self, overlay, mode=None):
        super().__init__(overlay, mode)
        self._frame = None             # 当前帧（PIL RGBA）——推图数据源
        self._frame_pushed = False     # 当前帧是否已推给当前窗口
        self._hwnd = 0                 # 最近一次推图使用的顶层句柄
        self._pushed_size = (0, 0)
        self._pushed_pos = (0, 0)
        self._n_push = 0               # 推送次数（B_test 验「静态只推一次 / 动图每帧推」）
        self._n_fail = 0
        self._reset_done = set()       # 已做过 layered 状态复位的窗口句柄（每个窗口一次）
        self.last_error = ''

    # ---------- 帧链路：保留 RGBA（真 alpha）----------
    def flatten(self, img_rgba, key=MAGENTA, Image=None):
        """不抠色：原样保留 RGBA（键色是 compat 硬抠色的产物，对逐像素 alpha 无意义）"""
        try:
            return img_rgba.copy()
        except Exception:
            return img_rgba

    def to_photo(self, img):
        """不经 Tk PhotoImage：把 RGBA 帧记为本渲染器的当前帧，返回 LayerFrame 交给 load_char。

        LayerFrame 提供 width()/height()（与 PhotoImage 同语义），.image 才是 PIL 帧。
        """
        self._frame = img
        self._frame_pushed = False
        return LayerFrame(img)

    def _as_image(self, obj):
        """帧对象 → PIL Image（LayerFrame 解包；不是图像则返回 None）"""
        if obj is None:
            return None
        inner = getattr(obj, 'image', None)
        if inner is not None and hasattr(inner, 'tobytes'):
            return inner
        if hasattr(obj, 'tobytes') and hasattr(obj, 'size'):
            return obj
        return None

    def make_label(self, parent, photo, key_rgb, cursor='fleur'):
        """不放贴图，仍造 Label 承载拖动/滚轮/右键事件（交互链路照旧）"""
        return tk.Label(parent, bg='#000000', cursor=cursor)

    def apply_window(self, key_rgb):
        """窗口准备 + 首推位图。

        先摘掉 Tk 的 -transparentcolor：它在 Windows 上走 SetLayeredWindowAttributes
        （LWA_COLORKEY），与 UpdateLayeredWindow 对同一个 WS_EX_LAYERED 窗口互斥 ——
        不清掉会把位图内容整片抠掉（手册 ① 步 5「内容完全由位图决定」）。
        """
        self.drop_tk_transparency()
        return self.push_static()

    def drop_tk_transparency(self):
        """清掉 Tk 键色透明度与底色（alpha 模式不再需要，且会与 ULW 打架）"""
        root = self.root
        if root is None:
            return
        try:
            root.attributes('-transparentcolor', '')
        except Exception:
            pass
        try:
            root.configure(bg='#000000')
        except Exception:
            pass

    def apply_label(self, label, photo, key_rgb):
        return None       # 位图模式：Label 不贴图、也不设 -transparentcolor

    def apply_photo_only(self, label, photo):
        """换帧（动图节拍 / 热重载 / 滚轮缩放）：同一帧已推过就跳过，绝不轮询硬推"""
        img = self._as_image(photo)
        if img is None:
            return None
        if img is not self._frame:
            self._frame = img
            self._frame_pushed = False
        if self._frame_pushed:
            return True
        return self.push_static()

    def on_moved(self, x=None, y=None):
        """移动/缩放/图层同步后重推（手册 ① 步 6 的「移动」时机）"""
        self._frame_pushed = False
        return self.push_static()

    def on_shown(self):
        """从隐藏恢复显示后重推（隐藏期间位图内容可能未生效）"""
        self._frame_pushed = False
        return self.push_static()

    # ---------- 窗口准备 ----------
    def ensure_layered(self, hwnd):
        """确保顶层句柄带 WS_EX_LAYERED（Tk 每次 attributes()/geometry 都可能冲掉 → 推图前重设）。

        首次拿到的窗口还要做一次「摘掉再戴上」复位：Tk 的 -transparentcolor 会用
        SetLayeredWindowAttributes 把窗口锁进另一种分层模式，此时 UpdateLayeredWindow
        永远返回 0（实测）。复位后 ULW 立刻可用 —— 也让「compat 皮肤切到 alpha 皮肤」
        这种运行时切换不会变成黑窗。
        """
        if not hwnd:
            return False
        try:
            _prepare_win32()
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if hwnd not in self._reset_done:
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)
                self._reset_done.add(hwnd)
                return bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_LAYERED)
            if ex & WS_EX_LAYERED:
                return True
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)
            return bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_LAYERED)
        except Exception as e:
            self.last_error = f'ensure_layered: {e!r}'
            return False

    def _ensure_window(self):
        """手册 ① 步 4：窗口准备放在"拿到顶层句柄"之后。

        用 update_idletasks 让 Tk 把窗口真正建出来（不用 update()：推图可能在
        Tk 回调里发生，update() 会重入处理事件队列）。
        """
        ov, root = self.overlay, self.root
        if root is not None:
            try:
                root.update_idletasks()
            except Exception:
                pass
        hwnd = 0
        try:
            hwnd = int(getattr(ov, '_top_hwnd', lambda: 0)() or 0)
        except Exception:
            hwnd = 0
        if not hwnd and root is not None:
            # 兜底：窗口还没 map 时 GetParent 链可能拿不到，用 GetAncestor(GA_ROOT) 直接取顶层
            try:
                hwnd = int(user32.GetAncestor(root.winfo_id(), 2) or 0)
            except Exception:
                hwnd = 0
        if not hwnd:
            hwnd = self._hwnd
        if not hwnd:
            self.last_error = '顶层句柄不可用（窗口未建立）'
            return 0
        try:
            if not user32.IsWindow(hwnd):
                self.last_error = f'句柄已失效 0x{hwnd:X}'
                return 0
        except Exception:
            pass
        self._hwnd = hwnd
        self.ensure_layered(hwnd)
        return hwnd

    def _window_pos(self, hwnd):
        """窗口当前屏幕坐标（GetWindowRect 为权威，退回镜像坐标 _x/_y）"""
        try:
            r = wintypes.RECT()
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            user32.GetWindowRect.restype = wintypes.BOOL
            if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                return int(r.left), int(r.top)
        except Exception:
            pass
        return int(getattr(self.overlay, '_x', 0) or 0), int(getattr(self.overlay, '_y', 0) or 0)

    # ---------- 位图推送 ----------
    def make_bmi(self, w, h):
        """BITMAPINFO：32bpp / BI_RGB / biHeight 取负（自上而下，手册 ① 步 3）"""
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = int(w)
        bmi.bmiHeader.biHeight = -int(h)
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = LAYERED_BI_RGB
        return bmi

    def premultiply_bgra(self, img_rgba):
        """PIL 向量化预乘 → BGRA bytes（手册 ① 步 3）。

        split 出 a 后逐通道 ImageChops.multiply(ch, a)（= c*a/255 整数口径，与 spike 的
        (c*a)//255 逐像素参考实现一致），再按 B,G,R,A 合并 —— 全程 C 实现，无 Python 逐像素循环。
        """
        img = img_rgba
        Image, chops = _pil()
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        r, g, b, a = img.split()
        out = Image.merge('RGBA', (chops.multiply(b, a), chops.multiply(g, a),
                                   chops.multiply(r, a), a))
        return out.tobytes()

    def push_bitmap(self, hwnd, img_rgba, x, y):
        """spike 六步：GetDC → CreateCompatibleDC → CreateDIBSection → memmove 预乘 BGRA
        → UpdateLayeredWindow → 释放 GDI 句柄（手册 ① 步 2）。失败返回 False 并记 last_error。"""
        _prepare_win32()
        w, h = img_rgba.size
        data = self.premultiply_bgra(img_rgba)
        screen_dc = mem_dc = hbmp = None
        ok = False
        try:
            screen_dc = user32.GetDC(0)
            if not screen_dc:
                self.last_error = 'GetDC 失败'
                return False
            mem_dc = gdi32.CreateCompatibleDC(screen_dc)
            if not mem_dc:
                self.last_error = 'CreateCompatibleDC 失败'
                return False
            bmi = self.make_bmi(w, h)
            bits = ctypes.c_void_p()
            hbmp = gdi32.CreateDIBSection(mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                          ctypes.byref(bits), None, 0)
            if not hbmp or not bits:
                self.last_error = 'CreateDIBSection 失败'
                return False
            ctypes.memmove(bits, data, len(data))
            gdi32.SelectObject(mem_dc, hbmp)
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            pt_dst = LAYER_POINT(int(x), int(y))
            sz = LAYER_SIZE(int(w), int(h))
            pt_src = LAYER_POINT(0, 0)
            ok = bool(user32.UpdateLayeredWindow(
                hwnd, screen_dc, ctypes.byref(pt_dst), ctypes.byref(sz),
                mem_dc, ctypes.byref(pt_src), 0, ctypes.byref(blend), ULW_ALPHA))
            if not ok:
                self.last_error = 'UpdateLayeredWindow 返回 0'
        except Exception as e:
            self.last_error = f'push_bitmap: {e!r}'
            ok = False
        finally:
            try:
                if hbmp:
                    gdi32.DeleteObject(hbmp)
            except Exception:
                pass
            try:
                if mem_dc:
                    gdi32.DeleteDC(mem_dc)
            except Exception:
                pass
            try:
                if screen_dc:
                    user32.ReleaseDC(0, screen_dc)
            except Exception:
                pass
        return ok

    def clear(self):
        """把分层窗内容清成全透明（切回 compat / 让出显示权时调用）。

        分层窗的内容一旦推上去就一直挂在窗口 surface 上：切回 compat 后由 Tk 常规绘制
        接管，先推一张全透明图可以避免旧位图残留在画面上。
        """
        img = self._frame
        hwnd = self._hwnd
        if img is None or not hwnd:
            return False
        try:
            Image, _chops = _pil()
            blank = Image.new('RGBA', img.size, (0, 0, 0, 0))
            x, y = self._window_pos(hwnd)
            ok = self.push_bitmap(hwnd, blank, x, y)
            self._frame_pushed = False
            return ok
        except Exception as e:
            self.last_error = f'clear: {e!r}'
            return False

    def push_static(self, force=False):
        """把当前帧推给分层窗（帧未变且已推过则跳过）。返回是否成功。"""
        img = self._frame
        if img is None:
            return False
        if self._frame_pushed and not force:
            return True
        hwnd = self._ensure_window()
        if not hwnd:
            self._n_fail += 1
            return False
        x, y = self._window_pos(hwnd)
        if self.push_bitmap(hwnd, img, x, y):
            self._frame_pushed = True
            self._pushed_size = tuple(img.size)
            self._pushed_pos = (x, y)
            self._n_push += 1
            return True
        self._n_fail += 1
        return False

    def push_frame(self, img_rgba, key_rgb=None, x=None, y=None):
        """逐帧推送入口（动图节拍用：帧已由 to_photo 记好，这里只负责推）"""
        img = self._as_image(img_rgba)
        if img is not None and img is not self._frame:
            self._frame = img
            self._frame_pushed = False
        return self.push_static(force=True)

    def describe(self):
        return (f'{type(self).__name__}(mode={self.mode} ready={self.alpha_ready} '
                f'push={self._n_push} fail={self._n_fail}'
                + (f' err={self.last_error}' if self.last_error else '') + ')')


RENDERER_CLASSES = {'compat': CompatRenderer, 'alpha': LayeredRenderer}


def create_renderer(overlay, cfg=None, mode=None):
    """按 render_mode 造渲染器。缺键 / 非法值 / 构造失败一律 compat 兜底 —— 渲染层不能成为启动崩溃源。"""
    if cfg is None:
        cfg = getattr(overlay, 'cfg', None)
    m = mode or resolve_render_mode(cfg)
    if m == 'alpha' and getattr(overlay, '_ImageTk', None) is None:
        # alpha 依赖 PIL（向量化预乘 + RGBA 帧）；PIL 缺失时回落 compat，画面照旧能显示
        try:
            _write_log('[渲染] alpha 需要 Pillow，未安装 → 回落 compat')
        except Exception:
            pass
        m = 'compat'
    cls = RENDERER_CLASSES.get(m, CompatRenderer)
    try:
        r = cls(overlay, m)
        if not isinstance(r, Renderer):     # 防御：实现必须满足接口
            raise TypeError(f'{cls.__name__} 不是 Renderer')
        r.cfg = cfg or {}
        return r
    except Exception as e:
        try:
            _write_log(f'[渲染] {m} 渲染器构造失败 → 回落 compat: {e}')
        except Exception:
            pass
        r = CompatRenderer(overlay, 'compat')
        r.cfg = cfg or {}
        return r


def _renderer_of(overlay):
    """取 overlay 的渲染器；没有则按当前 cfg 现造一个并挂回去（惰性兜底，等效 compat）。

    正常路径的渲染器在 FollowOverlay.__init__ 就建好；这里是给「桩对象直接调
    FollowOverlay 方法」的场景兜底（如 B_test_anim_sim 的 _decode_frame 壳），
    也给极端情况下 renderer 字段丢失留一条自愈路径 —— 渲染层不该是崩溃源。
    """
    r = getattr(overlay, 'renderer', None)
    if r is None:
        r = create_renderer(overlay, getattr(overlay, 'cfg', None))
        try:
            overlay.renderer = r
        except Exception:
            pass
    return r


# ============ 动图支持（v1.6）============
ANIM_CACHE_MAX = 6          # LRU 帧缓存上限（张 PhotoImage），足够顺序播放 + 预取
ANIM_KEY_SAMPLE = 48        # 统计抠色键色的最大采样帧数（帧多时均匀采样，含首帧）
ANIM_PREPROCESS_MAX = 300   # 预处理动图最多处理的帧数（超了均匀采样，防一次处理几千帧卡死）
ANIM_HIDDEN_POLL_MS = 200   # 窗口隐藏时动画暂停，仅按此间隔探活（最大 CPU 省钱点）
ANIM_MIN_MS, ANIM_MAX_MS = 20, 1000   # 单帧时长钳位（防异常 duration 把 UI 抳死）
# R6 图片预处理的动图预览：帧缓存上限（work 尺寸 RGBA，够顺序播放 + 回退几帧）+ 棋盘格同色
# 注意：棋盘格颜色是「预处理对话框」专属口径（深灰底 #2b2b2b + 亮格 #4a4a4a），与向导预览的
# CHECKER_LIGHT/CHECKER_DARK（白/浅灰，R1 那套）不是一个东西，故用 PREPROCESS_ 前缀区分。
ANIM_PREVIEW_CACHE_MAX = 12
PREPROCESS_CHECKER_LIGHT = '#4a4a4a'
PREPROCESS_CHECKER_BASE = '#2b2b2b'
# R8 图片预处理对话框的右栏容器：固定宽 240（与改前观感逐像素一致），内容高于可视区时
# 让出 17px 给竖直滚动条 → 内容被压窄后折行更高，两者都在 _fit_dialog_size 里算。
PREPROCESS_PANEL_W = 240
PREPROCESS_PANEL_SB_W = 17
PREPROCESS_CHROME_H = 40    # 窗口标题栏 + 边框预留（map 前量不到，保守取值）


def _sample_frame_indices(n, limit):
    """均匀采样帧号（含首帧、末帧）：n<=limit 时全取（不丢帧）。"""
    n = int(n)
    if n <= 1:
        return [0]
    if n <= limit:
        return list(range(n))
    step = n / float(limit)
    idx = sorted({int(i * step) for i in range(limit)} | {0, n - 1})
    return idx


def _frame_duration(img, default=100):
    """当前帧时长(ms)：GIF/WebP 在 img.info['duration']（需先 seek 到该帧），
    钳到 [ANIM_MIN_MS, ANIM_MAX_MS]，缺失/异常回退 default。"""
    try:
        d = int(img.info.get('duration') or default)
    except Exception:
        d = default
    return max(ANIM_MIN_MS, min(ANIM_MAX_MS, d))


BAYER4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def _tile_bayer(size, Image):
    """拼一块 4×4 有序抖动阈值图（0~255）：把羽化渐变近似成「点阵半透明」"""
    w, h = size
    small = Image.new('L', (4, 4))
    small.putdata([BAYER4[y][x] * 16 + 8 for y in range(4) for x in range(4)])
    out = Image.new('L', (w, h))
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            out.paste(small, (x, y))
    return out


def _feather_true_alpha(cfg):
    """羽化走「逐像素真羽化」还是「4×4 点阵近似」？

    v2.0-R1：真 alpha 分层窗支持逐像素 alpha，羽化就可以是真渐变；而 Tk 老路径
    （-transparentcolor）只有全透明/全不透明两档，只能拿点阵近似。判定口径：
      · cfg['true_alpha'] 显式给真值 → 真羽化（向导预览用它对齐模式）
      · 否则看 cfg['render_mode'] == 'alpha'（运行时 overlay.cfg 自带该键）
      · 缺键 / 非法值 → 点阵近似（compat 老路径零变化）
    """
    try:
        if bool(cfg.get('true_alpha')):
            return True
    except Exception:
        return False
    try:
        return resolve_render_mode(cfg) == 'alpha'
    except Exception:
        return False


def apply_display_effects(img_rgba, cfg, Image=None):
    """显示期特效：水平翻转 + 羽化（alpha）+ 圆角遮罩（alpha）。

    ⚠️ 透明机制上限（README「已知限制」同步写明）：tkinter 的 -transparentcolor
    只支持「全透明 / 全不透明」两档，做不出真正的半透明渐变。所以：
      · 水平翻转：显示期镜像（不动文件，动图同样生效，随时可逆）；
      · 羽化：兼容模式用 4×4 有序抖动把羽化带内的 alpha 近似成渐变
        （远看像边缘渐隐，贴近看是细点阵）；**增强模式**（render_mode=alpha /
        cfg['true_alpha']）改走逐像素高斯渐变 —— 真羽化，见 _feather_true_alpha；
      · 圆角：作用在 alpha 上，4× 超采样绘制后缩回，让硬边尽量贴合轮廓。
    与预处理抠图共存：alpha 相乘关系，抠图得出的透明区不受影响。
    """
    if Image is None:
        from PIL import Image as _I
        Image = _I
    out = img_rgba
    try:
        if cfg.get('flip_h'):
            out = out.transpose(Image.FLIP_LEFT_RIGHT)
    except Exception:
        pass
    try:
        fr = int(cfg.get('feather_radius', 0) or 0)
        on = bool(cfg.get('feather_enabled')) or bool(cfg.get('feather_dither'))  # 兼容旧配置
        if on and fr > 0:
            from PIL import ImageDraw, ImageFilter, ImageChops
            w, h = out.size
            band = max(2, min(fr, min(w, h) // 2))
            # 内部掩膜：带内 0 → 内部 255（高斯过渡）。兼容模式拿它当抖动坡度，
            # 增强模式（v2.0-R1）直接拿它当逐像素 alpha。
            inner = Image.new('L', (w, h), 0)
            ImageDraw.Draw(inner).rectangle((band, band, w - band - 1, h - band - 1),
                                            fill=255)
            inner = inner.filter(ImageFilter.GaussianBlur(band * 0.5))
            out = out.copy()
            if _feather_true_alpha(cfg):
                # 增强（真羽化）：分层窗支持逐像素 alpha → 渐变本身就是边缘过渡，
                # 没有点阵颗粒（4×4 有序抖动只是它在兼容模式下的近似）
                out.putalpha(ImageChops.multiply(out.split()[3], inner))
            else:
                # 兼容：Tk 键色透明只有「全透明/全不透明」两档 → 用 4×4 有序抖动近似渐变
                ramp = ImageChops.add(inner, _tile_bayer((w, h), Image), 1.0, -128)
                out.putalpha(ImageChops.multiply(
                    out.split()[3], ramp.point(lambda v: 255 if v > 128 else 0)))
    except Exception:
        pass
    try:
        cr = int(cfg.get('corner_radius', 0) or 0)
        if cfg.get('corner_enabled') and cr > 0:
            from PIL import ImageDraw, ImageChops
            w, h = out.size
            r = max(1, min(cr, min(w, h) // 2))
            s = 4
            mask = Image.new('L', (w * s, h * s), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * s - 1, h * s - 1),
                                                   radius=r * s, fill=255)
            mask = mask.resize((w, h), Image.LANCZOS)
            out = out.copy()
            out.putalpha(ImageChops.multiply(out.split()[3], mask))
    except Exception:
        pass
    return out


# ---- 预览棋盘格（v2.0-R1）：Tk 的 PhotoImage 不支持逐像素 alpha，预览必须先把 RGBA 合成掉 ----
CHECKER_CELL = 16                       # 棋盘格边长（对齐 ImagePreprocessDialog._draw_checker 的 16px）
CHECKER_LIGHT = (255, 255, 255)
CHECKER_DARK = (214, 214, 214)


def checker_background(size, cell=CHECKER_CELL, light=CHECKER_LIGHT, dark=CHECKER_DARK,
                       Image=None):
    """生成透明棋盘格底图（RGB）。

    与 ImagePreprocessDialog._draw_checker 同一套做法（16px 一格、偶格用深色），
    区别只是：那边画在 Tk Canvas 上当背景，这里生成 PIL 底图供 alpha 合成。
    """
    if Image is None:
        from PIL import Image as _I
        Image = _I
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    cell = max(2, int(cell))
    bg = Image.new('RGB', (w, h), light)
    try:
        from PIL import ImageDraw
        d = ImageDraw.Draw(bg)
        for y in range(0, h, cell):
            for x in range(0, w, cell):
                if ((x // cell) + (y // cell)) % 2 == 0:
                    d.rectangle((x, y, min(x + cell - 1, w - 1), min(y + cell - 1, h - 1)),
                                fill=dark)
    except Exception:
        pass
    return bg


def compose_on_checker(img_rgba, cell=CHECKER_CELL, Image=None):
    """把 RGBA 合成到棋盘格上 → RGB 图（预览专用）。

    Tk PhotoImage 丢掉 alpha、画布又是白底，所以透明与半透明在预览里根本看不出来
    （用户实测：「渲染增强没看见对应的预览」）。先合成再显示就能看见：
      · 全透明像素 → 露出棋盘格（= 这里是透明的）
      · 半透明像素 → 图片颜色与棋盘格的混合色（= 这里是半透明的）
    这样「兼容 = 硬边点阵 / 增强 = 颜色到棋盘格的平滑过渡」才肉眼可辨。
    """
    if Image is None:
        from PIL import Image as _I
        Image = _I
    bg = checker_background(img_rgba.size, cell=cell, Image=Image)
    try:
        return Image.alpha_composite(bg.convert('RGBA'),
                                     img_rgba.convert('RGBA')).convert('RGB')
    except Exception:
        try:
            out = bg.copy()
            out.paste(img_rgba.convert('RGB'), (0, 0), img_rgba.split()[3])
            return out
        except Exception:
            return bg


# ---- 预览纯色底（v2.0-R7）：透明区不再垫棋盘格，改回画布底色 ----
# 用户第三轮实测：「抠图后会变成这样，不再透明」——先生截的是**向导预览区**，R1 垫的棋盘格
# 被看成了「不透明」，用户明确要求预览改回纯色底。上面那套棋盘格（CHECKER_*，本文件预览专用）
# 保留作实现/测试的对照口径，不再参与预览显示；预处理对话框用的是另一套（PREPROCESS_CHECKER_*），
# 两者互不影响。
PREVIEW_BG_HEX = '#ffffff'              # = 预览画布底色（ConfigWizard.CV_BG）
PREVIEW_BG_RGB = (255, 255, 255)


def compose_on_solid(img_rgba, bg_color=PREVIEW_BG_RGB, Image=None):
    """把 RGBA 合成到纯色底上 → RGB 图（预览专用）。

    Tk PhotoImage 丢掉 alpha、画布又是白底，所以透明与半透明在预览里根本看不出来，
    先合成再显示就能看见：
      · 全透明像素 → 与画布底色同色（= 这里是透明的，融进背景）
      · 半透明像素 → 图片颜色与底色的混合色（= 这里是半透明的）
    这样「兼容 = 硬边点阵 / 增强 = 颜色到底色的平滑过渡」仍肉眼可辨（R1 的合成口径不变，只换底）。
    """
    if Image is None:
        from PIL import Image as _I
        Image = _I
    w, h = max(1, int(img_rgba.size[0])), max(1, int(img_rgba.size[1]))
    bg = Image.new('RGB', (w, h), tuple(bg_color))
    try:
        return Image.alpha_composite(bg.convert('RGBA'),
                                     img_rgba.convert('RGBA')).convert('RGB')
    except Exception:
        try:
            out = bg.copy()
            out.paste(img_rgba.convert('RGB'), (0, 0), img_rgba.split()[3])
            return out
        except Exception:
            return bg


def decode_anim_frame_rgba(overlay, idx):
    """动图单帧解码到 **RGBA**（seek → RGBA → 缩放 → 特效），不做抠色。

    v2.0-② 模块级实现（不依赖 overlay 的其它方法）：
      · 单层老路径由 FollowOverlay._decode_frame 调它 → 再走渲染层 prepare；
      · 多图层路径直接拿它当合成输入（合成必须在抠色之前）；
      · 测试桩（只有 _Image / anim_src / anim_n / _base_h / cfg）也能直接调。
    """
    src = getattr(overlay, 'anim_src', None)
    if src is None:
        return None
    Image = getattr(overlay, '_Image', None)
    if Image is None:
        return None
    n = int(getattr(overlay, 'anim_n', 1) or 1)
    src.seek(int(idx) % n)
    img = src.convert('RGBA')
    base_h = getattr(overlay, '_base_h', 300.0)
    if img.height > 0:
        ratio = base_h / img.height
        img = img.resize((max(1, int(img.width * ratio)), max(1, int(base_h))),
                         Image.LANCZOS)
    cfg = getattr(overlay, 'cfg', None) or {}
    return apply_display_effects(img, cfg, Image)    # 与静态图一致的特效管线


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

def _is_candidate_window(hwnd):
    """候选框统一判定（v1.6 起 直挂/全扫 共用；2026-09-06 实机诊断修复误贴）：
    1) 类名必须 ATL: 前缀 —— TSF 注入候选框类名恒为 ATL:；Electron/Edge 菜单与
       网址提示浮层（Chrome_WidgetWin_1）、explorer TaskListOverlayWnd、tooltip
       等非 ATL: 弹层一律排除（原 SHOW 直挂路径缺此约束是误贴根因）；
    2) 样式 TSF 三件套（POPUP+TOOLWINDOW+NOACTIVATE）为主，weasel 进程兜底
       （兼容旧架构独立候选窗）；
    3) 尺寸合理；其中属 weasel 进程的窗口若宽高均 <120（如 32×32 大小写/状态
       切换指示窗）判定为非候选框 —— weasel 进程内不会出现微缩候选框，
       真实候选框恒为「注入应用进程（et/electron/msedge…）内的 ATL: 窗」。"""
    try:
        cls = ctypes.create_unicode_buffer(256)
        if not user32.GetClassNameW(hwnd, cls, 256):
            return False
        if not cls.value.startswith('ATL:'):
            return False
        weasel = False
        if not _is_tsf_candidate_style(hwnd):
            weasel = _window_belongs_to_weasel(hwnd)
            if not weasel:
                return False
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if not (0 < w < 1300 and 0 < h < 1000 and h < w * 4):
            return False
        # weasel 微缩窗排除：32×32 大小写/状态切换指示窗同样满足
        # 「ATL:+TSF 样式+weasel 进程」，仅凭样式/进程区分不了候选框 →
        # 对「小到可疑」的窗补查一次进程归属（低频路径，可接受），属 weasel 即排除。
        if w < 120 and h < 120 and _window_belongs_to_weasel(hwnd):
            return False
        return True
    except Exception:
        return False

# ---- EnumWindows 回调：模块级单例（改造后仅低频重扫才调用，一次创建反复使用，
#      避免旧版每 50ms 重建 WINFUNCTYPE 闭包的浪费；结果放模块级缓冲 + 锁防重入）----
_find_results = []
_find_lock = threading.Lock()


@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def _find_enum_proc(hwnd, lparam):
    """EnumWindows 回调：统一候选框判定（v1.6 _is_candidate_window），命中即收集。"""
    try:
        if not user32.IsWindowVisible(hwnd):
            return True
        if _is_candidate_window(hwnd):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
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
# ============ 清理垃圾（向导 / 托盘共用）============
KEEP_FILES = {'config.json', 'error.log', 'readme.md', 'changelog.md', 'license',
              'icon.png', 'icon.ico'}
# 受保护扩展名：源码/脚本/图标/文档/程序本体一律不算垃圾，永不删
# （.png 不保护 —— cfg_image_*.png / preprocessed_*.png 才是要清的垃圾；
#   icon.png 靠 KEEP_FILES 名字保护）
PROTECTED_EXT = {'.py', '.spec', '.ico', '.lnk', '.bat', '.cmd', '.ps1', '.vbs',
                 '.exe', '.dll', '.pyd', '.md', '.json', '.yml', '.yaml', '.ini', '.cfg'}


def _referenced_images():
    """当前配置 + 所有皮肤档案引用的图片（绝对路径）——这些绝不能当垃圾删"""
    paths = set()
    try:
        cfg = load_config()
        if cfg and cfg.get('image'):
            paths.add(os.path.abspath(cfg['image']))
    except Exception:
        pass
    try:
        for _name, scfg in list_skins():
            if scfg.get('image'):
                paths.add(os.path.abspath(scfg['image']))
    except Exception:
        pass
    return paths


def _file_hash(path):
    import hashlib
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 16), b''):
            h.update(chunk)
    return h.hexdigest()


def _managed_copy_dup(path):
    """若 path 是「配置托管副本」（cfg_image_* / preprocessed_*）且 skins/ 下有
    字节完全相同的副本，返回那个皮肤副本路径（清理时用它顶上），否则 None。

    背景：向导保存预处理图时会复制成 cfg_image_*.png 副本；若用户又存了皮肤，
    skins/<名>/image.png 就是同一张图 —— 这种重复副本应当可以清掉，
    删除前把 config 指向改到皮肤那份，不影响使用。
    """
    name = os.path.basename(path or '')
    if not (name.startswith('cfg_image_') or name.startswith('preprocessed_')):
        return None
    try:
        sz = os.path.getsize(path)
        h = _file_hash(path)
    except OSError:
        return None
    for _n, scfg in list_skins():
        sp = scfg.get('image')
        if not sp or os.path.abspath(sp) == os.path.abspath(path) or not os.path.exists(sp):
            continue
        try:
            if os.path.getsize(sp) == sz and _file_hash(sp) == h:
                return sp
        except OSError:
            continue
    return None


def collect_junk_files(folder=None, extra_keep=()):
    """列出「清理垃圾」的目标：程序目录下的普通文件（不含子目录），
    排除白名单（skins/ config error.log README CHANGELOG LICENSE icon.*）、受保护类型、
    当前正在使用的图片。
    特例：config 指向的「托管副本」若在 skins/ 下有字节完全相同的副本 → 算冗余副本，
    可清理（删除前会把 config 指向改到皮肤那份，不影响使用）。
    返回 [(path, size), ...]。
    """
    folder = folder or HERE
    keep = set(KEEP_FILES)
    for p in list(extra_keep):
        if p:
            keep.add(os.path.basename(p).lower())
    for p in _referenced_images():
        if not p:
            continue
        if _managed_copy_dup(p):
            continue                      # 冗余副本：不保护，交给下面当垃圾收走
        keep.add(os.path.basename(p).lower())
    out = []
    try:
        for name in os.listdir(folder):
            p = os.path.join(folder, name)
            if not os.path.isfile(p):
                continue                      # 目录（skins/ build/ …）一律不动
            low = name.lower()
            if low.startswith('.'):
                continue                      # 点文件（.gitignore 等）一律不碰
            if low in keep or os.path.splitext(low)[1] in PROTECTED_EXT:
                continue
            try:
                out.append((p, os.path.getsize(p)))
            except OSError:
                pass
    except OSError:
        pass
    return out


def _send_to_recycle_bin(paths):
    """送进回收站（SHFileOperation + FOF_ALLOWUNDO）——宁回收站不永久删。
    返回是否成功（整体失败返回 False，由调用方决定怎么办）。"""
    if not paths:
        return True
    try:
        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [('hwnd', wintypes.HWND), ('wFunc', wintypes.UINT),
                        ('pFrom', wintypes.LPCWSTR), ('pTo', wintypes.LPCWSTR),
                        ('fFlags', ctypes.c_ushort), ('fAnyOperationsAborted', wintypes.BOOL),
                        ('hNameMappings', ctypes.c_void_p),
                        ('lpszProgressTitle', wintypes.LPCWSTR)]
        FO_DELETE = 3
        FOF_SILENT, FOF_NOCONFIRMATION = 0x0004, 0x0010
        FOF_ALLOWUNDO, FOF_NOERRORUI = 0x0040, 0x0400
        buf = '\0'.join(os.path.abspath(p) for p in paths) + '\0\0'
        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = buf
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
        return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0
    except Exception:
        return False


def cleanup_junk_files(extra_keep=(), parent=None, confirm=True, folder=None):
    """清理程序目录垃圾（向导按钮 / 托盘菜单共用）。返回 (清理数, 总字节)。

    folder=None 时清理程序自身目录（生产用法）；显式传路径便于测试/其他目录。
    安全设计：只删「本目录下的普通文件」，目录一律不碰；白名单与受保护类型不碰；
    config.json/皮肤正在引用的图片不碰；优先进回收站（可还原）。
    """
    items = collect_junk_files(folder, extra_keep=extra_keep)
    if not items:
        if confirm:
            messagebox.showinfo('清理垃圾', '程序目录很干净，没有可清理的文件。', parent=parent)
        return 0, 0
    total = sum(s for _p, s in items)
    # 删除前处理「配置指向的冗余副本」：把 config 指向改到 skins/ 里的同一张图
    repoint = {}
    for p, _s in items:
        dup = _managed_copy_dup(p)
        if dup:
            repoint[os.path.abspath(p)] = dup
    if repoint:
        try:
            cfg0 = load_config()
            cur = os.path.abspath(cfg0['image']) if (cfg0 and cfg0.get('image')) else None
            if cur and cur in repoint:
                cfg1 = dict(cfg0)
                cfg1['image'] = repoint[cur]
                save_config(cfg1)
                _write_log(f'[清理] config 指向改到皮肤副本: {cfg1["image"]}')
        except Exception as e:
            try:
                _write_log(f'[清理] 改指向失败，跳过冗余副本: {e}')
            except Exception:
                pass
            items = [(p, s) for p, s in items if os.path.abspath(p) not in repoint]
            total = sum(s for _p, s in items)
            if not items:
                if confirm:
                    messagebox.showinfo('清理垃圾', '没有可安全清理的文件（冗余副本改指向失败）。',
                                        parent=parent)
                return 0, 0
    if confirm:
        names = '\n'.join(f'· {os.path.basename(p)}（{_human_size(s)}）' for p, s in items[:20])
        if len(items) > 20:
            names += f'\n… 等共 {len(items)} 个'
        extra = ('\n其中「配置正在使用的副本」在皮肤档案里有同一张图，清理后会自动改指向皮肤，不影响使用。'
                 if repoint else '')
        ok = messagebox.askyesno(
            '清理垃圾',
            f'将清理程序目录下的 {len(items)} 个文件（共 {_human_size(total)}）：\n\n{names}\n\n'
            f'skins/、config、error.log、README、CHANGELOG、LICENSE、正在使用的图片都不会动；\n'
            f'删除进回收站，可还原。{extra}', parent=parent)
        if not ok:
            return 0, 0
    if _send_to_recycle_bin([p for p, _s in items]):
        n = len(items)
    else:
        n = 0
        for p, _s in items:
            try:
                os.remove(p)
                n += 1
            except OSError:
                pass
    _write_log(f'[清理] 清理垃圾文件 {n}/{len(items)} 个（共 {_human_size(total)}）')
    if confirm:
        messagebox.showinfo('清理垃圾',
                            f'已清理 {n} 个文件（{_human_size(total)}），可在回收站还原。',
                            parent=parent)
    return n, total


def _describe_window(hwnd):
    """窗口指纹（类名 + 尺寸 + 进程名）：候选框命中的日志靠它复现"""
    try:
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = ''
        try:
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
            if h:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(len(buf))
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                        h, 0, buf, ctypes.byref(size)):
                    name = os.path.basename(buf.value)
                ctypes.windll.kernel32.CloseHandle(h)
        except Exception:
            pass
        return (f'类名={cls.value} {rect.right - rect.left}x{rect.bottom - rect.top} '
                f'进程={name or pid.value}')
    except Exception:
        return '(窗口信息读取失败)'


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

    def __init__(self, master, image_path, layer_hint=None):
        self.master = master
        self.src_path = image_path
        self.layer_hint = layer_hint     # R9：标题上标明「这一份属于第几层」（None = 不标）
        self.result_path = None
        try:
            from PIL import Image, ImageTk, ImageChops
        except ImportError:
            messagebox.showerror('缺少依赖', '图片预处理需要 Pillow 库，当前环境未安装。')
            raise
        self._Image, self._ImageTk = Image, ImageTk
        self._Chops = ImageChops

        self._src = self._Image.open(image_path)   # 源图（动图可 seek 逐帧）
        try:
            self.n_frames = int(getattr(self._src, 'n_frames', 1) or 1)
        except Exception:
            self.n_frames = 1
        try:
            self._src.seek(0)
        except Exception:
            pass
        self.orig = self._src.convert('RGBA')
        self._frames_ms = {0: _frame_duration(self._src)}   # 当前帧时长（seek 后读，别处 seek 会变）
        # ---- R6 动图预览状态：按需解码 + 节流播放（一律主线程内，无跨线程 Tk 调用）----
        self.preview_idx = 0            # 当前显示帧号（0 = 首帧；静态图恒为 0）
        self.preview_steps = 0          # 播放推进计数（测试观测用）
        self._playing = False
        self._anim_after = None         # 播放节拍 id（销毁前必须 after_cancel）
        self._alive = True              # 销毁后置 False，迟到的回调靠它安全返回
        self._frame_cache = collections.OrderedDict()   # 帧号 → work 尺寸 RGBA（LRU）
        self._checker_cache = {}                        # (w,h) → 棋盘格垫底图
        self._decode_calls = 0          # 解码次数（校验「按需」而不是一次性全解码）
        self._last_decode_ms = 0.0      # 最近一次单帧解码耗时（自适应节流用）
        self._size_fixups = 0           # 帧尺寸与首帧不一致被归一的次数（兜底可观测）
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
        self.crop = (0, 0, self.work.width, self.work.height)  # 缩略图坐标 (x0,y0,x1,y1)
        self.lock_ratio = None             # None=原图比例 / 'free'=自由 / float=锁定宽高比
        self.use_key = tk.BooleanVar(master=master, value=True)
        self.tol_var = tk.IntVar(master=master, value=20)
        self.bg_color = None               # 抠图背景色 (r,g,b)，None=未检测
        self.drag = None                   # 拖拽状态 (mode, ...)
        self.tk_img = None
        self._photo_refs = []              # PhotoImage 引用保留，防 GC

        self.root = tk.Toplevel(master)
        self.root.title('图片预处理 - 裁剪 / 抠图' + (f'（{layer_hint}）' if layer_hint else ''))
        self.root.resizable(False, False)
        self.root.transient(master)
        self.root.protocol('WM_DELETE_WINDOW', self._cancel)
        self.root.bind('<Destroy>', self._on_destroy, add='+')
        self._build_ui()
        self._fit_dialog_size()          # R8：定窗口尺寸（保证下方功能不被挤出可视区）
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
        self.cv.pack(side='left', anchor='n')
        self.cv.bind('<ButtonPress-1>', self._on_press)
        self.cv.bind('<B1-Motion>', self._on_drag)
        self.cv.bind('<ButtonRelease-1>', self._on_release)

        # 右：控制面板（v2.0-R8：装进「Canvas + 竖直滚动条」容器）
        # 改前这里是 `panel = Frame(width=240); pack_propagate(False); pack(fill='y')` —— 一个
        # 高度被左画布（602px）锁死的固定框。R6 加了「▶ 动图预览」区后右栏内容需求 662px，
        # pack 就把最后排的「应用 / 重置 / 取消」压成 1px 高且不 map（winfo_ismapped=0），
        # 用户实测原话：「动图抠图时下方的功能会被挤到无法点击的位置。」
        # 现在容器高度改为跟窗口走（见 _fit_dialog_size：窗口高度 = max(左画布, 右栏内容)），
        # 内容仍然装不下时出滚动条 —— 只裁内容不裁控件，任何情况下都能点到底部按钮。
        # 静态图（内容 534px < 602px）不显示滚动条、宽度仍是 240px → 观感与改前逐像素一致。
        self.panel_wrap = tk.Frame(main, width=PREPROCESS_PANEL_W)
        self.panel_wrap.pack(side='right', fill='y', padx=(10, 0))
        self.panel_wrap.pack_propagate(False)
        self.panel_canvas = tk.Canvas(self.panel_wrap, width=PREPROCESS_PANEL_W,
                                      highlightthickness=0, bd=0, bg=self.root.cget('bg'))
        self.panel_sb = tk.Scrollbar(self.panel_wrap, orient='vertical',
                                     command=self.panel_canvas.yview)
        self.panel_canvas.configure(yscrollcommand=self.panel_sb.set)
        self.panel_canvas.pack(side='left', fill='both', expand=True)
        panel = tk.Frame(self.panel_canvas)
        self.panel = panel
        self._panel_win = self.panel_canvas.create_window((0, 0), window=panel, anchor='nw')
        panel.bind('<Configure>', self._on_panel_configure)
        self.panel_canvas.bind('<Configure>', self._on_panel_configure)

        anim_txt = f'（动图 {self.n_frames} 帧，处理完仍是动图）' if self.n_frames > 1 else ''
        tk.Label(panel, text=f'原图 {self.orig.width}×{self.orig.height}{anim_txt}',
                 font=('Microsoft YaHei', 9), fg='#888').pack(anchor='w')

        # R6 动图预览：播放 / 逐帧查看（只对动图出现；静态图 UI 一字不变）
        if self.n_frames > 1:
            tk.Label(panel, text='▶ 动图预览（裁剪框对每帧都生效）',
                     font=('Microsoft YaHei', 10)).pack(anchor='w', pady=(8, 2))
            prow = tk.Frame(panel)
            prow.pack(anchor='w', fill='x')
            self.btn_play = tk.Button(prow, text='▶ 播放', width=8, command=self._toggle_preview,
                                      font=('Microsoft YaHei', 9))
            self.btn_play.pack(side='left', padx=(0, 2))
            tk.Button(prow, text='⏮', width=3, command=lambda: self._preview_goto(0),
                      font=('Microsoft YaHei', 9)).pack(side='left', padx=1)
            tk.Button(prow, text='◀', width=3, command=lambda: self._preview_step(-1),
                      font=('Microsoft YaHei', 9)).pack(side='left', padx=1)
            tk.Button(prow, text='▶', width=3, command=lambda: self._preview_step(1),
                      font=('Microsoft YaHei', 9)).pack(side='left', padx=1)
            self.lbl_frame = tk.Label(panel, text='第 1 / %d 帧' % self.n_frames, fg='#888',
                                      font=('Microsoft YaHei', 9))
            self.lbl_frame.pack(anchor='w', pady=(2, 0))
            tk.Label(panel, text='按需解码 + 按帧时长节流：播放只解当前帧，\n大动图不会一次性全解码（不卡界面）',
                     fg='#999', font=('Microsoft YaHei', 8), justify='left').pack(anchor='w')
            for seq, fn in (('<Left>', lambda _e: self._preview_step(-1)),
                            ('<Right>', lambda _e: self._preview_step(1)),
                            ('<space>', lambda _e: self._toggle_preview())):
                try:
                    self.root.bind(seq, fn)
                except Exception:
                    pass

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

        # ② 纯色背景抠图
        tk.Label(panel, text='② 纯色背景抠图:', font=('Microsoft YaHei', 10)).pack(anchor='w', pady=(10, 2))
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

        # 滚轮：右栏内容超出可视区时能滚（Tk 的滚轮事件只发给指针下的控件，不冒泡，
        # 所以把右栏子树整体绑一遍；作用域限在本对话框内，不动宿主窗口）
        self._bind_wheel(panel)

    # ---------- R8：窗口尺寸自适应 + 右栏滚动 ----------
    def _bind_wheel(self, widget):
        try:
            widget.bind('<MouseWheel>', self._on_panel_wheel)
        except Exception:
            pass
        try:
            for ch in widget.winfo_children():
                self._bind_wheel(ch)
        except Exception:
            pass

    def _on_panel_wheel(self, e):
        """右栏滚轮滚动（没滚动条时 yview_scroll 是空操作，不会动）。"""
        try:
            self.panel_canvas.yview_scroll(-1 if int(getattr(e, 'delta', 0)) > 0 else 1, 'units')
        except Exception:
            pass

    def _on_panel_configure(self, _e=None):
        """右栏内容尺寸变化 → 更新滚动范围；并让内容 frame 宽度 == canvas 宽度。

        宽度口径很关键：静态图（无滚动条）时 canvas 宽 240 → 内容宽 240，折行位置与改前
        「固定 240px 面板」逐像素一致；出滚动条时 canvas 让出 17px，内容宽 223。
        canvas 未 map 时 winfo_width() 返回 1，必须回落到 cget('width') —— 否则会把内容
        挤成 1px 宽、需求高度爆表（测试大量在 withdraw 的宿主里跑，这条踩了就必炸）。
        """
        try:
            self.panel_canvas.configure(scrollregion=self.panel_canvas.bbox('all'))
        except Exception:
            pass
        try:
            w = int(self.panel_canvas.winfo_width())
            if w <= 1:
                w = int(self.panel_canvas.cget('width'))
            if w > 1 and int(getattr(self, '_panel_w_set', 0)) != w:
                self._panel_w_set = w
                self.panel_canvas.itemconfigure(self._panel_win, width=w)
        except Exception:
            pass

    def _panel_view_h(self):
        """右栏可视高度（px）——「内容有没有被挤出可视区」的直接判据。

        map 之后用 canvas 实际高度；未 map（测试宿主 withdraw / 构造瞬间）时回落到
        _fit_dialog_size 算出的目标值，避免 winfo_height()==1 造成误判。
        """
        try:
            h = int(self.panel_canvas.winfo_height())
            if h > 1:
                return h
        except Exception:
            pass
        try:
            return max(1, int(self._panel_h_target))
        except Exception:
            return 0

    def _fit_dialog_size(self):
        """定窗口尺寸：高 = max(左画布需求, 右栏内容需求)，并对屏幕工作区封顶。

        v2.0-R8 修的是 R6 引入的真 bug（用户第三轮实测第 2 条）：
          改前右栏是固定高（跟左画布 602px），R6 的「▶ 动图预览」区把内容顶到 662px，
          pack 把最下面的「应用 / 重置 / 取消」压成 1px 且不 map —— 量出来 y=-31、h=1、
          ismapped=0，用户根本点不到（静态图 534px 不触发，所以只在动图模式暴露）。
        两条保证：
          1) 装得下 → 窗口按内容加高，整屏可见（动图 618 → 678px，远小于 1080p 工作区）；
          2) 装不下（小屏 / 高 DPI / 以后再加东西）→ 右栏出竖直滚动条 + 窗口不越出工作区，
             滚到底任何控件都可见可点。两条路径都不裁控件。
        """
        try:
            self.root.update_idletasks()
            pad_h = 16                                   # main 的上下 pad(8+8)
            cv_h = int(self.cv.winfo_reqheight())        # 左画布（含 1px 描边）
            cv_w = int(self.cv.winfo_reqwidth())
            panel_w = int(self.panel_wrap.winfo_reqwidth())
            content_h = int(self.panel.winfo_reqheight())  # 右栏内容需求高
            want_h = max(cv_h, content_h) + pad_h
            work_h = int(screen_work_area_height(self.root))
            chrome = int(getattr(self, '_chrome_h', 0) or PREPROCESS_CHROME_H)
            h = min(want_h, max(300, work_h - chrome - 8))
            view_h = max(120, h - pad_h)
            self._panel_h_target = view_h
            need_sb = content_h > view_h
            if need_sb:
                self.panel_sb.pack(side='right', fill='y')
                self.panel_canvas.configure(width=max(140, PREPROCESS_PANEL_W - PREPROCESS_PANEL_SB_W))
            else:
                self.panel_sb.pack_forget()
                self.panel_canvas.configure(width=PREPROCESS_PANEL_W)
            self._panel_w_set = 0            # 宽度变了 → 让 _on_panel_configure 重设内容宽
            self._on_panel_configure()
            self.root.update_idletasks()
            # 宽度：左画布 + 10 间距 + 右栏 + 左右 pad(10+10)（1080p 下 = 912px，与改前一致）
            w = cv_w + 10 + panel_w + 20
            try:
                wat, wab = screen_work_area(self.root)
                scr_w = int(self.root.winfo_screenwidth())
                x = max(0, (scr_w - w) // 2)
                y = wat + max(0, ((wab - wat) - (h + chrome)) // 2)
                self.root.geometry(f'{w}x{h}+{x}+{y}')
            except Exception:
                self.root.geometry(f'{w}x{h}')
            self.root.update_idletasks()
        except Exception as e:
            try:
                _write_log(f'[预处理布局] 尺寸自适应失败: {e}')
            except Exception:
                pass

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
        """透明棋盘格背景（Tk 层画法）。

        R6 起 `_draw` 走「烘进显示图」的快路径（Tk 对混合 alpha 推图极慢，见 _screen_image），
        本方法只在烘焙失败时兜底补画；颜色口径与烘出来的那层一致（PREPROCESS_CHECKER_*）。
        """
        cell = 16
        c = PREPROCESS_CHECKER_LIGHT
        for i in range(int(w // cell) + 1):
            for j in range(int(h // cell) + 1):
                if (i + j) % 2 == 0:
                    cv.create_rectangle(ox + i * cell, oy + j * cell,
                                        ox + min((i + 1) * cell, w),
                                        oy + min((j + 1) * cell, h),
                                        fill=c, outline='')

    def _checker_bg(self, size, cell=16):
        """棋盘格垫底图（按尺寸缓存）：亮格 PREPROCESS_CHECKER_LIGHT、暗格 = 画布底色"""
        key = (int(size[0]), int(size[1]), int(cell))
        hit = self._checker_cache.get(key)
        if hit is not None:
            return hit
        w, h = key[0], key[1]
        bg = self._Image.new('RGB', (w, h), PREPROCESS_CHECKER_BASE)
        light = self._Image.new('RGB', (cell, cell), PREPROCESS_CHECKER_LIGHT)
        for y0 in range(0, h, cell):
            for x0 in range(0, w, cell):
                if (x0 // cell + y0 // cell) % 2 == 0:
                    bg.paste(light, (x0, y0))
        if len(self._checker_cache) > 4:      # 尺寸变了才新键，最多留几份
            self._checker_cache.clear()
        self._checker_cache[key] = bg
        return bg

    def _screen_image(self, frame, s):
        """显示帧 → 推给 Tk 的「成品图」：抠图 → 缩放 → 棋盘格垫底合成 → RGB。

        R6 为什么要烘棋盘格：Tk 的 photo put 对 alpha **不一致**的图走逐像素合成慢路径
        （实测 640×480 混合 alpha = 81~219 ms，而 alpha 全一致只有 2~6 ms）。动图每帧都要
        推图，走慢路径就必然卡；烘成不透明 RGB 后单帧 ≈ 4 ms。视觉与老画法一致：老代码在
        图下垫 Tk 画的同色棋盘格，透明处露出的就是这层。
        """
        disp = frame
        if self.use_key.get() and self.bg_color:
            disp = self._chroma_key(frame, self.bg_color, self.tol_var.get())
        dw = max(1, int(disp.width * s))
        dh = max(1, int(disp.height * s))
        if (dw, dh) != disp.size:
            disp = disp.resize((dw, dh), self._Image.LANCZOS)
        if disp.mode != 'RGBA':
            disp = disp.convert('RGBA')
        try:
            out = self._checker_bg((dw, dh)).copy()
            out.paste(disp, (0, 0), disp)
            return out
        except Exception:
            # 极端兜底：烘不进去就退回老路径（_draw 会补画 Tk 棋盘格 + 直接推 RGBA）
            return disp

    def _draw(self):
        if not getattr(self, '_alive', True):
            return                      # 已销毁：迟到的节拍直接返回，别碰 Tk
        cv = self.cv
        cv.delete('all')
        s, ox, oy = self._fit()
        frame = self._frame_work(self.preview_idx)
        disp_w, disp_h = frame.width * s, frame.height * s

        # 图片（含棋盘格垫底；R6 起棋盘格烘进图里，Tk 层不再重复画）
        shot = self._screen_image(frame, s)
        if shot.mode == 'RGBA':
            self._draw_checker(cv, ox, oy, disp_w, disp_h)   # 兜底：烘焙失败时回到老画法
        self.tk_img = self._ImageTk.PhotoImage(shot, master=self.root)
        self._photo_refs.append(self.tk_img)
        if len(self._photo_refs) > 3:
            _release_photo(self._photo_refs.pop(0))
        cv.create_image(ox, oy, anchor='nw', image=self.tk_img)
        self._update_frame_label()

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

    # ---------- R6：动图预览（按需解码 + 节流播放） ----------
    def _canonical_frame(self, img):
        """帧尺寸归一：**以首帧尺寸为准**（拉伸到首帧画布）。

        为什么定这条策略：
          · 裁剪框只有一个矩形（在 work 坐标系里），若逐帧换尺寸，框会在播放时来回漂、
            用户根本没法"照着某一帧裁剪"；
          · 输出 APNG 也要求所有帧同一画布 —— 尺寸不一的帧会被"顶左贴一块"，等于错位；
          · 实测 PIL 的 GIF/APNG 读入器本身会把局部帧合成到逻辑画布（同格式文件读回每帧尺寸一致），
            所以这条分支正常文件走不到，纯属兜底（第三方写入器 / 未来格式）——归一后坐标与首帧一一对应。
        """
        if img.size != self.orig.size:
            self._size_fixups += 1
            img = img.resize(self.orig.size, self._Image.LANCZOS)
        return img

    def _decode_frame_rgba(self, idx):
        """按需解码**这一帧**：seek → RGBA → 尺寸归一。返回 (img, 毫秒, 该帧时长)。"""
        n = max(1, int(self.n_frames))
        idx = int(idx) % n
        t0 = time.perf_counter()
        try:
            self._src.seek(idx)
        except Exception:
            try:
                self._src.seek(0)
            except Exception:
                pass
        img = self._src.convert('RGBA')
        dur = _frame_duration(self._src)
        img = self._canonical_frame(img)
        self._last_decode_ms = (time.perf_counter() - t0) * 1000.0
        self._decode_calls += 1
        self._frames_ms[idx] = dur
        return img, self._last_decode_ms, dur

    def _frame_work(self, idx):
        """第 idx 帧的 work 尺寸缩略图（LRU 缓存）：命中直接返回；未命中才解码这一帧。

        静态图（n_frames<=1）恒返回 self.work —— 老路径逐像素不变。
        """
        if self.n_frames <= 1:
            return self.work
        idx = int(idx) % self.n_frames
        if idx == 0:
            return self.work                   # 首帧就是静态路径的 work，不为它多存一份
        hit = self._frame_cache.get(idx)
        if hit is not None:
            self._frame_cache.move_to_end(idx)
            return hit
        img, _ms, _dur = self._decode_frame_rgba(idx)
        work = img.resize(self.work.size, self._Image.LANCZOS)   # 与首帧同尺寸 → 裁剪框坐标系一致
        self._frame_cache[idx] = work
        while len(self._frame_cache) > ANIM_PREVIEW_CACHE_MAX:
            self._frame_cache.popitem(last=False)
        return work

    def _frame_delay_ms(self, idx):
        """下一次节拍间隔：≥该帧时长，且不低于「上次解码耗时 × 2」。

        自适应节流的意义：单帧解码越慢，节拍放得越宽 —— 宁可把播放放慢，也不让主线程
        被连续解码塞满（实测单帧增量解码 ~2 ms，所以正常动图不受影响）。
        """
        try:
            dur = int(self._frames_ms.get(int(idx) % max(1, self.n_frames)) or 100)
        except Exception:
            dur = 100
        dur = max(ANIM_MIN_MS, min(ANIM_MAX_MS, dur))
        return int(max(ANIM_MIN_MS, min(ANIM_MAX_MS, max(dur, self._last_decode_ms * 2.0))))

    def _update_frame_label(self):
        if not hasattr(self, 'lbl_frame'):
            return
        try:
            self.lbl_frame.config(text='第 %d / %d 帧' % (self.preview_idx + 1, self.n_frames))
        except Exception:
            pass

    def _schedule_tick(self, ms):
        if not (self._alive and self._playing):
            self._anim_after = None
            return
        try:
            self._anim_after = self.root.after(int(ms), self._preview_tick)
        except Exception:
            self._anim_after = None

    def _preview_tick(self):
        """播放节拍：推进一帧 → 重绘 → 按该帧时长（含自适应节流）重排下一次。

        每 tick 只解一帧（缓存命中则不解）；这是「不卡 UI」的关键 —— 大 GIF 不会一次性全解码。
        """
        self._anim_after = None
        if not (self._alive and self._playing and self.n_frames > 1):
            return
        self.preview_idx = (self.preview_idx + 1) % self.n_frames
        self.preview_steps += 1
        self._draw()
        self._schedule_tick(self._frame_delay_ms(self.preview_idx))

    def _toggle_preview(self):
        """▶ 播放 / ⏸ 暂停（暂停保持当前帧，不清进度）"""
        if self.n_frames <= 1:
            return
        if self._playing:
            self._stop_preview(reset=False)
            return
        self._playing = True
        try:
            self.btn_play.config(text='⏸ 暂停')
        except Exception:
            pass
        self._draw()
        self._schedule_tick(self._frame_delay_ms(self.preview_idx))

    def _preview_step(self, delta):
        """逐帧查看（±1）；手动翻帧时暂停播放，免得跟节拍抢帧"""
        if self.n_frames <= 1:
            return
        self._stop_preview(reset=False)
        self.preview_idx = (self.preview_idx + int(delta)) % self.n_frames
        self._draw()

    def _preview_goto(self, idx):
        """跳到指定帧（0 = 首帧）"""
        if self.n_frames <= 1:
            return
        self._stop_preview(reset=False)
        self.preview_idx = int(idx) % self.n_frames
        self._draw()

    def _stop_preview(self, reset=False):
        """停表：取消 after、复位按钮（销毁/应用/手动翻帧都走这里）"""
        self._playing = False
        if self._anim_after is not None:
            try:
                self.root.after_cancel(self._anim_after)
            except Exception:
                pass
            self._anim_after = None
        try:
            if hasattr(self, 'btn_play'):
                self.btn_play.config(text='▶ 播放')
        except Exception:
            pass
        if reset:
            self.preview_idx = 0

    def _on_destroy(self, event=None):
        """Toplevel 被销毁（含父窗连带销毁）→ 停表 + 标记不再碰 Tk"""
        try:
            if event is not None and getattr(event, 'widget', None) is not self.root:
                return
        except Exception:
            pass
        self._alive = False
        self._stop_preview(reset=False)

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
        # 框外点击：若启用抠图 → 手动指定背景色（R6：取当前显示帧的像素，与眼睛所见一致）
        if self.use_key.get():
            ix, iy = int(x), int(y)
            if 0 <= ix < self.work.width and 0 <= iy < self.work.height:
                src = self._frame_work(self.preview_idx) if self.n_frames > 1 else self.work
                self.bg_color = src.getpixel((ix, iy))[:3]
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
        """（已移出：水平翻转现为向导里的显示期开关，见 ConfigWizard 的「水平翻转」）"""
        return

    # ---------- 抠图 ----------    # ---------- 抠图 ----------
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
        self.crop = (0, 0, self.work.width, self.work.height)
        self.var_ratio.set(0)
        self.lock_ratio = None
        self.tol_var.set(20)
        self.use_key.set(True)
        self._auto_detect_bg()
        self._auto_crop()

    def _frame_transform(self):
        """把当前 UI 状态固化成「单帧变换」函数（裁剪框 / 镜像 / 抠图参数）。

        预览基于缩略图，这里统一映射回原图坐标；动图逐帧复用同一个变换，
        保证每帧处理一致、结果仍是动图。
        """
        x0, y0, x1, y1 = [int(v) for v in self.crop]
        if self.scale < 1.0:
            inv = 1.0 / self.scale
            box = (int(x0 * inv), int(y0 * inv),
                   int(min(self.orig.width, x1 * inv)), int(min(self.orig.height, y1 * inv)))
        else:
            box = (x0, y0, x1, y1)
        flip = False   # 水平翻转已移到外挂配置（显示期），预处理不再烘入
        keying = bool(self.use_key.get() and self.bg_color)
        bg, tol = self.bg_color, self.tol_var.get()

        def _tf(img):
            out = img.crop(box)
            if flip:
                out = out.transpose(self._Image.FLIP_LEFT_RIGHT)
            if keying:
                out = self._chroma_key(out, bg, tol)
            return out
        return _tf

    def _shrink_frame(self, img, limit=1200):
        """动图输出限幅：皮肤最大按 base_height 缩放显示，1200 足够且 APNG 体积可控"""
        longest = max(img.size)
        if longest <= limit:
            return img
        s = limit / float(longest)
        return img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))),
                          self._Image.LANCZOS)

    def _apply(self):
        try:
            x0, y0, x1, y1 = [int(v) for v in self.crop]
            if (x1 - x0) < 2 or (y1 - y0) < 2:
                messagebox.showwarning('提示', '裁剪区域太小！', parent=self.root)
                return
            self._stop_preview(reset=False)    # R6：应用期间不许节拍来抢 self._src 的 seek
            tf = self._frame_transform()
            out_path = os.path.join(HERE, f'preprocessed_{int(time.time() * 1000)}.png')
            if self.n_frames > 1:
                # 动图：逐帧同一变换 → 存 APNG（多帧 + 每帧时长），皮肤保持会动
                idxs = _sample_frame_indices(self.n_frames, ANIM_PREPROCESS_MAX)
                outs, durs = [], []
                try:
                    self.root.config(cursor='watch')
                except Exception:
                    pass
                for k, i in enumerate(idxs):
                    img, _ms, dur = self._decode_frame_rgba(i)
                    durs.append(dur)
                    outs.append(self._shrink_frame(tf(img)))
                    if k % 10 == 0:
                        try:
                            self.lbl_crop.config(text=f'处理中 {k + 1}/{len(idxs)} 帧...')
                            self.root.update_idletasks()
                        except Exception:
                            pass
                outs[0].save(out_path, 'PNG', save_all=True, append_images=outs[1:],
                             duration=durs, loop=0)
            else:
                self._src.seek(0)
                tf(self.orig).save(out_path, 'PNG')
            self.result_path = out_path
            for p in self._photo_refs:
                _release_photo(p)
            self._photo_refs.clear()
            self._alive = False
            self.root.destroy()
        except Exception as e:
            messagebox.showerror('处理失败', str(e), parent=self.root)

    def _cancel(self):
        self.result_path = None
        self._stop_preview(reset=False)
        for p in self._photo_refs:
            _release_photo(p)
        self._photo_refs.clear()
        self._alive = False
        self.root.destroy()


# ============ 配置向导（所见即所得）============
def screen_work_area(root=None):
    """屏幕工作区矩形 (top, bottom)（像素，已排除任务栏）。失败回落 (0, screenheight)。"""
    try:
        import ctypes

        class _RECT(ctypes.Structure):
            _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                        ('right', ctypes.c_long), ('bottom', ctypes.c_long)]

        r = _RECT()
        # SPI_GETWORKAREA = 0x0030
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
            top, bottom = int(r.top), int(r.bottom)
            if bottom - top > 200:
                return top, bottom
    except Exception:
        pass
    try:
        return 0, int(root.winfo_screenheight())
    except Exception:
        return 0, 768


def screen_work_area_height(root=None):
    """屏幕可用工作区高度（像素，已排除任务栏）。

    v2.0-t15：向导要按「用户实际能看见的高度」约束自己 —— 只用 winfo_screenheight()
    会把任务栏那 40~80px 也算进去，导致按钮行正好卡在任务栏底下点不到。
    取不到工作区时回落 winfo_screenheight()，再不行给 768 兜底（绝不抛）。
    """
    top, bottom = screen_work_area(root)
    spi_h = bottom - top
    scr_h = 0
    try:
        if root is not None:
            scr_h = int(root.winfo_screenheight())
    except Exception:
        scr_h = 0
    cands = [h for h in (spi_h, scr_h) if h > 200]
    if not cands:
        return 768
    return min(cands)


def screen_work_area_width(root=None):
    """屏幕可用工作区宽度（像素，已排除停靠栏）。

    v2.0-R4：向导的「⚙ 高级设置」改成横排多列后，列数要按用户实际能用的宽度算
    （1080p = 1920 → 3 列；1366 宽 → 3 列；1024 → 2 列；再窄 → 1 列），
    同时窗口自身宽度也按它封顶，绝不把内容顶出屏幕。取不到就回落屏幕宽度、再兜底 1280。
    """
    try:
        import ctypes

        class _RECT(ctypes.Structure):
            _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                        ('right', ctypes.c_long), ('bottom', ctypes.c_long)]

        r = _RECT()
        # SPI_GETWORKAREA = 0x0030
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
            w = int(r.right) - int(r.left)
            if w > 200:
                return w
    except Exception:
        pass
    try:
        return int(root.winfo_screenwidth())
    except Exception:
        return 1280


class ConfigWizard:
    LAYOUT_INFO = {
        'horizontal_single': ('单行横排', 460, 42),
        'horizontal_double': ('双行横排', 460, 84),
        'vertical': ('竖排', 96, 320),
    }
    CV_W, CV_H = 620, 260     # 预览画布尺寸（调小给窗口减高，绘制逻辑自动等比适配）
    CV_BG = PREVIEW_BG_HEX    # 预览画布底色（v2.0-R7：预览透明区 = 这个色，不再垫棋盘格）

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
        # 动图预览（v1.6）：默认只显示首帧，点「预览动画」才播
        self._anim_n = 0
        self._anim_idx = 0
        self._anim_on = False
        self._anim_after = None
        # R1：进入「增强（真羽化）」模式前的点阵羽化勾选（切回兼容时原样恢复）
        self._feather_prev = None

        self.root = tk.Tk()
        self.root.title(f'Rime 皮肤外挂 {VERSION} - 配置')
        self.root.resizable(False, False)
        self.root.protocol('WM_DELETE_WINDOW', self._on_cancel)
        if self.PIL:
            set_window_icon(self.root, (self._Image, self._ImageTk))
        self._build_ui()

    def _build_ui(self):
        """布局（v2.0-t15 重排）：
          顶部固定区（提示 + ① 图片）
          可滚动主体（② ~ ⑭：左栏普通设置 + 右栏高级设置）← 内容高时在这里滚
          底部固定按钮行（保存并启动 / 取消 / 清理垃圾…）← 永远贴着窗口底、任何分辨率都可见

        重排动机：⑫ 图层区加控件后窗口需求高度 1107px > 1080p 工作区 1040px，
        按钮行被推到屏外（bottom=1128）→ 用户点不到保存。现在按钮行用 side='bottom'
        优先占位，主体塞进 Canvas 按工作区高度封顶，放不下就出滚动条。
        """
        pad = {'padx': 12, 'pady': 4}
        frm = tk.Frame(self.root)
        frm.pack(fill='both', expand=True, **pad)
        # 三行 grid：0=顶部固定 / 1=可滚动主体（吸收所有压缩）/ 2=底部固定按钮行。
        # 用 grid 而不是 pack 的原因：pack 在空间不足时会先把后 pack 的控件挤出可视区
        # （实测按钮行被推到底边外 26~31px），grid 的第 1 行带 weight=1 只会被压缩，
        # 第 0/2 行永远拿满自己的需求高度 → 按钮行在任何分辨率下都在窗内。
        frm.grid_columnconfigure(0, weight=1)
        frm.grid_rowconfigure(1, weight=1)

        # ===== 顶部固定区（不随主体滚动）=====
        self.top_area = tk.Frame(frm)
        self.top_area.grid(row=0, column=0, sticky='ew')

        # 顶部提示（一行，省竖向空间）
        tk.Label(self.top_area,
                 text='支持 PNG/JPG/WEBP/GIF/BMP（动图保持会动）　建议竖版 2:3、≤2000×2000　💡 预处理 = 裁剪 / 纯色背景抠图',
                 fg='#e67e22', font=('Microsoft YaHei', 9), justify='left').pack(anchor='w', pady=(0, 1))
        # 品红冲突提示（动态抠色键）：图片含品红时显示，提示已自动切换
        self.lbl_keyhint = tk.Label(self.top_area, text='', fg='#e67e22', font=('Microsoft YaHei', 9), justify='left')
        self.lbl_keyhint.pack(anchor='w', pady=(0, 2))

        # ① 图片选择（整行）
        row1 = tk.Frame(self.top_area)
        row1.pack(fill='x', pady=3)
        tk.Label(row1, text='① 图片:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.btn_img = tk.Button(row1, text='选择图片...', command=self._pick_image,
                                 font=('Microsoft YaHei', 10))
        self.btn_img.pack(side='left', padx=6)
        self.btn_prep = tk.Button(row1, text='图片预处理', command=self._preprocess_image,
                                  font=('Microsoft YaHei', 10), state='disabled')
        self.btn_prep.pack(side='left', padx=2)
        # 动图预览（按需播放，不点就是静态首帧 —— 不卡 UI）
        self.btn_anim = tk.Button(row1, text='▶ 预览动画', command=self._toggle_anim_preview,
                                  font=('Microsoft YaHei', 10), state='disabled')
        self.btn_anim.pack(side='left', padx=2)
        self.lbl_img = tk.Label(row1, text='未选择', fg='#888', font=('Microsoft YaHei', 9))
        self.lbl_img.pack(side='left')

        # ==== 底部固定按钮行（grid 第 2 行：永远拿满需求高度，不会溢出窗口）====
        self.btn_row = tk.Frame(frm)
        self.btn_row.grid(row=2, column=0, sticky='ew', pady=(6, 0))
        tk.Button(self.btn_row, text='保存并启动', command=self._save_and_start,
                  bg='#4CAF50', fg='white', font=('Microsoft YaHei', 10, 'bold')).pack(side='left', padx=4)
        tk.Button(self.btn_row, text='取消', command=self._on_cancel,
                  font=('Microsoft YaHei', 10)).pack(side='left', padx=4)
        tk.Button(self.btn_row, text='🧹 清理垃圾…', command=self._cleanup_junk,
                  font=('Microsoft YaHei', 10)).pack(side='left', padx=4)
        tk.Label(self.btn_row, text='💡 保存后启动；下次双击可重新配置',
                 fg='#e67e22', font=('Microsoft YaHei', 11, 'bold')).pack(side='right')

        # ==== 可滚动主体（② ~ ⑭；内容高于工作区时在这里滚，顶部与按钮行都不动）====
        # v2.0-R4 重排：主体不再左右分栏，而是「上=设置+预览 / 下=高级设置横排多列」
        #   · 上半块 self.top_block：② 候选框类型 / ④⑤⑥ 滑条 / ⑦ 预览画布
        #   · 下半块 self.adv_area：⚙ 高级设置（⑧~⑭），按工作区宽度分 1~3 列并排
        # 动机（用户原话）：「你不如把高级设置完整放预览框下面横排放置。」
        # 右栏竖排时高级设置需求高 901px 独占窗口高度（左栏只有 390px），横排后最高列
        # 只有 ~315px → 窗口需求高度从 1038 降到 ~840。
        body = self._build_scroll_body(frm)

        # ---- 上半块：② / ④⑤⑥ / ⑦ 预览 ----
        self.top_block = tk.Frame(body)
        self.top_block.pack(fill='x', pady=(2, 0))
        left = self.top_block      # 沿用原变量名：下面 ②~⑦ 的构建代码一行不用改

        # ② 候选框类型（读取 Rime 配置按钮放这一行）
        row3 = tk.Frame(left)
        row3.pack(fill='x', pady=1)
        tk.Label(row3, text='② 候选框类型:', font=('Microsoft YaHei', 10)).pack(side='left')
        self.var_layout = tk.StringVar(master=self.root, value='horizontal_double')
        for text, val in [('单行', 'horizontal_single'),
                          ('双行', 'horizontal_double'),
                          ('竖排', 'vertical')]:
            tk.Radiobutton(row3, text=text, variable=self.var_layout, value=val,
                           font=('Microsoft YaHei', 9),
                           command=self._update_preview).pack(side='left', padx=2)
        tk.Button(row3, text='读取当前Rime配置', command=self._read_rime,
                  font=('Microsoft YaHei', 9)).pack(side='left', padx=8)

        # ③ 贴边方向（v2.0-R11：用户实测「贴边做错了，贴边放回原位，24中间」→ 从 ⑫ 图层区
        # 搬回**通用区原位（② 与 ④ 之间）**，语义同时升级为**统一管所有图层**：
        # 点一次 = 全部图层的 anchor 一起改（图层区不再有「选中层贴哪儿」，界面回到最简）。
        # 顶层 cfg['side'] 仍是主层锚点的权威（resolve_layers / save_layers_into_cfg 口径不变），
        # 统一同步由 _sync_side_to_all_layers() 一处收口 —— R2 修过的「多图层时主层贴边改不动」
        # 的 bug 继续被守护（那条通路现在写的是全部层，含第 0 层）。
        # 这里的两个变量：
        #   · var_side = ③ 的单选值，也是**全部图层** anchor 的 UI 权威；
        #   · var_flip = 当前选中层的水平翻转（图层区勾选框复用同一个变量，与 ④⑤⑥ 同族）。
        row4 = tk.Frame(left)
        row4.pack(fill='x', pady=1)
        tk.Label(row4, text='③ 贴边方向（所有图层统一）:',
                 font=('Microsoft YaHei', 10)).pack(side='left')
        self.var_side = tk.StringVar(master=self.root, value='right')
        for text, val in [('右侧', 'right'), ('左侧', 'left'), ('中间', 'center')]:
            tk.Radiobutton(row4, text=text, variable=self.var_side, value=val,
                           font=('Microsoft YaHei', 9),
                           command=self._on_side_change).pack(side='left', padx=2)
        self.var_flip = tk.BooleanVar(master=self.root, value=False)

        # ④⑤⑥ 缩放 / 水平 / 垂直（合一行，紧凑）
        # v2.0-t15：这三条滑条 = **当前选中图层**的缩放/水平/垂直（图层区不再重复一套），
        # 选中哪层就自动切换到哪层的值（_on_layer_select），拖动即写入该层（_on_main_slider）
        row5 = tk.Frame(left)
        row5.pack(fill='x', pady=1)
        self.lbl_slider_target = tk.Label(row5, text='④ 缩放:', font=('Microsoft YaHei', 10))
        self.lbl_slider_target.pack(side='left')
        self.var_scale = tk.DoubleVar(master=self.root, value=1.0)
        tk.Scale(row5, from_=0.2, to=2.0, resolution=0.1, orient='horizontal',
                 variable=self.var_scale, length=140, sliderlength=13,
                 command=self._on_main_slider,
                 font=('Microsoft YaHei', 8)).pack(side='left', padx=2)
        self.lbl_scale = tk.Label(row5, text='1.0x', fg='#888', font=('Microsoft YaHei', 9),
                                  width=4)
        self.lbl_scale.pack(side='left')
        tk.Label(row5, text='⑤ 水平:', font=('Microsoft YaHei', 10)).pack(side='left', padx=(8, 0))
        self.var_offx = tk.IntVar(master=self.root, value=0)
        tk.Scale(row5, from_=-200, to=200, orient='horizontal',
                 variable=self.var_offx, length=140, sliderlength=13,
                 command=self._on_main_slider,
                 font=('Microsoft YaHei', 8)).pack(side='left', padx=2)
        self.lbl_offx = tk.Label(row5, text='0px', fg='#888', font=('Microsoft YaHei', 9),
                                 width=5)
        self.lbl_offx.pack(side='left')
        tk.Label(row5, text='⑥ 垂直:', font=('Microsoft YaHei', 10)).pack(side='left', padx=(8, 0))
        self.var_offy = tk.IntVar(master=self.root, value=0)
        tk.Scale(row5, from_=-150, to=150, orient='horizontal',
                 variable=self.var_offy, length=140, sliderlength=13,
                 command=self._on_main_slider,
                 font=('Microsoft YaHei', 8)).pack(side='left', padx=2)
        self.lbl_offy = tk.Label(row5, text='0px', fg='#888', font=('Microsoft YaHei', 9),
                                 width=5)
        self.lbl_offy.pack(side='left')
        self.lbl_slider_hint = tk.Label(left, text='', fg='#888',
                                        font=('Microsoft YaHei', 8), justify='left')
        self.lbl_slider_hint.pack(anchor='w')

        # ⑦ 预览区（候选框 + 图片 组合）
        tk.Label(left, text='⑦ 预览（候选框 + 图片组合样式）:', font=('Microsoft YaHei', 9),
                 fg='#555').pack(anchor='w', pady=(2, 0))
        self.canvas = tk.Canvas(left, width=self.CV_W, height=self.CV_H, bg=self.CV_BG,
                                highlightthickness=1, highlightbackground='#ccc')
        self.canvas.pack(pady=2)

        # ==== 下半块：⚙ 高级设置（R4：横排多列，按编号找）====
        cols, col_of = self._adv_columns(body)

        # ⑧ 图层（图片相对候选框层级；below 仅重叠居中可见）
        adv = cols[col_of['layer']]
        tk.Label(adv, text='⑧ 图层:', font=('Microsoft YaHei', 10)).pack(anchor='w')
        row_layer = tk.Frame(adv)
        row_layer.pack(anchor='w', pady=(0, 2))
        self.var_layer = tk.StringVar(master=self.root, value='above')
        for text, val in [('候选框上方', 'above'), ('候选框下方', 'below')]:
            tk.Radiobutton(row_layer, text=text, variable=self.var_layer, value=val,
                           font=('Microsoft YaHei', 9),
                           command=self._update_preview).pack(side='left', padx=2)
        self.lbl_layer_hint = tk.Label(adv, text='', fg='#888', font=('Microsoft YaHei', 8),
                                       justify='left', wraplength=300)
        self.lbl_layer_hint.pack(anchor='w', pady=(0, 4))

        # ⑨ 特效（显示期：圆角；只影响外挂显示，不改图片文件）
        adv = cols[col_of['fx']]
        tk.Label(adv, text='⑨ 特效（只影响显示）:', font=('Microsoft YaHei', 10)).pack(anchor='w')
        row_fx = tk.Frame(adv)
        row_fx.pack(anchor='w', pady=(0, 4))
        self.var_corner = tk.BooleanVar(master=self.root, value=False)
        tk.Checkbutton(row_fx, text='圆角', variable=self.var_corner,
                       font=('Microsoft YaHei', 9),
                       command=self._update_preview).pack(side='left')
        self.var_corner_r = tk.IntVar(master=self.root, value=24)
        tk.Scale(row_fx, from_=0, to=120, orient='horizontal', variable=self.var_corner_r,
                 length=110, command=lambda _: self._update_preview(),
                 font=('Microsoft YaHei', 8)).pack(side='left', padx=2)

        # ⑩ 点阵羽化（用 4×4 有序抖动把边缘 alpha 近似成渐变）+ R1「增强（真羽化）」开关
        adv = cols[col_of['feather']]
        tk.Label(adv, text='⑩ 点阵羽化:', font=('Microsoft YaHei', 10)).pack(anchor='w')
        row_fe = tk.Frame(adv)
        row_fe.pack(anchor='w')
        self.var_feather = tk.BooleanVar(master=self.root, value=False)
        self.chk_feather = tk.Checkbutton(row_fe, text='启用', variable=self.var_feather,
                                          font=('Microsoft YaHei', 9),
                                          command=self._update_preview)
        self.chk_feather.pack(side='left')
        self.var_feather_r = tk.IntVar(master=self.root, value=24)
        self.scl_feather = tk.Scale(row_fe, from_=0, to=80, orient='horizontal',
                                    variable=self.var_feather_r,
                                    length=110, command=lambda _: self._update_preview(),
                                    font=('Microsoft YaHei', 8))
        self.scl_feather.pack(side='left', padx=2)
        # v2.0-R1：真 alpha 以前只做在 ⑪ 单选里，用户要的是「放后面的开关」→ 加在 ⑩ 后面。
        # v2.0-R10：⑪ 单选已删（用户实测「有增强按钮后渲染模式部分就可以取了」），
        # 本开关成为**唯一入口**；内部状态与提示文案都收口到 _update_render_hint()。
        self.var_alpha_feather = tk.BooleanVar(master=self.root, value=False)
        self.chk_alpha_feather = tk.Checkbutton(
            row_fe, text='增强（真羽化）', variable=self.var_alpha_feather,
            font=('Microsoft YaHei', 9), command=self._on_alpha_feather_toggle)
        self.chk_alpha_feather.pack(side='left', padx=(8, 0))
        self.lbl_feather_hint = tk.Label(
            adv, text='带宽 px；点阵羽化是兼容模式下的近似（远看半透明，近看有细点阵）',
            fg='#888', font=('Microsoft YaHei', 8))
        self.lbl_feather_hint.pack(anchor='w', pady=(0, 4))

        # 渲染模式（v2.0-① → v2.0-R10 收口）：兼容 = v1.6 老路径；增强 = 真 alpha 分层窗（真·半透明）。
        # R10：删掉 ⑪「渲染模式」单选组（Label + Radiobutton + 排版），入口只剩 ⑩ 旁那个开关；
        # var_render 保留为**内部状态**（由该开关驱动、供 cfg['render_mode'] 读写），
        # _update_render_hint 仍是唯一收口：开关 → 提示文案 + 预览重绘，回显时同步给开关。
        _cur_render = resolve_render_mode(self.cfg)
        if self.overlay is not None:      # 打开向导时回显当前模式，避免一保存就被打回兼容
            _cur_render = resolve_render_mode({'render_mode':
                                               getattr(self.overlay, 'render_mode', _cur_render)})
        self.var_render = tk.StringVar(master=self.root, value=_cur_render)
        self.lbl_render_hint = tk.Label(adv, text='', fg='#888', font=('Microsoft YaHei', 8),
                                        justify='left', wraplength=320)
        self.lbl_render_hint.pack(anchor='w', pady=(0, 4))
        self._update_render_hint()

        # ⑫ 图层（v2.0-② 套层皮肤）：一个皮肤 = 多个图片图层，各层可锚到候选框左/右/中间
        adv = cols[col_of['lay']]
        lay_box = tk.LabelFrame(adv, text='🧩 ⑫ 图层（可叠多张）',
                                font=('Microsoft YaHei', 9), fg='#555', padx=6, pady=4)
        lay_box.pack(fill='x', pady=(4, 0))
        self.layer_list = tk.Listbox(lay_box, height=4, width=27,
                                     font=('Microsoft YaHei', 9), exportselection=False)
        self.layer_list.pack(anchor='w')
        self.layer_list.bind('<<ListboxSelect>>', lambda _e: self._on_layer_select())
        lay_btns = tk.Frame(lay_box)
        lay_btns.pack(anchor='w', pady=(2, 2))
        self.btn_layer_add = tk.Button(lay_btns, text='➕ 加一张图', command=self._layer_add,
                                       font=('Microsoft YaHei', 9))
        self.btn_layer_add.pack(side='left', padx=(0, 2))
        self.btn_layer_del = tk.Button(lay_btns, text='🗑 删这层', command=self._layer_delete,
                                       font=('Microsoft YaHei', 9))
        self.btn_layer_del.pack(side='left', padx=(0, 2))
        tk.Button(lay_btns, text='↑ 上移', command=lambda: self._layer_move(-1),
                  font=('Microsoft YaHei', 8)).pack(side='left', padx=(0, 2))
        tk.Button(lay_btns, text='↓ 下移', command=lambda: self._layer_move(1),
                  font=('Microsoft YaHei', 8)).pack(side='left')

        # ③ 贴边方向（v2.0-R11）：已搬回通用区（② 与 ④ 之间）并统一管所有图层 ——
        # 这里只留一行小字说明 + 「当前选中层」的水平翻转（与 ④⑤⑥ 同族：选中哪层调哪层）。
        # var_layer_anchor 自 R11 起不再绑任何单选按钮，保留为**当前选中层 anchor 的回显镜像**
        # （切层时更新；既有回归脚本按它核对「切层回显」）。
        self.lbl_side_target = tk.Label(lay_box, text='', fg='#555',
                                        font=('Microsoft YaHei', 9), justify='left',
                                        wraplength=300)
        self.lbl_side_target.pack(anchor='w')
        row_la = tk.Frame(lay_box)
        row_la.pack(anchor='w', pady=(2, 0))
        self.var_layer_anchor = tk.StringVar(master=self.root, value='right_edge')
        tk.Checkbutton(row_la, text='水平翻转（当前层）', variable=self.var_flip,
                       font=('Microsoft YaHei', 8),
                       command=self._on_layer_flip).pack(side='left')
        # v2.0-t15：缩放/水平/垂直 不再在本区重复一套 —— 复用上方 ④⑤⑥（选中哪层就调哪层）
        tk.Label(lay_box, text='↖ 这一层的大小/位置用上方 ④缩放 ⑤水平 ⑥垂直 调',
                 fg='#888', font=('Microsoft YaHei', 8)).pack(anchor='w', pady=(1, 0))
        row_lr = tk.Frame(lay_box)
        row_lr.pack(anchor='w', pady=(1, 0))
        self.var_lay_follow = tk.BooleanVar(master=self.root, value=False)
        tk.Checkbutton(row_lr, text='随候选框变宽往外让', variable=self.var_lay_follow,
                       font=('Microsoft YaHei', 8),
                       command=self._on_layer_param_change).pack(side='left')
        self.var_lay_follow_r = tk.IntVar(master=self.root, value=30)
        tk.Scale(row_lr, from_=0, to=60, orient='horizontal', length=70, sliderlength=12,
                 variable=self.var_lay_follow_r,
                 command=lambda _v: self._on_layer_param_change(),
                 font=('Microsoft YaHei', 8)).pack(side='left')
        tk.Label(row_lr, text='%', font=('Microsoft YaHei', 8)).pack(side='left')
        self.lbl_layer_hint2 = tk.Label(lay_box, text='', fg='#888',
                                        font=('Microsoft YaHei', 8), justify='left',
                                        wraplength=300)
        self.lbl_layer_hint2.pack(anchor='w', pady=(2, 0))
        self._update_side_hint()
        self._layer_sync_from_cfg()

        # ⑬ 皮肤管理（图片 + 全套参数整套切换）
        adv = cols[col_of['skin']]
        skin_box = tk.LabelFrame(adv, text='💾 ⑬ 皮肤管理',
                                 font=('Microsoft YaHei', 9), fg='#555', padx=6, pady=4)
        skin_box.pack(fill='x', pady=(2, 0))
        self.skin_var = tk.StringVar(master=self.root)
        self.skin_cb = ttk.Combobox(skin_box, textvariable=self.skin_var, state='readonly',
                                    width=16, font=('Microsoft YaHei', 9))
        self.skin_cb.pack(anchor='w')
        # 选中即应用：预览 + 立即切换到运行中的外挂（若有）
        self.skin_cb.bind('<<ComboboxSelected>>', lambda _e: self._apply_skin_to_wizard())
        skin_btns = tk.Frame(skin_box)
        skin_btns.pack(anchor='w', pady=(2, 0))
        tk.Button(skin_btns, text='💾 存为皮肤', command=self._save_as_skin,
                  font=('Microsoft YaHei', 9)).pack(side='left', padx=(0, 2))
        tk.Button(skin_btns, text='🗑 删除', command=self._delete_skin,
                  font=('Microsoft YaHei', 9)).pack(side='left')
        # ③ 候选框配色：从当前图片（含动图所有帧）提色 → 生成 21 字段配色 → 注入 + 重部署
        scheme_row = tk.Frame(skin_box)
        scheme_row.pack(anchor='w', pady=(3, 0))
        self.btn_scheme = tk.Button(scheme_row, text='🎨 生成候选框配色…',
                                    command=self._generate_scheme,
                                    font=('Microsoft YaHei', 9))
        self.btn_scheme.pack(side='left')
        self.btn_scheme_restore = tk.Button(scheme_row, text='↩ 还原配色备份',
                                            command=self._restore_scheme_backup,
                                            font=('Microsoft YaHei', 9))
        self.btn_scheme_restore.pack(side='left', padx=(6, 0))
        self.lbl_skin_hint = tk.Label(skin_box, text='选中即应用，可整套切换',
                                      fg='#999', font=('Microsoft YaHei', 8))
        self.lbl_skin_hint.pack(anchor='w', pady=(2, 0))
        self.lbl_scheme_hint = tk.Label(skin_box, text='配色：未生成（生成时先存皮肤名）',
                                        fg='#999', font=('Microsoft YaHei', 8),
                                        justify='left', wraplength=300)
        self.lbl_scheme_hint.pack(anchor='w', pady=(2, 0))
        self._refresh_skin_list()

        # ⑭ 开机自启（真相 = 启动文件夹快捷方式，勾选态直接读实际状态）
        adv = cols[col_of['start']]
        row_start = tk.Frame(adv)
        row_start.pack(anchor='w', pady=(6, 0))
        self.var_autostart = tk.BooleanVar(master=self.root, value=autostart_installed())
        tk.Checkbutton(row_start, text='⑭ 开机自启（静默到托盘）',
                       variable=self.var_autostart,
                       font=('Microsoft YaHei', 10)).pack(side='left')
        self.lbl_autostart = tk.Label(adv, text='', fg='#888', font=('Microsoft YaHei', 8))
        self.lbl_autostart.pack(anchor='w', pady=(0, 2))

        # 收尾：按屏幕工作区给滚动区定高（内容放得下 = 不滚、观感不变；放不下 = 出滚动条）
        self._fit_window_height()

    # ---------- v2.0-R4 布局：高级设置横排多列 ----------
    def _adv_column_count(self):
        """「⚙ 高级设置」列数：按工作区宽度自适应（每列约 380px，最多 3 列，最少 1 列）。

        除数取 380 而不是先写的 330：⑩/⑪ 那张卡实测最宽 385px，列宽要按最宽卡算，
        窄屏才不会把内容顶出窗口。实测：1080p（1920）→ 3 列；1366 → 3；1024 → 2；
        900 → 2；800 → 1（此时窗口宽度改由 640px 的预览块决定）。
        """
        try:
            w = int(screen_work_area_width(self.root))
        except Exception:
            w = 0
        if w <= 0:
            w = 1280
        return max(1, min(3, (w - 60) // 380))

    def _adv_columns(self, body):
        """建「⚙ 高级设置」的横排多列骨架，返回 (列 Frame 列表, 卡片→列 映射)。

        卡片→列用一张手工平衡表（各卡片实测高度：⑫≈315 / ⑩⑪≈190 / ⑬≈170 /
        ⑧≈80 / ⑨≈72 / ⑭≈56）：
          · 3 列 → 列高 ≈ [315, 270, 298]，最高列只有 315（原来是整列竖排 901）
          · 2 列 → 列高 ≈ [440, 443]，仍然平衡
          · 1 列 → 退化成原来的自然竖排顺序
        这就是「窗口显著变小」的主要来源；预览块宽度不受影响。

        v2.0-R12：整块再做成**可折叠** —— 用户原话「"高级设置"那个位置是否可做成折叠按钮，
        点一下弹出/折叠」。外层由 LabelFrame 换成普通 Frame：
          · self.btn_adv_toggle = 可点的标题（文案带 ▾/▸，点一下展开/折叠）
          · self.adv_body       = 内容区（各列都在它下面），折叠时 pack_forget
        折叠后由 _fit_window_height() 重算：窗口跟着变矮、滚动条按需收回。列骨架
        (adv_cols / _adv_col_of) 与展开态完全一致，折叠只是「不 pack 内容区」。
        """
        n = int(self._adv_column_count())
        self.adv_area = tk.Frame(body)
        self.adv_area.pack(fill='x', pady=(8, 0))
        head = tk.Frame(self.adv_area)
        head.pack(fill='x')
        self.btn_adv_toggle = tk.Button(head, text='', font=('Microsoft YaHei', 9),
                                        anchor='w', relief='flat', bd=0, fg='#555',
                                        activeforeground='#000', cursor='hand2',
                                        command=self._toggle_adv_collapse)
        self.btn_adv_toggle.pack(side='left')
        self.lbl_adv_hint = tk.Label(head, text='（折叠只是收起来，设置不会丢）',
                                     fg='#999', font=('Microsoft YaHei', 8))
        self.lbl_adv_hint.pack(side='left', padx=(6, 0))
        self.adv_body = tk.Frame(self.adv_area, padx=8, pady=6)
        self.adv_body.pack(fill='x')
        cols = []
        for c in range(n):
            f = tk.Frame(self.adv_body)
            f.grid(row=0, column=c, sticky='nw', padx=(0, 12))
            cols.append(f)
        self.adv_cols = cols
        if n >= 3:
            col_of = {'lay': 0, 'feather': 1, 'layer': 1,
                      'skin': 2, 'fx': 2, 'start': 2}
        else:
            col_of = {k: i % n for i, k in enumerate(
                ('layer', 'fx', 'feather', 'lay', 'skin', 'start'))}
        col_of = {k: max(0, min(v, n - 1)) for k, v in col_of.items()}
        self._adv_col_of = col_of
        self._adv_collapsed = False
        self._apply_adv_collapsed()       # 初态 = 展开（标题行/内容区与状态一致）
        return cols, col_of

    # ---------- v2.0-R12 布局：⚙ 高级设置可折叠 ----------
    def _toggle_adv_collapse(self, collapse=None):
        """点标题 = 展开/折叠「⚙ 高级设置」（R12）。

        参数 collapse 可显式指定目标态（None = 取反，按钮 command 走这条）；
        传给测试/程序化调用 True/False。切完必须重算窗口高度：折叠后内容需求变矮
        → 窗口跟着收、滚动条按需收回（_scroll_needed 由 _fit_window_height 重算）。
        """
        if collapse is None:
            collapse = not bool(getattr(self, '_adv_collapsed', False))
        self._adv_collapsed = bool(collapse)
        self._apply_adv_collapsed()
        self._fit_window_height()

    def _apply_adv_collapsed(self):
        """把当前折叠状态落到控件上（单独抽出的执行点：只做「收起/放回 + 文案」）。

        折叠 = adv_body.pack_forget()（不 pack 的控件不参与父容器需求高度计算 →
        窗口需求高度立刻变小）；展开 = 重新 pack 回标题行下面。幂等，可反复切。
        """
        collapsed = bool(getattr(self, '_adv_collapsed', False))
        try:
            if collapsed:
                self.adv_body.pack_forget()
            elif self.adv_body.winfo_manager() != 'pack':
                self.adv_body.pack(fill='x')
        except Exception:
            pass
        try:
            self.btn_adv_toggle.config(
                text=('▸ ⚙ 高级设置（⑧~⑭，点这里展开）' if collapsed
                      else '▾ ⚙ 高级设置（⑧~⑭ 横排多列，点这里折叠）'))
        except Exception:
            pass

    # ---------- v2.0-t15 布局：可滚动主体 ----------
    def _build_scroll_body(self, parent):
        """把 ② ~ ⑭ 装进 Canvas + Scrollbar 的可滚动容器（grid 第 1 行），返回内容 frame。

        要点：Canvas 不设固定宽度 —— 宽度跟随内容（保证 ≥1080p 下窗口宽度与观感不变）；
        高度先设成内容高度让窗口拿到正确需求，窗口放不下时由 _fit_window_height 封顶，
        多出来的内容由 grid 压缩这一行 → 出滚动条。顶部区与按钮行在这个容器外面，
        所以它们不随内容滚动。
        """
        self.body_wrap = tk.Frame(parent)
        self.body_wrap.grid(row=1, column=0, sticky='nsew')
        self.body_canvas = tk.Canvas(self.body_wrap, highlightthickness=0, bd=0,
                                     bg=self.root.cget('bg'))
        self.body_scrollbar = tk.Scrollbar(self.body_wrap, orient='vertical',
                                           command=self.body_canvas.yview)
        self.body_canvas.configure(yscrollcommand=self.body_scrollbar.set)
        self.body_canvas.pack(side='left', fill='both', expand=True)
        inner = tk.Frame(self.body_canvas)
        self.body_inner = inner
        self._body_win = self.body_canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>', self._on_body_configure)
        self.body_canvas.bind('<Configure>', self._on_body_configure)
        # 滚轮：canvas 与内容区各绑一次，再挂一个全局兜底（子控件上的滚轮也能滚）
        for w in (self.body_canvas, inner):
            w.bind('<MouseWheel>', self._on_body_wheel)
        try:
            self.root.bind_all('<MouseWheel>', self._on_body_wheel, add='+')
        except Exception:
            pass
        self._scroll_needed = False
        return inner

    def _on_body_configure(self, _e=None):
        """内容尺寸变化 → 更新滚动范围；同时让 Canvas 宽度跟随内容（窗口宽度不被 Canvas 定死）"""
        try:
            self.body_canvas.configure(scrollregion=self.body_canvas.bbox('all'))
        except Exception:
            pass
        try:
            want = int(self.body_inner.winfo_reqwidth())
            if want > 0 and int(self.body_canvas.cget('width')) != want:
                self.body_canvas.configure(width=want)
        except Exception:
            pass

    def _body_scroll_height(self):
        """当前内容需求高度（用于判断要不要滚动条）"""
        try:
            return int(self.body_inner.winfo_reqheight())
        except Exception:
            return 0

    def _fit_window_height(self):
        """按屏幕工作区给窗口封顶：按钮行永远在可视区内，多出来的内容交给滚动条。

        布局是 grid 三行（顶固定 / 主体 weight=1 / 底固定），所以这里只做三件事：
          1) 让 canvas 先撑到内容高度 → 窗口拿到「完整内容」的需求高度；
          2) 需求高度超过工作区就按工作区封顶（此时主体行被 grid 压缩 → 出滚动条）；
          3) 显式定位到工作区内（Tk 首次 map 会居中，可能把底边放到任务栏下）。
        踩过并已修的坑：一开始用 pack(side='bottom') 让按钮行贴底，空间不足时 Tk 会把
        后 pack 的主体挤出可视区（实测按钮行跑到窗口外 26~31px）—— grid 的固定行不会。
        """
        try:
            self.root.update_idletasks()
            cv = self.body_canvas
            work_h = int(screen_work_area_height(self.root))
            content_h = self._body_scroll_height()

            cv.configure(height=max(200, content_h))       # 先按完整内容要高度
            self.root.update_idletasks()
            need_h = int(self.root.winfo_reqheight())
            w = int(self.root.winfo_reqwidth())
            # v2.0-R4：宽度也按工作区封顶（横排多列后内容可能比屏幕宽 → 绝不顶出屏）
            try:
                w = min(w, max(600, int(screen_work_area_width(self.root)) - 20))
            except Exception:
                pass

            self._scroll_needed = need_h > work_h
            if self._scroll_needed:
                self.body_scrollbar.pack(side='right', fill='y')
            else:
                self.body_scrollbar.pack_forget()
                try:
                    cv.yview_moveto(0)
                except Exception:
                    pass
            self.root.update_idletasks()

            h = min(need_h, max(240, work_h - self._frame_extra()))
            try:
                wt, wb = screen_work_area(self.root)
                scr_w = int(self.root.winfo_screenwidth())
                x = max(0, (scr_w - w) // 2)
                y = wt + max(0, ((wb - wt) - (h + self._frame_extra())) // 2)
                self.root.geometry(f'{w}x{h}+{x}+{y}')
            except Exception:
                pass
            self.root.update_idletasks()
            # 标题栏高度只有窗口 map 之后才量得准 → 再校正一次（只做一次，防递归）
            if not getattr(self, '_fit_refined', False):
                self._fit_refined = True
                try:
                    self.root.after_idle(self._fit_window_height)
                except Exception:
                    pass
        except Exception as e:
            try:
                _write_log(f'[向导布局] 高度封顶失败: {e}')
            except Exception:
                pass

    def _frame_extra(self):
        """窗口外框比客户区多出来的高度（标题栏等）。

        Windows 上 Tk 的 winfo_rooty() 含标题栏而 winfo_height() 只算客户区 —— 实测差
        31px，不把它算进预算窗口底边就会压到任务栏下面（按钮行看得见却点不到）。
        窗口还没 map 时量不到，先用 60px 的保守值，map 后由 _fit_window_height 的
        二次校正换成实测值。
        """
        try:
            r = int(self.root.winfo_rooty()) - int(self.root.winfo_y())
            if r > 0:
                return r
        except Exception:
            pass
        return 60

    def _on_body_wheel(self, event):
        """鼠标滚轮滚主体区（指针在滚动区内才响应，避免干扰其它区域）"""
        try:
            cv = self.body_canvas
            if not self._pointer_in_scroll(event):
                return
            delta = getattr(event, 'delta', 0) or 0
            if not delta:
                return
            step = int(-delta / 120) or (-1 if delta > 0 else 1)
            cv.yview_scroll(step, 'units')
        except Exception:
            pass

    def _pointer_in_scroll(self, event):
        """滚轮事件是否落在滚动区内。

        优先看事件源控件（bind_all 时 event.widget 就是鼠标下那个控件）—— 直接比对它是否
        属于滚动区子树；x_root/y_root 只在真实鼠标事件里才可靠（event_generate 造的事件
        里它们是 0），所以放在后面做兜底。
        """
        try:
            cv = self.body_canvas
            w = getattr(event, 'widget', None)
            if w is not None:
                sw = str(w)
                if sw == str(cv) or sw.startswith(str(self.body_inner)) \
                        or sw.startswith(str(self.body_wrap)):
                    return True
        except Exception:
            pass
        try:
            cv = self.body_canvas
            x = getattr(event, 'x_root', None)
            y = getattr(event, 'y_root', None)
            if not x or not y:
                return False
            return (cv.winfo_rootx() <= x <= cv.winfo_rootx() + cv.winfo_width()
                    and cv.winfo_rooty() <= y <= cv.winfo_rooty() + cv.winfo_height())
        except Exception:
            return False

    def _on_main_slider(self, *_a):
        """④缩放 / ⑤水平 / ⑥垂直 滑条 = **当前选中图层**的参数（v2.0-t15）。

        写入规则与 F-V3 的单一权威一致：第 0 层（主图）写顶层兼容字段、层内 offset 归零；
        其余层写各自 layers[i]。
        """
        if getattr(self, '_layer_loading', False):
            return
        try:
            if hasattr(self, 'lbl_scale'):
                self.lbl_scale.config(text=f'{float(self.var_scale.get()):.1f}x')
            if hasattr(self, 'lbl_offx'):
                self.lbl_offx.config(text=f'{int(self.var_offx.get())}px')
            if hasattr(self, 'lbl_offy'):
                self.lbl_offy.config(text=f'{int(self.var_offy.get())}px')
        except Exception:
            pass
        try:
            i = self._cur_layer_index()
            self._layer_set_params(i, scale=float(self.var_scale.get()),
                                   offset_x=int(self.var_offx.get()),
                                   offset_y=int(self.var_offy.get()))
        except Exception:
            pass
        self._update_preview()

    def _on_layer_flip(self):
        """水平翻转：翻转勾选框与上方 ④⑤⑥ 同族 —— 勾一下就写进**当前选中图层**"""
        if getattr(self, '_layer_loading', False):
            return
        try:
            i = self._cur_layer_index()
            self._layer_set_params(i, flip=bool(self.var_flip.get()))
        except Exception:
            pass
        self._update_preview()

    def _sync_side_to_all_layers(self, force=False):
        """③ 贴边方向的统一同步（v2.0-R11：③ 一处驱动**全部图层**的 anchor）。

        语义：通用区 ③（UI 镜像 var_side）是全部图层锚点的唯一权威 —— 点一次 =
        cfg['side'] 与 layers[*].anchor 一起改，图层列表文案与预览随之刷新。
        顶层 cfg['side'] 仍是主层锚点的权威（resolve_layers / save_layers_into_cfg 口径不变）。

        什么时候推给所有层（而不是只保底主层）：
          · force=True：保存 / 存皮肤 / 切皮肤 / 点 ③ 这些**显式动作**，必须保证各层一致；
          · ③ 的值与 cfg['side'] 不一致：说明用户刚改了 ③（Tk 的 Radiobutton 先改变量、
            再调 command，所以进到这里时已是「改过」状态）→ 推给所有层；
          · 其余情况（打开向导 / 切层 / 普通重绘）只做**主层保底归一** —— 不静默改写老档案里
            其它层的历史 anchor（R2 时代的多层档案仍能原样读出来看）。
        返回值 = 本轮是否做了「全部层」同步（测试用来验判别力）。

        与 R2 的关系：R2 修过的 bug（多图层时主层贴边改不动：旧入口只刷预览、既不写
        cfg['side'] 也不写 layers[0].anchor）在本方法里继续成立 —— 主层永远跟着 ③ 走，
        只不过现在其余层也一起走；调用点仍是预览前 / 保存前两个通路（R2 同款）。
        """
        try:
            layers = self._layers()
            if not layers:
                return False
            side = None
            w = getattr(self, 'var_side', None)
            if w is not None:
                v = str(w.get() or '')
                if v in ('left', 'right', 'center'):
                    side = v
            if side is None:
                side = self.cfg.get('side')
            if side not in ('left', 'right', 'center'):
                side = 'right'
            anc = anchor_from_side(side)
            spread = bool(force) or (self.cfg.get('side') != side)
            self.cfg['side'] = side
            if spread:
                for i, ld in enumerate(layers):
                    if ld.get('anchor') != anc:
                        ld['anchor'] = anc
                        self._refresh_layer_row(i)
            elif layers[0].get('anchor') != anc:
                layers[0]['anchor'] = anc
                self._refresh_layer_row(0)
            self._mirror_layer_anchor(layers)
            return spread
        except Exception:
            return False

    def _sync_side_to_layer0(self):
        """R2 兼容名：③ 的「预览前归一」入口（v2.0-R11 起实现搬进 _sync_side_to_all_layers）。

        保留这个名字是因为 R2 起的两个调用点（_update_preview_impl 与保存前）按它写；
        非 force 调用 = 「用户改了 ③ 才推全部层，否则只保底主层」的原行为。
        """
        return self._sync_side_to_all_layers()

    def _on_side_change(self):
        """③ 贴边方向（通用区）的单选 command：一次改动驱动**全部图层**的 anchor。

        v2.0-R11：用户实测「贴边做错了，贴边放回原位，24中间」→ 控件回通用区、语义统一。
        force=True 表示「点一下 = 所有层都改」（不依赖 var_side 与 cfg['side'] 的差集判断，
        点同值也算一次显式动作，代价只是重刷列表文案）。
        """
        self._sync_side_to_all_layers(force=True)
        self._update_preview()

    def _mirror_layer_anchor(self, layers=None):
        """刷新图层区的「当前层锚点镜像」（var_layer_anchor）与统一说明行。

        v2.0-R11：var_layer_anchor 不再绑单选按钮（贴边方向已收归通用区 ③ 统一），
        它保留为**当前选中层 anchor 的回显镜像** —— 既有回归脚本按它核对「切层回显」。
        """
        try:
            layers = layers if layers is not None else self._layers()
            i = int(getattr(self, '_layer_sel', 0) or 0)
            if not (0 <= i < len(layers)):
                i = 0
            cur = str(layers[i].get('anchor') or 'right_edge') if layers else 'right_edge'
            if str(self.var_layer_anchor.get()) != cur:
                self.var_layer_anchor.set(cur)
        except Exception:
            pass
        self._update_side_hint()

    def _update_side_hint(self):
        """图层区那行小字：讲清「贴边方向由通用区 ③ 统一管所有图层」并回显当前统一值"""
        try:
            side = 'right'
            w = getattr(self, 'var_side', None)
            if w is not None:
                v = str(w.get() or '')
                if v in ('left', 'right', 'center'):
                    side = v
            word = {'left': '贴左', 'right': '贴右', 'center': '居中'}.get(side, '贴右')
            self.lbl_side_target.config(
                text=f'③ 贴边方向统一 = {word}（在通用区改）')
        except Exception:
            pass

    def _refresh_layer_row(self, i):
        """按当前 cfg 重画第 i 行的列表文案（贴哪边 / 文件名会变），选中项保持不变。"""
        try:
            i = int(i)
            layers = self._layers()
            if not (0 <= i < len(layers)) or self.layer_list.size() <= i:
                return
            txt = self._layer_label(i, layers[i])
            if self.layer_list.get(i) == txt:
                return
            sel = [int(x) for x in self.layer_list.curselection()]
            self.layer_list.delete(i)
            self.layer_list.insert(i, txt)
            self.layer_list.selection_clear(0, 'end')
            for s in sel:
                self.layer_list.selection_set(s)
        except Exception:
            pass

    def _layer_get_params(self, i):
        """取第 i 层的 (scale, offset_x, offset_y, flip) —— 第 0 层以顶层兼容字段为权威"""
        try:
            layers = self._layers()
            if not layers:
                return 1.0, 0, 0, False
            i = max(0, min(int(i), len(layers) - 1))
            if i == 0:
                return (round(float(self.cfg.get('scale', 1.0) or 1.0), 2),
                        int(self.cfg.get('offset_x', 0) or 0),
                        int(self.cfg.get('offset_y', 0) or 0),
                        bool(self.cfg.get('flip_h', False)))
            ld = layers[i]
            return (round(float(ld.get('scale', 1.0) or 1.0), 2),
                    int(ld.get('offset_x', 0) or 0),
                    int(ld.get('offset_y', 0) or 0),
                    bool(ld.get('flip', False)))
        except Exception:
            return 1.0, 0, 0, False

    def _layer_set_params(self, i, scale=None, offset_x=None, offset_y=None, flip=None):
        """把参数写进第 i 层。第 0 层写顶层兼容字段（层内 offset 归零，防 F-V3 双计）。"""
        layers = self._layers()
        if not layers:
            return False
        i = max(0, min(int(i), len(layers) - 1))
        ld = layers[i]
        if i == 0:
            if scale is not None:
                self.cfg['scale'] = round(float(scale), 2)
                ld['scale'] = self.cfg['scale']
            if offset_x is not None:
                self.cfg['offset_x'] = int(offset_x)
                ld['offset_x'] = 0
            if offset_y is not None:
                self.cfg['offset_y'] = int(offset_y)
                ld['offset_y'] = 0
            if flip is not None:
                self.cfg['flip_h'] = bool(flip)
                ld['flip'] = bool(flip)
        else:
            if scale is not None:
                ld['scale'] = round(min(2.0, max(0.2, float(scale))), 2)
            if offset_x is not None:
                ld['offset_x'] = int(offset_x)
            if offset_y is not None:
                ld['offset_y'] = int(offset_y)
            if flip is not None:
                ld['flip'] = bool(flip)
        return True

    def _sync_slider_to_layer(self):
        """把上方 ④⑤⑥ + 翻转 切到当前选中图层的值（点选层时调用，不触发写回）"""
        try:
            i = self._cur_layer_index()
            sc, ox, oy, fl = self._layer_get_params(i)
            self._layer_loading = True
            self.var_scale.set(sc)
            self.var_offx.set(ox)
            self.var_offy.set(oy)
            self.var_flip.set(fl)
            try:
                self.lbl_scale.config(text=f'{sc:.1f}x')
                self.lbl_offx.config(text=f'{ox}px')
                self.lbl_offy.config(text=f'{oy}px')
                self.lbl_slider_target.config(
                    text=f'④ 缩放（第 {i + 1} 层）:')
            except Exception:
                pass
        except Exception:
            pass
        finally:
            self._layer_loading = False

    def _is_alpha_mode(self):
        """内部渲染模式是不是「增强」。

        v2.0-R10：入口只剩 ⑩ 旁「增强（真羽化）」开关；var_render 是该开关的内部状态
        （写回 cfg 时仍读它，口径与 R1/R7 一致）。
        """
        try:
            return resolve_render_mode({'render_mode': self.var_render.get()}) == 'alpha'
        except Exception:
            return False

    def _on_alpha_feather_toggle(self):
        """⑩ 旁「增强（真羽化）」开关：勾/取消 = 切内部渲染模式，随即刷新提示并立刻重绘预览。

        v2.0-R10：⑪ 单选已删，本开关是**唯一入口**（Tk 的 set() 不触发 command，
        所以这里与 _update_render_hint 之间没有递归）。
        """
        try:
            want = bool(self.var_alpha_feather.get())
        except Exception:
            want = False
        try:
            self.var_render.set('alpha' if want else 'compat')
        except Exception:
            pass
        self._update_render_hint()

    def _sync_feather_widgets(self):
        """⑩ 旁开关回显 + 「点阵羽化」勾选框的可编辑性（增强模式下置灰）。

        v2.0-R1：增强模式走分层窗的逐像素 alpha，「点阵羽化」（compat 的 4×4 抖动近似）
        已不参与渲染 —— 所以勾选框锁定在勾选态并置灰，提示行写明「点阵 = 兼容模式的近似」；
        切回兼容模式恢复用户原来的勾选（self._feather_prev 记忆）。
        带宽滑条仍可拖：增强模式下它调的就是真羽化的过渡带宽度（拖到 0 = 不羽化）。
        """
        alpha = self._is_alpha_mode()
        try:
            if bool(self.var_alpha_feather.get()) != alpha:
                self.var_alpha_feather.set(alpha)
        except Exception:
            pass
        try:
            if alpha:
                if self._feather_prev is None:
                    self._feather_prev = bool(self.var_feather.get())
                if not bool(self.var_feather.get()):
                    self.var_feather.set(True)
            elif self._feather_prev is not None:
                self.var_feather.set(bool(self._feather_prev))
                self._feather_prev = None
        except Exception:
            pass
        try:
            self.chk_feather.config(state='disabled' if alpha else 'normal')
        except Exception:
            pass
        try:
            self.lbl_feather_hint.config(
                text=('带宽 px；增强模式 = 逐像素真羽化（点阵近似已被替代，勾选已锁定）'
                      if alpha else
                      '带宽 px；点阵羽化是兼容模式下的近似（要逐像素真羽化请勾右边「增强」）'),
                fg='#2e7d32' if alpha else '#888')
        except Exception:
            pass

    def _safe_update_preview(self):
        """开关即时反馈：立刻重绘预览。控件还没建好（构造期）时静默跳过，不炸向导构建。"""
        try:
            if getattr(self, 'canvas', None) is None:
                return False
            self._update_preview()
            return True
        except Exception:
            return False

    def _update_render_hint(self):
        """渲染模式提示（大白话，不摆 compat/alpha 术语）。

        v2.0-R1：这里同时是「⑪ 渲染模式 ↔ ⑩ 旁「增强（真羽化）」开关」双向联动的收口。
        v2.0-R10：⑪ 单选已删 —— 现在只有 ⑩ 旁开关一个入口，本方法负责「开关 → 提示文案 +
        立刻重绘预览」，并在从老配置/皮肤档案回显时把内部状态同步到开关（_sync_feather_widgets）。
        文案不再引用 ⑪，但仍要讲清「点阵羽化 = 兼容模式下的近似」。
        """
        try:
            names = dict(RENDER_MODE_CHOICES)
            if self._is_alpha_mode():
                txt = ('💡 %s（已开）：支持真·半透明（羽化/圆角边缘更柔和、'
                       '图里含品红也不再被抠穿）。\n'
                       '透明区域会点击穿透（不挡鼠标，点击落到下面的窗口）；'
                       '拖动请抓图片不透明部分。'
                       % names.get('alpha', '增强（真羽化）'))
            else:
                txt = ('💡 %s（未勾，默认）：与旧版显示方式完全一致，最稳；\n'
                       '圆角/羽化的边缘是硬边（近看有点阵/毛边）—— 点阵羽化是兼容模式下的近似，'
                       '要逐像素真羽化请勾 ⑩ 旁的「增强（真羽化）」。'
                       % names.get('compat', '兼容'))
            self.lbl_render_hint.configure(text=txt)
        except Exception:
            pass
        self._sync_feather_widgets()
        self._safe_update_preview()

    def _preview_render_mode_img(self, img):
        """预览的「显示口径」对齐运行时渲染模式。

        兼容（compat）：Tk 键色透明只有全透/全不透两档 → alpha 二值化（>=128 不透明），
                        半透明在真实窗口里也是硬边，预览不能假装它平滑；
        增强（alpha）：分层窗支持逐像素 alpha → 原样保留（半透明 / 真羽化都平滑）。
        """
        try:
            if self._is_alpha_mode():
                return img
            a = img.split()[3].point(lambda v: 255 if v >= 128 else 0)
            out = img.copy()
            out.putalpha(a)
            return out
        except Exception:
            return img

    def _preview_compose(self, img):
        """预览用：按渲染模式对齐显示口径 → 合成到画布底色（Tk 画布不支持逐像素 alpha）。

        用户实测「渲染增强没看见对应的预览」的根因就在这：以前 RGBA 直接塞给
        PhotoImage（alpha 被丢）又画在白底上，兼容/增强、透明/半透明全长一样。
        现有口径：兼容 = 二值 alpha + 点阵 → 硬边；增强 = 逐像素 alpha + 真羽化 → 平滑过渡。

        v2.0-R7：底从 R1 的棋盘格改回**纯色底**（= 画布底色）—— 用户把棋盘格当成了「不透明」，
        明确要求预览里不要棋盘格；合成口径（上面那两步）不变，只换底。
        """
        try:
            return compose_on_solid(self._preview_render_mode_img(img),
                                    PREVIEW_BG_RGB, self._Image)
        except Exception:
            try:
                return img.convert('RGB')
            except Exception:
                return img

    def _effects_cfg(self):
        """向导里的特效参数（与 config 同名字段，可直接喂给 apply_display_effects）

        v2.0-R1：增强（真羽化）模式下羽化恒定开启且走逐像素真羽化（true_alpha）——
        与「⑩ 旁开关勾上 = 点阵被真羽化替代」的 UI 口径一致，保存与预览也不打架。
        """
        try:
            alpha = self._is_alpha_mode()
            return {'corner_enabled': bool(self.var_corner.get()),
                    'corner_radius': int(self.var_corner_r.get()),
                    'feather_enabled': bool(self.var_feather.get()) or alpha,
                    'feather_radius': int(self.var_feather_r.get()),
                    'true_alpha': alpha,
                    'flip_h': bool(self.var_flip.get())}
        except Exception:
            return {}

    def _image_effects(self, img):
        try:
            return apply_display_effects(img, self._effects_cfg(), self._Image)
        except Exception:
            return img

    def _cleanup_junk(self):
        """🧹 清理程序目录垃圾（白名单之外、非保护类型、非正在使用的图片；走回收站）"""
        cleanup_junk_files(extra_keep=[self.cfg.get('image', '')], parent=self.root)

    # ---------- ② 多层预览（向导）----------
    def _preview_specs(self):
        """预览用图层列表：只有 ≥2 层才返回（单层返回 [] → 预览走 v1.6 原路径，行为零变化）。

        v2.0-t15：把**当前选中图层**的 UI 值（锚点/缩放/偏移/翻转/随宽度比例）合进那一层
        —— 这样「点选第 N 层 → 拖上方 ④⑤⑥」时，预览里变的正是第 N 层（而不是永远变主层）。
        其余层沿用它们各自的持久值（层间记忆）。
        """
        try:
            layers = resolve_layers(self.cfg)
            if len(layers) <= 1:
                return []
            i = int(getattr(self, '_layer_sel', 0))
            if not (0 <= i < len(layers)):
                i = 0
            ld = dict(layers[i])
            try:
                # v2.0-R11：贴边方向已收归通用区 ③ 统一（点一次全部层同步），所以这里直接
                # 用该层自己的 anchor（主层由 resolve_layers 取顶层 side，口径不变），
                # 不再需要 R2 那套「主层读 var_side / 其余层读图层区控件」的分支。
                ld['scale'] = round(float(self.var_scale.get()), 2)
                ld['flip'] = bool(self.var_flip.get())
                ld['offset_x'] = int(self.var_offx.get())
                ld['offset_y'] = int(self.var_offy.get())
                ld['follow_width_ratio'] = (int(self.var_lay_follow_r.get()) / 100.0
                                            if self.var_lay_follow.get() else 0.0)
                if i == 0:
                    # true_alpha 是「预览当前渲染模式」的口径，不是图层参数，逐层注入（见下）
                    ld['effects'] = {k: v for k, v in self._effects_cfg().items()
                                     if k not in ('flip_h', 'true_alpha')}
            except Exception:
                pass
            layers[i] = ld
            return layers
        except Exception:
            return []

    def _preview_layer_imgs(self, layers):
        """多层预览：逐层出 PIL 图（缩放 / 特效口径与运行时一致）。失败的层返回 None。"""
        out = []
        for i, ld in enumerate(layers):
            im = None
            try:
                if i == 0:
                    im = self._get_preview_img()
                else:
                    with self._Image.open(ld.get('image')) as _im:
                        im = _im.convert('RGBA')
                if im is None:
                    raise ValueError('图片加载失败')
                base_h = 300 * float(ld.get('scale', 1.0) or 1.0)
                if im.height > 0:
                    ratio = base_h / im.height
                    im = im.resize((max(1, int(im.width * ratio)), max(1, int(base_h))),
                                   self._Image.BILINEAR)
                eff = dict(ld.get('effects') or {})
                eff['flip_h'] = bool(ld.get('flip'))
                # v2.0-R1：羽化实现跟当前渲染模式走（增强 = 逐像素真羽化）
                eff['true_alpha'] = self._is_alpha_mode()
                im = apply_display_effects(im, eff, self._Image)
            except Exception:
                im = None
            out.append(im)
        return out

    def _get_preview_img(self):
        """预览图片缓存：文件未变时复用已打开的图，避免每次滑块都重开大图。

        动图（n_frames>1）：缓存保持可 seek 的源图，每次返回 self._anim_idx
        对应帧的 RGBA（预览动画就是改 _anim_idx 后重绘）。
        静态图：缓存直接存缩好的 RGBA（与原行为一致）。
        """
        path = self.cfg.get('image')
        if not path or not self.PIL:
            return None
        try:
            mtime = os.path.getmtime(path)
            if not (self._cache and self._cache[0] == path and self._cache[1] == mtime):
                img = self._Image.open(path)
                if int(getattr(img, 'n_frames', 1) or 1) <= 1:
                    # 大图先缩到最长边 1600，减少后续预览缩放开销
                    longest = max(img.size)
                    if longest > 1600:
                        s = 1600.0 / longest
                        img = img.resize((max(1, int(img.width * s)),
                                          max(1, int(img.height * s))), self._Image.LANCZOS)
                    img = img.convert('RGBA')
                self._cache = (path, mtime, img)
            img = self._cache[2]
            n = int(getattr(img, 'n_frames', 1) or 1)
            if n > 1:
                try:
                    img.seek(int(self._anim_idx) % n)   # 同帧 seek 不重解
                except Exception:
                    pass
                return img.convert('RGBA')   # 每帧转一次，不缓存转换结果（否则丢帧）
            return img
        except Exception:
            return None

    def _refresh_anim_state(self):
        """按当前 cfg['image'] 重新检测动图帧数（选图 / 预处理后共用）。

        返回帧数；>1 才点亮「预览动画」按钮。
        """
        self._anim_after_stop()
        self._anim_on = False
        self._anim_idx = 0
        self._anim_n = 0
        path = self.cfg.get('image')
        if self.PIL and path:
            try:
                with self._Image.open(path) as probe:
                    self._anim_n = int(getattr(probe, 'n_frames', 1) or 1)
            except Exception:
                self._anim_n = 0
        if self._anim_n > 1:
            self.btn_anim.config(state='normal', text=f'▶ 预览动画({self._anim_n}帧)')
        else:
            self.btn_anim.config(state='disabled', text='▶ 预览动画')
        return self._anim_n

    # ---------- 向导内动图预览（v1.6）----------
    def _anim_after_stop(self):
        if self._anim_after:
            try:
                self.root.after_cancel(self._anim_after)
            except Exception:
                pass
            self._anim_after = None

    def _toggle_anim_preview(self):
        """▶ 预览动画 / ⏸ 停止预览：按需播放，不播时只显示首帧"""
        if self._anim_n <= 1:
            return
        self._anim_on = not self._anim_on
        if self._anim_on:
            self.btn_anim.config(text='⏸ 停止预览')
            self._anim_idx = 0
            self._anim_step()
        else:
            self._anim_after_stop()
            self._anim_idx = 0
            self.btn_anim.config(text=f'▶ 预览动画({self._anim_n}帧)')
            self._update_preview()

    def _anim_step(self):
        """预览动图节拍：推进一帧后重绘预览，按该帧时长重排"""
        self._anim_after = None
        if not self._anim_on or self._anim_n <= 1:
            return
        self._anim_idx = (self._anim_idx + 1) % self._anim_n
        self._update_preview()
        dur = 100
        try:
            src = self._cache[2] if self._cache else None
            if src is not None and int(getattr(src, 'n_frames', 1) or 1) > 1:
                dur = _frame_duration(src)   # _update_preview 已 seek 到当前帧
        except Exception:
            dur = 100
        try:
            self._anim_after = self.root.after(int(dur), self._anim_step)
        except Exception:
            self._anim_after = None

    def _pick_image(self):
        path = filedialog.askopenfilename(
            title='选择图片', parent=self.root,
            filetypes=[('图片文件', '*.png *.jpg *.jpeg *.webp *.gif *.bmp'),
                       ('所有文件', '*.*')])
        if not path:
            return
        self._set_main_image(path)

    def _set_main_image(self, path, suffix=''):
        """换主图（选图 / 预处理共用）——把「顶层 image」与「第 0 层图层图」一次改同步。

        v2.0-t15 修复「点选图片时无法预览」，三处根因一起收口：
          · 图层路径：以前只改 cfg['image']，layers[0].image 还指旧图 → 预览/保存/删层
            三条链路看到两张不同的图（状态分裂）。现在同步写进 layers[0]。
          · 缓存：预览缓存键是 (path, mtime)，同名覆盖或陈旧缓存会让画面停在上一次；
            换图时直接丢掉缓存（同步 _cache 与 PhotoImage 引用）。
          · 刷新时机：换完图立即 update_idletasks + _update_preview，尺寸变化也重算窗口高度。
        """
        self.cfg['image'] = path
        try:
            layers = self._layers()
            if layers:
                layers[0]['image'] = path      # 关键：第 0 层跟着走，别留旧路径
        except Exception:
            pass
        self._cache = None                      # 丢预览缓存，强制重新打开
        try:
            if self.tk_img is not None:
                _release_photo(self.tk_img)
                self.tk_img = None
            for p in self._photo_refs:
                _release_photo(p)
            self._photo_refs.clear()
        except Exception:
            pass
        off = os.path.basename(path) if not suffix else f'{os.path.basename(path)}{suffix}'
        self.lbl_img.config(text=off, fg='#2e7d32' if suffix else '#333')
        self.btn_prep.config(state='normal')
        self._refresh_anim_state()   # 动图检测：n_frames>1 才亮出「预览动画」按钮
        try:
            self.root.update_idletasks()
        except Exception:
            pass
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
                self._set_main_image(dlg.result_path, '（已预处理）')
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

    # ---------- ② 图层（套层皮肤）----------
    def _layers(self):
        """当前编辑中的图层列表（老 cfg 没有 layers 时自动包成单元素列表）。"""
        if not isinstance(self.cfg.get('layers'), list) or not self.cfg['layers']:
            self.cfg = migrate_skin_cfg(self.cfg)
        return self.cfg['layers']

    def _cur_layer_index(self):
        try:
            sel = self.layer_list.curselection()
            i = int(sel[0]) if sel else 0
        except Exception:
            i = 0
        return max(0, min(i, len(self._layers()) - 1))

    def _layer_label(self, i, ld):
        """列表项文案（大白话：第几层 + 贴哪边 + 文件名）"""
        where = {'left_edge': '贴左', 'right_edge': '贴右', 'center': '居中'}.get(
            ld.get('anchor'), '贴右')
        name = os.path.basename(ld.get('image') or '') or '（未选图）'
        tag = f'第{i + 1}层（主图）' if i == 0 else f'第{i + 1}层'
        return f'{tag} · {where} · {name}'

    def _layer_sync_from_cfg(self):
        """把 cfg 里的图层刷进列表控件（打开向导 / 切皮肤 / 增删层后调用）。"""
        try:
            layers = self._layers()
            self.layer_list.delete(0, 'end')
            for i, ld in enumerate(layers):
                self.layer_list.insert('end', self._layer_label(i, ld))
            keep = max(0, min(int(getattr(self, '_layer_sel', 0)), len(layers) - 1))
            self.layer_list.selection_clear(0, 'end')
            self.layer_list.selection_set(keep)
            self._layer_sel = keep
            self._on_layer_select()
        except Exception:
            pass

    def _layer_hint(self, i):
        # 文案长度有讲究：本行是右栏（高级设置）的高度瓶颈之一，wraplength=300，
        # 多折一行就把窗口需求高度顶上去（R2 实测 +16px）。控制在两行内。
        if i == 0:
            return ('第 1 层是主图：贴哪边由上方 ③ 统一（所有图层一起改）；'
                    '大小/位置用上方 ④⑤⑥ 调，翻转勾选框只作用当前层。')
        return ('这一层跟着候选框走：贴哪边同样由上方 ③ 统一；翻转与 ④⑤⑥ 只调当前层；'
                '勾「随候选框变宽往外让」后它会按比例再外让。')

    def _on_layer_select(self, _e=None):
        """选中某层 → 上方 ④⑤⑥/翻转 与图层区参数一起切到该层（v2.0-t15 点选即同步）。

        切换只回显、不写回（_layer_loading 挡住回调），所以「切走再切回」仍是各层原值 ——
        这就是层间短时记忆：参数一直存在 cfg['layers'][i] / 顶层字段里，不是在 UI 里临时存。
        """
        try:
            sel = self.layer_list.curselection()
            if not sel:
                return
            i = int(sel[0])
            layers = self._layers()
            if i >= len(layers):
                return
            self._layer_sel = i
            ld = layers[i]
            self._layer_loading = True
            # v2.0-R2/R11：③ 已回通用区统一管所有图层 —— var_layer_anchor 只是「当前层
            # anchor 的回显镜像」（不再有绑定它的单选按钮）；主层取顶层 side 的映射，
            # 其余层取各自 anchor（统一同步后它们本就同值，这里保留回显口径不变）。
            self.var_layer_anchor.set(anchor_from_side(self.cfg.get('side')) if i == 0
                                      else ld.get('anchor', 'right_edge'))
            try:
                self._update_side_hint()
            except Exception:
                pass
            # ④⑤⑥ + 翻转：切到该层的值（第 0 层取顶层兼容字段）
            sc, ox, oy, fl = self._layer_get_params(i)
            self.var_scale.set(sc)
            self.var_offx.set(ox)
            self.var_offy.set(oy)
            self.var_flip.set(fl)
            try:
                self.lbl_scale.config(text=f'{sc:.1f}x')
                self.lbl_offx.config(text=f'{ox}px')
                self.lbl_offy.config(text=f'{oy}px')
                self.lbl_slider_target.config(text=f'④ 缩放（第 {i + 1} 层）:')
                self.lbl_slider_hint.config(
                    text=(f'↑ ④⑤⑥ 调的是第 {i + 1} 层'
                          + ('（主图）' if i == 0 else f'（{os.path.basename(ld.get("image") or "")}）')
                          + '；换层会自动切到那一层的值'))
            except Exception:
                pass
            r = abs(float(ld.get('follow_width_ratio', 0.0) or 0.0))
            self.var_lay_follow.set(r > 1e-9)
            self.var_lay_follow_r.set(int(round(r * 100)))
            self.lbl_layer_hint2.config(text=self._layer_hint(i))
        except Exception:
            pass
        finally:
            self._layer_loading = False
        # 点选即刷新预览（v2.0-t15：以前只回显控件不重绘 → 用户看着像"点了没反应/无法预览"）
        self._update_preview()

    def _on_layer_param_change(self, *_a):
        """图层区自有控件（「随候选框变宽往外让」比例）写回当前选中层。

        v2.0-R11：贴边方向的单选取控件已搬回通用区（③ 统一管所有图层），本方法不再碰
        anchor；缩放/水平/垂直/翻转由上方 ④⑤⑥ 与翻转勾选框负责 —— 单一入口，
        避免两套控件互相覆盖。
        """
        if getattr(self, '_layer_loading', False):
            return
        try:
            i = self._cur_layer_index()
            layers = self._layers()
            if i >= len(layers):
                return
            ld = layers[i]
            ld['follow_width_ratio'] = (int(self.var_lay_follow_r.get()) / 100.0
                                        if self.var_lay_follow.get() else 0.0)
            self.lbl_layer_hint2.config(text=self._layer_hint(i))
            self._update_preview()
        except Exception:
            pass

    def _layer_add(self):
        """加一个图层（选图；默认贴到主图的另一侧 —— 左右夹持是最常见的套层用法）。"""
        try:
            layers = self._layers()
            if len(layers) >= MAX_LAYERS:
                messagebox.showinfo('图层已满',
                                    f'最多 {MAX_LAYERS} 层（再多屏幕也放不下了）', parent=self.root)
                return
            path = filedialog.askopenfilename(
                title='选一张图作为新图层',
                filetypes=[('图片文件', '*.png *.jpg *.jpeg *.webp *.gif *.bmp'),
                           ('所有文件', '*.*')], parent=self.root)
            if not path:
                return
            # v2.0-R11：新层的贴边方向也跟随 ③ 的统一值（不再默认「贴到主图另一侧」——
            # 统一语义下所有层同一边；想左右夹持可用 ⑤水平偏移 微调）。
            anc = anchor_from_side(self.var_side.get())
            z = max([int(x.get('z', 0) or 0) for x in layers] or [0]) + 1
            layers.append(normalize_layer({'image': path, 'anchor': anc, 'z': z}))
            self.cfg['layers'] = layers
            self._layer_sel = len(layers) - 1
            self._layer_sync_from_cfg()
            self._update_preview()
        except Exception as e:
            messagebox.showerror('加图层失败', str(e), parent=self.root)

    def _layer_delete(self):
        """删掉选中的图层。第 1 层（主图）保底不可删 —— 否则整条叠加链失去基准。"""
        try:
            i = self._cur_layer_index()      # 实时读列表选中（不依赖缓存，程序化选择也准）
            layers = self._layers()
            if len(layers) <= 1:
                messagebox.showinfo('只剩一层',
                                    '至少要留一张图（第 1 层是主图）', parent=self.root)
                return
            if i == 0:
                messagebox.showinfo('第 1 层不能删',
                                    '第 1 层是主图，其它层都跟着它叠。\n想换主图请直接点「① 选择图片」。',
                                    parent=self.root)
                return
            layers.pop(i)
            for k, ld in enumerate(layers):
                ld['z'] = k
            self.cfg['layers'] = layers
            self._layer_sel = max(0, i - 1)
            self._layer_sync_from_cfg()
            self._update_preview()
        except Exception as e:
            messagebox.showerror('删图层失败', str(e), parent=self.root)

    def _layer_move(self, delta):
        """调整叠放顺序（z）：列表里越靠后越在上层。"""
        try:
            i = self._cur_layer_index()      # 实时读列表选中
            layers = self._layers()
            j = i + int(delta)
            if i < 0 or i >= len(layers) or j < 0 or j >= len(layers):
                return
            layers[i], layers[j] = layers[j], layers[i]
            for k, ld in enumerate(layers):
                ld['z'] = k
            save_layers_into_cfg(self.cfg, layers)   # 第 1 层可能换了 → 顶层兼容字段跟着同步
            self._layer_sel = j
            self._layer_sync_from_cfg()
            self._update_preview()
        except Exception:
            pass

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
        # v2.0-R11：切皮肤后**所有图层** anchor 统一到档案顶层 side（统一语义下的「不串层」：
        # 只按新皮肤的 ③ 走，不残留上一个皮肤 / 向导里的贴边值）
        self._sync_side_to_all_layers(force=True)
        self.var_layer.set(cfg.get('layer', 'above'))
        self.var_scale.set(cfg.get('scale', 1.0))
        self.var_offx.set(cfg.get('offset_x', 0))
        self.var_offy.set(cfg.get('offset_y', 0))
        # 特效参数随皮肤整套恢复
        self.var_corner.set(bool(cfg.get('corner_enabled', False)))
        self.var_corner_r.set(int(cfg.get('corner_radius', 24) or 0))
        self.var_feather.set(bool(cfg.get('feather_enabled', False)))
        self.var_feather_r.set(int(cfg.get('feather_radius', 24) or 0))
        self.var_flip.set(bool(cfg.get('flip_h', False)))
        # 渲染模式：皮肤档案显式声明才改（缺键保持全局开关，与 _sync_render_mode 同语义）
        if 'render_mode' in cfg:
            try:
                self.var_render.set(resolve_render_mode(cfg))
                self._update_render_hint()
            except Exception:
                pass
        img = cfg.get('image', '')
        self.lbl_img.config(text=os.path.basename(img) + f'（皮肤: {name}）', fg='#2e7d32')
        self.btn_prep.config(state='normal' if img else 'disabled')
        self._layer_sync_from_cfg()      # ② 套层：切皮肤后图层列表跟着换（含各层参数）
        self._update_preview()
        self._update_key_hint()
        # ③ 配色绑定回显：皮肤档案存了配色名 → 提示行回显（切皮肤时由外挂整套恢复）
        try:
            sn = str(cfg.get('rime_scheme') or '')
            self._set_scheme_hint(('配色：%s（切皮肤时自动恢复）' % sn) if sn
                                  else '配色：该皮肤未绑定（可一键生成）',
                                  True if sn else None)
        except Exception:
            pass
        # 选中即应用：若外挂正在运行，立即切换皮肤（托盘菜单选中态同步）
        if self.overlay is not None:
            try:
                self.overlay.apply_skin(name)
            except Exception:
                pass

    def _save_skin_named(self, name, ask_overwrite=True):
        """按指定名字把当前向导状态存成皮肤档案；返回 (ok, 实际名字, 提示语)。

        R5 抽出：按钮「💾 存为皮肤」（先问名字）与「🎨 生成候选框配色」（配色要先绑皮肤名）
        共用同一段落盘逻辑，避免两处口径漂移。
        """
        name = str(name or '').strip()
        if not self.cfg.get('image'):
            return False, '', '请先选择图片！'
        if not _valid_skin_name(name):
            return False, '', '皮肤名称限 1-40 字符（中文/字母/数字/空格/横线）'
        # 同名覆盖确认
        existing = [n for n, _ in list_skins() if n.lower() == name.lower()]
        if existing:
            if ask_overwrite and not messagebox.askyesno('覆盖确认',
                                                         f'皮肤「{existing[0]}」已存在，覆盖？',
                                                         parent=self.root):
                return False, '', '已取消（未保存皮肤）'
            name = existing[0]
        tcfg = dict(self.cfg)
        tcfg['layout'] = self.var_layout.get()
        tcfg['layer'] = self.var_layer.get()
        try:
            # ④⑤⑥/翻转 属于「当前选中图层」：先落回那一层（同 _save_and_start 的口径），
            # 顶层兼容字段只由主层决定，避免把第 N 层的值当成主图参数存进档案
            _lyr = self._layers()
            i = self._cur_layer_index()
            self._layer_set_params(i, scale=float(self.var_scale.get()),
                                   offset_x=int(self.var_offx.get()),
                                   offset_y=int(self.var_offy.get()),
                                   flip=bool(self.var_flip.get()))
            tcfg['side'] = self.var_side.get()
            _lyr0 = self._layers()
            if _lyr0:
                # v2.0-R11：档案里**各层** anchor 与 ③ 保持一致（统一语义；切皮肤不串层）
                _anc = anchor_from_side(tcfg['side'])
                for _ld in _lyr0:
                    _ld['anchor'] = _anc
                tcfg['side'] = side_from_anchor(_anc)
                _lyr0[0]['image'] = tcfg.get('image') or _lyr0[0].get('image')
            save_layers_into_cfg(tcfg, _lyr0)     # ② 套层：多图层一起进档案
        except Exception as _e:
            try:
                _write_log(f'[向导] 存皮肤时图层写回失败: {_e}')
            except Exception:
                pass
        try:
            save_skin(name, tcfg)
        except ValueError as e:
            return False, '', str(e)
        except Exception as e:
            return False, '', str(e)
        self.cfg['name'] = name        # R5：记住归属（配色/档案恢复都认它）
        self._refresh_skin_list()
        self.skin_var.set(name)
        return True, name, f'皮肤「{name}」已保存。'

    def _save_as_skin(self):
        """把当前向导参数保存为皮肤档案"""
        if not self.cfg.get('image'):
            messagebox.showwarning('提示', '请先选择图片！')
            return
        default = (str(self.cfg.get('name') or '').strip()
                   or os.path.splitext(os.path.basename(self.cfg.get('image') or ''))[0])
        name = simpledialog.askstring('保存皮肤',
                                      '皮肤名称（保存图片 + 全套参数，\n保存后可在托盘「皮肤选择」随时切换）：',
                                      initialvalue=default, parent=self.root)
        if not name or not name.strip():
            return
        ok, _nm, msg = self._save_skin_named(name.strip())
        if not ok:
            if msg and '已取消' not in msg:
                messagebox.showwarning('无法保存', msg, parent=self.root)
            return
        messagebox.showinfo('已保存', f'{msg}\n托盘「皮肤选择」可随时切换。', parent=self.root)

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

    # ---------- ③ 选图自动生成候选框配色（升级四）----------
    def _scheme_skin_name(self):
        """配色归属名（尽力而为）：已保存皮肤名 > cfg['name'] > 图片文件名（去扩展名）"""
        n = self._saved_skin_name()
        if n:
            return n
        n = str(self.cfg.get('name') or '').strip()
        if n:
            return n
        return os.path.splitext(os.path.basename(self.cfg.get('image') or ''))[0] or 'skin'

    def _saved_skin_name(self):
        """当前向导对应的「已保存皮肤名」：下拉选中名 / cfg['name']，且档案真的存在；否则 ''"""
        for cand in ((self.skin_var.get() or '').strip(),
                     str(self.cfg.get('name') or '').strip()):
            if cand and find_skin(cand):
                return cand
        return ''

    def _scheme_name_candidate(self):
        """还没保存皮肤时给输入框/程序化保存用的默认名（图片文件名去扩展名）"""
        stem = os.path.splitext(os.path.basename(self.cfg.get('image') or ''))[0]
        return stem if _valid_skin_name(stem) else 'skin'

    def _ensure_scheme_skin(self, auto=False, dry_run=False):
        """R5：生成配色前先取得/确认皮肤名（用户反馈「没有先保存皮肤名字的提醒」）。

        返回 {'ok','skin','saved','msg','cancelled'}：
          · 已有皮肤档案 → 直接用（saved=False，不打扰）
          · 没有档案 → 先提示保存并完成保存；用户拒绝/没填名字 → ok=False（不落盘、不建档案）
          · auto=True（自动化/测试）跳过弹窗，直接按候选名程序化保存
          · dry_run=True 例外：零副作用，只用候选名试算方案名，不建任何档案
        """
        res = {'ok': False, 'skin': '', 'saved': False, 'msg': '', 'cancelled': False}
        n = self._saved_skin_name()
        if n:
            res.update(ok=True, skin=n, msg='配色将绑定到皮肤「%s」' % n)
            return res
        cand = self._scheme_name_candidate()
        if dry_run:
            # dry-run 零副作用：用候选名算一遍方案名，但不保存皮肤档案
            res.update(ok=True, skin=cand, saved=False,
                       msg='dry-run：以皮肤名「%s」试算（未保存皮肤档案）' % cand)
            return res
        if not auto:
            if not messagebox.askyesno(
                    '先保存皮肤名（配色要用它命名）',
                    '配色方案名以当前皮肤名命名，方便你在 weasel.custom.yaml 里找到、以后修改；\n'
                    '切皮肤时也能整套恢复（图片 + 参数 + 配色）。\n\n'
                    '当前还没有保存皮肤。现在保存吗？\n'
                    '（点「否」= 先不生成配色）', parent=self.root):
                res.update(msg='未保存皮肤，已取消生成配色（配色名要跟随皮肤名）',
                           cancelled=True)
                return res
            name = simpledialog.askstring(
                '保存皮肤（配色将绑定到它）',
                '皮肤名称（1-40 字符，中文/字母/数字/空格/横线）：',
                initialvalue=cand, parent=self.root)
            if not name or not name.strip():
                res.update(msg='未填写皮肤名，已取消生成配色', cancelled=True)
                return res
            ok, nm, m = self._save_skin_named(name.strip())
            if not ok:
                res.update(msg=m or '保存皮肤失败')
                return res
            res.update(ok=True, skin=nm, saved=True, msg='皮肤「%s」已保存（%s）' % (nm, m))
            return res
        ok, nm, m = self._save_skin_named(cand, ask_overwrite=False)
        if not ok:
            res.update(msg=m or '保存皮肤失败')
            return res
        res.update(ok=True, skin=nm, saved=True, msg='皮肤「%s」已保存（%s）' % (nm, m))
        return res

    def _set_scheme_hint(self, text, ok=None):
        """向导内配色结果提示（成功绿 / 警告橙 / 普通灰）"""
        if not hasattr(self, 'lbl_scheme_hint'):
            return
        color = '#2e7d32' if ok else ('#e67e22' if ok is False else '#999')
        try:
            self.lbl_scheme_hint.config(text=text, fg=color)
        except Exception:
            pass

    def _generate_scheme(self, auto=False, dry_run=False):
        """③ 一键生成候选框配色：提色 → 21 字段亮/暗两套 → 确认 → 备份注入 → 重部署。

        auto=True 跳过所有弹窗（自动化/测试用）；dry_run=True 只算 diff 不落盘。
        返回 {'ok','msg','plan','apply','deploy','theme',...}，向导与测试共用同一份结果。
        """
        res = {'ok': False, 'msg': '', 'plan': None, 'apply': None, 'deploy': None,
               'theme': None, 'theme_info': {}, 'skin': '', 'skin_saved': False,
               'bound': False, 'needs_skin': False, 'scheme_light': '',
               'scheme_dark': '', 'backup': None}
        img = self.cfg.get('image')
        if not img or not os.path.exists(img):
            res['msg'] = '请先选择图片，再生成候选框配色'
            self._set_scheme_hint(res['msg'], ok=False)
            if not auto:
                messagebox.showwarning('生成候选框配色', res['msg'], parent=self.root)
            return res
        if not self.PIL:
            res['msg'] = '需要 Pillow(PIL) 才能提取图片颜色（当前环境不可用）'
            self._set_scheme_hint(res['msg'], ok=False)
            if not auto:
                messagebox.showwarning('生成候选框配色', res['msg'], parent=self.root)
            return res
        try:
            # R5：先绑皮肤名 —— 没有皮肤档案就先提示保存（配色名跟随皮肤名，便于查找/切皮肤整套恢复）
            ens = self._ensure_scheme_skin(auto=auto, dry_run=dry_run)
            res['skin_saved'] = ens['saved']
            if not ens['ok']:
                res['msg'] = ens['msg']
                res['needs_skin'] = True
                self._set_scheme_hint('配色未生成：%s' % ens['msg'], ok=False)
                # 用户主动取消/没填名字已在提示框里表达过，不再叠一个弹窗；真失败才弹
                if not auto and not ens.get('cancelled'):
                    messagebox.showwarning('先保存皮肤名', ens['msg'], parent=self.root)
                return res
            skin = ens['skin']
            res['skin'] = skin
            frames, meta = collect_scheme_frames(img, self._Image)
            theme = extract_scheme_theme(frames, self._Image)
            res['theme'] = theme
            res['theme_info'] = {'n_frames': meta['n_frames'], 'used': meta['used'],
                                 'sampled': meta['sampled'],
                                 'note': '图片整体偏暗（亮套会偏亮）' if theme.get('is_dark')
                                         else '图片偏亮/中等'}
            names = make_scheme_names(skin)
            res['scheme_light'], res['scheme_dark'] = names
            light = build_scheme_fields(skin, theme, dark=False, scheme=names[0])
            dark = build_scheme_fields(skin, theme, dark=True, scheme=names[1])
            man = load_scheme_manifest()
            old = [x for x in (man.get(skin) or []) if x not in names]
            plan = plan_scheme_injection(WEASEL_CUSTOM, skin=skin, light=light, dark=dark,
                                         scheme_light=names[0], scheme_dark=names[1],
                                         set_active=False, stale_schemes=old, dry_run=dry_run)
            res['plan'] = plan
            if not plan['ok']:
                res['msg'] = plan['msg']
                self._set_scheme_hint('配色未生成：%s' % res['msg'], ok=False)
                if not auto:
                    messagebox.showwarning('生成候选框配色', res['msg'], parent=self.root)
                return res
            if auto:
                set_active = True
            else:
                preview = '\n'.join(plan['diff'][:10])
                if len(plan['diff']) > 10:
                    preview += '\n…（共 %d 行改动）' % len(plan['diff'])
                summary = ('目标文件：%s\n\n配色方案：%s（亮） / %s（暗）\n'
                           '图片帧数 %d（参与统计 %d 帧）%s\n'
                           '改动预览：\n%s' % (WEASEL_CUSTOM, names[0], names[1],
                                            meta['n_frames'], meta['used'],
                                            '（帧数过多已均匀采样）' if meta['sampled'] else '',
                                            preview))
                if not messagebox.askyesno('生成候选框配色（%s）' % skin, summary,
                                           parent=self.root):
                    res['msg'] = '已取消（未写入任何文件）'
                    self._set_scheme_hint('配色：已取消（未写入）', ok=False)
                    return res
                set_active = messagebox.askyesno(
                    '一并切换候选框配色？',
                    '是否同时把当前候选框切到这套配色（style/color_scheme）？\n'
                    '选「否」= 只写入配色方案，不动你现在的候选框', parent=self.root)
            if set_active:
                plan = plan_scheme_injection(WEASEL_CUSTOM, skin=skin, light=light, dark=dark,
                                             scheme_light=names[0], scheme_dark=names[1],
                                             set_active=True, stale_schemes=old, dry_run=dry_run)
                res['plan'] = plan
            if dry_run:
                res['ok'] = True
                res['msg'] = 'dry-run：%d 行改动（未写入任何文件）' % len(plan['diff'])
                self._set_scheme_hint('配色：dry-run 完成（%d 行改动，未落盘）'
                                      % len(plan['diff']), True)
                return res
            if plan['diff']:
                wr = apply_scheme_injection(plan)
                res['apply'] = wr
                res['backup'] = wr.get('backup')
                if not wr['ok']:
                    res['msg'] = wr['msg']
                    self._set_scheme_hint('配色写入失败：%s' % wr['msg'], ok=False)
                    if not auto:
                        messagebox.showwarning('配色写入失败', wr['msg'], parent=self.root)
                    return res
                dep = run_weasel_deployer()
            else:
                dep = {'ok': True, 'rc': None, 'exe': None, 'timed_out': False,
                       'msg': '配色与现状一致，跳过重复部署'}
            res['deploy'] = dep
            # 记录到 cfg：随 config.json / 皮肤档案保存 → 切皮肤时整套恢复（含光环联动）
            self.cfg['rime_scheme'] = names[0]
            self.cfg['rime_scheme_dark'] = names[1]
            self.cfg['name'] = skin
            # R5：顺手把配色名写进皮肤档案（只改这两个键）→ 切皮肤时整套恢复不用再手动存一次
            res['bound'] = bind_scheme_to_skin(skin, names[0], names[1])
            man[skin] = list(names)
            save_scheme_manifest(man)
            res['ok'] = True
            res['msg'] = '配色已生成：%s（亮）/ %s（暗）；%s（皮肤「%s」%s）' % (
                names[0], names[1], dep['msg'], skin,
                '已绑定' if res['bound'] else '档案未绑定（请用「💾 存为皮肤」保存一次）')
            self._set_scheme_hint('配色：%s / %s%s' % (
                names[0], names[1],
                '（已写入并部署）' if dep['ok'] else '（已写入，部署未成功：详见弹窗/日志）'), dep['ok'])
            _write_log('[配色] 生成 %s → %s / %s；%s' % (skin, names[0], names[1], dep['msg']))
            if not auto:
                if dep['ok']:
                    messagebox.showinfo('配色已生成', res['msg'], parent=self.root)
                else:
                    messagebox.showwarning('配色已写入，但部署未成功', res['msg'], parent=self.root)
            return res
        except Exception as e:
            res['msg'] = '生成配色失败：%s' % e
            self._set_scheme_hint(res['msg'], ok=False)
            _write_log('[配色] 生成失败：%s' % e)
            if not auto:
                messagebox.showerror('生成候选框配色', res['msg'], parent=self.root)
            return res

    def _restore_scheme_backup(self, auto=False):
        """↩ 一键还原：用最近的 weasel.custom.yaml.bak-* 覆盖回去 + 重部署 + 解绑配色名。

        还原前会把当前文件另存 .bak-restore-<时间戳>（可再次撤回）；找不到备份时明确提示。
        """
        res = {'ok': False, 'msg': '', 'backup': None, 'deploy': None}
        bak = find_latest_weasel_backup(WEASEL_CUSTOM)
        if not bak:
            res['msg'] = '没有找到配色备份（%s.bak-*）' % os.path.basename(WEASEL_CUSTOM)
            self._set_scheme_hint(res['msg'], ok=False)
            if not auto:
                messagebox.showwarning('还原配色备份', res['msg'], parent=self.root)
            return res
        res['backup'] = bak
        if not auto and not messagebox.askyesno(
                '还原配色备份',
                '用备份覆盖当前候选框配色？\n\n备份：%s\n目标：%s\n\n'
                '（当前文件会另存 .bak-restore-<时间戳>，可再次撤回）'
                % (os.path.basename(bak), WEASEL_CUSTOM), parent=self.root):
            res['msg'] = '已取消（未还原）'
            return res
        try:
            rb = restore_weasel_backup(bak, WEASEL_CUSTOM)
            if not rb['ok']:
                res['msg'] = rb['msg']
                self._set_scheme_hint('配色还原失败：%s' % res['msg'], ok=False)
                if not auto:
                    messagebox.showwarning('还原配色备份', res['msg'], parent=self.root)
                return res
            dep = run_weasel_deployer()
            res['deploy'] = dep
            # 解绑：向导配置与生成记录同步清掉（避免下一步又把它切回去）
            self.cfg['rime_scheme'] = ''
            self.cfg['rime_scheme_dark'] = ''
            try:
                skin = self._scheme_skin_name()
                man = load_scheme_manifest()
                if skin in man:
                    man.pop(skin, None)
                    save_scheme_manifest(man)
                # R5：皮肤档案也解绑（还原后那套方案已不在 yaml 里，留着会切皮肤时又写回去）
                bind_scheme_to_skin(skin, '', '')
            except Exception:
                pass
            res['ok'] = True
            res['msg'] = '已从 %s 还原；%s' % (os.path.basename(bak), dep['msg'])
            self._set_scheme_hint('配色：已还原到备份（%s）%s'
                                  % (os.path.basename(bak),
                                     '' if dep['ok'] else '，但部署未成功'), dep['ok'])
            _write_log('[配色] 还原 %s：%s' % (bak, dep['msg']))
            if not auto:
                if dep['ok']:
                    messagebox.showinfo('已还原配色备份', res['msg'], parent=self.root)
                else:
                    messagebox.showwarning('已还原，但部署未成功', res['msg'], parent=self.root)
            return res
        except Exception as e:
            res['msg'] = '还原配色备份失败：%s' % e
            self._set_scheme_hint(res['msg'], ok=False)
            if not auto:
                messagebox.showerror('还原配色备份', res['msg'], parent=self.root)
            return res

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
        # v2.0-R2：重入保护 —— _sync_side_to_layer0 会刷新图层列表文案，而 Listbox 事件会
        # 回调 _on_layer_select → 再进这里；嵌套重绘会把候选框/图片画两遍（canvas items 翻倍）。
        if getattr(self, '_preview_busy', False):
            return
        self._preview_busy = True
        try:
            self._update_preview_impl()
        finally:
            self._preview_busy = False

    def _update_preview_impl(self):
        # v2.0-R2：画之前先把 ③ 主层贴边归一（var_side → cfg['side'] → layers[0].anchor）
        self._sync_side_to_layer0()
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
        base_x = (self.CV_W - cw) // 2
        base_y = (360 - ch) // 2
        # 候选框配色（用 Rime 皮肤主色，简单示意）
        accent = get_rime_accent() if self.PIL else (0, 137, 123)
        hex_acc = '#%02x%02x%02x' % accent

        # 图片（贴候选框侧边；缩放逻辑与运行时一致：高度 = base_height×scale）
        img = None
        new_w = new_h = 0
        ix = iy = 0
        self._preview_layers = []          # ② 多层预览：(x, y, PIL图, PhotoImage)
        preview_layers = self._preview_specs()
        multi = len(preview_layers) > 1
        if not multi and not self.cfg.get('image'):
            multi = False
        if multi and self.PIL:
            try:
                imgs = self._preview_layer_imgs(preview_layers)
                sizes = [(im.size[0], im.size[1]) if im is not None else (0, 0) for im in imgs]
                wx0, wy0, ww, wh, pl = plan_layer_layout(preview_layers, sizes,
                                                         (0, 0, cw, ch))
                if ww > 0 and wh > 0:
                    fit = min((self.CV_W - 30) / float(ww),
                              (self.CV_H - 40) / float(wh), 1.0)
                    if fit < 1.0:
                        imgs = [None if im is None else
                                im.resize((max(1, int(im.size[0] * fit)),
                                           max(1, int(im.size[1] * fit))), self._Image.LANCZOS)
                                for im in imgs]
                        sizes = [(im.size[0], im.size[1]) if im is not None else (0, 0)
                                 for im in imgs]
                        cw, ch = max(1, int(cw * fit)), max(1, int(ch * fit))
                        wx0, wy0, ww, wh, pl = plan_layer_layout(preview_layers, sizes,
                                                                 (0, 0, cw, ch))
                    base_x = (self.CV_W - cw) // 2
                    base_y = (360 - ch) // 2
                    pos = {p[0]: (p[1], p[2]) for p in pl}
                    for k, im in enumerate(imgs):
                        if im is None:
                            continue
                        dx, dy = pos.get(k, (0, 0))
                        px, py = base_x + wx0 + dx, base_y + wy0 + dy
                        # v2.0-R7：预览先合成到画布底色再显示（Tk 图片丢 alpha，白底上看不出透明/半透明）
                        tk_im = self._ImageTk.PhotoImage(self._preview_compose(im),
                                                         master=self.root)
                        self._photo_refs.append(tk_im)
                        if len(self._photo_refs) > MAX_LAYERS + 2:
                            _release_photo(self._photo_refs.pop(0))
                        self._preview_layers.append((px, py, im, tk_im))
                    self.tk_img = None
                else:
                    # v2.0-t15：算不出画布尺寸（所有图层图都缺失/加载失败）时给出明确文字，
                    # 不再留一块静默空白 —— 用户看到的「无法预览」多数就是这一支。
                    miss = [i + 1 for i, im in enumerate(imgs) if im is None]
                    cv.create_text(self.CV_W // 2, 120,
                                   text=f'图片加载失败：第 {"/".join(map(str, miss))} 层的图片'
                                        f'找不到或读不出来\n请用 ① 重新选择，或删掉这几层',
                                   fill='#c0392b', font=('Microsoft YaHei', 10),
                                   justify='center')
                    self._preview_layers = []
                    self.tk_img = None
            except Exception as e:
                cv.create_text(380, 180, text=f'图层预览失败: {e}', fill='red',
                               font=('Microsoft YaHei', 9))
                self._preview_layers = []
                self.tk_img = None
        elif self.cfg.get('image') and self.PIL:
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
                # 特效与运行时一致（圆角 / 模糊按显示尺寸套）
                img = self._image_effects(img)
                new_w, new_h = img.size
                # 若图片+候选框超出画布，整体等比缩小（保持相对位置比例）
                total_w = new_w + 8 + cw
                total_h = max(new_h, ch)
                cv_w, cv_h = self.CV_W, self.CV_H
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
                # v2.0-R7：合成到画布底色再显示 —— 兼容 = 硬边点阵、增强 = 颜色到底色的平滑过渡
                self.tk_img = self._ImageTk.PhotoImage(self._preview_compose(img),
                                                       master=self.root)
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
            if self._preview_layers:      # ② 多层：每层各画一份（含虚线框，便于看清各自范围）
                for _px, _py, _im, _tk in self._preview_layers:
                    cv.create_image(_px, _py, anchor='nw', image=_tk)
                    cv.create_rectangle(_px, _py, _px + _im.size[0], _py + _im.size[1],
                                        outline='#ff6a00', dash=(4, 2))
                return
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
        self.cfg['layer'] = self.var_layer.get()
        # ④⑤⑥/翻转 现在是「当前选中图层」的滑条（v2.0-t15）：先把当前值落回那一层，
        # 再由 save_layers_into_cfg 把主层的值同步到顶层兼容字段。
        # 不能像以前那样无条件用 var_scale/var_offx/var_offy 覆盖顶层 —— 否则选中第 2 层
        # 时保存会把第 2 层的缩放写进主图（实测 R01：0.9 被写成 1.0）。
        try:
            self._layer_set_params(self._cur_layer_index(),
                                   scale=float(self.var_scale.get()),
                                   offset_x=int(self.var_offx.get()),
                                   offset_y=int(self.var_offy.get()),
                                   flip=bool(self.var_flip.get()))
            # v2.0-R2/R11：③ 归一（var_side → cfg['side'] → **全部图层** anchor）——
            # 与预览/切层同一个入口，保存出来的 side 与各层 anchor 永远与界面一致
            self._sync_side_to_all_layers(force=True)
            _lyr0 = self._layers()
            if _lyr0:
                self.cfg['side'] = side_from_anchor(_lyr0[0].get('anchor'))
                self.var_side.set(self.cfg['side'])
        except Exception as _e:
            try:
                _write_log(f'[向导] 保存图层参数失败: {_e}')
            except Exception:
                pass
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
        # 显示期特效（圆角 / 高斯模糊）：写进配置，随皮肤一起保存
        self.cfg['corner_enabled'] = bool(self.var_corner.get())
        self.cfg['corner_radius'] = int(self.var_corner_r.get())
        self.cfg.pop('blur_enabled', None)   # 旧字段清理（整体模糊已移除）
        self.cfg.pop('blur_radius', None)
        # v2.0-R1：增强（真羽化）模式下羽化恒定开启（走逐像素真羽化）—— 与预览口径一致；
        # 兼容模式下仍按用户在 ⑩ 的勾选（老路径零变化）
        self.cfg['feather_enabled'] = bool(self.var_feather.get()) or self._is_alpha_mode()
        self.cfg['feather_radius'] = int(self.var_feather_r.get())
        # 注意：flip_h 不再在这里从 var_flip 写顶层 —— var_flip 是「当前选中图层」的翻转
        # （v2.0-t15 复用），主层的翻转已由上面的 _layer_set_params 处理好
        self.cfg.pop('feather_dither', None)   # 旧字段清理（点阵羽化已成为唯一实现）
        # 渲染模式（v2.0-①）：UI 只有中文选项，写回时归一成 compat/alpha（非法值回落 compat）
        self.cfg['render_mode'] = resolve_render_mode({'render_mode': self.var_render.get()})
        # ② 套层（v2.0-②）：图层列表与顶层兼容字段对齐后一起存（schema 2 + layers）
        try:
            _lyr = self._layers()
            _lyr[0]['image'] = self.cfg['image']   # 主图可能刚换成预处理持久化副本，同步给第 0 层
            save_layers_into_cfg(self.cfg, _lyr)
        except Exception as _e:
            _write_log(f'[套层] 图层写回失败: {_e}')
        # 开机自启（真相 = 启动文件夹快捷方式；勾选态与实际同步后才算完成）
        want_start = bool(self.var_autostart.get())
        ok, msg = set_autostart(want_start, force=want_start)
        self.cfg['autostart'] = want_start
        if not ok:
            messagebox.showwarning('开机自启', msg)
        save_config(self.cfg)
        _write_log(f'[配置] 保存 image={self.cfg.get("image")} layout={self.cfg.get("layout")} '
                   f'side={self.cfg.get("side")} layer={self.cfg.get("layer")} '
                   f'scale={self.cfg.get("scale")} 圆角={self.cfg.get("corner_enabled")}/'
                   f'{self.cfg.get("corner_radius")} 点阵羽化={self.cfg.get("feather_enabled")}/'
                   f'{self.cfg.get("feather_radius")} 渲染={resolve_render_mode(self.cfg)} '
                   f'自启={self.cfg.get("autostart")}')
        self.root.destroy()
        self.on_done(self.cfg)

    def _on_cancel(self):
        # 只销毁窗口，让 mainloop 自然返回（不要 sys.exit，否则 Tk 清理会卡住）
        # 先停动图预览节拍，再显式释放全部 PhotoImage（tcl 端 image table 同步清理）
        self._anim_on = False
        self._anim_after_stop()
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
                pystray.MenuItem('开机自启', self._toggle_autostart,
                                 checked=lambda item: autostart_installed()),
                pystray.MenuItem('清理垃圾文件…', self._cleanup_junk),
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

    def _toggle_autostart(self, icon, item):
        """托盘开关开机自启（pystray 线程 → Tk 主线程执行）"""
        try:
            self.overlay.root.after(0, self._autostart_main)
        except Exception:
            pass

    def _autostart_main(self):
        """主线程切换自启：以启动文件夹实况为准取反，成功后同步配置并托盘提示"""
        try:
            want = not autostart_installed()
            ok, msg = set_autostart(want, force=want)
            if ok:
                try:
                    self.overlay.cfg['autostart'] = want
                    save_config(self.overlay.cfg)
                except Exception:
                    pass
                try:
                    if self.icon is not None:
                        self.icon.update_menu()
                except Exception:
                    pass
            else:
                try:
                    import tkinter.messagebox as _mb
                    _mb.showwarning('开机自启', msg, parent=self.overlay.root)
                except Exception:
                    pass
        except Exception as e:
            try:
                _write_log(f'[_autostart_main] 异常: {e}')
            except Exception:
                pass

    def _cleanup_junk(self, icon, item):
        """托盘入口：清理程序目录垃圾（pystray 线程 → Tk 主线程）"""
        try:
            self.overlay.root.after(0, self._cleanup_junk_main)
        except Exception:
            pass

    def _cleanup_junk_main(self):
        try:
            cleanup_junk_files(extra_keep=[self.overlay.cfg.get('image', '')],
                               parent=self.overlay.root)
        except Exception as e:
            try:
                _write_log(f'[_cleanup_junk] 异常: {e}')
            except Exception:
                pass

    def _quit(self, icon, item):
        try:
            icon.stop()
        except Exception:
            pass
        try:
            self.overlay.root.after(0, self.overlay._graceful_quit)
        except Exception:
            pass

    def stop(self):
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass


# ============ 主窗口 ============
_ACTIVE_OVERLAY = None   # 进程内当前活跃的外挂实例（防同进程多实例 → 叠出多个托盘图标/窗口）


def _close_active_overlay():
    """确保进程内只有一个外挂实例：把上一个停动画 / 收托盘 / 销毁窗口。"""
    global _ACTIVE_OVERLAY
    ov = _ACTIVE_OVERLAY
    _ACTIVE_OVERLAY = None
    if ov is None:
        return
    try:
        ov._graceful_quit()
    except Exception:
        pass


class FollowOverlay:
    def __init__(self, cfg):
        self.cfg = cfg
        _close_active_overlay()          # 同进程只留一个（防连点托盘/重复保存叠出多个）
        global _ACTIVE_OVERLAY
        _ACTIVE_OVERLAY = self
        self._wizard = None              # 当前打开的配置向导（防连点叠出多个配置窗）
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
        # 渲染模式先定：窗口初始化就要按它选路 —— alpha 绝不能用 -transparentcolor。
        # Tk 的透明色在 Windows 上走 SetLayeredWindowAttributes，一旦对某窗口调用过，
        # 同一窗口的 UpdateLayeredWindow 会永久返回 0（2026-09-26 实测：先设再清也没救，
        # 必须「摘掉再戴上 WS_EX_LAYERED」才复位；见 LayeredRenderer.ensure_layered）。
        self.render_mode = resolve_render_mode(self.cfg)
        if self.render_mode == 'compat':
            self.root.attributes('-transparentcolor', '#FF00FF')  # 默认品红，load_char 后按实际键色覆盖
            self.root.configure(bg='#FF00FF')
        else:
            self.root.configure(bg='#000000')   # 内容全由位图决定，底色只是兜底
        if self.PIL:
            set_window_icon(self.root, (self._Image, self._ImageTk))

        self.raw_img = None
        self.cur_accent = None
        self.img_mtime = None
        self.key_rgb = MAGENTA          # 当前抠色键（动态，随图片变化）
        self.layer = self.cfg.get('layer', 'above')  # 图层：above=图片置顶 / below=候选框压图（v1.5）
        # ===== 渲染层（v2.0-①a）：render_mode=compat(默认)/alpha → Renderer 实现 =====
        # 缺键/非法值一律 compat（老用户零感知）；alpha 走真分层窗（①b 已实装）
        self.renderer = create_renderer(self, self.cfg, self.render_mode)
        try:
            _write_log(f'[渲染] render_mode={self.render_mode} '
                       f'renderer={type(self.renderer).__name__}')
        except Exception:
            pass
        # ===== 动图状态（v1.6；静态图时 anim_n=1 全走老路径）=====
        self.anim_src = None            # 动画源图（保持打开，供 seek 逐帧解码）
        self.anim_n = 0                 # 总帧数
        self.anim_idx = 0               # 当前帧号
        self.anim_after = None          # after() 句柄（停止/重载时 cancel）
        self._frame_cache = collections.OrderedDict()  # 帧号 → PhotoImage（LRU）
        self._base_h = 300.0            # 帧缩放基准高度（base_height × scale）
        # ===== ② 套层运行时缓存/记账（v2.0 R3）=====
        # _dims_cache：各图层显示尺寸，键 (图路径, base_height×scale) → (w,h)。
        #   定位路径每帧都要问「各层多大」，缓存前是每帧每层一次 Image.open+解码+LANCZOS
        #   缩放（实测 3 层 400x600 约 30ms/帧）→ 事件节拍被拖到 45ms+，图跟不上候选框。
        #   失效点只有一个：load_char（换图/切皮肤/滚轮缩放/热重载都走它）。
        self._dims_cache = {}
        self._composed_plan = None      # 最近一次「已合成」的布局指纹 (ww, wh, placements)
        self._applied_size = (0, 0)     # 最近一次真正落到窗口上的画布尺寸 (w, h)
        self.load_char()

        self.label = self.renderer.make_label(self.root, self.img, self.key_rgb)
        self.label.pack()

        self.label.bind('<ButtonPress-1>', self.on_press)
        self.label.bind('<B1-Motion>', self.on_drag)
        self.label.bind('<MouseWheel>', self.on_wheel)
        self.label.bind('<Button-3>', self.on_right_click)
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label='隐藏/显示 Ctrl+Alt+C', command=self.toggle)
        self.menu.add_command(label='退出 Ctrl+Alt+Q', command=self._graceful_quit)
        self.root.bind('<Control-Alt-Key-c>', lambda e: self.toggle())
        self.root.bind('<Control-Alt-Key-q>', lambda e: self._graceful_quit())
        # WM_DELETE_WINDOW 协议：注册后 _kill_existing 的 WM_CLOSE 才能让它体面退出（S8）。
        # 不注册时 overrideredirect 窗被 WM_CLOSE 干掉后 Tk 记账不对，进程会残留在后台。
        self.root.protocol('WM_DELETE_WINDOW', self._graceful_quit)
        # 销毁前停掉动画节拍：否则遗留的 after 回调会在 Tcl 里报 invalid command name
        self.root.bind('<Destroy>', self._on_root_destroy, add='+')

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
        """加载/重载图片（热重载、切皮肤、滚轮缩放共用入口）。

        静态图：原管线不变（缩放 → 动态键色 → 渲染层出图 → 贴 Label）。
        动图（GIF/动图 WebP/APNG，n_frames>1）：建帧序列 + after 按帧时长播放；
        帧按需解码（LRU 6 张），键色取多帧颜色并集。

        v2.0-①a：出图与应用全部经渲染器（_renderer_of(self)；CompatRenderer = v1.6 老路径原样
        承载），这里不再直接调 _flatten_alpha_for_tk / ImageTk.PhotoImage / -transparentcolor。
        """
        img_path = self.cfg['image']
        renderer = _renderer_of(self)      # 渲染层（v2.0-①a）：出图与应用都走它
        self._anim_stop()
        self.anim_src = None
        self.anim_n = 0
        self.anim_idx = 0
        # R3：图层显示尺寸缓存与「已合成布局」记账一律作废 —— 本函数是「图/配置变了」的唯一入口
        # （换图、切皮肤、滚轮缩放、热重载、预处理保存都走这里），失效点集中在此最好审计。
        self._dims_cache = {}
        self._composed_plan = None
        old_frames = list(getattr(self, '_frame_cache', {}).values())
        self._frame_cache.clear()
        if not self.PIL:
            self.img = tk.PhotoImage(file=img_path, master=self.root)
            self.w, self.h = self.img.width(), self.img.height()
            self.layer = self.cfg.get('layer', 'above')
            return
        Image = self._Image
        base_h = self.cfg.get('base_height', 300) * self.cfg.get('scale', 1.0)
        self._base_h = base_h
        layers = self._layer_specs()
        multi = self._layers_active()      # ② 套层：>1 层才走「单窗多图合成」路径
        self._layer_raw = []               # 各层原始 RGBA 帧（抠色前），合成与抠色键都用它
        src = Image.open(img_path)
        try:
            n = int(getattr(src, 'n_frames', 1) or 1)
        except Exception:
            n = 1
        if n > 1:
            # ---- 动图：帧序列播放 ----
            self.anim_src = src
            self.anim_n = n
            self.key_rgb = self._pick_anim_key(Image, n)
            if multi:
                f0 = self._decode_frame_rgba(0)
                if f0 is None:
                    self.anim_src, self.anim_n = None, 0
                    raise ValueError('首帧解码失败')
                self._layer_raw = [f0]
            else:
                self.img = self._decode_frame(0)
                if self.img is None:      # 解码失败 → 退回静态首帧路径
                    self.anim_src, self.anim_n = None, 0
                    raise ValueError('首帧解码失败')
                self._frame_cache[self.anim_idx] = self.img
            self.raw_img = None
        else:
            # ---- 静态图：原管线（行为与 v1.5 一致）----
            img = src.convert('RGBA')
            if img.height > 0:
                ratio = base_h / img.height
                new_w = max(1, int(img.width * ratio))
                img = img.resize((new_w, max(1, int(base_h))), Image.LANCZOS)
            # 显示期特效（圆角 / 高斯模糊）——在选抠色键之前做（模糊会改颜色分布）
            img = apply_display_effects(img, self.cfg, Image)
            if multi:
                self._layer_raw = [img]    # 未抠色的原始帧：合成必须在抠色之前
            else:
                # 动态颜色键：统计颜色并集，选图中不存在的颜色当抠色键（消灭「图含品红被误抠」）
                self.key_rgb = renderer.pick_key([img], Image)
                # 渲染层出帧（compat = 修复紫边：缩放后 alpha 二值化 + 透明区填键色）
                img = renderer.flatten(img, self.key_rgb, Image)
                self.raw_img = img.copy()
                old = getattr(self, 'img', None)
                self.img = renderer.to_photo(img)
                if old is not None:
                    renderer.release(old)  # 显式释放旧 tcl image（热重载/切皮肤同步清理）
        self.img_mtime = os.path.getmtime(img_path)
        # 不画光环（纯图片）
        self.cur_accent = None
        if multi:
            # ② 步 4 单窗多图：各层原始帧 → 合成画布 → 渲染层出图（compat/alpha 同一入口）
            for i, ld in enumerate(layers):
                if i == 0:
                    continue
                self._layer_raw.append(self._layer_raw_frame(i, ld, Image))
            self._compose_into_renderer(layers)
        else:
            # 窗口透明色 / 背景 / Label 底色全部跟随动态键色（渲染层统一应用：
            # compat = -transparentcolor + 键色底；alpha = 推分层位图）
            renderer.apply_window(self.key_rgb)
            renderer.apply_label(getattr(self, 'label', None), self.img, self.key_rgb)
            self.w, self.h = self.img.width(), self.img.height()
        self.layer = self.cfg.get('layer', 'above')  # 热重载/切皮肤/缩放重载后同步图层配置
        # 新图已挂上 Label，再释放旧帧序列的 tcl image（避免切换瞬间画布指向已删 image）
        for _p in old_frames:
            renderer.release(_p)
        if self.anim_n > 1:
            self._anim_start()

    # ---------- 动图播放（v1.6）----------
    def _pick_anim_key(self, Image, n):
        """动图抠色键：多帧颜色并集（帧多则均匀采样，始终含首帧）"""
        src = self.anim_src
        imgs = []
        for i in _sample_frame_indices(n, ANIM_KEY_SAMPLE):
            try:
                src.seek(i)
                imgs.append(src.convert('RGBA'))
            except Exception:
                break
        try:
            src.seek(0)
        except Exception:
            pass
        if not imgs:
            return MAGENTA
        return _renderer_of(self).pick_key(imgs, Image)

    def _sync_render_mode(self):
        """切皮肤后同步渲染层（render_mode 是全局渲染开关，不属于皮肤参数）。

        规则：皮肤档案**显式**声明 render_mode 才采纳；缺键（老档案）保持当前全局值 ——
        否则 skin.json 里没有该键的老皮肤一被切过去就会把 alpha 用户莫名打回 compat。
        """
        cfg = self.cfg if isinstance(self.cfg, dict) else {}
        mode = resolve_render_mode(cfg) if 'render_mode' in cfg else self.render_mode
        if mode != self.render_mode:
            old = _renderer_of(self)
            if mode == 'compat' and hasattr(old, 'clear'):
                old.clear()      # 让出显示权前清空分层窗内容，避免旧位图残留
            self.render_mode = mode
            self.renderer = create_renderer(self, cfg, mode)
            try:
                _write_log(f'[渲染] 皮肤档案声明 render_mode={mode} → 切换渲染器')
            except Exception:
                pass
        else:
            _renderer_of(self).cfg = cfg   # 换的是同一个全局开关 → 只更新 cfg 引用
        return self.render_mode

    def _decode_frame_rgba(self, idx):
        """按需解码单帧到 **RGBA**（seek → RGBA → 缩放 → 特效），不做抠色。

        v2.0-② 拆出的中间层：多图层合成必须在抠色之前拿到原始帧，所以先解码到 RGBA，
        再由 _decode_frame（单层老路径）走渲染层 prepare —— 老路径行为逐位不变。
        实现放在模块级函数里：测试桩对象（只有 _Image/anim_src/_base_h）直接调
        _decode_frame 时也不必补齐本方法。
        """
        return decode_anim_frame_rgba(self, idx)

    def _decode_frame(self, idx):
        """按需解码单帧：seek → RGBA → 缩放 → 抠色（渲染层）→ PhotoImage（不写 self.img）。"""
        img = decode_anim_frame_rgba(self, idx)
        if img is None:
            return None
        return _renderer_of(self).prepare(img, self.key_rgb, self._Image)

    def _get_frame(self, idx):
        """取帧（LRU 缓存，上限 ANIM_CACHE_MAX 张）：命中即置为最近使用，
        未命中则解码并按 FIFO 淘汰最旧（永不淘汰当前显示帧）。"""
        idx = idx % self.anim_n
        if idx in self._frame_cache:
            self._frame_cache.move_to_end(idx)
            return self._frame_cache[idx]
        while len(self._frame_cache) >= ANIM_CACHE_MAX:
            if len(self._frame_cache) == 1:
                break                      # 只剩当前显示帧，宁可多留一帧
            old_idx = next(iter(self._frame_cache))
            if old_idx == self.anim_idx:
                self._frame_cache.move_to_end(old_idx)   # 当前显示帧保底，改淘汰下一个
                continue
            _renderer_of(self).release(self._frame_cache.pop(old_idx))
        photo = self._decode_frame(idx)
        if photo is None:
            return getattr(self, 'img', None)
        self._frame_cache[idx] = photo
        return photo

    def _on_root_destroy(self, event=None):
        """root 销毁前取消动画 after（只在 root 自己身上触发时动作）"""
        try:
            if event is not None and getattr(event, 'widget', None) is not self.root:
                return
            self._anim_stop()
        except Exception:
            pass

    def _graceful_quit(self):
        """体面退出（右键菜单 / Ctrl+Alt+Q / 托盘退出 / 外部 WM_CLOSE 共用）：
        停动画节拍 → 收托盘图标 → 销毁窗口，让 run() 的 finally 正常释放事件线程。"""
        global _ACTIVE_OVERLAY
        _write_log('[退出] 体面退出')
        if _ACTIVE_OVERLAY is self:
            _ACTIVE_OVERLAY = None
        try:
            self._anim_stop()
        except Exception:
            pass
        try:
            if getattr(self, 'tray', None):
                self.tray.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _anim_start(self):
        self._anim_stop()
        if self.anim_n > 1:
            self.anim_idx = 0
            self._schedule_anim(0)

    def _anim_stop(self):
        h = getattr(self, 'anim_after', None)
        if h:
            try:
                self.root.after_cancel(h)
            except Exception:
                pass
            self.anim_after = None

    def _schedule_anim(self, delay_ms):
        try:
            self.anim_after = self.root.after(int(delay_ms), self._anim_tick)
        except Exception:
            self.anim_after = None

    def _anim_tick(self):
        """动图播放节拍：窗口隐藏 → 暂停（仅低频探活，CPU 最大省钱点）；
        显示 → 推进到下一帧并按该帧时长重排，顺带预解下下帧消 seek 卡顿。"""
        self.anim_after = None
        if self.anim_n <= 1:
            return
        try:
            if not self.visible:
                self._schedule_anim(ANIM_HIDDEN_POLL_MS)
                return
            src = self.anim_src
            nxt = (self.anim_idx + 1) % self.anim_n
            try:
                src.seek(nxt)
                dur = _frame_duration(src)
            except Exception:
                dur = 100
            self.anim_idx = nxt
            if self._layers_active():
                # ② 套层 + 动图：第 0 层换帧 → 整张画布重新合成（其余层静止），
                # 抠色键沿用 load_char 时算好的值（多帧颜色并集），不每帧重算
                fr = self._decode_frame_rgba(nxt)
                if fr is not None:
                    raws = getattr(self, '_layer_raw', None)
                    if raws:
                        raws[0] = fr
                    self._compose_into_renderer(key=self.key_rgb, apply=False)
                    self._push_render_frame()
                self._schedule_anim(dur)
                return
            photo = self._get_frame(nxt)
            if photo is not None:
                self.img = photo
                # 换帧走渲染层（compat = 贴 Label；alpha 实装后 = 推分层位图）
                _renderer_of(self).apply_photo_only(getattr(self, 'label', None), photo)
            self._prefetch(nxt)
            self._schedule_anim(dur)
        except Exception as e:
            try:
                _write_log(f'[_anim_tick] 异常: {e}')
            except Exception:
                pass
            self._schedule_anim(200)

    def _prefetch(self, idx):
        """预解下一帧（最多再解 1 帧，单帧开销 15-30ms，不影响 15-30fps）"""
        try:
            if self.anim_n > 1:
                self._get_frame((idx + 1) % self.anim_n)
        except Exception:
            pass

    # ---------- 多皮肤 ----------
    def apply_skin(self, name):
        """切换皮肤：整套参数（图片/布局/贴边/缩放/偏移）恢复，保持当前位置"""
        cfg = find_skin(name)
        if not cfg:
            return False
        self.cfg = cfg
        # 渲染层同步：皮肤档案显式声明 render_mode 才切换，缺键保持全局开关（见 _sync_render_mode）
        self._sync_render_mode()
        self.load_char()
        _write_log(f'[皮肤] 切换到 {name} image={cfg.get("image")}')
        self._sync_tk_geometry()  # 尺寸变化：低频 geometry 同步镜像坐标（与 SetWindowPos 镜像一致）
        # 图层同步：切皮肤后候选框在场 → 重插层级（layer/side 可能已随皮肤变化）
        self._sync_layer_with_candidate()
        # S1 修复：切换后持久化，重启仍用当前皮肤
        try:
            save_config(self.cfg)
        except Exception:
            pass
        # ③ 配色联动：该皮肤绑定了 Rime 配色名 → 切候选框配色 + 重部署（未绑定则静默跳过）
        try:
            self._bind_rime_scheme(cfg)
        except Exception as _e:
            _write_log(f'[配色] 皮肤 {name} 绑定异常: {_e}')
        # S3 修复：同步托盘菜单选中态缓存（pystray 线程读，不直接碰主线程 cfg）
        try:
            if self.tray:
                self.tray._cur_name = name
        except Exception:
            pass
        return True

    def _bind_rime_scheme(self, cfg):
        """③ 切皮肤时把该皮肤绑定的 Rime 配色名写回 weasel.custom.yaml 并重部署。

        未绑定（cfg 无 rime_scheme）→ 静默跳过、不碰任何文件（老用户零感知）。
        返回 (ok, msg)；失败只记日志，不让切皮肤崩掉。
        """
        try:
            r = apply_rime_scheme_binding(cfg)
            _write_log(f'[配色] 皮肤 {cfg.get("name", "")}: {r["msg"]}')
            return bool(r.get('ok')), r.get('msg', '')
        except Exception as e:
            _write_log(f'[配色] 皮肤绑定失败: {e}')
            return False, str(e)

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
                    _renderer_of(self).apply_photo_only(self.label, self.img)
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
        # 拖动中位图要跟着走（alpha）；compat 下无操作
        self._push_render_frame()
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
            _renderer_of(self).apply_photo_only(self.label, self.img)
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
            # 手动显示（可能无候选框、_position_once 没推）→ 补推一次位图（compat 无操作）
            self._push_render_frame()
        else:
            self.root.withdraw()
            self.visible = False

    def open_wizard(self):
        """打开配置向导（托盘与后台全程保持）。

        向导作为独立窗口打开（双 Tk 嵌套 mainloop，overlay 的跟随/托盘不受影响）：
        - 保存新配置 → 替换当前实例（停托盘、关窗口、启动新配置的 overlay）
        - 取消/关闭向导 → 什么都不动，外挂继续后台运行
        - 单实例守卫：连点托盘/右键菜单只保留一个配置窗，后到的把已有窗提到前面
          （否则每次点击都会排队开一个新向导 → 「托盘多点几次多出几个程序」）
        """
        w = getattr(self, '_wizard', None)
        if w is not None:
            try:
                w.root.deiconify()
                w.root.lift()
                w.root.focus_force()
                return
            except Exception:
                self._wizard = None

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
            self._wizard = wizard
            wizard.root.mainloop()
        except Exception:
            pass
        finally:
            self._wizard = None

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

    def _push_render_frame(self):
        """渲染层重推（v2.0-①b）：移动/缩放/显隐之后让分层窗位图跟上。

        compat 模式下 on_moved 是空操作（显示由 Tk Label 承担），所以这里无条件调用，
        不需要在调用点再判断 render_mode —— 老路径行为零变化。
        """
        try:
            _renderer_of(self).on_moved()
        except Exception as e:
            try:
                _write_log(f'[渲染] 重推位图失败: {e}')
            except Exception:
                pass

    def _sync_tk_geometry(self):
        """低频（尺寸变化/手动交互后）把镜像坐标同步回 Tk：
        SetWindowPos 直移后 Tk 内部 winfo_x/y 可能过时，凡 w/h 变化
        （切皮肤/滚轮缩放/热重载）都必须用一次 geometry 校正，否则 Tk
        下次布局/update 会把窗口拉回旧位置，与事件定位打架。
        geometry 仅在此类低频路径使用；高频跟随一律 SetWindowPos。"""
        try:
            self.root.geometry(f'{self.w}x{self.h}+{int(self._x)}+{int(self._y)}')
            self._applied_size = (int(self.w), int(self.h))   # R3：geometry 也是真改窗口尺寸
        except Exception:
            pass
        # 尺寸/位置变了 → alpha 下位图要重推一次（compat 无操作）
        self._push_render_frame()

    def _cached_hwnd_ok(self):
        """缓存句柄仍有效：窗口存在且可见（O(1)，无枚举）。"""
        try:
            return bool(self._cached_hwnd) and bool(user32.IsWindow(self._cached_hwnd)) \
                and bool(user32.IsWindowVisible(self._cached_hwnd))
        except Exception:
            return False

    def _calc_target(self, rect):
        """候选框 rect → 贴边目标 (x, y)（逻辑与改造前一致，含用户微调偏移）。

        v2.0-②：改为委托 _calc_layer_targets —— 单图层时两者逐位相同（B_test 守），
        多图层时这里返回的是「合成画布」的左上角（全部图层的包围盒原点）。
        """
        wx, wy, _ww, _wh, _pl = self._calc_layer_targets(rect)
        return int(wx), int(wy)

    # ---------- ② 套层皮肤：多图层布局（v2.0）----------
    def _layer_specs(self):
        """当前 cfg 解析出的图层列表（运行时形态：键齐全、路径已解析）。"""
        try:
            return resolve_layers(self.cfg if isinstance(self.cfg, dict) else {})
        except Exception:
            return []

    def _layers_active(self):
        """是否走「单窗多图合成」路径。只有 >1 层才启用 —— 单层严格退化为 v1.6 老路径。"""
        try:
            return bool(self.PIL) and len(self._layer_specs()) > 1
        except Exception:
            return False

    def _layout_rect(self):
        """布局参考矩形：优先当前缓存候选框的真实矩形；没有则用上次已知的，再退化为空矩形。

        空矩形（0,0,0,0）只影响"首次加载时画布多大"—— 每次定位都会用真 rect 重算，
        所以无候选框时算出来的画布尺寸不会漏到屏幕上。
        """
        try:
            if self._cached_hwnd and user32.IsWindow(self._cached_hwnd):
                r = wintypes.RECT()
                if user32.GetWindowRect(self._cached_hwnd, ctypes.byref(r)):
                    self._last_rect = (int(r.left), int(r.top), int(r.right), int(r.bottom))
                    return self._last_rect
        except Exception:
            pass
        return getattr(self, '_last_rect', None) or (0, 0, 0, 0)

    def _layer_display_size(self, path, base_h, Image):
        """单层按 base_h 缩放后的显示尺寸（与 _layer_raw_frame / load_char 同一口径）。

        只在缓存未命中时调用 → 每个 (图, 缩放) 组合一生只付一次「open+解码+LANCZOS」的钱。
        """
        try:
            with Image.open(path) as _im:
                src = _im.convert('RGBA')
            if src.height > 0:
                ratio = base_h / src.height
                src = src.resize((max(1, int(src.width * ratio)), max(1, int(base_h))),
                                 Image.LANCZOS)
            return int(src.size[0]), int(src.size[1])
        except Exception:
            return 0, 0

    def _layer_dims(self, Image=None, layers=None):
        """各图层的显示尺寸 [(w,h), ...]（与 load_char 同一缩放口径：高度 = base_height×scale）。

        R3：结果按 (图路径, base_height×scale) 缓存 —— 尺寸只随「图/缩放」变，不随时间变。
        缓存前这里是定位路径上最大的一笔开销：每帧每层一次 Image.open + 解码 + LANCZOS
        缩放（实测 3 层 400x600 ≈ 30ms/帧），而定位节拍只有 16ms → 图永远慢候选框一拍。
        失效点：load_char（唯一入口）清空缓存；缓存按本次用到的键裁剪，不会随皮肤切换涨。
        只缓存**量成功**的结果：坏图/缺图保持改造前的「每帧重试」语义（F3 已知遗留），
        一旦图恢复可用（或用户重选图 → load_char）就能自动补上，不会把一次失败钉死。
        """
        Image = Image or getattr(self, '_Image', None)
        layers = layers if layers is not None else self._layer_specs()
        if Image is None:
            return []
        base_h = self.cfg.get('base_height', 300)
        cache = getattr(self, '_dims_cache', None)
        if cache is None:
            cache = self._dims_cache = {}
        out, live = [], set()
        for ld in layers:
            path = str(ld.get('image') or '')
            bh = base_h * float(ld.get('scale', 1.0) or 1.0)
            key = (path, round(bh, 4))
            wh = cache.get(key)
            if wh is None:
                wh = self._layer_display_size(path, bh, Image)
                if wh[0] > 0 and wh[1] > 0:
                    cache[key] = wh
            live.add(key)
            out.append(wh)
        if len(cache) != len(live):
            for k in [k for k in cache if k not in live]:
                cache.pop(k, None)
        return out

    def _layer_plan(self, rect):
        """一帧的布局三件套 (layers, dims, plan) —— 同一帧只解析一次，供定位与合成共用。

        R3 关键点：定位（窗口落位）与合成（画布内各层落点）必须用**同一份 rect 快照**。
        以前合成自己再调 _layout_rect() 重新读一次候选框矩形，而两次读之间隔着 N 次图层
        解码（实测 15~44ms）—— 打字时候选框在这期间移动/变宽，就会出现「窗口按旧矩形、
        画面按新矩形」的整层错位（实测差 40px）。
        """
        layers = self._layer_specs()
        if self._layers_active():
            dims = self._layer_dims(self._Image, layers)
        else:
            dims = [(int(getattr(self, 'w', 0) or 0), int(getattr(self, 'h', 0) or 0))]
        plan = plan_layer_layout(layers, dims, rect,
                                 main_off=(getattr(self, 'off_x', 0), getattr(self, 'off_y', 0)))
        return layers, dims, plan

    def _calc_layer_targets(self, rect):
        """② 步 3：一次算出全部图层的目标坐标（返回窗口位置/尺寸 + 各层画布内偏移）。

        单图层时窗口尺寸取 self.w/self.h（与 v1.6 的 PhotoImage 尺寸同源），
        保证 _calc_target 结果与改造前逐位一致 —— 老路径零漂移。
        """
        return self._layer_plan(rect)[2]

    def _plan_targets(self, rect):
        """候选框 rect → 本次要应用的 (x, y, w, h, size_changed)。

        单层：w/h 返回 None → _move_to 走 SWP_NOSIZE（与 v1.6 逐位一致），size_changed 恒 False。
        多层：w/h = 合成画布尺寸；只有「布局指纹」变了才重合成（尺寸或各层落点变化 ——
        候选框纯平移不重合成，因为平移不改变画布内相对落点），并同步一次 Tk geometry 记账。

        size_changed 的判据是「窗口当前尺寸 != 目标画布尺寸」，不是「画布重新合成过」——
        动图节拍会在不移动窗口的情况下换画布，两者混用会让窗口尺寸停摆（R3 修）。
        size_changed 必须回传给调用方：候选框"只变宽不移动"时窗口坐标一模一样，
        只看坐标的死区判断会把整条 resize 路径吞掉（实测窗口会停在旧宽度）。
        """
        layers, dims, plan = self._layer_plan(rect)
        wx, wy, ww, wh, pl = plan
        if not self._layers_active():
            return int(wx), int(wy), None, None, False
        ww, wh = int(ww), int(wh)
        if ww <= 0 or wh <= 0:
            # 布局算不出尺寸（所有图层图都缺失/尺寸为 0）→ 保持窗口现状，
            # 绝不能把 SetWindowPos 的 cx/cy 传 0（那会把窗口缩成一条线）
            return int(wx), int(wy), None, None, False
        plan_key = (ww, wh, tuple(pl))
        if plan_key != getattr(self, '_composed_plan', None):
            try:
                self._compose_into_renderer(layers, sizes=dims, rect=rect, plan_key=plan_key)
            except Exception as e:
                try:
                    _write_log(f'[套层] 候选框变宽后重合成失败: {e}')
                except Exception:
                    pass
            try:
                self.root.geometry(f'{ww}x{wh}+{int(wx)}+{int(wy)}')
            except Exception:
                pass
        size_changed = (ww, wh) != tuple(getattr(self, '_applied_size', None) or (0, 0))
        return int(wx), int(wy), ww, wh, size_changed

    def _rect_changed(self):
        """候选框矩形（位置或尺寸）与上次已应用的记录不同 → True（O(1) 一次 GetWindowRect）。

        v2.0-② 套层用：候选框"只变宽不移动"时 weasel 未必发 LOCATIONCHANGE 事件，
        心跳（200ms）用这个兜底把多图层窗口的宽度跟上 —— 单图层路径不查它，零影响。
        """
        r = self._read_cached_rect()
        if r is None:
            return False
        cur = (int(r.left), int(r.top), int(r.right), int(r.bottom))
        return cur != tuple(getattr(self, '_applied_rect', None) or ())

    def _layer_raw_frame(self, idx, ld, Image):
        """取第 idx 层的原始 RGBA 帧（缩放 + 特效后、抠色前）。命中 _layer_raw 缓存即复用。"""
        raws = getattr(self, '_layer_raw', None) or []
        if 0 <= idx < len(raws) and raws[idx] is not None:
            return raws[idx]
        try:
            with Image.open(ld.get('image')) as _im:
                src = _im.convert('RGBA')
            bh = self.cfg.get('base_height', 300) * float(ld.get('scale', 1.0) or 1.0)
            if src.height > 0:
                ratio = bh / src.height
                src = src.resize((max(1, int(src.width * ratio)), max(1, int(bh))),
                                 Image.LANCZOS)
            eff = ld.get('effects') or {}
            fx = dict(self.cfg)
            fx.update({k: eff.get(k) for k in ('corner_enabled', 'corner_radius',
                                               'feather_enabled', 'feather_radius')
                       if k in eff})
            fx['flip_h'] = False        # 翻转按「层」判定，不让顶层 flip_h 重复生效
            src = apply_display_effects(src, fx, Image)
            if ld.get('flip'):
                src = src.transpose(Image.FLIP_LEFT_RIGHT)
            return src
        except Exception:
            return None

    def _compose_frame(self, layers=None, sizes=None, out_frames=None, rect=None, plan_out=None):
        """② 步 4：把全部图层合成成一张 RGBA 画布（单窗多图，各层自身 alpha 保留）。

        返回 canvas（RGBA 图）；无有效图层时返回 None。
        out_frames 非空时回传各层原始帧（抠色键要用），避免重复解码。
        rect 非空时用调用方给的候选框矩形快照（定位路径必须传：同一帧只能有一个矩形），
        否则回退到自己读一次缓存句柄矩形（动图节拍/加载路径用）。
        plan_out 非空时回传本次布局指纹 (ww, wh, placements)，供调用方做「要不要重合成」的判断。
        """
        if not self.PIL:
            return None
        Image = self._Image
        layers = layers if layers is not None else self._layer_specs()
        if not layers:
            return None
        dims = sizes if sizes is not None else self._layer_dims(Image, layers)
        if rect is None:
            rect = self._layout_rect()
        wx, wy, ww, wh, pl = plan_layer_layout(
            layers, dims, rect,
            main_off=(getattr(self, 'off_x', 0), getattr(self, 'off_y', 0)))
        if ww <= 0 or wh <= 0:
            return None
        frames = [self._layer_raw_frame(i, ld, Image) for i, ld in enumerate(layers)]
        if out_frames is not None:
            out_frames.extend(frames)
        if plan_out is not None:
            plan_out.append((int(ww), int(wh), tuple(pl)))
        return compose_layers(frames, (ww, wh), pl, Image)

    def _compose_into_renderer(self, layers=None, key=None, apply=True, sizes=None, rect=None,
                               plan_key=None):
        """合成 → 交给渲染层出图（compat = 键色抠色 + Label；alpha = 保留 RGBA 推位图）。

        这是 ② 与 ① 的接口点：合成只做一次，抠色/贴图/推位图的差别全部留在 Renderer 里。
        key 给定则复用现有抠色键（动图逐帧不重算，避免每帧统计颜色）；
        apply=False 表示窗口级设置不动，只换帧（动图节拍路径）。
        sizes/rect/plan_key 由定位路径传入：同一帧共用一份布局输入（R3：防「窗口按旧矩形、
        画面按新矩形」的错位），并让「已合成布局」记账与实际合成保持一致。
        """
        renderer = _renderer_of(self)
        frames = []
        plan_out = []
        canvas = self._compose_frame(layers, sizes=sizes, out_frames=frames, rect=rect,
                                     plan_out=plan_out)
        if canvas is None:
            return None
        if plan_key is not None:
            self._composed_plan = tuple(plan_key)
        elif plan_out:
            self._composed_plan = plan_out[-1]
        if key is not None:
            self.key_rgb = key
        else:
            raws = [r for r in frames if r is not None]
            self.key_rgb = renderer.pick_key(raws or [canvas], self._Image)
        flat = renderer.flatten(canvas, self.key_rgb, self._Image)
        self.raw_img = flat.copy() if hasattr(flat, 'copy') else flat
        old = getattr(self, 'img', None)
        self.img = renderer.to_photo(flat)
        if apply:
            renderer.apply_window(self.key_rgb)
            renderer.apply_label(getattr(self, 'label', None), self.img, self.key_rgb)
        else:
            renderer.apply_photo_only(getattr(self, 'label', None), self.img)
        try:
            self.w, self.h = self.img.width(), self.img.height()
        except Exception:
            self.w, self.h = canvas.size
        self._canvas_size = (int(self.w), int(self.h))
        if old is not None:
            renderer.release(old)
        return canvas

    def _move_to(self, x, y, w=None, h=None):
        """主定位路径：SetWindowPos 一次完成「移动 + HWND_TOPMOST」，
        顺带 SWP_NOACTIVATE。窗口显示/隐藏统一由 deiconify/withdraw 管理
        （避免 Tk withdraw 状态与 SWP_SHOWWINDOW 状态机打架）。
        维护 _x/_y 镜像（Tk 的 winfo 在此之后可能过时，以镜像为准）。

        v2.0-②：多图层时 w/h 给出「合成画布」尺寸 → 一次 SetWindowPos 同时移动 + 改尺寸
        （候选框变宽时画布跟着变宽，两侧图层自然拉开，无中间态、无残影）。
        单图层时 w/h 不传 → 严格保持 v1.6 的 SWP_NOSIZE 行为。
        """
        top = self._top_hwnd()
        if not top:
            return False
        try:
            if w is None or h is None:
                ok = user32.SetWindowPos(top, HWND_TOPMOST, int(x), int(y), 0, 0,
                                         SWP_NOACTIVATE | SWP_NOSIZE)
            else:
                ok = user32.SetWindowPos(top, HWND_TOPMOST, int(x), int(y), int(w), int(h),
                                         SWP_NOACTIVATE)
        except Exception:
            return False
        if ok:
            self._x, self._y = int(x), int(y)
            if w is not None and h is not None:
                self._applied_size = (int(w), int(h))   # R3：窗口尺寸记账（判 size_changed 用）
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
                        x, y, w, h, size_changed = self._plan_targets(rect)
                        self._applied_rect = (int(rect.left), int(rect.top),
                                              int(rect.right), int(rect.bottom))
                        # 死区：窗口已显示、位置变化 <2px 且画布尺寸未变 → 不移动
                        # （省一次系统调用与重绘；尺寸变了必须走完整路径，否则窗口停在旧宽度）
                        if (self.visible and not size_changed
                                and abs(x - self._x) < 2 and abs(y - self._y) < 2):
                            self._apply_layer(self._cached_hwnd)  # 成功定位后同步图层（事件驱动，频率低）
                            return True
                        moved = self._move_to(x, y, w, h)
                        self._pos_dirty = False
                        if not self.visible:
                            self.root.deiconify()
                            self.visible = True
                        if PERF_LOG_ENABLED and moved:
                            _perf_log(f'  ├ SetWindowPos -> ({x},{y})')
                        self._push_render_frame()  # 移动/首显后重推位图（compat 无操作）
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
        """SHOW 事件候选句柄直挂（免全扫）：与全扫共用 _is_candidate_window 统一判定。
        v1.6 修复误贴：原直挂路径缺 ATL: 类名约束，Electron/Edge 菜单与网址提示浮层、
        explorer 浮层等非候选小窗在候选框空缺时 SHOW 即被直挂（见 B_test_misdetect_diag）。"""
        try:
            if not hwnd or not user32.IsWindowVisible(hwnd):
                return False
            if not _is_candidate_window(hwnd):
                return False
            self._cached_hwnd = hwnd
            set_candidate_hwnd(hwnd)
            self._hide_since = None
            self._pos_dirty = True
            _write_log(f'[候选框] SHOW 直挂 hwnd=0x{hwnd:X} {_describe_window(hwnd)}')
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
        hwnd, rect = win
        if hwnd != self._cached_hwnd:
            self._cached_hwnd = hwnd
            set_candidate_hwnd(hwnd)
            _write_log(f'[候选框] 命中 hwnd=0x{hwnd:X} {_describe_window(hwnd)}')
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
                elif self._layers_active() and self._rect_changed():
                    # ② 套层兜底（v2.0-②）：候选框只改宽度（候选数变化）时事件可能不到，
                    # 心跳发现矩形变了就补一次定位 → 两侧图层最多晚 200ms 拉开/收拢。
                    # 单图层不查（_layers_active() 先短路），v1.6 行为零变化。
                    self._position_once(allow_scan=False)
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
    """写关键操作日志到 exe 同目录 error.log（带时间戳；超 256KB 自动轮转）。

    只记关键点：启动/退出、配置保存、切皮肤、预处理、自启开关、清理、候选框首次命中、
    异常（含 traceback）。日常打字/跟随/移动不记，所以长期用也不会膨胀。
    """
    try:
        path = os.path.join(HERE, 'error.log')
        try:
            if os.path.getsize(path) > 256 * 1024:
                bak = path + '.1'
                if os.path.exists(bak):
                    os.remove(bak)
                os.rename(path, bak)
        except OSError:
            pass
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n')
    except Exception:
        pass


def _log_env(tag='启动'):
    """记录环境指纹：版本/打包形式/Python/系统/DPI/参数 —— 事后按日志就能复现大半"""
    try:
        import platform
        dpi = ''
        try:
            g32 = ctypes.windll.gdi32
            dc = ctypes.windll.user32.GetDC(0)
            dpi = f' dpi={g32.GetDeviceCaps(dc, 90)}'   # LOGPIXELSY（gdi32）
            ctypes.windll.user32.ReleaseDC(0, dc)
        except Exception:
            pass
        _write_log(f'[{tag}] {VERSION} frozen={getattr(sys, "frozen", False)} '
                   f'python={sys.version.split()[0]} os={platform.platform()}{dpi} '
                   f'cwd={os.getcwd()} argv={sys.argv[1:]}')
    except Exception:
        pass


def _human_size(n):
    try:
        n = float(n)
    except Exception:
        return '?'
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024.0

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
        # 启动即写日志（环境指纹：版本/打包形式/系统/DPI/参数 —— 事后按日志就能复现大半）
        _log_env('启动')
        argv = [a for a in sys.argv if not a.startswith('--')]
        # --tray：开机自启专用（静默启动到托盘，不弹选择框/不显示窗口）
        tray_mode = '--tray' in sys.argv
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
            if tray_mode:
                # 自启模式：已有实例就静默退出（开机重复触发不打扰），否则直接后台跑到托盘
                if _already_running():
                    _write_log('[启动] --tray 已有实例在跑，静默退出')
                    return
                _write_log(f'[启动] --tray 静默启动到托盘: {cfg}')
                FollowOverlay(cfg).run()
                return
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

        # 无配置 → 直接弹向导（保存后若已有实例则替换）；--tray 下不弹（开机不该蹦出配置窗）
        if tray_mode:
            _write_log('[启动] --tray 尚无配置，静默退出')
            return

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
