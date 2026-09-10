# -*- coding: utf-8 -*-
"""
B_test_misdetect_diag.py —— 误贴诊断（实机，配合用户复现三场景）

背景（2026-09-06 公子实机报告）：外挂启用后，当
  1) Openclaw/DSH 按 Alt 弹菜单点击
  2) 切换大小写（Rime 弹出切换/大写提示）
  3) 浏览器网页左下/右下显示网址提示
时，皮肤会出现在这些「临时小窗」附近 —— 即外挂把非候选框窗口误当成
Rime 候选框并贴图。

机理（代码审查）：候选框判定有两条不一致的路径
  · 全扫 _find_enum_proc      → 要求类名 ATL: 前缀 + (TSF样式 | weasel进程) + 尺寸
  · SHOW 直挂 _try_attach_show_hwnd → 不查类名，只看 (TSF样式 | weasel进程) + 尺寸
SHOW 直挂缺类名约束：Edge/Chromium 输入层、tooltip、conhost ATL 窗等
POPUP+TOOLWINDOW+NOACTIVATE 小窗在候选框空缺时 SHOW 即被直挂。

本脚本：真实 SetWinEventHook(EVENT_OBJECT_SHOW) 全桌监听，对每次 SHOW 的
窗口即时执行两套判定（与主程序同款条件），命中即打印
  类名 | 句柄 | 尺寸 | 位置 | 标题 | 进程名 | 是否前台 | 窗口可见
  → P1(直挂)命中 / P2(全扫)命中
供实机复现采集，实锤每个场景误判的是哪个窗口。

用法: python B_test_misdetect_diag.py [秒数] [日志文件]
示例: python B_test_misdetect_diag.py 90
输出: 实时打印到控制台 + 同目录 diag_misdetect.log（追加）
"""
import sys, os, time, ctypes, datetime
import ctypes.wintypes as wt

WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WEASEL = ('weaselserver.exe', 'weaseltsf.exe', 'weaselime.exe', 'weasel.exe')
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
OBJID_WINDOW = 0
CHILDID_SELF = 0
WINEVENT_OUTOFCONTEXT = 0x0002

u = ctypes.windll.user32
k = ctypes.windll.kernel32
u.SetWinEventHook.argtypes = [wt.DWORD, wt.DWORD, wt.HMODULE, ctypes.c_void_p,
                              wt.DWORD, wt.DWORD, wt.DWORD]
u.SetWinEventHook.restype = wt.HANDLE
u.UnhookWinEvent.argtypes = [wt.HANDLE]
u.UnhookWinEvent.restype = wt.BOOL
u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
u.IsWindowVisible.argtypes = [wt.HWND]
u.IsWindowVisible.restype = wt.BOOL
u.GetForegroundWindow.restype = wt.HWND
u.GetWindow.argtypes = [wt.HWND, wt.UINT]
u.GetWindow.restype = wt.HWND
k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k.OpenProcess.restype = wt.HANDLE
k.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR,
                                         ctypes.POINTER(wt.DWORD)]
k.CloseHandle.argtypes = [wt.HANDLE]

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'diag_misdetect.log')


def log(msg):
    line = f'[{datetime.datetime.now():%H:%M:%S.%f}'[:-3] + f'] {msg}'
    print(line, flush=True)
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def proc_name(pid):
    try:
        h = k.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not h:
            return f'pid{pid}'
        try:
            b = ctypes.create_unicode_buffer(1024)
            sz = wt.DWORD(1024)
            if k.QueryFullProcessImageNameW(h, 0, b, ctypes.byref(sz)):
                return os.path.basename(b.value)
            return f'pid{pid}'
        finally:
            k.CloseHandle(h)
    except Exception:
        return f'pid{pid}'


def inspect(hwnd):
    """返回 (tsf_style, weasel_proc, cls, title, w, h, x, y, proc, visible)。"""
    try:
        visible = bool(u.IsWindowVisible(hwnd))
        cls = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, cls, 256)
        cls = cls.value
        style = u.GetWindowLongPtrW(hwnd, -16)
        ex = u.GetWindowLongPtrW(hwnd, -20)
        tsf = bool(style & WS_POPUP and ex & WS_EX_TOOLWINDOW
                   and ex & WS_EX_NOACTIVATE)
        pid = wt.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pn = proc_name(pid.value).lower()
        weasel = pn in WEASEL
        title = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, title, 512)
        r = wt.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        return tsf, weasel, cls, title.value, r.right - r.left, \
            r.bottom - r.top, r.left, r.top, pn, visible
    except Exception:
        return None


@ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, ctypes.c_long,
                    ctypes.c_long, wt.DWORD, wt.DWORD)
def _proc(hook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
    """SHOW 回调：即时判定 + 打印（诊断用，允许重 API）。"""
    try:
        if not hwnd or idObject != OBJID_WINDOW or idChild != CHILDID_SELF:
            return
        if event == EVENT_OBJECT_SHOW:
            t = inspect(hwnd)
            if not t:
                return
            tsf, weasel, cls, title, w, h, x, y, pn, visible = t
            if not visible:
                return
            size_ok = 0 < w < 1300 and 0 < h < 1000 and h < w * 4
            if not size_ok:
                return
            p1 = bool(tsf or weasel)          # 现状直挂路径判定
            p2 = bool(cls.startswith('ATL:') and (tsf or weasel))  # 现状全扫路径判定
            if p1 or p2:
                fg = u.GetForegroundWindow()
                fg_note = '前台' if fg == hwnd else (
                    f'非前台(fg=0x{fg:x})')
                marks = []
                if p1:
                    marks.append('P1直挂命中')
                if p2:
                    marks.append('P2全扫命中')
                log('SHOW ' + ' | '.join(marks) +
                    f' | cls={cls!r} | hwnd=0x{hwnd:x} | {w}x{h}@({x},{y})'
                    f' | title={title!r} | proc={pn} | {fg_note} | styleTSF={tsf} weasel={weasel}')
    except Exception:
        pass


def main():
    secs = 120
    if len(sys.argv) > 1:
        try:
            secs = max(5, min(int(sys.argv[1]), 600))
        except ValueError:
            pass
    log('=== 误贴诊断启动: 监听 SHOW 事件 %d 秒（请依次复现：①Alt菜单 ②切大小写 ③浏览器网址提示）===' % secs)
    proc_ref = _proc  # 防 GC
    hook = u.SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, 0,
                             proc_ref, 0, 0, WINEVENT_OUTOFCONTEXT)
    if not hook:
        log('SetWinEventHook 失败！')
        return 1
    log(f'hook=0x{hook:x} 已挂载，开始监听…')
    end = time.time() + secs
    fg_prev = 0
    while time.time() < end:
        # 简易消息泵：OUTOFCONTEXT 回调投递到本线程，须 pump
        msg = wt.MSG()
        while u.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))
        # 每秒汇报前台窗口变化，方便对照「当时在哪个应用」
        fg = u.GetForegroundWindow()
        if fg != fg_prev:
            fg_prev = fg
            t = inspect(fg)
            if t:
                _, _, cls, title, w, h, x, y, pn, vis = t
                log(f'  └ 前台切换 → cls={cls!r} title={title!r} proc={pn} {w}x{h}@({x},{y})')
        time.sleep(0.02)
    u.UnhookWinEvent(hook)
    log(f'=== 监听结束，共 %d 秒。结果已存 {LOG_PATH} ===' % secs)
    return 0


if __name__ == '__main__':
    sys.exit(main())
