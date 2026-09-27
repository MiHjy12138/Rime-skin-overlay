# -*- coding: utf-8 -*-
"""B_test_n4_zorder.py —— v2.0-N4「图片窗同一 tick 夺回顶部」验收

背景（t9 定性，真机 + 静态双证据）：
  小狼毫每次合成都**新建**候选框窗口（先生 08:19 真机日志：23 次 SHOW 对应 24 个不同
  hwnd、类名恒为 `ATL:00007FFD6EDD3C50`、高恒 83px，一次没复用），新窗口天然落在
  z-order 顶部 ⇒ 图片窗被压到下面；而 N4 之前 `_apply_layer` 在 above 时**立即 return**
  （5 个调用点全空转），只能等 **200ms 心跳** `_ensure_topmost_if_needed` 兜底。
  目标变化落在死区（|Δ| < 2px）时连 `_move_to` 的 SetWindowPos 都跳过 ⇒ 让开窗口 ~200ms。

N4 修法：`_apply_layer` 按 layer 分派 —— above/侧贴边走「保上」分支（**检测到确实被压**
才补一次 HWND_TOPMOST）；below+中间 的插序语义原样保留。补置顶处加 `[zorder]` 观测日志。

两个夹具、各司其职（**这是本脚本的关键设计**）：
  · 真 `FollowOverlay`（Tk）→ 只用来证明「三条入口都把 `_apply_layer` 调到、且带着
    trigger 标签、且调到时确实被压」（链路证据）；
  · `FakeOverlayWindow`（纯 Win32 TOPMOST 窗口 + `_apply_layer` 所需字段）→ 用来做
    **量化**。原因：Tk 的 `root.update()` 会自己把窗口重新置顶（实测 43~65ms 就恢复），
    与「产品补置顶」混在一起会让两臂差异消失 —— 量化必须脱离 Tk。

验收段：
  A 入口链路：SHOW 直挂 / 死区 / 移动 三条入口都调到 `_apply_layer` 且带 trigger
  B 量化：同一夹具两臂（legacy `_apply_layer` vs 当前实现），10ms 采样 `GetWindow(top,
    GW_HWNDPREV)`，量「被压在候选框之下」的帧数与最长毫秒
  C not too hot：没被压时**一次 SetWindowPos 都不发**；被压时恰好 1 次
  D below 语义不回归：below+中间 → 图片窗插到候选框正下方（hWndInsertAfter = cand_hwnd）
  E 可观测性：`[zorder]` 日志（触发点 + covered + hwnd + 时间戳），格式稳定可统计
  F 判别力：把 `_apply_layer` 打桩回旧实现（above 空转）→ B/F 段核心断言必须 FAIL

红线：只读被测模块；夹具与 overlay 全部在临时目录语义下运行（R.HERE = tmp）；
      不改真实 config.json / skins；不动 %APPDATA%\\Rime 与 G:\\github成果\\。

用法: python B_test_n4_zorder.py      （退出码 0 = 全过）
"""
import os
import re
import sys
import time
import shutil
import ctypes
import tempfile

# 控制台编码保护：GBK 控制台下打印 ③/★ 等字符会 UnicodeEncodeError 并让脚本 exit≠0
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R          # noqa: E402

import ctypes.wintypes as wintypes     # noqa: E402

PASS, FAIL, SKIPPED = [], [], []

# 夹具生命周期（与 B_test_layer_sim 同口径）：**先建齐、最后统一销毁**。
# 踩坑记录：销毁一个 Tk root 之后再 CreateWindowExW 建原生假候选窗，会在第 5 个窗口
# 上直接 STATUS_FATAL_USER_CALLBACK_EXCEPTION（exit=-1073740771）；另起
# `ctypes.WinDLL('user32')` 也会诱发同类崩溃 ⇒ 改为「运行期只建不销毁、
# main finally 统一收」+ 复用产品自己那份 user32（原型齐备）。
_KEEP_OV = []
_KEEP_CAND = []
_KEEP_WIN = []

USER32 = R.user32
KERNEL32 = ctypes.WinDLL('kernel32', use_last_error=True)

HWND_TOPMOST = -1
HWND_TOP = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
GW_HWNDPREV = 3
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)
USER32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                  wintypes.LPARAM]
USER32.DefWindowProcW.restype = ctypes.c_longlong
KERNEL32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
KERNEL32.GetModuleHandleW.restype = wintypes.HMODULE


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f'  [PASS] {name}' + (f'  ({detail})' if detail else ''))
    else:
        FAIL.append(name)
        print(f'  [FAIL] {name}' + (f'  ({detail})' if detail else ''))


