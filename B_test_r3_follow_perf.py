# -*- coding: utf-8 -*-
"""B_test_r3_follow_perf.py —— R3「多图层跟随缓慢 + 错位」量化与机制回归

用户反馈（原话）：「多图情况下打字时图片跟随缓慢，且存在错位。」

本脚本做两件事，全部用「同口径可复核的数字」说话：

  【一】慢——定位路径的每帧成本与文件 I/O 计数
      · 计数：稳态打字帧里 `Image.open`（= 磁盘解码）次数、`compose_layers`（整图合成）次数
      · 计时：稳态帧 p50/p90 每帧耗时，并与「一次全图层冷解码」成本做同机比值
      · 期望（修复后）：稳态帧 0 次 open、0 次整图合成，单帧耗时 ≤ 冷解码一轮的 1/10

  【二】错位——「一帧两个矩形快照」机制复现
      定位一帧内部有两次候选框矩形读取：帧首 `_read_cached_rect()`（用于窗口位置/尺寸）与
      合成时的 `_layout_rect()`（用于画布内各层落点）。两者之间隔着 N 次图层解码
      （实测 15~44ms），打字时候选框在这期间移动/变宽 → 画布按新矩形排布、窗口按旧矩形定位
      → 整层错位。
      复现方式：在定位调用内部（`_layer_dims` 被调用时）真实移动假候选框，
      断言「窗口位置 + 窗口尺寸 + 画面内容」三者都与**帧首那一份矩形快照**逐位一致。

用法: python B_test_r3_follow_perf.py   （退出码 0=全过 / 1=断言失败 / 2=异常）
"""
import sys, os, time, ctypes, tempfile, shutil, traceback
import ctypes.wintypes as wintypes

# 控制台编码保护（默认 GBK 控制台直跑必须 exit=0；HANDOFF §5 第 10 条）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
try:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, 'rime_char_overlay.py')


def _load_module(path, name):
    import importlib.util
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


m = _load_module(SRC, 'rime_char_overlay_r3')
USER32 = m.user32
KERNEL32 = m.kernel32

# ---------- 假候选框窗口（真实 Win32 顶层窗口：类名 ATL: + 候选框样式）----------
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
    _seq = [0]

    def __init__(self, x=60, y=120, w=420, h=72):
        type(self)._seq[0] += 1
        cls = f'ATL:R3PerfCand{type(self)._seq[0]}'
        self.proc = WNDPROC(_def_proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self.proc
        wc.hInstance = KERNEL32.GetModuleHandleW(None)
        wc.lpszClassName = cls
        USER32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        USER32.RegisterClassExW.restype = wintypes.ATOM
        if not USER32.RegisterClassExW(ctypes.byref(wc)):
            raise RuntimeError('RegisterClassExW failed')
        USER32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                           wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                           wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        USER32.CreateWindowExW.restype = wintypes.HWND
        USER32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
        USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.hwnd = USER32.CreateWindowExW(
            0x80 | 0x08000000, cls, 'mock', 0x80000000 | 0x10000000,
            x, y, w, h, 0, 0, wc.hInstance, None)
        if not self.hwnd:
            raise RuntimeError('CreateWindowExW failed')

    def rect(self):
        r = wintypes.RECT()
        USER32.GetWindowRect(self.hwnd, ctypes.byref(r))
        return r

    def rtuple(self):
        r = self.rect()
        return int(r.left), int(r.top), int(r.right), int(r.bottom)

    def move(self, x=None, y=None, w=None, h=None):
        r = self.rect()
        x = r.left if x is None else x
        y = r.top if y is None else y
        w = (r.right - r.left) if w is None else w
        h = (r.bottom - r.top) if h is None else h
        USER32.SetWindowPos(self.hwnd, 0, int(x), int(y), int(w), int(h), 0x0010)

    def destroy(self):
        try:
            USER32.DestroyWindow(self.hwnd)
        except Exception:
            pass


# 各层色块颜色（块心取样用；彼此差异大，便于逐层核对）
COLORS = [(255, 0, 0), (0, 150, 0), (0, 0, 255), (255, 140, 0), (140, 0, 200), (0, 160, 160)]
KEY_MAGENTA = (255, 0, 255)


class Checker:
    def __init__(self):
        self.n_pass = 0
        self.fails = []

    def check(self, ok, name, detail=''):
        if ok:
            self.n_pass += 1
            print(f'  [PASS] {name}' + (f'  ({detail})' if detail else ''))
        else:
            print(f'  [FAIL] {name}' + (f'  ({detail})' if detail else ''))
            self.fails.append(name)

    def done(self):
        if self.fails:
            print(f'\nRESULT FAIL: {len(self.fails)} 项断言未通过')
            return 1
        print(f'\nALL CHECKS PASS  (共 {self.n_pass} 项断言通过)')
        return 0


def make_layers(d, sizes, block=20):
    """临时目录里生成各层 PNG（透明底 + 居中方块），返回路径列表。"""
    from PIL import Image as I
    os.makedirs(d, exist_ok=True)
    files = []
    for i, (w, h) in enumerate(sizes):
        p = os.path.join(d, f'layer{i}.png')
        im = I.new('RGBA', (w, h), (0, 0, 0, 0))
        im.paste(I.new('RGBA', (w - 2 * block, h - 2 * block), COLORS[i % 6] + (255,)),
                 (block, block))
        im.save(p)
        files.append(p)
    return files


def make_anim_gif(d, wh=(200, 300), n=8):
    """临时目录里生成 n 帧动图（GIF，逐帧色块轻微变化），返回路径。"""
    from PIL import Image as I
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'anim.gif')
    frames = []
    for i in range(n):
        im = I.new('RGBA', wh, (0, 0, 0, 0))
        im.paste(I.new('RGBA', (wh[0] - 40, wh[1] - 40), (200, 40 + i * 20, 40, 255)), (20, 20))
        frames.append(im.convert('RGB'))
    frames[0].save(p, save_all=True, append_images=frames[1:], duration=33, loop=0)
    return p


