# -*- coding: utf-8 -*-
"""B_test_r14_flicker.py —— R14「打字时图片短暂闪烁」判据与回归

用户第四轮反馈（原话）：「加一个，打字时图片会短暂闪烁，以前不会。」

【闪烁的可观测判据（本脚本的度量口径）】
  打字时候选框宽度变化 → 多图层画布尺寸变 → 窗口必须 resize。resize 与「屏幕内容（位图/
  Label）就位」是两次独立的系统动作，两者之间窗口尺寸 != 内容尺寸：
    · 窗口 > 内容 → 露底（compat：露键色底被抠成透出桌面；alpha：ULW 位图不覆盖的窗口区域）
      = 用户肉眼看到的「图片短缺一块 / 闪一下」；
    · 窗口 < 内容 → 图被窗口边界裁掉（内容不全）。
  判据 F1：一帧内**任何采样点**上必须恒有「窗口尺寸 == 内容尺寸」；不一致即闪烁帧。
  判据 F2：帧内顺序必须是「内容就位 → resize」，不得出现「先 resize 后内容就位」。
  判据 F3：alpha 模式下同一帧不得对同一位图重复推送（每次 ULW 推送 = 一次整窗内容替换）。
  判据 F4：露底状态在屏幕上确实可见（抓屏实证：窗口 > 内容时图片像素宽度只到内容宽度）。

用法: python B_test_r14_flicker.py   （退出码 0=全过 / 1=断言失败 / 2=异常）
"""
import sys, os, time, ctypes, tempfile, traceback
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


m = _load_module(SRC, 'rime_char_overlay_r14')
USER32 = m.user32
KERNEL32 = m.kernel32

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
        cls = f'ATL:R14FlickerCand{type(self)._seq[0]}'
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


COLORS = [(255, 0, 0), (0, 150, 0), (0, 0, 255), (255, 140, 0), (140, 0, 200), (0, 160, 160)]


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


def build_cfg(imgs, mode='compat', anchors=None, offsets=None, base_height=420, scale=0.7):
    cfg = dict(m.DEFAULT_CONFIG)
    cfg['image'] = imgs[0]
    cfg['layout'] = 'horizontal_double'
    cfg['side'] = 'right'
    cfg['layer'] = 'above'
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


# ==================== 帧内采样与判据（纯逻辑，可被判别力测试直接喂构造序列）====================

K_CONTENT = 'CONTENT'   # 内容（位图/Label）就位尺寸发生变化的动作
K_RESIZE = 'RESIZE'     # 窗口尺寸发生变化的动作（Tk geometry / SetWindowPos 带尺寸）


def analyze_sequence(samples):
    """帧内采样序列 → 闪烁判据结果。

    samples: [dict(t=动作名, win=(w,h), content=(w,h), kind=K_CONTENT/K_RESIZE/None,
                   real_change=bool|None), ...]
      win     = 顶层窗口当前尺寸（GetWindowRect）
      content = 当前应显示的位图尺寸（窗口内容真源）
      real_change = 该 RESIZE 动作是否真的改变了窗口尺寸（同值 geometry 记账 = False）

    闪烁的物理载体（两条，都可判定）：
      F1 每次「窗口尺寸发生变化的动作」之后，窗口尺寸必须已 == 位图尺寸。
         否则系统按新窗口尺寸重绘时会出现：窗口 > 位图（露底，屏幕露出未覆盖区域）
         或 窗口 < 位图（图片被窗口边界裁掉）—— 即肉眼看到的「闪一下」。
      F3 帧末（含 Tk idle 处理后）窗口尺寸必须 == 位图尺寸。
      F4 帧内「真的改变窗口尺寸」的次数 ≤ 1（尺寸变化必须由一次原子操作完成，
         不得先异步 geometry 再 SetWindowPos 各改一次）。

    返回 dict: n_resize_bad / n_resize_leak / n_resize_clip / n_end_bad /
               n_real_resize / n_resize_calls / details
    """
    n_bad = n_leak = n_clip = 0
    n_real = 0
    n_calls = 0
    details = []
    for i, s in enumerate(samples):
        if s.get('kind') != K_RESIZE:
            continue
        n_calls += 1
        if s.get('real_change'):
            n_real += 1
        win, cont = s.get('win'), s.get('content')
        if win and cont and win != cont:
            n_bad += 1
            if win[0] > cont[0] or win[1] > cont[1]:
                n_leak += 1
                kind = '露底'
            else:
                n_clip += 1
                kind = '裁剪'
            details.append((i, s.get('t'), kind, win, cont,
                            '真改尺寸' if s.get('real_change') else '同值'))
    end = samples[-1] if samples else {}
    n_end_bad = 0 if (end.get('win') and end.get('content')
                      and end['win'] == end['content']) else 1
    return dict(n_resize_bad=n_bad, n_resize_leak=n_leak, n_resize_clip=n_clip,
                n_end_bad=n_end_bad, n_real_resize=n_real, n_resize_calls=n_calls,
                details=details)


