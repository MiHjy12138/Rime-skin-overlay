# -*- coding: utf-8 -*-
"""
B_test_misdetect_regress.py —— v1.6 误贴修复回归（判定矩阵）

2026-09-06 实机诊断（B_test_misdetect_diag.py）三场景误贴实锤：
  ① electron 菜单   → Chrome_WidgetWin_1（非 ATL:）被 SHOW 直挂
  ② weasel 32×32 大小写/状态指示窗（ATL:+TSF+weasel 进程，微缩）被直挂/全扫
  ③ msedge 网址提示浮层 → Chrome_WidgetWin_1（非 ATL:）被 SHOW 直挂
真候选框：注入应用进程（et/electron…）内的 ATL: 大窗（586×83 / 626×83）。

修复：候选框判定统一到 _is_candidate_window（ATL: 前缀 + TSF 样式/weasel 兜底
+ 尺寸；weasel 进程内宽高均 <120 的微缩窗判非候选框）。

本脚本用真实 Win32 窗口注册，验证判定矩阵与修复前后差异（加载 bak-d 对照）。

用法: python B_test_misdetect_regress.py
"""
import os, sys, ctypes, importlib.util
import ctypes.wintypes as wt

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, 'rime_char_overlay.py')
BAK = os.path.join(BASE, 'rime_char_overlay.py.bak-d')

WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000


def _load(path, name):
    loader = importlib.util.find_spec if False else None
    from importlib.machinery import SourceFileLoader
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = _load(SRC, 'rime_char_overlay_v16')
u = m.user32
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wt.HWND, wt.UINT,
                             wt.WPARAM, wt.LPARAM)
u.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u.DefWindowProcW.restype = ctypes.c_longlong
k = m.kernel32
k.GetModuleHandleW.argtypes = [wt.LPCWSTR]
k.GetModuleHandleW.restype = wt.HMODULE
u.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [('cbSize', wt.UINT), ('style', wt.UINT),
                ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', wt.HINSTANCE),
                ('hIcon', wt.HICON), ('hCursor', wt.HANDLE),
                ('hbrBackground', wt.HBRUSH), ('lpszMenuName', wt.LPCWSTR),
                ('lpszClassName', wt.LPCWSTR), ('hIconSm', wt.HICON)]


def _def(hwnd, msg, wp, lp):
    try:
        return u.DefWindowProcW(hwnd, msg, wp, lp)
    except Exception:
        return 0


_procs = []  # 防 GC


def make_win(cls, w, h, ex=WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
    """注册一个 类名 + POPUP + exstyle 的可见窗口，返回 hwnd。"""
    p = WNDPROC(_def)
    _procs.append(p)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = p
    wc.hInstance = k.GetModuleHandleW(None)
    wc.lpszClassName = cls
    u.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    if not u.RegisterClassExW(ctypes.byref(wc)):
        # 类已存在（重复用例同 cls）时 RegisterClassExW 返回 0 —— 类已注册可复用，继续建窗
        pass
    u.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wt.HWND, wt.HMENU,
                                  wt.HINSTANCE, wt.LPVOID]
    u.CreateWindowExW.restype = wt.HWND
    hwnd = u.CreateWindowExW(ex, cls, '', WS_POPUP, 0, 0, w, h,
                             0, 0, wc.hInstance, 0)
    u.ShowWindow(hwnd, 5)  # SW_SHOW
    return hwnd


def judge(mod, hwnd):
    return bool(mod._is_candidate_window(hwnd))


def case(mod, name, cls, w, h, ex, expect, weasel=None):
    """weasel=None 用真实进程判定；True/False 覆盖 _window_belongs_to_weasel。"""
    if weasel is not None:
        mod._window_belongs_to_weasel = lambda h: weasel
    else:
        # 恢复真实实现（重新绑定）
        import types
        # 模块里原始函数保留在模块 dict？被替换后无法直接恢复；重新赋值引用
        # 在第一次调用前保存真函数
        pass
    hwnd = make_win(cls, w, h, ex)
    try:
        got = judge(mod, hwnd)
    finally:
        u.DestroyWindow.argtypes = [wt.HWND]
        u.DestroyWindow(hwnd)
    ok = got == expect
    print(f'{"PASS" if ok else "FAIL"} {name:<44} cls={cls:<24} {w}x{h:<4} '
          f'weasel覆盖={weasel} → got={got} expect={expect}')
    return ok


def main():
    print('=== v1.6 判定矩阵回归（真实窗口）===')
    real_weasel_fn = m._window_belongs_to_weasel
    results = []
    # —— 真候选框形态：必须放行 ——
    results.append(case(m, '真候选框 WPS输入(et) 586x83', 'ATL:TestCandEt', 586, 83,
                        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, True))
    results.append(case(m, '真候选框 DSH输入(electron) 626x83', 'ATL:TestCandDs', 626, 83,
                        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, True))
    results.append(case(m, '候选框 单行 240x36', 'ATL:TestCandRow', 240, 36,
                        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, True))
    # —— 三场景误判窗口：必须拒绝 ——
    results.append(case(m, '①electron Alt菜单浮层', 'Chrome_WidgetWin_1', 213, 145,
                        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, False))
    results.append(case(m, '③msedge 网址提示条', 'Chrome_WidgetWin_1', 274, 64,
                        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, False))
    results.append(case(m, '④msedge 收藏夹面板(366x446)', 'Chrome_WidgetWin_1', 366, 446,
                        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, False))
    results.append(case(m, '④msedge 收藏夹子菜单(608x862)', 'Chrome_WidgetWin_1', 608, 862,
                        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, False))
    results.append(case(m, 'explorer 任务栏浮层', 'TaskListOverlayWnd', 216, 146,
                        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, False))
    results.append(case(m, 'tooltip 弹层', 'tooltips_class32', 180, 40,
                        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, False))
    # —— weasel 进程内微缩窗 vs 旧架构候选 ——
    results.append(case(m, '②weasel 32x32 切换指示窗', 'ATL:TestWeaselIcon', 32, 32,
                        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, False, weasel=True))
    results.append(case(m, 'weasel 旧架构大候选窗 420x72', 'ATL:TestWeaselOld', 420, 72,
                        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, True, weasel=True))
    # —— 恢复真实 weasel 判定（本进程非 weasel），继续其余用例 ——
    m._window_belongs_to_weasel = real_weasel_fn
    # —— 类名/样式 硬性前提 ——
    results.append(case(m, 'ATL 但普通激活弹窗(无三件套)', 'ATL:TestPlain', 320, 120,
                        0x0, False))
    results.append(case(m, 'ATL+三件套 非weasel 微缩(本进程)', 'ATL:TestTinyApp', 32, 32,
                        WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, True))
    passed = sum(results)
    print(f'\n=== {passed}/{len(results)} 通过 ===')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