def build_cfg(imgs, mode='compat', anchors=None, offsets=None, base_height=300, scale=0.7):
    cfg = dict(m.DEFAULT_CONFIG)
    cfg['image'] = imgs[0]
    cfg['layout'] = 'horizontal_double'
    cfg['side'] = 'right'
    cfg['scale'] = scale
    cfg['base_height'] = base_height
    cfg['offset_x'] = 0
    cfg['offset_y'] = 0
    cfg['render_mode'] = mode
    anchors = anchors or ['right_edge'] * len(imgs)
    offsets = offsets or [(0, 0)] * len(imgs)
    cfg['layers'] = [{'image': p, 'anchor': anchors[i],
                      'offset_x': offsets[i][0], 'offset_y': offsets[i][1],
                      'scale': scale, 'flip': False, 'z': i}
                     for i, p in enumerate(imgs)]
    return cfg


# ---------- 计数器：把「文件 I/O」与「整图合成」变成可断言的数量 ----------
class IOCounter:
    """包住 PIL.Image.open 与 compose_layers，统计次数（只在测量窗口内生效）。"""

    def __init__(self):
        self.opens = 0
        self.composes = 0
        self._orig_open = None
        self._orig_compose = None

    def start(self):
        from PIL import Image as PILImage
        self._orig_open = PILImage.open
        self._orig_compose = m.compose_layers

        def counting_open(*a, **kw):
            self.opens += 1
            return self._orig_open(*a, **kw)

        def counting_compose(*a, **kw):
            self.composes += 1
            return self._orig_compose(*a, **kw)

        PILImage.open = counting_open
        m.compose_layers = counting_compose

    def stop(self):
        from PIL import Image as PILImage
        if self._orig_open is not None:
            PILImage.open = self._orig_open
        if self._orig_compose is not None:
            m.compose_layers = self._orig_compose
        self._orig_open = self._orig_compose = None

    def reset(self):
        self.opens = 0
        self.composes = 0


def _win_rect(ov):
    r = wintypes.RECT()
    USER32.GetWindowRect(ov._top_hwnd(), ctypes.byref(r))
    return int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)