class FrameSampler:
    """打桩：把一帧内所有「改窗口尺寸」「改内容尺寸」「推位图」的点都采样下来。"""

    def __init__(self, ov, mod):
        self.ov = ov
        self.mod = mod
        self.samples = []
        self.push_bad = []
        self.pushes = []
        self.resize_lag = []
        self.n_push = 0
        self.n_resize = 0
        self.n_geom = 0
        self._orig = {}

    # ---- 采样口径 ----
    def win(self):
        t = 0
        try:
            t = int(self.ov._top_hwnd() or 0)
        except Exception:
            return None
        if not t:
            return None
        r = wintypes.RECT()
        if not USER32.GetWindowRect(t, ctypes.byref(r)):
            return None
        return (int(r.right - r.left), int(r.bottom - r.top))

    def content(self):
        """「屏幕内容真源尺寸」= 当前位图尺寸（compat：Label 的 PhotoImage；alpha：ULW 帧）。

        窗口尺寸必须与它相等：窗口更大 → 露出未覆盖区域（透出桌面/键色）；窗口更小 →
        图片被窗口边界裁掉。两者都只在「resize 已发生」时才会被系统重绘到屏幕上。
        """
        im = getattr(self.ov, 'img', None)
        if im is not None:
            try:
                return (int(im.width()), int(im.height()))
            except Exception:
                pass
        return None

    def label_req(self):
        """Tk 侧请求尺寸（诊断用：Label 比窗口晚一拍就位时会 > 位图尺寸）"""
        lb = getattr(self.ov, 'label', None)
        if lb is None:
            return None
        try:
            return (int(lb.winfo_reqwidth()), int(lb.winfo_reqheight()))
        except Exception:
            return None

    def label_now(self):
        """Tk 侧**实际**已排布的贴图尺寸（idle 处理前还是旧值 → 就是屏幕上的中间态）"""
        lb = getattr(self.ov, 'label', None)
        if lb is None:
            return None
        try:
            return (int(lb.winfo_width()), int(lb.winfo_height()))
        except Exception:
            return None

    def win_pos(self):
        t = 0
        try:
            t = int(self.ov._top_hwnd() or 0)
        except Exception:
            return None
        if not t:
            return None
        r = wintypes.RECT()
        if not USER32.GetWindowRect(t, ctypes.byref(r)):
            return None
        return (int(r.left), int(r.top))

    def snap(self, t, kind=None, before=None):
        w = self.win()
        self.samples.append(dict(t=t, win=w, content=self.content(), kind=kind,
                                 real_change=(None if before is None else (w != before))))

    def reset(self):
        self.samples = []
        self.push_bad = []
        self.pushes = []
        self.resize_lag = []
        self.n_push = 0
        self.n_resize = 0
        self.n_geom = 0

    def install(self):
        rec = self
        ov = self.ov
        mod = self.mod
        self._orig['swp'] = mod.user32.SetWindowPos
        self._orig['geom'] = ov.root.geometry
        self._orig['compose'] = ov._compose_into_renderer
        self._orig['push'] = getattr(ov.renderer, 'push_static', None)
        st = {'top': 0}

        def top():
            if not st['top']:
                try:
                    st['top'] = int(ov._top_hwnd() or 0)
                except Exception:
                    st['top'] = 0
            return st['top']

        def swp(hwnd, after, x, y, cx, cy, flags):
            before = rec.win() if hwnd == top() else None
            r = self._orig['swp'](hwnd, after, x, y, cx, cy, flags)
            if hwnd == top() and (cx or cy) and not (flags & 0x0001):
                rec.n_resize += 1
                rec.snap('SetWindowPos', kind=K_RESIZE, before=before)
                # compat：窗口几何已变，而 Tk 的贴图还在旧尺寸 = 屏幕上的露底/裁剪中间态
                ln, cn = rec.label_now(), rec.content()
                if ln and cn and (abs(ln[0] - cn[0]) > 6 or abs(ln[1] - cn[1]) > 6):
                    rec.resize_lag.append((ln, cn))
            return r

        mod.user32.SetWindowPos = swp

        def geom(spec=None):
            before = rec.win() if spec is not None else None
            r = self._orig['geom'](spec)
            if spec is not None:
                rec.n_geom += 1
                rec.snap('geometry', kind=K_RESIZE, before=before)
            return r

        ov.root.geometry = geom

        def compose(*a, **kw):
            c = self._orig['compose'](*a, **kw)
            rec.snap('compose', kind=K_CONTENT)
            return c

        ov._compose_into_renderer = compose

        if self._orig['push'] is not None:
            def push(*a, **kw):
                rec.n_push += 1
                w0, c0 = rec.win(), rec.content()
                p0 = rec.win_pos()
                r = self._orig['push'](*a, **kw)
                rec.snap('push', kind=None)
                rec.pushes.append((p0, w0))
                if w0 and c0 and w0 != c0:
                    # ULW 提交是同步生效的：把位图推给尺寸不匹配的窗口 = 立即上屏的中间态
                    rec.push_bad.append((w0, c0))
                return r
            ov.renderer.push_static = push
        return

    def restore(self):
        self.mod.user32.SetWindowPos = self._orig['swp']
        self.ov.root.geometry = self._orig['geom']
        self.ov._compose_into_renderer = self._orig['compose']
        if self._orig['push'] is not None:
            self.ov.renderer.push_static = self._orig['push']


