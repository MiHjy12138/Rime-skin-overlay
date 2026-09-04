# -*- coding: utf-8 -*-
"""
B_test_follow_sim.py —— 路径 B 改造验证（第三步）
模拟候选框窗口 + overlay 定位逻辑端到端验证 + 事件驱动消费验证 + CPU 对比。

说明：本脚本在无「真实系统窗口事件投递」的环境（沙箱/远程会话）也能验证
改造逻辑：
  1) find_candidate_window（EnumWindows）能找到 ATL: 假候选框 —— 首贴验证；
  2) 事件注入式驱动：模拟事件线程置位时间戳（等价于 WinEventHook 回调命中），
     走真实 _event_tick → SetWindowPos 链路，测「事件→到位」延迟；
  3) 去抖/心跳/隐藏/置顶 行为单测；
  4) 与旧实现（bak-b 全扫轮询）的 CPU/延迟对比采样。
真实 WinEventHook 系统事件投递环节（沙箱不派发自建窗口事件）列需实机验证。

用法: python B_test_follow_sim.py
"""
import sys, os, time, ctypes
import ctypes.wintypes as wintypes

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, 'rime_char_overlay.py')
BAK = os.path.join(BASE, 'rime_char_overlay.py.bak-b')


def _load_module(path, name):
    import importlib.util
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


m = _load_module(SRC, 'rime_char_overlay_b')
USER32 = m.user32
KERNEL32 = m.kernel32
# 旧实现对照模块（仅做纯扫描成本对比；旧版 FollowOverlay 依赖轮询，不在本沙箱跑 GUI）
try:
    old = _load_module(BAK, 'rime_char_overlay_old')
except Exception as e:
    old = None
    print('bak-b 加载失败（对照采样跳过）:', e)

# ---------- 假候选框窗口（真实 Win32 顶层窗口，类名 ATL: + 候选框样式）----------
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)
USER32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
USER32.DefWindowProcW.restype = ctypes.c_longlong
KERNEL32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
KERNEL32.GetModuleHandleW.restype = wintypes.HMODULE


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