def _expect(ov, rect):
    """该矩形下应当呈现的 (win_x, win_y, win_w, win_h, placements)"""
    return m.plan_layer_layout(ov._layer_specs(), ov._layer_dims(), rect,
                               main_off=(ov.off_x, ov.off_y))


def _cmp_frame(ov, exp, label):
    """显示帧逐位核对：用「期望布局」独立合成一张参考帧，与 overlay 真正贴到窗口上的
    `raw_img` 逐字节比较（同一份原始帧 + 同一抠色键 + 同一条 flatten 管线）。

    这样断言的是「屏幕上真正显示的内容」= plan_layer_layout 的期望，而不只是算术。
    返回 (ok, 详情)。"""
    try:
        from PIL import Image as PILImage
        ww, wh = int(exp[2]), int(exp[3])
        frames = list(getattr(ov, '_layer_raw', []) or [])
        if not frames:
            return False, f'{label}: 原始帧缓存缺失'
        ref_canvas = m.compose_layers(frames, (ww, wh), exp[4], PILImage)
        ref = m._flatten_alpha_for_tk(ref_canvas, PILImage, ov.key_rgb)
        got = getattr(ov, 'raw_img', None)
        if got is None or not hasattr(got, 'tobytes'):
            return False, f'{label}: 显示帧不可用（raw_img=None）'
        if tuple(got.size) != tuple(ref.size):
            return False, f'{label}: 画布尺寸不符 got={tuple(got.size)} ref={tuple(ref.size)}'
        if got.convert('RGB').tobytes() == ref.convert('RGB').tobytes():
            return True, f'{label}: {ww}x{wh} 全帧逐字节一致'
        import PIL.ImageChops as Chops
        diff = Chops.difference(got.convert('RGB'), ref.convert('RGB'))
        bbox = diff.getbbox()
        n = sum(1 for px in diff.getdata() if any(px))
        return False, (f'{label}: 画面与期望不一致 差异像素 {n} 个，bbox={bbox} '
                       f'（首个差异区左上角偏移即错位量）')
    except Exception as e:
        return False, f'{label}: 比对异常 {e!r}'