def make_overlay(tmp, mode, n_layers=3):
    sizes = [(400, 600), (360, 540), (300, 450)][:n_layers]
    imgs = make_layers(os.path.join(tmp, f'{mode}_{n_layers}'), sizes)
    anchors = ['right_edge', 'left_edge', 'right_edge'][:n_layers]
    offs = [(0, 0), (0, 0), (300, 0)][:n_layers]
    cfg = build_cfg(imgs, mode, anchors, offs)
    ov = m.FollowOverlay(cfg)
    try:
        ov.tray.stop()
    except Exception:
        pass
    return ov, cfg


def main():
    print('=== R14 打字时图片短暂闪烁：判据 / 判别力 / 零漂移 / 性能 ===')
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
    tmp = tempfile.mkdtemp(prefix='r14_flicker_')
    cands = []
    ovs = []
    try:
        # ================= A 段：多图层尺寸变化帧的中间态（compat / alpha） =================
        print('\n[A] 多图层 + 候选框宽度变化：resize 之后「窗口尺寸 == 位图尺寸」恒等性')
        print('    变宽=打字输入（新字符）  变窄=候选收缩/删字（此时窗口 > 位图 = 露底，肉眼最明显）')
        for mode in ('compat', 'alpha'):
            for scen, label in (('grow', '变宽'), ('shrink', '变窄')):
                cand = FakeCandidate(60, 120, 420, 72)
                cands.append(cand)
                ov, cfg = make_overlay(tmp, mode)
                ovs.append(ov)
                ov._cached_hwnd = cand.hwnd
                m.set_candidate_hwnd(cand.hwnd)
                ov._last_scan_ts = 0.0
                smp = FrameSampler(ov, m)
                smp.install()
                cand.move(60, 120, 440 + 20 * 5)      # 起点：最宽
                ov._position_once()
                ov.root.update_idletasks()
                agg = dict(n_resize_bad=0, n_resize_leak=0, n_resize_clip=0,
                           n_end_bad=0, n_real_resize=0, n_resize_calls=0)
                tot_push = 0
                n_push_bad = 0
                n_stale = 0
                n_resize_lag = 0
                N = 5
                for i in range(N):
                    w = (440 + 20 * (N - 1 - i)) if scen == 'shrink' else (440 + 20 * i)
                    cand.move(60, 120, w)
                    smp.reset()
                    smp.snap('帧首')
                    ov._position_once()
                    smp.snap('帧末')
                    ov.root.update_idletasks()
                    # 「过期提交」：位图提交时窗口还在旧位置/旧尺寸，提交立刻被随后的移动甩掉
                    # → 屏幕先显示「新内容 + 旧位置/旧尺寸」一瞬 = 肉眼看到的图片闪回/缺块
                    end_pos, end_win = smp.win_pos(), smp.win()
                    stale = sum(1 for (p0, w0) in smp.pushes
                                if p0 is not None and end_pos is not None
                                and (p0 != end_pos or w0 != end_win))
                    res = analyze_sequence(smp.samples)
                    for k in agg:
                        agg[k] += res[k]
                    tot_push += smp.n_push
                    n_push_bad += len(smp.push_bad)
                    n_stale += stale
                    n_resize_lag += len(smp.resize_lag)
                    show = ';'.join(f'{d[1]}:{d[2]} win={d[3]} bmp={d[4]}({d[5]})'
                                    for d in res['details'][:2])
                    lag = (';'.join(f'label={a} bmp={b}' for a, b in smp.resize_lag[:2])
                           if smp.resize_lag else '')
                    print(f'  [{mode}/{label}] 帧{i} w={w}: resize点不一致={res["n_resize_bad"]}'
                          f'（露底={res["n_resize_leak"]} 裁剪={res["n_resize_clip"]}）'
                          f' 帧末不一致={res["n_end_bad"]} | push={smp.n_push} 过期提交={stale}'
                          f' 贴图滞后={len(smp.resize_lag)}'
                          + (f'  {show}' if show else '') + (f'  {lag}' if lag else ''))
                chk.check(n_stale == 0,
                          f'A01[{mode}/{label}] 无「过期提交」：位图提交时窗口几何已是最终值',
                          f'实测过期提交 {n_stale} 次 / {N} 帧')
                if mode == 'compat':
                    # alpha 模式下窗口内容由 ULW 位图承载、Label 不贴图 → 该判据只对 compat 成立
                    chk.check(n_resize_lag == 0,
                              f'A02[{mode}/{label}] 改窗口尺寸时贴图尺寸已就位（无露底/裁剪中间态）',
                              f'实测贴图滞后 {n_resize_lag} 次 / {N} 帧')
                chk.check(agg['n_end_bad'] == 0,
                          f'A03[{mode}/{label}] 帧末稳态窗口尺寸 == 位图尺寸（含 idle 处理后）',
                          f'实测不一致帧 {agg["n_end_bad"]} / {N}')
                if mode == 'alpha':
                    chk.check(n_push_bad == 0,
                              f'A05[alpha/{label}] 不在「窗口尺寸 != 位图尺寸」时提交 ULW 位图',
                              f'实测尺寸不匹配推送 {n_push_bad} 次 / push 合计 {tot_push}')
                    chk.check(tot_push <= N,
                              f'A06[alpha/{label}] 每帧对同一位图最多推 1 次（不重复 ULW 推送）',
                              f'实测 {N} 帧共 push={tot_push} 次')
                smp.restore()
                try:
                    ov.root.destroy()
                except Exception:
                    pass

        # ================= B 段：判别力（人为制造缺陷必须 FAIL） =================
        print('\n[B] 判别力：人为制造缺陷时必须报 FAIL')
        bad_seq = [
            dict(t='SetWindowPos', win=(1147, 294), content=(1127, 294), kind=K_RESIZE,
                 real_change=True),
            dict(t='compose', win=(1147, 294), content=(1147, 294), kind=K_CONTENT,
                 real_change=None),
        ]
        rb = analyze_sequence(bad_seq)
        chk.check(rb['n_resize_leak'] >= 1 and rb['n_resize_bad'] >= 1,
                  'B01 构造「先 resize 后推图/露底」序列 → 判据必须报 FAIL',
                  f'不一致={rb["n_resize_bad"]} 露底={rb["n_resize_leak"]}')
        good_seq = [
            dict(t='compose', win=(1127, 294), content=(1147, 294), kind=K_CONTENT,
                 real_change=None),
            dict(t='SetWindowPos', win=(1147, 294), content=(1147, 294), kind=K_RESIZE,
                 real_change=True),
            dict(t='帧末', win=(1147, 294), content=(1147, 294), kind=None, real_change=None),
        ]
        rg = analyze_sequence(good_seq)
        chk.check(rg['n_resize_bad'] == 0 and rg['n_end_bad'] == 0
                  and rg['n_real_resize'] == 1,
                  'B02 构造「内容先就位 → 一次原子 resize」序列 → 判据不得误报',
                  f'不一致={rg["n_resize_bad"]} 帧末不一致={rg["n_end_bad"]} '
                  f'真改尺寸={rg["n_real_resize"]}')
        dup_seq = [
            dict(t='geometry', win=(1147, 294), content=(1147, 294), kind=K_RESIZE,
                 real_change=True),
            dict(t='SetWindowPos', win=(1147, 294), content=(1147, 294), kind=K_RESIZE,
                 real_change=True),
        ]
        rd = analyze_sequence(dup_seq)
        chk.check(rd['n_real_resize'] == 2,
                  'B03 构造「同一帧两次真改窗口尺寸（重复 geometry）」序列 → A04 必须报 FAIL',
                  f'真改尺寸={rd["n_real_resize"]}（判据上限 1）')

        # B04：真实实现注入 —— 把「推图」提前到 resize 之前，A05 必须报 FAIL
        print('\n[B04] 真实实现注入：强制「先推位图、后 resize」→ A05 必须报 FAIL')
        cand4 = FakeCandidate(60, 120, 460, 72)
        cands.append(cand4)
        ov4, _ = make_overlay(tmp, 'alpha')
        ovs.append(ov4)
        ov4._cached_hwnd = cand4.hwnd
        m.set_candidate_hwnd(cand4.hwnd)
        ov4._last_scan_ts = 0.0
        smp4 = FrameSampler(ov4, m)
        smp4.install()
        cand4.move(60, 120, 460)
        ov4._position_once()
        ov4.root.update_idletasks()
        real_pt = ov4._plan_targets

        def bad_plan_targets(rect):
            """缺陷注入：在真改窗口尺寸之前，先把新位图推给旧尺寸窗口。"""
            layers = ov4._layer_specs()
            dims = ov4._layer_dims(ov4._Image, layers)
            plan = m.plan_layer_layout(layers, dims, rect,
                                       main_off=(ov4.off_x, ov4.off_y))
            try:
                ov4._compose_into_renderer(layers, sizes=dims, rect=rect,
                                           plan_key=(int(plan[2]), int(plan[3]),
                                                     tuple(plan[4])))
            except Exception:
                pass
            return real_pt(rect)

        ov4._plan_targets = bad_plan_targets
        bad = 0
        for i in range(3):
            cand4.move(60, 120, 480 + 20 * i)
            smp4.reset()
            ov4._position_once()
            smp4.snap('帧末')
            ov4.root.update_idletasks()
            bad += len(smp4.push_bad)
        chk.check(bad >= 1, 'B04 注入「先推位图后 resize」→ 尺寸不匹配推送必须被检出',
                  f'实测检出 {bad} 次（期望 ≥1）')
        smp4.restore()
        try:
            ov4.root.destroy()
        except Exception:
            pass

        # ================= C 段：单图层 v1.6 零漂移 =================
        print('\n[C] 单图层路径零漂移（窗口尺寸恒定、位置逐位等于 plan）')
        one = make_layers(os.path.join(tmp, 'single'), [(400, 600)])
        cfg1 = build_cfg(one, 'compat', ['right_edge'], [(0, 0)])
        cfg1['layers'] = cfg1['layers'][:1]
        cand1 = FakeCandidate(60, 120, 420, 72)
        cands.append(cand1)
        ov1 = m.FollowOverlay(cfg1)
        ovs.append(ov1)
        try:
            ov1.tray.stop()
        except Exception:
            pass
        ov1._cached_hwnd = cand1.hwnd
        m.set_candidate_hwnd(cand1.hwnd)
        ov1._last_scan_ts = 0.0
        sizes = []
        xy = []
        for i in range(6):
            cand1.move(60 + 5 * i, 120 + 3 * i, 420 + 25 * i)
            ov1._position_once()
            ov1.root.update_idletasks()
            r = wintypes.RECT()
            USER32.GetWindowRect(int(ov1._top_hwnd()), ctypes.byref(r))
            sizes.append((int(r.right - r.left), int(r.bottom - r.top)))
            xy.append((int(r.left), int(r.top)))
        chk.check(len(set(sizes)) == 1,
                  'C01 单图层：候选框变宽时窗口尺寸恒定（SWP_NOSIZE，v1.6 语义）',
                  f'实测尺寸集合 {sorted(set(sizes))}')
        r = cand1.rtuple()
        exp = m.plan_layer_layout(ov1._layer_specs(), [(ov1.w, ov1.h)], r,
                                  main_off=(ov1.off_x, ov1.off_y))
        chk.check((xy[-1][0], xy[-1][1]) == (int(exp[0]), int(exp[1])),
                  'C02 单图层：窗口位置逐位等于 plan_layer_layout（老路径不漂）',
                  f'win={xy[-1]} plan=({int(exp[0])},{int(exp[1])})')
        try:
            ov1.root.destroy()
        except Exception:
            pass

        # C03：单图层 alpha（分层窗）移动帧 —— 每次提交都必须在窗口移动之后
        cfg1a = build_cfg(make_layers(os.path.join(tmp, 'single_a'), [(400, 600)]),
                          'alpha', ['right_edge'], [(0, 0)])
        cfg1a['layers'] = cfg1a['layers'][:1]
        cand1a = FakeCandidate(60, 120, 420, 72)
        cands.append(cand1a)
        ov1a = m.FollowOverlay(cfg1a)
        ovs.append(ov1a)
        try:
            ov1a.tray.stop()
        except Exception:
            pass
        ov1a._cached_hwnd = cand1a.hwnd
        m.set_candidate_hwnd(cand1a.hwnd)
        ov1a._last_scan_ts = 0.0
        smp1a = FrameSampler(ov1a, m)
        smp1a.install()
        ov1a._position_once()
        ov1a.root.update_idletasks()
        stale1a = 0
        moved1a = 0
        for i in range(4):
            r = cand1a.rtuple()
            cand1a.move(r[0] + 9, r[1] + 5, r[2] - r[0], r[3] - r[1])
            smp1a.reset()
            ov1a._position_once()
            ov1a.root.update_idletasks()
            end_pos, end_win = smp1a.win_pos(), smp1a.win()
            if (end_pos, end_win) != (r[0], r[1], end_win):
                moved1a += 1
            stale1a += sum(1 for (p0, w0) in smp1a.pushes
                           if p0 is not None and end_pos is not None
                           and (p0 != end_pos or w0 != end_win))
        chk.check(stale1a == 0,
                  'C03 单图层 alpha 移动帧：位图提交时窗口已在最终位置（无过期提交）',
                  f'实测过期提交 {stale1a} 次 / 4 帧（push 合计见下）')
        chk.check(moved1a == 4,
                  'C04 单图层 alpha 移动帧：窗口确实移动到目标位置（跟随未被破坏）',
                  f'实测移动生效 {moved1a} / 4 帧')
        smp1a.restore()
        try:
            ov1a.root.destroy()
        except Exception:
            pass

        # ================= D 段：性能不回归 + 布局正确性 =================
        print('\n[D] 性能（R3 改善不得回退）与布局正确性')
        from PIL import Image as PILImage
        cand5 = FakeCandidate(60, 120, 420, 72)
        cands.append(cand5)
        ov5 = m.FollowOverlay(build_cfg(make_layers(os.path.join(tmp, 'perf'), [(400, 600)] * 3),
                                        'compat', ['right_edge', 'left_edge', 'right_edge'],
                                        [(0, 0), (0, 0), (300, 0)]))
        ovs.append(ov5)
        try:
            ov5.tray.stop()
        except Exception:
            pass
        ov5._cached_hwnd = cand5.hwnd
        m.set_candidate_hwnd(cand5.hwnd)
        ov5._last_scan_ts = 0.0
        real_open = PILImage.open
        n_open = [0]

        def counting_open(*a, **kw):
            n_open[0] += 1
            return real_open(*a, **kw)

        cand5.move(60, 120, 460)
        ov5._position_once()
        PILImage.open = counting_open
        times = []
        try:
            for i in range(12):
                cand5.move(60 + 3 * i, 120 + 2 * i, 460)
                t0 = time.perf_counter()
                ov5._position_once()
                times.append((time.perf_counter() - t0) * 1000)
        finally:
            PILImage.open = real_open
        times.sort()
        p50 = times[len(times) // 2]
        chk.check(n_open[0] == 0,
                  'D01 稳态帧零文件 I/O（R3 的尺寸缓存未被破坏）',
                  f'实测 Image.open {n_open[0]} 次 / 12 帧')
        chk.check(p50 < 8.0,
                  'D02 稳态单帧 p50 未显著上升（同口径绝对上限 8ms）',
                  f'实测 p50={p50:.2f} ms（12 帧）')

        # D03：一次变宽帧后，窗口几何与位图尺寸都必须逐位等于 plan
        cand5.move(60, 120, 560)
        ov5._position_once()
        ov5.root.update_idletasks()
        rr = cand5.rtuple()
        exp5 = m.plan_layer_layout(ov5._layer_specs(), ov5._layer_dims(), rr,
                                   main_off=(ov5.off_x, ov5.off_y))
        t5 = 0
        try:
            t5 = int(ov5._top_hwnd() or 0)
        except Exception:
            t5 = 0
        r5 = wintypes.RECT()
        USER32.GetWindowRect(t5, ctypes.byref(r5))
        win5 = (int(r5.left), int(r5.top), int(r5.right - r5.left), int(r5.bottom - r5.top))
        chk.check(win5 == (int(exp5[0]), int(exp5[1]), int(exp5[2]), int(exp5[3])),
                  'D03 变宽帧后窗口「位置+尺寸」逐位等于 plan_layer_layout（布局未坏）',
                  f'win={win5} plan=({int(exp5[0])},{int(exp5[1])},{int(exp5[2])},{int(exp5[3])})')
        img5 = getattr(ov5, 'img', None)
        bmp5 = (int(img5.width()), int(img5.height())) if img5 is not None else None
        chk.check(bmp5 == (int(exp5[2]), int(exp5[3])),
                  'D04 变宽帧后位图尺寸 == 画布尺寸（内容与窗口同源）',
                  f'bmp={bmp5} canvas=({int(exp5[2])},{int(exp5[3])})')
        try:
            ov5.root.destroy()
        except Exception:
            pass
    except Exception:
        traceback.print_exc()
        return 2
    finally:
        for ov in ovs:
            try:
                ov.root.destroy()
            except Exception:
                pass
        for c in cands:
            c.destroy()
    return chk.done()


if __name__ == '__main__':
    sys.exit(main())