class FakeCandidate:
    """类名 ATL: 前缀 + WS_POPUP|WS_EX_TOOLWINDOW|WS_EX_NOACTIVATE 假候选框。"""

    def __init__(self, cls_name='ATL:MockCandidateB', x=60, y=120, w=420, h=72):
        self.proc = WNDPROC(_def_proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self.proc
        wc.hInstance = KERNEL32.GetModuleHandleW(None)
        wc.lpszClassName = cls_name
        USER32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        USER32.RegisterClassExW.restype = wintypes.ATOM
        if not USER32.RegisterClassExW(ctypes.byref(wc)):
            raise RuntimeError('RegisterClassExW failed')
        self.cls = cls_name
        USER32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                           wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                           wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        USER32.CreateWindowExW.restype = wintypes.HWND
        self.hwnd = USER32.CreateWindowExW(
            0x80 | 0x08000000, cls_name, 'mock', 0x80000000 | 0x10000000,
            x, y, w, h, 0, 0, wc.hInstance, None)
        if not self.hwnd:
            raise RuntimeError('CreateWindowExW failed')

    def rect(self):
        r = wintypes.RECT()
        USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        USER32.GetWindowRect(self.hwnd, ctypes.byref(r))
        return r

    def w(self):
        r = self.rect()
        return r.right - r.left

    def h(self):
        r = self.rect()
        return r.bottom - r.top

    def destroy(self):
        try:
            USER32.DestroyWindow(self.hwnd)
        except Exception:
            pass


def _expected_xy(ov, rect):
    cw, ch = rect.right - rect.left, rect.bottom - rect.top
    side = ov.cfg.get('side', 'right')
    gap = 8
    if side == 'left':
        x = rect.left - ov.w - gap + ov.off_x + ov.cfg.get('offset_x', 0)
    elif side == 'right':
        x = rect.right + gap + ov.off_x + ov.cfg.get('offset_x', 0)
    else:
        x = rect.left + (cw - ov.w) // 2 + ov.off_x + ov.cfg.get('offset_x', 0)
    y = rect.top + (ch - ov.h) // 2 + ov.off_y + ov.cfg.get('offset_y', 0)
    return int(x), int(y)


def _move_fake(fake, x, y):
    """真实移动假窗口（SetWindowPos 带真实尺寸，保持可见可测）。"""
    USER32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    USER32.SetWindowPos(fake.hwnd, 0, int(x), int(y), fake.w(), fake.h(), 0x0010)


def main():
    print('=== B 路径改造验证：模拟候选框 + 定位/事件逻辑 + 性能对比 ===')
    print('Python', sys.version.split()[0])
    import tkinter
    print('tk', tkinter.TkVersion)

    try:
        probe = tkinter.Tk()
        probe.withdraw()
        probe.update()
        probe.destroy()
    except Exception as e:
        print('SKIP：GUI 不可用 ->', repr(e))
        return

    img = os.path.join(BASE, 'char.png')
    cfg = dict(m.DEFAULT_CONFIG)
    cfg['image'] = img
    cfg['layout'] = 'horizontal_double'
    cfg['side'] = 'right'
    cfg['scale'] = 0.7
    cfg['offset_x'] = 0
    cfg['offset_y'] = 0

    fake = None
    ov = None
    try:
        fake = FakeCandidate()
        fr = fake.rect()
        print(f'[1] 假候选框 hwnd=0x{fake.hwnd:X} ({fr.left},{fr.top}) {fake.w()}x{fake.hwnd and fake.h()}')
        r0 = fake.rect()
        print(f'    rect0=({r0.left},{r0.top},{r0.right},{r0.bottom})')

        ov = m.FollowOverlay(cfg)
        try:
            ov.tray.stop()
        except Exception:
            pass

        # ---- [2] 定位逻辑：find 识别假窗口 + 缓存句柄直贴 ----
        # 2a. EnumWindows 全扫应能识别假候选框（类名 ATL: + 样式 + 尺寸全命中）
        win = m.find_candidate_window()
        found_fake = bool(win) and win[0] == fake.hwnd
        print(f'[2a] find_candidate_window 识别假候选框: hit={bool(win)} '
              f'==fake={win and win[0] == fake.hwnd}')
        # 2b. 直接缓存假窗口句柄并首贴（等价 SHOW 直挂/重扫命中后立即定位）
        ov._cached_hwnd = fake.hwnd
        m.set_candidate_hwnd(fake.hwnd)
        ov._last_scan_ts = 0.0
        ex, ey = _expected_xy(ov, fake.rect())
        got = ov._position_once()
        print(f'[2b] 首贴 _position_once hit={got} overlay=({ov._x},{ov._y}) '
              f'expect=({ex},{ey}) visible={ov.visible}')
        ok_first = got and abs(ov._x - ex) < 2 and abs(ov._y - ey) < 2 and ov.visible
        print('    首贴结果:', 'PASS' if ok_first else 'FAIL')
        if not (found_fake and ok_first):
            raise AssertionError('首贴/识别失败')

        # ---- [3] 事件注入驱动：模拟 LOCATIONCHANGE 到达（事件线程置位时间戳）----
        # 沙箱不派发自建窗口事件 → 直接注入 _EVT_MOVE_TS 走真实事件消费链路
        latencies = []
        targets = [(120, 260), (420, 120), (200, 360), (520, 240), (90, 170)]
        for i, (mx, my) in enumerate(targets):
            _move_fake(fake, mx, my)  # 真实移动窗口（位置事实更新）
            # 模拟 WinEventHook 回调命中：递增序号 + 置时间戳（真实回调同样逻辑）
            m._EVT_MOVE_CNT += 1
            m._EVT_MOVE_TS = time.monotonic()
            m._EVT_CACHE_HWND = fake.hwnd
            t0 = time.monotonic()
            ov._event_tick()          # 真实消费：读序号 → 缓存定位 → SetWindowPos
            rect = fake.rect()
            ex, ey = _expected_xy(ov, rect)
            done = abs(ov._x - ex) < 2 and abs(ov._y - ey) < 2
            lat = (time.monotonic() - t0) * 1000
            latencies.append(lat)
            # 校验窗口真实位置
            top = ov._top_hwnd()
            wr = wintypes.RECT()
            USER32.GetWindowRect(top, ctypes.byref(wr))
            pos_ok = abs(wr.left - ex) < 4 and abs(wr.top - ey) < 4
            print(f'[3] move#{i} -> ({mx},{my}) 事件消费定位 mirror=({ov._x},{ov._y}) '
                  f'expect=({ex},{ey}) 窗口实际=({wr.left},{wr.top}) '
                  f'逻辑PASS={done} 实窗PASS={pos_ok} 单拍延迟={lat:.2f}ms')
            if not (done and pos_ok):
                raise AssertionError(f'move#{i} 未跟上')

        # ---- [4] 去抖/隐藏/自愈行为 ----
        # 4a. 消失去抖：HIDE 后 150ms 内不应 withdraw
        ov._last_gone_cnt = m._EVT_GONE_CNT
        m._EVT_GONE_CNT += 1             # 模拟 DESTROY/HIDE 事件
        m._EVT_GONE_TS = time.monotonic()
        ov._event_tick()
        still_visible = ov.visible and ov._hide_since is not None
        print(f'[4a] 收到 GONE 事件后 150ms 去抖窗口内: visible={ov.visible} (应 True, 防闪烁) PASS={ov.visible}')
        assert ov.visible
        # 4b. 超时隐藏（非 pinned）
        ov._hide_since = time.time() - 0.2
        ov._heartbeat()
        print(f'[4b] 消失超 150ms 心跳: visible={ov.visible} (应 False 自动隐藏) PASS={not ov.visible}')
        assert not ov.visible
        # 4c. pinned 不隐藏（模拟手动固定显示后再消失）
        ov.pinned = True
        ov.root.deiconify()
        ov.visible = True
        ov._hide_since = time.time() - 0.3
        ov._heartbeat()
        print(f'[4c] pinned 时消失: visible={ov.visible} (应 True) PASS={ov.visible}')
        assert ov.visible
        ov.pinned = False
        # 4d. SHOW 自愈：重新出现 → 心跳/事件重扫找回
        ov._hide_since = None
        ov._last_show_cnt = m._EVT_SHOW_CNT
        m._EVT_SHOW_CNT += 1             # 模拟任意窗口 SHOW 事件
        m._EVT_SHOW_TS = time.monotonic()
        m._EVT_SHOW_HWND = fake.hwnd
        ov._event_tick()
        print(f'[4d] SHOW 自愈: cached=0x{ov._cached_hwnd:X} (应=0x{fake.hwnd:X}) visible={ov.visible}')
        assert ov._cached_hwnd == fake.hwnd

        # ---- [5] CPU/延迟对比采样 ----
        # 5a. EnumWindows 全扫成本（旧轮询每秒 20 次的开销主成分）
        n = 30
        t0 = time.perf_counter()
        for _ in range(n):
            m.find_candidate_window()
        per_scan = (time.perf_counter() - t0) / n
        print(f'[5a] 全扫单次 {per_scan*1000:.2f} ms → 旧版 50ms 轮询≈每秒20次 → '
              f'约 {per_scan*20*1000:.1f} ms CPU/s（纯扫描，不含 geometry/置顶）')
        # 5b. 新事件 tick 空转成本
        t0 = time.perf_counter()
        for _ in range(200):
            ov._event_tick()
        tick_cost = (time.perf_counter() - t0) / 200
        print(f'[5b] 事件 tick 单次 ≈ {tick_cost*1e6:.1f} us → 每秒 {1000/ov.event_ms:.0f} 次 ≈ '
              f'{tick_cost*(1000/ov.event_ms)*1000:.2f} ms CPU/s（空事件时）')
        # 5c. 单拍事件→到位 延迟（不含系统事件投递，只含 tick 消费+SetWindowPos）
        avg = sum(latencies) / len(latencies)
        print(f'[5c] 事件注入→SetWindowPos 到位延迟: n={len(latencies)} '
              f'avg={avg:.2f}ms max={max(latencies):.2f}ms')
        # 5d. 对照旧版（若可加载）
        if old is not None:
            t0 = time.perf_counter()
            for _ in range(n):
                old.find_candidate_window()
            per_scan_old = (time.perf_counter() - t0) / n
            print(f'[5d] 旧版全扫单次 {per_scan_old*1000:.2f} ms '
                  f'→ 每秒20次 ≈ {per_scan_old*20*1000:.1f} ms CPU/s（同一环境对照）')
        print('ALL CHECKS PASS')
    except AssertionError as e:
        print('RESULT FAIL:', e)
        sys.exit(1)
    except Exception:
        import traceback
        traceback.print_exc()
        print('RESULT ERROR')
        sys.exit(2)
    finally:
        try:
            if ov is not None:
                ov.root.withdraw()
                ov.root.destroy()
        except Exception:
            pass
        try:
            if fake is not None:
                fake.destroy()
        except Exception:
            pass
        try:
            m._release_event_thread()
        except Exception:
            pass
        time.sleep(0.1)


if __name__ == '__main__':
    main()