def main():
    print('=== R3 多图层跟随：量化 + 错位机制回归 ===')
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
        return 0

    chk = Checker()
    tmp = tempfile.mkdtemp(prefix='r3_perf_')
    # 只读约束（HANDOFF-2.1 §8.5 · t15）：日志/临时产物只落临时目录，不碰项目 error.log。
    # 产品 _write_log 是调用时取模块全局 HERE，运行期改这一处即可（不改产品代码）。
    m.HERE = tmp
    ovs, cands = [], []
    io = IOCounter()
    try:
        # ================= R3-1 / R3-2: 稳态定位路径的 I/O、合成与耗时 =================
        print('\n[R3-1] 稳态打字：每帧 Image.open / 整图合成次数（3 层 400x600 真实尺寸）')
        big = make_layers(os.path.join(tmp, 'big'), [(400, 600), (360, 540), (300, 450)])
        cfg = build_cfg(big, 'compat', ['right_edge', 'left_edge', 'right_edge'],
                        [(0, 0), (0, 0), (300, 0)], base_height=420, scale=0.7)
        cand = FakeCandidate()
        cands.append(cand)
        ov = m.FollowOverlay(cfg)
        ovs.append(ov)
        try:
            ov.tray.stop()
        except Exception:
            pass
        ov._cached_hwnd = cand.hwnd
        m.set_candidate_hwnd(cand.hwnd)
        ov._last_scan_ts = 0.0

        # 同口径基线：一次「全图层冷解码」的成本（= 修复前每帧至少要付的代价）
        ov._dims_cache = {}
        t0 = time.perf_counter()
        dims_cold = ov._layer_dims()
        t_cold = (time.perf_counter() - t0) * 1000
        print(f'  基线：全图层冷解码一轮 {t_cold:.1f} ms（{len(dims_cold)} 层 '
              f'{dims_cold}），这就是修复前每帧定位至少付一次的钱')

        ov._position_once()          # 预热一帧（首帧允许建缓存）
        io.start()
        frames = []                  # (dt_ms, opens, composes, width_changed)
        N = 24
        for i in range(N):
            r = cand.rtuple()
            nw = (r[2] - r[0]) + (40 if i % 4 == 0 and i else 0)
            cand.move(r[0] + 3, r[1] + 2, nw)
            width_changed = (nw != (r[2] - r[0]))
            io.reset()
            t0 = time.perf_counter()
            if i % 8 == 3:           # 真实入口之一：事件 tick 消费（含 _position_once）
                m._EVT_MOVE_CNT += 1
                m._EVT_MOVE_TS = time.monotonic()
                m._EVT_CACHE_HWND = cand.hwnd
                ov._event_tick()
            else:
                ov._position_once()
            frames.append(((time.perf_counter() - t0) * 1000, io.opens, io.composes,
                           width_changed))
        io.stop()

        total_opens = sum(f[1] for f in frames)
        total_comp = sum(f[2] for f in frames)
        steady = [f for f in frames if not f[3]]
        steady_opens = sum(f[1] for f in steady)
        steady_comp = sum(f[2] for f in steady)
        times = sorted(f[0] for f in steady)
        p50 = times[len(times) // 2]
        p90 = times[int(len(times) * 0.9)] if len(times) > 3 else times[-1]
        print(f'  {N} 帧（稳态 {len(steady)} 帧 / 变宽 {N - len(steady)} 帧）')
        print(f'  Image.open：稳态合计 {steady_opens} 次（{steady_opens / max(1, len(steady)):.2f}/帧），'
              f'全程合计 {total_opens} 次')
        print(f'  compose_layers：稳态合计 {steady_comp} 次（{steady_comp / max(1, len(steady)):.2f}/帧），'
              f'全程合计 {total_comp} 次')
        print(f'  稳态单帧耗时：p50={p50:.2f} ms  p90={p90:.2f} ms'
              f'（冷解码一轮 {t_cold:.1f} ms → 比值 {t_cold / max(1e-6, p50):.1f}x）')

        chk.check(steady_opens == 0, 'R3-1a 稳态帧不再逐帧做文件 I/O（Image.open=0）',
                  f'实测 {steady_opens} 次 / {len(steady)} 帧')
        chk.check(total_opens == 0, 'R3-1b 全程（含变宽帧）文件 I/O 为 0（尺寸缓存 + 原始帧缓存）',
                  f'实测 {total_opens} 次 / {N} 帧')
        chk.check(steady_comp == 0, 'R3-1c 稳态帧不再重复整图合成（compose=0）',
                  f'实测 {steady_comp} 次 / {len(steady)} 帧')
        chk.check(total_comp <= N - len(steady) + 1,
                  'R3-1d 整图合成只在画布布局真变了的帧发生',
                  f'实测 {total_comp} 次 ≤ 变宽帧 {N - len(steady)} + 1')
        chk.check(p50 * 10 < t_cold, 'R3-2 稳态单帧耗时 ≤ 冷解码一轮的 1/10（同机同口径）',
                  f'p50={p50:.2f}ms ×10={p50 * 10:.1f}ms < {t_cold:.1f}ms')
        chk.check(p50 < 8.0, 'R3-2b 稳态单帧耗时的绝对上限（防退化）', f'p50={p50:.2f}ms < 8ms')

        # 稳态帧的窗口位置必须严格等于 plan（顺带守住无漂移）
        r = cand.rtuple()
        exp = _expect(ov, r)
        wr = _win_rect(ov)
        chk.check(wr == tuple(exp[:4]), 'R3-1e 稳态窗口位置/尺寸 = plan_layer_layout 逐位一致',
                  f'win={wr} plan={tuple(exp[:4])}')

        # ================= R3-3: 一帧一个矩形快照（错位机制） =================
        print('\n[R3-3] 错位机制：定位调用内部候选框移动/变宽（模拟解码耗时里的打字输入）')
        # 先让「上次合成画布」对应宽 420 的矩形，再把候选框改成宽 520（不定位）
        cand.move(80, 140, 420)
        ov._position_once()
        cand.move(80, 140, 520)
        # 本帧：帧首矩形 = rect_A（宽 520 → 与上次合成画布不同 → 本帧必然重合成）
        # 注入：_layer_dims 被调用时（= 解码原本要花的时间窗内）候选框真实移动 + 变宽 → rect_B
        rect_A = cand.rtuple()
        rect_B_holder = {}
        orig_dims = ov._layer_dims
        armed = [True]

        def dims_with_typing(*a, **kw):
            if armed[0]:
                armed[0] = False
                cand.move(rect_A[0] + 7, rect_A[1] + 5, 560)   # 打字：位置 + 宽度同时变
                rect_B_holder['r'] = cand.rtuple()
            return orig_dims(*a, **kw)

        ov._layer_dims = dims_with_typing
        try:
            ov._position_once()
        finally:
            ov._layer_dims = orig_dims
        rect_B = rect_B_holder.get('r')
        print(f'  帧首矩形 rect_A={rect_A} → 帧内（解码窗口里）候选框变成 rect_B={rect_B}')
        dims_now = ov._layer_dims()
        expA = m.plan_layer_layout(ov._layer_specs(), dims_now, rect_A,
                                   main_off=(ov.off_x, ov.off_y))
        expB = m.plan_layer_layout(ov._layer_specs(), dims_now, rect_B,
                                   main_off=(ov.off_x, ov.off_y))
        wr = _win_rect(ov)
        ok_pos = wr[:2] == tuple(expA[:2])
        ok_size = wr[2:] == tuple(expA[2:4])
        c_ok, c_det = _cmp_frame(ov, expA, '按 rect_A（帧首快照）核对画面')
        print(f'  窗口 win={wr}；按 rect_A 期望 {tuple(expA[:4])}；按 rect_B 期望 {tuple(expB[:4])}')
        print(f'  {c_det}')
        chk.check(ok_pos and ok_size,
                  'R3-3a 窗口位置与尺寸按帧首矩形（rect_A）落位',
                  f'win={wr} vs expA={tuple(expA[:4])}')
        chk.check(c_ok,
                  'R3-3b 画面内容也按帧首矩形（rect_A）排布 —— 一帧只用一个矩形快照',
                  c_det)

        # 下一帧收敛：候选框静止后，窗口与画面都等于当前矩形的 plan
        ov._position_once()
        r = cand.rtuple()
        exp = _expect(ov, r)
        wr = _win_rect(ov)
        c_ok2, c_det2 = _cmp_frame(ov, exp, '按当前矩形核对画面')
        chk.check(wr == tuple(exp[:4]) and c_ok2,
                  'R3-3c 下一帧完全收敛（窗口 + 画面 = 当前矩形 plan，逐位一致）',
                  f'win={wr} plan={tuple(exp[:4])} {c_det2}')

        # ================= R3-4: 变宽帧的窗口尺寸必须真落到窗口上 =================
        print('\n[R3-4] 画布变宽/收窄后窗口尺寸必须真改（含「只变宽不移动」）')
        r0 = cand.rtuple()
        cand.move(r0[0], r0[1], 700)     # 只变宽、不动
        ov._position_once()
        r = cand.rtuple()
        exp = _expect(ov, r)
        wr = _win_rect(ov)
        chk.check(wr == tuple(exp[:4]), 'R3-4a 只变宽不移动：窗口尺寸跟上新画布',
                  f'win={wr} plan={tuple(exp[:4])}')
        cand.move(r0[0], r0[1], 430)     # 收窄
        ov._position_once()
        r = cand.rtuple()
        exp = _expect(ov, r)
        wr = _win_rect(ov)
        chk.check(wr == tuple(exp[:4]), 'R3-4b 收窄：窗口尺寸同步收窄',
                  f'win={wr} plan={tuple(exp[:4])}')

        # ================= R3-5: 单图层路径零漂移（v1.6 退化） =================
        print('\n[R3-5] 单图层：多图层改动不许碰单层路径（v1.6 退化）')
        single = make_layers(os.path.join(tmp, 'one'), [(160, 240)])
        cfg1 = build_cfg(single, 'compat')
        cfg1['layers'] = [cfg1['layers'][0]]           # 显式单层
        ov1 = m.FollowOverlay(cfg1)
        ovs.append(ov1)
        try:
            ov1.tray.stop()
        except Exception:
            pass
        chk.check(not ov1._layers_active(), 'R3-5a 单层 cfg → _layers_active() 为 False')
        cand1 = FakeCandidate(x=300, y=200, w=380, h=64)
        cands.append(cand1)
        ov1._cached_hwnd = cand1.hwnd
        m.set_candidate_hwnd(cand1.hwnd)
        ov1._last_scan_ts = 0.0
        ov1._position_once()
        rr = cand1.rect()
        x, y, w, h, size_changed = ov1._plan_targets(rr)
        ewx = rr.right + 8 + ov1.off_x + ov1.cfg.get('offset_x', 0)
        ewy = rr.top + ((rr.bottom - rr.top) - ov1.h) // 2 + ov1.off_y + ov1.cfg.get('offset_y', 0)
        chk.check((x, y) == (int(ewx), int(ewy)),
                  'R3-5b 单层目标坐标 = v1.6 公式（逐位一致）',
                  f'got=({x},{y}) v1.6=({int(ewx)},{int(ewy)})')
        chk.check((w is None and h is None and size_changed is False),
                  'R3-5c 单层 _plan_targets 仍返回 (None,None,False)（SWP_NOSIZE 老路径）',
                  f'w={w} h={h} size_changed={size_changed}')
        wr = _win_rect(ov1)
        chk.check(abs(wr[0] - x) < 2 and abs(wr[1] - y) < 2,
                  'R3-5d 单层窗口实际位置到位', f'win={wr[:2]} target=({x},{y})')
        try:
            ov1.root.withdraw(); ov1.root.destroy()
        except Exception:
            pass
        ovs.remove(ov1)
        m.set_candidate_hwnd(cand.hwnd)

        # ================= R3-6: 稳态不动帧不许重复推图（alpha 模式） =================
        print('\n[R3-6] alpha 模式：窗口不动时不许逐帧重复推位图')
        cfg2 = build_cfg(big, 'alpha', ['right_edge', 'left_edge', 'right_edge'],
                        [(0, 0), (0, 0), (300, 0)], base_height=420, scale=0.7)
        ov2 = m.FollowOverlay(cfg2)
        ovs.append(ov2)
        try:
            ov2.tray.stop()
        except Exception:
            pass
        cand2 = FakeCandidate(x=120, y=260, w=500, h=72)
        cands.append(cand2)
        ov2._cached_hwnd = cand2.hwnd
        m.set_candidate_hwnd(cand2.hwnd)
        ov2._last_scan_ts = 0.0
        ov2._position_once()
        n0 = getattr(ov2.renderer, '_n_push', 0)
        for _ in range(10):
            ov2._position_once()          # 候选框不动：死区应吞掉整条路径
        n1 = getattr(ov2.renderer, '_n_push', 0)
        chk.check(n1 == n0, 'R3-6 窗口未移动 → 分层窗不再重复推位图',
                  f'push {n0} → {n1}（10 帧静止）')
        r = cand2.rtuple()
        exp = _expect(ov2, r)
        wr = _win_rect(ov2)
        chk.check(wr == tuple(exp[:4]), 'R3-6b alpha 模式窗口位置/尺寸 = plan 逐位一致',
                  f'win={wr} plan={tuple(exp[:4])}')

        # ================= R3-7: 动图 + 多图层：换帧不许让画布与窗口尺寸脱钩 =================
        print('\n[R3-7] 动图层 + 多图层：换帧后画布尺寸必须与窗口尺寸一致')
        gif = make_anim_gif(os.path.join(tmp, 'anim'), n=8)
        p2 = make_layers(os.path.join(tmp, 'anim2'), [(200, 300)], block=20)[0]
        cfg3 = build_cfg([gif, p2], 'compat', ['right_edge', 'left_edge'], [(0, 0), (0, 0)])
        ov3 = m.FollowOverlay(cfg3)
        ovs.append(ov3)
        try:
            ov3.tray.stop()
        except Exception:
            pass
        cand3 = FakeCandidate(x=140, y=280, w=460, h=72)
        cands.append(cand3)
        ov3._cached_hwnd = cand3.hwnd
        m.set_candidate_hwnd(cand3.hwnd)
        ov3._last_scan_ts = 0.0
        chk.check(ov3.anim_n > 1, 'R3-7a 夹具确为动图（多帧）', f'anim_n={ov3.anim_n}')
        ov3._position_once()
        for i in range(12):                      # 动图节拍与打字节奏交替（共用主线程）
            r = cand3.rtuple()
            if i % 3 == 0:
                cand3.move(r[0] + 5, r[1] + 2, (r[2] - r[0]) + (60 if i == 6 else 0))
                ov3._position_once()
            else:
                ov3._anim_tick()
        r = cand3.rtuple()
        ov3._position_once()
        exp = _expect(ov3, r)
        wr = _win_rect(ov3)
        canvas_wh = (ov3.img.width(), ov3.img.height())
        chk.check(wr == tuple(exp[:4]), 'R3-7b 动图+多图层：窗口位置/尺寸 = plan 逐位一致',
                  f'win={wr} plan={tuple(exp[:4])}')
        chk.check(canvas_wh == wr[2:], 'R3-7c 画布尺寸 = 窗口尺寸（换帧不许让两者脱钩）',
                  f'canvas={canvas_wh} window={wr[2:]}')

        # ================= R3-8: 热重载后尺寸缓存必须失效 =================
        print('\n[R3-8] 热重载（同路径换图、尺寸变）：尺寸缓存必须失效')
        hot = make_layers(os.path.join(tmp, 'hot'), [(160, 240), (120, 180)], block=20)
        cfg4 = build_cfg(hot, 'compat', ['right_edge', 'left_edge'], [(0, 0), (0, 0)])
        ov4 = m.FollowOverlay(cfg4)
        ovs.append(ov4)
        try:
            ov4.tray.stop()
        except Exception:
            pass
        cand4 = FakeCandidate(x=90, y=210, w=440, h=72)
        cands.append(cand4)
        ov4._cached_hwnd = cand4.hwnd
        m.set_candidate_hwnd(cand4.hwnd)
        ov4._last_scan_ts = 0.0
        ov4._position_once()
        d0 = ov4._layer_dims()
        from PIL import Image as PILImage
        im2 = PILImage.new('RGBA', (300, 500), (0, 0, 0, 0))
        im2.paste(PILImage.new('RGBA', (260, 460), (0, 150, 0, 255)), (20, 20))
        im2.save(hot[1])
        ov4.load_char()                     # check_skin 检测到 mtime 变化后走的同一条路
        ov4._position_once()
        d1 = ov4._layer_dims()
        r = cand4.rtuple()
        exp = _expect(ov4, r)
        wr = _win_rect(ov4)
        chk.check(d0[1] != d1[1], 'R3-8a 换图后该层显示尺寸被重新测量（缓存已失效）',
                  f'{d0} → {d1}')
        chk.check(wr == tuple(exp[:4]), 'R3-8b 热重载后窗口位置/尺寸 = plan 逐位一致',
                  f'win={wr} plan={tuple(exp[:4])}')

        return chk.done()
    except AssertionError as e:
        print('RESULT FAIL:', e)
        return 1
    except Exception:
        traceback.print_exc()
        print('RESULT ERROR')
        return 2
    finally:
        try:
            io.stop()
        except Exception:
            pass
        for o in list(ovs):
            try:
                o.root.withdraw(); o.root.destroy()
            except Exception:
                pass
        for c in list(cands):
            try:
                c.destroy()
            except Exception:
                pass
        try:
            m.set_candidate_hwnd(0)
        except Exception:
            pass
        try:
            m._release_event_thread()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
        time.sleep(0.05)


if __name__ == '__main__':
    sys.exit(main())