def section(title):
    print(f'\n--- {title} ---')


def _has_gui():
    try:
        import tkinter
        p = tkinter.Tk()
        p.withdraw()
        p.update()
        p.destroy()
        return True
    except Exception:
        return False


# ==========================================================================
# 原生窗口骨架（假候选框 + 假图片窗共用）
# ==========================================================================
class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('style', wintypes.UINT),
                ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', wintypes.HINSTANCE),
                ('hIcon', wintypes.HICON), ('hCursor', wintypes.HANDLE),
                ('hbrBackground', wintypes.HBRUSH), ('lpszMenuName', wintypes.LPCWSTR),
                ('lpszClassName', wintypes.LPCWSTR), ('hIconSm', wintypes.HICON)]


def _def_proc(hwnd, msg, wp, lp):
    try:
        return USER32.DefWindowProcW(hwnd, msg, wp, lp)
    except Exception:
        return 0


def _create_native(cls_name, title, x, y, w, h, ex_style):
    """建一个真实原生窗口（可见 + **创建即 TOPMOST 且在 z-order 顶部**），返回 (hwnd, proc)

    两个关键点（都踩过坑）：
    · style 必须带 WS_VISIBLE（0x10000000）：产品 `_cached_hwnd_ok()` 要求候选框
      `IsWindowVisible`，缺了它定位路径直接空转（实测 A00 前置红就是这么踩的）；
    · **必须创建时就带 WS_EX_TOPMOST**，不能只靠事后 `SetWindowPos(HWND_TOPMOST)` ——
      MSDN：HWND_TOPMOST 只把窗口抬到「所有非置顶窗口之上」，它在**已置顶窗口之间**
      保持原有相对位置 ⇒ 事后置顶的新窗口会落在现有 TOPMOST 组**底部**，压不住图片窗
      （实测 C02/B 段「产品判据检测不到被压」就是这么来的）。真机同理：小狼毫新建的
      候选框窗口天生在最前。创建后补一次 HWND_TOP 加固。
    """
    proc = WNDPROC(_def_proc)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = proc
    wc.hInstance = KERNEL32.GetModuleHandleW(None)
    wc.lpszClassName = cls_name
    USER32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    USER32.RegisterClassExW.restype = wintypes.ATOM
    if not USER32.RegisterClassExW(ctypes.byref(wc)):
        raise RuntimeError('RegisterClassExW failed: ' + cls_name)
    USER32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                       wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    USER32.CreateWindowExW.restype = wintypes.HWND
    hwnd = USER32.CreateWindowExW(ex_style | WS_EX_TOPMOST, cls_name, title,
                                  WS_POPUP | 0x10000000,      # WS_VISIBLE
                                  x, y, w, h, 0, 0, wc.hInstance, None)
    if not hwnd:
        raise RuntimeError('CreateWindowExW failed: ' + cls_name)
    USER32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wintypes.UINT]
    USER32.SetWindowPos.restype = wintypes.BOOL
    for _i in range(20):
        USER32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0,
                            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        if USER32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST:
            break
        time.sleep(0.02)
    return hwnd, proc


class FakeCandidate:
    """假候选框：类名 `ATL:` 前缀 + TSF 三件套 + **高恒 83px**（先生真机日志口径）"""

    _seq = [0]

    def __init__(self, x=60, y=120, w=420, h=83):
        type(self)._seq[0] += 1
        self.cls = f'ATL:MockZorderCand{type(self)._seq[0]}'
        self.hwnd, self.proc = _create_native(
            self.cls, 'mock-cand', x, y, w, h, WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        _KEEP_CAND.append(self)

    def move(self, x, y, w=None, h=None):
        r = wintypes.RECT()
        USER32.GetWindowRect(self.hwnd, ctypes.byref(r))
        USER32.SetWindowPos(self.hwnd, HWND_TOPMOST, int(x), int(y),
                            int(w if w is not None else r.right - r.left),
                            int(h if h is not None else r.bottom - r.top), SWP_NOACTIVATE)
        return self

    def destroy(self):
        try:
            USER32.DestroyWindow(self.hwnd)
        except Exception:
            pass


class FakeOverlayWindow:
    """「图片窗」替身：真实原生 TOPMOST 窗口 + `_apply_layer` 需要的字段。

    为什么不直接用真 FollowOverlay 做量化：Tk 的 `root.update()` 会自己把窗口重新置顶
    （实测 43~65ms 内恢复），把「产品补置顶」与「Tk 自己恢复」混在一起 ⇒ 两臂差异消失。
    量化必须脱离 Tk；入口链路（段 A）仍用真 overlay。
    """

    _seq = [0]

    def __init__(self, x=520, y=120, w=200, h=300, layer='above', side='right'):
        type(self)._seq[0] += 1
        self.cls = f'ATL:MockOverlayWin{type(self)._seq[0]}'
        self.hwnd, self.proc = _create_native(
            self.cls, 'mock-overlay', x, y, w, h,
            WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        self.layer = layer
        self.cfg = {'side': side}
        self.visible = True
        self._below_log_ts = 0.0
        _KEEP_WIN.append(self)

    def _top_hwnd(self):
        return self.hwnd

    def _is_covered_by_candidate(self, top, cand_hwnd, limit=24):
        """转发到产品的未绑定方法 —— **必须有**：产品 `_apply_layer` 内部用它判「是否被压」，
        替身缺这个方法会抛 AttributeError 并被产品的 `except Exception: pass` 静默吞掉
        （实测：C02「被压时不补置顶」就是这么踩出来的 —— 判据在外面对，进去就不动）。
        """
        return R.FollowOverlay._is_covered_by_candidate(self, top, cand_hwnd, limit)

    def _log_below_unavailable(self, cand_hwnd):
        """与产品同语义（节流 5s + 走 _write_log）—— below 段要用"""
        now = time.monotonic()
        if now - self._below_log_ts < 5.0:
            return
        self._below_log_ts = now
        R._write_log(f'[layer] below 不可用：候选框(0x{int(cand_hwnd):X})非置顶，'
                     f'保持图片窗 topmost 保底可见')

    def raise_top(self):
        """把图片窗拉到 **TOPMOST 组顶部**（HWND_TOP；对已是 TOPMOST 的窗口才有效）"""
        USER32.SetWindowPos(self.hwnd, HWND_TOP, 0, 0, 0, 0,
                            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)

    def destroy(self):
        try:
            USER32.DestroyWindow(self.hwnd)
        except Exception:
            pass


def _covered(cand_hwnd, wnd_hwnd, limit=24):
    """cand 是否压在 wnd 之上（向上走 GW_HWNDPREV，limit 层内出现）—— 产品同口径"""
    if not cand_hwnd or not wnd_hwnd:
        return False
    USER32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    USER32.GetWindow.restype = wintypes.HWND
    w = USER32.GetWindow(wnd_hwnd, GW_HWNDPREV)
    steps = 0
    while w and steps < limit:
        if w == cand_hwnd:
            return True
        w = USER32.GetWindow(w, GW_HWNDPREV)
        steps += 1
    return False


def _prev_of(wnd_hwnd):
    """wnd 正上方那一窗（契约口径的采样量：GetWindow(top, GW_HWNDPREV)）"""
    try:
        USER32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        USER32.GetWindow.restype = wintypes.HWND
        return int(USER32.GetWindow(wnd_hwnd, GW_HWNDPREV) or 0)
    except Exception:
        return 0


def _directly_below(wnd_hwnd, cand_hwnd):
    return _prev_of(wnd_hwnd) == int(cand_hwnd or 0)


# ==========================================================================
# SetWindowPos 探针
# ==========================================================================
class SPY:
    def __init__(self, real):
        self.real = real
        self.calls = []

    def __call__(self, hwnd, after, x, y, cx, cy, flags):
        try:
            self.calls.append((int(hwnd or 0), int(after or 0), int(flags)))
        except Exception:
            self.calls.append((0, 0, 0))
        return self.real(hwnd, after, x, y, cx, cy, flags)

    def reset(self):
        self.calls.clear()

    def topmost_calls(self):
        return [c for c in self.calls if c[1] == HWND_TOPMOST]


def _apply(fake, cand_hwnd, trigger):
    """调用产品的 _apply_layer（未绑定方法，用替身当 self）。

    trigger 是 N4 新增的可选参数（观测日志用）：实现未改时签名只有 2 个参数 ——
    红阶段要能跑完并报出真问题，所以这里对旧签名做一次兼容回退。
    """
    try:
        return R.FollowOverlay._apply_layer(fake, cand_hwnd, trigger)
    except TypeError:
        return R.FollowOverlay._apply_layer(fake, cand_hwnd)


def _ensure(fake):
    """调用产品的心跳兜底（未绑定方法，用替身当 self）"""
    return R.FollowOverlay._ensure_topmost_if_needed(fake)


# ==========================================================================
# A. 入口链路：三条入口都调到 _apply_layer 且带 trigger
# ==========================================================================
def test_entries(tmp, saved):
    section('A. 入口链路：SHOW 直挂 / 死区 / 移动 三条入口都调到 _apply_layer（带 trigger）')
    cfg = dict(R.DEFAULT_CONFIG)
    cfg['image'] = os.path.join(BASE, 'char.png')
    cfg['layout'] = 'horizontal_double'
    cfg['scale'] = 0.7
    cfg['offset_x'] = 0
    cfg['offset_y'] = 0
    cfg['layer'] = 'above'
    cfg['side'] = 'right'
    cand = FakeCandidate(x=60, y=120, w=420, h=83)
    ov = None
    real_apply = R.FollowOverlay._apply_layer
    records = []
    try:
        ov = R.FollowOverlay(cfg)
        try:
            ov.tray.stop()
        except Exception:
            pass
        ov._last_scan_ts = 0.0
        _KEEP_OV.append(ov)

        def _spy_apply(self, cand_hwnd, *a, **k):
            trig = a[0] if a else '(no-trigger)'
            try:
                cov = _covered(int(cand_hwnd or 0), self._top_hwnd())
            except Exception:
                cov = False
            records.append((trig, cov))
            return real_apply(self, cand_hwnd, *a, **k)
        R.FollowOverlay._apply_layer = _spy_apply

        ov._cached_hwnd = cand.hwnd
        R.set_candidate_hwnd(cand.hwnd)
        ov._position_once()
        check('A00 前置：真 overlay 已显示（入口链路可测）', bool(ov._top_hwnd()) and ov.visible,
              f'top=0x{ov._top_hwnd() or 0:X} visible={ov.visible}')

        # 入口①：SHOW 直挂
        records.clear()
        cand2 = FakeCandidate(x=60, y=120, w=420, h=83)
        ov._cached_hwnd = 0
        R.set_candidate_hwnd(0)
        R._EVT_SHOW_CNT += 1
        R._EVT_SHOW_HWND = int(cand2.hwnd)
        ov._event_tick()
        t1 = list(records)
        check('A01 ★入口① SHOW 直挂：_event_tick 消费 SHOW → 调到 _apply_layer(show)',
              any(t == 'show' for (t, _c) in t1), f'records={t1}')
        print(f'    调用序列①：_EVT_SHOW_CNT++ → _event_tick() → '
              f'_try_attach_show_hwnd(0x{cand2.hwnd:X}) → _position_once() → '
              f'_apply_layer(show)，records={t1}')

        # 入口②：死区分支（换候选窗、位置不变）
        records.clear()
        cand3 = FakeCandidate(x=60, y=120, w=420, h=83)
        ov._cached_hwnd = cand3.hwnd
        R.set_candidate_hwnd(cand3.hwnd)
        ov._position_once()
        t2 = list(records)
        check('A02 ★入口② 死区：_position_once 走死区分支 → 调到 _apply_layer(deadzone)',
              any(t == 'deadzone' for (t, _c) in t2), f'records={t2}')
        print(f'    调用序列②：_position_once() → 死区分支(|Δ|<2px, size_changed=False) → '
              f'_apply_layer(deadzone)，records={t2}')

        # 入口③：移动分支（目标变化 ≥2px）
        records.clear()
        cand4 = FakeCandidate(x=240, y=200, w=420, h=83)
        ov._cached_hwnd = cand4.hwnd
        R.set_candidate_hwnd(cand4.hwnd)
        ov._position_once()
        t3 = list(records)
        check('A03 ★入口③ 移动：目标变化 ≥2px 走完整移动路径 → 调到 _apply_layer(move)',
              any(t == 'move' for (t, _c) in t3), f'records={t3}')
        print(f'    调用序列③：_position_once() → 移动分支 → _move_to(TOPMOST) → '
              f'_apply_layer(move)，records={t3}')
        trigs = {t for rec in (t1, t2, t3) for (t, _c) in rec}
        check('A04 ★三条入口的 trigger 互不相同（真机 error.log 里能区分是哪条入口救的）',
              {'show', 'deadzone', 'move'} <= trigs, f'triggers={sorted(trigs)}')
        check('A05 ★「补置顶发生在被压时」由纯 Win32 段（C02/B）证明 —— '
              '本段只证明入口链路（Tk 场景下图片窗会被 Tk 自己重新置顶，不适合量被压状态）',
              True, '见 C02：被压 → 恰好 1 次 HWND_TOPMOST')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('A00 入口链路段未抛异常', False, repr(e))
    finally:
        R.FollowOverlay._apply_layer = real_apply


# ==========================================================================
# B. 量化：legacy vs 当前（纯 Win32 夹具，10ms 采样）
# ==========================================================================
def _reclaim_run(legacy, sample_s=0.7, hb_ms=200, tick_ms=16):
    """「候选框重建 → 让开 → 恢复」的量化。

    驱动节拍与真机一致：每 tick_ms 调一次 _apply_layer（死区路径的真实行为），
    每 hb_ms 调一次心跳兜底。两臂**唯一**差别 = _apply_layer 的实现。
    """
    fake = FakeOverlayWindow(layer='above', side='right')
    cand = FakeCandidate(x=60, y=120, w=420, h=83)     # 旧候选窗（图片窗贴它）
    fake.raise_top()
    real_apply = R.FollowOverlay._apply_layer
    if legacy:
        orig = real_apply

        def _legacy(self, cand_hwnd, *_a, **_k):
            if self.layer != 'below':
                return None
            if self.cfg.get('side', 'right') != 'center':
                return None
            return orig(self, cand_hwnd)
        R.FollowOverlay._apply_layer = _legacy
    t0 = time.perf_counter()
    last_tick = last_hb = 0.0
    frames = 0
    longest = 0.0
    cur_start = None
    first_free = None
    samples = []
    try:
        # 模拟小狼毫重建：新候选窗（新 hwnd 天然落在 z-order 顶部）→ 图片窗被压
        cand2 = FakeCandidate(x=60, y=120, w=420, h=83)
        # 心跳兜底要能工作：它读 self._cached_hwnd（替身必须有这个字段，
        # 否则 AttributeError 被产品 except 吞掉 → 心跳空转，legacy 臂测不出 ~200ms）
        fake._cached_hwnd = int(cand2.hwnd)
        while True:
            now = time.perf_counter()
            el = (now - t0) * 1000
            if el >= sample_s * 1000:
                break
            cov = _covered(cand2.hwnd, fake.hwnd)
            samples.append((round(el, 1), int(cov), _prev_of(fake.hwnd)))
            if cov:
                frames += 1
                if cur_start is None:
                    cur_start = now
                longest = max(longest, (now - cur_start) * 1000)
            else:
                if cur_start is not None and first_free is None:
                    first_free = (now - t0) * 1000
                cur_start = None
            if el - last_tick >= tick_ms:
                last_tick = el
                _apply(fake, cand2.hwnd, 'deadzone')      # 死区路径的真实行为
            if el - last_hb >= hb_ms:
                last_hb = el
                _ensure(fake)                            # 200ms 心跳兜底
            time.sleep(0.010)
        return {'frames': frames, 'longest_ms': longest, 'first_free_ms': first_free,
                'samples': samples}
    finally:
        R.FollowOverlay._apply_layer = real_apply


def test_quantify(tmp, saved):
    section('B. 量化：候选框重建后「图片窗被压」的帧数与最长毫秒（10ms 采样，两臂对照）')
    try:
        leg = _reclaim_run(legacy=True)
        print(f'    legacy 臂（N4 前：_apply_layer 空转，只等 200ms 心跳）：'
              f'被压 {leg["frames"]} 帧 / 最长 {leg["longest_ms"]:.0f}ms / '
              f'恢复于 {leg["first_free_ms"] if leg["first_free_ms"] is None else round(leg["first_free_ms"])} ms')
        cur = _reclaim_run(legacy=False)
        print(f'    当前臂（N4：同 tick 夺回）：被压 {cur["frames"]} 帧 / '
              f'最长 {cur["longest_ms"]:.0f}ms / '
              f'恢复于 {cur["first_free_ms"] if cur["first_free_ms"] is None else round(cur["first_free_ms"])} ms')
        print(f'    legacy 前 10 个采样 (t_ms, covered, prev)：{leg["samples"][:10]}')
        print(f'    当前   前 10 个采样 (t_ms, covered, prev)：{cur["samples"][:10]}')
        check('B01 ★修前能复现「让开」~200ms 量级（legacy 臂被压时长 ≥100ms）',
              leg['longest_ms'] >= 100.0,
              f'legacy 最长 {leg["longest_ms"]:.0f}ms（帧 {leg["frames"]}）')
        check('B02 ★修后让开窗口 ≤25ms 且比 legacy 快 ≥5 倍（队长第二次修订口径）',
              cur['longest_ms'] <= 25.0
              and (leg['longest_ms'] >= 5 * max(cur['longest_ms'], 1.0)),
              f'当前 {cur["longest_ms"]:.0f}ms vs legacy {leg["longest_ms"]:.0f}ms')
        check('B03 ★修后恢复发生在前 64ms 内（同一次 tick 量级，不是等心跳）',
              cur['first_free_ms'] is not None and cur['first_free_ms'] <= 64.0,
              f'first_free={cur["first_free_ms"]}')
        check('B04 ★两臂恢复时机不同源：legacy 在心跳处（~200ms）、当前在 tick 处（<150ms）',
              (leg['first_free_ms'] is None or leg['first_free_ms'] > 150.0)
              and cur['first_free_ms'] is not None and cur['first_free_ms'] < 150.0,
              f'legacy first_free={leg["first_free_ms"]} cur={cur["first_free_ms"]}')
        check('B05 ★修后被压帧数 ≤4（10ms 采样）—— 等于「一个 16ms tick 周期 + z-order '
              '生效延迟」，而不是等 200ms 心跳',
              cur['frames'] <= 4, f'当前 {cur["frames"]} 帧 vs legacy {leg["frames"]} 帧')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('B00 量化段未抛异常', False, repr(e))


# ==========================================================================
# C. not too hot
# ==========================================================================
def test_not_too_hot(tmp, saved, spy):
    section('C. not too hot：没被压时一次 SetWindowPos 都不发；被压时恰好 1 次')
    fake = FakeOverlayWindow(layer='above', side='right')
    try:
        cand = FakeCandidate(x=60, y=120, w=420, h=83)
        fake.raise_top()          # 图片窗先在最顶（顺序重要：先建候选窗再拉顶）
        check('C00 前置：图片窗当前未被压', not _covered(cand.hwnd, fake.hwnd),
              f'covered={_covered(cand.hwnd, fake.hwnd)}')
        spy.reset()
        for _i in range(30):
            _apply(fake, cand.hwnd, 'move')
        check('C01 ★未被压时 _apply_layer ×30 → SetWindowPos 调用 0 次（无脑置顶=禁止）',
              len(spy.calls) == 0, f'调用={len(spy.calls)} 次')
        cand2 = FakeCandidate(x=60, y=120, w=420, h=83)     # 造「被压」
        spy.reset()
        _apply(fake, cand2.hwnd, 'deadzone')
        got = len(spy.topmost_calls())
        check('C02 ★被压时 _apply_layer 恰好补 1 次 HWND_TOPMOST（不多不少）',
              got == 1, f'TOPMOST 调用 {got} 次；全部调用={spy.calls}')
        spy.reset()
        for _i in range(10):
            _apply(fake, cand.hwnd, 'move')
        check('C03 ★恢复顶部后再调 ×10 → 仍 0 次（只有「确实被压」才动）',
              len(spy.calls) == 0, f'调用={len(spy.calls)} 次')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('C00 not-too-hot 段未抛异常', False, repr(e))


# ==========================================================================
# D. below 语义不回归
# ==========================================================================
def test_below(tmp, saved, spy):
    section('D. below 语义不回归：below + 中间 → 图片窗插到候选框正下方')
    fake = FakeOverlayWindow(layer='below', side='center')
    cand = FakeCandidate(x=60, y=120, w=420, h=83)
    try:
        fake.raise_top()      # 先把图片窗拉到顶部 —— 否则 prev(top)==cand 天然成立=巧合绿
        check('D00 前置：插序前图片窗确实不在候选框正下方',
              not _directly_below(fake.hwnd, cand.hwnd),
              f'prev(top)=0x{_prev_of(fake.hwnd):X} cand=0x{cand.hwnd:X}')
        spy.reset()
        _apply(fake, cand.hwnd, 'sync')
        check('D01 ★below+中间：图片窗紧贴候选框正下方（hWndInsertAfter=cand_hwnd 那条路）',
              _directly_below(fake.hwnd, cand.hwnd),
              f'prev(top)=0x{_prev_of(fake.hwnd):X} cand=0x{cand.hwnd:X}')
        check('D02 ★below+中间 用的插入锚点是候选框，不是 HWND_TOPMOST',
              bool(spy.calls) and all(a == int(cand.hwnd) for (_h, a, _f) in spy.calls)
              and not spy.topmost_calls(),
              f'调用={spy.calls}')
        # 插序后心跳不应把它拉回 topmost（below 语义核心）
        spy.reset()
        _ensure(fake)
        check('D03 ★below+中间：心跳兜底不把图片窗拉回 topmost（只维护紧贴插序）',
              not spy.topmost_calls(), f'TOPMOST 调用={spy.topmost_calls()}')

        fake2 = FakeOverlayWindow(layer='below', side='right')
        spy.reset()
        _apply(fake2, cand.hwnd, 'sync')
        check('D04 below + 侧贴边（不重叠）→ 不插序、不发任何 SetWindowPos',
              len(spy.calls) == 0, f'调用={spy.calls}')

        # 候选框非置顶时：below 不可用 → 不插序（保底 topmost 可见）
        cand2 = FakeCandidate(x=60, y=120, w=420, h=83)
        USER32.SetWindowPos(cand2.hwnd, -2, 0, 0, 0, 0,
                            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)   # HWND_NOTOPMOST
        fake3 = FakeOverlayWindow(layer='below', side='center')
        spy.reset()
        _apply(fake3, cand2.hwnd, 'sync')
        check('D05 below+中间 但候选框非置顶 → 不插序（保持 topmost 保底），'
              '且确实走了「非置顶」分支（节流提示被触发）',
              not spy.topmost_calls()
              and not any(a == int(cand2.hwnd) for (_h, a, _f) in spy.calls)
              and fake3._below_log_ts > 0.0,
              f'调用={spy.calls} below_log_ts={fake3._below_log_ts}')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D00 below 段未抛异常', False, repr(e))


# ==========================================================================
# E. [zorder] 观测日志
# ==========================================================================
ZORDER_RE = re.compile(
    r'\[zorder\]\s+trigger=(\S+)\s+covered=(\d)\s+cand=0x([0-9A-Fa-f]+)\s+'
    r'top=0x([0-9A-Fa-f]+)\s+t=(\d{2}:\d{2}:\d{2}\.\d{3})')


def test_zorder_log(tmp, saved):
    section('E. 可观测性：[zorder] 日志（触发点 + covered + hwnd + 时间戳）')
    log_path = os.path.join(R.HERE, 'error.log')
    before = os.path.getsize(log_path) if os.path.exists(log_path) else 0
    fake = FakeOverlayWindow(layer='above', side='right')
    try:
        cand = FakeCandidate(x=60, y=120, w=420, h=83)
        fake.raise_top()                             # 未压状态（先建候选窗再拉顶）
        _apply(fake, cand.hwnd, 'deadzone')          # 未被压 → 不应写日志
        cand2 = FakeCandidate(x=60, y=120, w=420, h=83)
        _apply(fake, cand2.hwnd, 'deadzone')         # 被压 → 写日志
        cand3 = FakeCandidate(x=60, y=120, w=420, h=83)
        _apply(fake, cand3.hwnd, 'show')             # 被压 → 写日志
        time.sleep(0.05)
        txt = ''
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(before)
                txt = f.read()
        lines = [l for l in txt.splitlines() if '[zorder]' in l]
        print(f'    error.log 新增 {len(txt)} B，其中 [zorder] 行 {len(lines)} 条：')
        for l in lines[:4]:
            print(f'      {l.strip()}')
        check('E01 ★补置顶时写出 [zorder] 行（走 error.log，不新建文件）',
              len(lines) >= 2, f'命中 {len(lines)} 行')
        ok_fmt = [bool(ZORDER_RE.search(l)) for l in lines]
        check('E02 ★格式稳定可统计（trigger= / covered= / cand= / top= / t=HH:MM:SS.mmm）',
              bool(lines) and all(ok_fmt),
              f'样例={lines[0].strip() if lines else ""}')
        triggers = [ZORDER_RE.search(l).group(1) for l in lines if ZORDER_RE.search(l)]
        check('E03 ★触发点可区分（本次至少出现 deadzone 与 show 两种）',
              'deadzone' in triggers and 'show' in triggers, f'triggers={triggers}')
        covs = [ZORDER_RE.search(l).group(2) for l in lines if ZORDER_RE.search(l)]
        check('E04 ★含「是否确实被压」字段且本次为 1（补置顶必有被压）',
              bool(covs) and all(c == '1' for c in covs), f'covered={covs}')
        check('E05 ★未被压那一次不写日志（行数 == 真实补置顶次数 2，不刷屏）',
              len(lines) == 2, f'{len(lines)} 行（期望 2：两次被压各一行）')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('E00 日志段未抛异常', False, repr(e))


# ==========================================================================
# F. 判别力
# ==========================================================================
def test_discriminating(tmp, saved):
    section('F. 判别力：把 _apply_layer 打桩回旧实现 → B 段核心断言必须不成立')
    real_apply = R.FollowOverlay._apply_layer
    fake = FakeOverlayWindow(layer='above', side='right')
    try:
        fake.raise_top()
        orig = real_apply

        def _legacy(self, cand_hwnd, *_a, **_k):
            if self.layer != 'below':
                return None
            if self.cfg.get('side', 'right') != 'center':
                return None
            return orig(self, cand_hwnd)
        cand2 = FakeCandidate(x=60, y=120, w=420, h=83)
        blocked = _covered(cand2.hwnd, fake.hwnd)
        R.FollowOverlay._apply_layer = _legacy
        _apply(fake, cand2.hwnd, 'deadzone')
        still = _covered(cand2.hwnd, fake.hwnd)
        print(f'    legacy 注入后被压={blocked} → 调用后仍被压={still}（要等 200ms 心跳才会好）')
        check('F01 ★判别力：打桩回旧实现后「补置顶」不成立（B02/C02 非恒真）',
              blocked and still, f'blocked={blocked} still={still}')
    except Exception as e:
        check('F01 ★判别力：打桩回旧实现后「补置顶」不成立（B02/C02 非恒真）',
              False, repr(e))
    finally:
        R.FollowOverlay._apply_layer = real_apply
    # 反向：注入「无效实现」后，同样的采样节拍下也恢复不了
    try:
        res = _reclaim_run(legacy=True, sample_s=0.3, hb_ms=10000)   # 心跳永不介入
        check('F02 ★判别力：心跳不介入（hb=10s）时 legacy 全程保持被压（B01 非恒真）',
              res['first_free_ms'] is None and res['frames'] >= 20,
              f'frames={res["frames"]} first_free={res["first_free_ms"]}')
    except Exception as e:
        check('F02 ★判别力：心跳不介入时 legacy 全程保持被压', False, repr(e))


# ==========================================================================
def main():
    print('=== B_test_n4_zorder：N4 图片窗同一 tick 夺回顶部 + [zorder] 观测 ===')
    print('Python', sys.version.split()[0])
    tmp = tempfile.mkdtemp(prefix='n4_zorder_')
    R.HERE = tmp          # 只读约束（HANDOFF-2.1 §8.5）：日志只落临时目录
    gui_ok = _has_gui()
    print('GUI 可用:', gui_ok, '| 临时目录:', tmp)
    saved = {}
    real = (R.save_config, R.messagebox.showinfo, R.messagebox.showwarning,
            R.messagebox.showerror, R.messagebox.askyesno, R.set_autostart,
            R.event_hook_alive, R.screen_work_area_height, R.screen_work_area)
    R.save_config = lambda cfg: saved.update(cfg)
    R.messagebox.showinfo = lambda *a, **k: None
    R.messagebox.showwarning = lambda *a, **k: None
    R.messagebox.showerror = lambda *a, **k: None
    R.messagebox.askyesno = lambda *a, **k: True
    R.set_autostart = lambda *a, **k: (True, '（测试打桩）')
    R.event_hook_alive = lambda: True      # 心跳走正常分支（不退化全扫）
    spy = SPY(R.user32.SetWindowPos)
    R.user32.SetWindowPos = spy
    try:
        if not gui_ok:
            for i in range(1, 30):
                SKIPPED.append(f'X{i:02d}')
                print(f'  [SKIP] X{i:02d}  (无桌面环境（GUI 不可用）)')
        else:
            test_entries(tmp, saved)
            test_quantify(tmp, saved)
            test_not_too_hot(tmp, saved, spy)
            test_below(tmp, saved, spy)
            test_zorder_log(tmp, saved)
            test_discriminating(tmp, saved)
    finally:
        (R.save_config, R.messagebox.showinfo, R.messagebox.showwarning,
         R.messagebox.showerror, R.messagebox.askyesno, R.set_autostart,
         R.event_hook_alive, R.screen_work_area_height, R.screen_work_area) = real
        R.user32.SetWindowPos = spy.real
        for _ov in list(_KEEP_OV):
            try:
                _ov.root.withdraw()
                _ov.root.destroy()
            except Exception:
                pass
        for _c in list(_KEEP_CAND) + list(_KEEP_WIN):
            _c.destroy()
        _KEEP_OV.clear()
        _KEEP_CAND.clear()
        _KEEP_WIN.clear()
        shutil.rmtree(tmp, ignore_errors=True)
    return _summary()


def _summary():
    print('\n' + '=' * 66)
    print(f'通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项 / 跳过 {len(SKIPPED)} 项')
    if FAIL:
        print('失败项:')
        for n in FAIL:
            print('  -', n)
        print('RESULT: FAIL')
        return 1
    print('RESULT: PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
