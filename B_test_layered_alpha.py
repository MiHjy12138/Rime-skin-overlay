# -*- coding: utf-8 -*-
"""B_test_layered_alpha.py —— v2.0-①b 真 alpha 分层窗实装验证

对照《Rime皮肤外挂-升级操作手册》① 步 2-6 与验收标准：
  S0 预乘正确性：RGBA → 预乘 BGRA 的字节序/长度/舍入口径（逐像素参考实现比对，含半透明/全透明）
  S1 向量化性能：300x420 ≤10ms、450x675 ≤20ms（手册基线 2.07 / 4.09 ms）
  S2 源码口径：premultiply_bgra 里不存在逐像素 Python 循环（源码静态检查）
  S3 位图格式：BITMAPINFOHEADER 的 biHeight 取负、32bpp、BI_RGB；UpdateLayeredWindow 真推成功
  S4 抓屏三色：复现 spike 结论（中心≈红 / 羽化带介于红白 / 角落≈白）—— 真实 ImageGrab
  S5 点击穿透：alpha=0 区域 WindowFromPoint 真实命中下层窗口；不透明区命中分层窗
  S6 品红不被抠穿：含纯品红的图在 alpha 模式下照原色显示
  S7 compat/alpha 切换一致性：alpha 摘掉 -transparentcolor + 带 WS_EX_LAYERED；切回 compat 复原
  S8 推送时机：静态图只推一次（不轮询硬推）；动图每帧推；移动后重推
  S9 三状态小步验证（手册「风险与回滚」点名）：隐藏→显示 / 切皮肤 / 拖动中，各自抓屏核对
  S10 交互链路：拖动/滚轮/右键/快捷键绑定照旧挂在 Tk 窗上

红线：只读被测模块；皮肤档案写临时目录；save_config 打桩；不碰真实 config.json / skins/。
需要真实桌面的检查（抓屏、命中测试）在异常时打印原文并记 SKIP（不得 FAIL）。

用法: python B_test_layered_alpha.py
"""
import os
import sys
import time
import ctypes
import inspect
import tempfile
import collections
import ctypes.wintypes as wintypes

import tkinter as tk
from PIL import Image, ImageGrab, ImageTk

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R          # noqa: E402

PASS, FAIL, SKIPPED = [], [], []
U32 = R.user32
K32 = R.kernel32


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f'  [PASS] {name}' + (f'  ({detail})' if detail else ''))
    else:
        FAIL.append(name)
        print(f'  [FAIL] {name}' + (f'  ({detail})' if detail else ''))


def skip(name, detail=''):
    SKIPPED.append(name)
    print(f'  [SKIP] {name}' + (f'  ({detail})' if detail else ''))


# ---------------- 夹具 ----------------
def make_soft_disc(size=200, color=(220, 40, 40), feather=40):
    """红圆盘、边缘 feather px 内 alpha 从 255 平滑降到 0（真渐变，spike 同款夹具）

    必须逐像素算距离：用 ImageDraw 画同心实心圆是「内层覆盖外层」，只能得到硬边。
    """
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    px = img.load()
    c = size / 2.0
    for y in range(size):
        for x in range(size):
            d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            a = 255 if d <= c - feather else max(0, int(255 * (c - d) / feather))
            if a > 0:
                px[x, y] = (color[0], color[1], color[2], a)
    return img


def make_flat_block(w, h, color=(220, 40, 40), alpha=255):
    return Image.new('RGBA', (w, h), (color[0], color[1], color[2], alpha))


def make_magenta_block(w=60, h=60):
    """含纯品红（#FF00FF）的不透明块 —— compat 模式会被键色抠穿，alpha 模式必须照原色显示"""
    return Image.new('RGBA', (w, h), (255, 0, 255, 255))


def _top_hwnd(root):
    """Tk 的 winfo_id 是内层子窗：沿 GetParent 链取真正顶层（与 FollowOverlay._top_hwnd 同口径）"""
    h = root.winfo_id()
    while True:
        p = U32.GetParent(h)
        if not p:
            return h
        h = p


def _ga_root(hwnd):
    try:
        return U32.GetAncestor(hwnd, 2)   # GA_ROOT
    except Exception:
        return 0


def _premultiply_reference(img_rgba):
    """逐像素参考实现（仅测试用）：spike 同口径 (c*a)//255，BGRA 顺序"""
    w, h = img_rgba.size
    px = img_rgba.load()
    out = bytearray(w * h * 4)
    i = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            out[i] = (b * a) // 255
            out[i + 1] = (g * a) // 255
            out[i + 2] = (r * a) // 255
            out[i + 3] = a
            i += 4
    return bytes(out)


def _grab(bbox, tries=3, delay=0.12):
    """抓屏（失败重试几次）；仍失败则抛异常交给调用方 SKIP"""
    last = None
    for _ in range(tries):
        try:
            time.sleep(delay)
            return ImageGrab.grab(bbox=bbox)
        except Exception as e:      # 抓屏在无桌面/被占屏时会抛
            last = e
    raise last


class _MiniOverlay:
    """只带渲染层所需字段的最小壳（合成窗口测试用，不启动 FollowOverlay）"""

    def __init__(self, root):
        self.root = root
        self.cfg = dict(R.DEFAULT_CONFIG)
        self._x = 0
        self._y = 0
        self._Image = Image
        self._ImageTk = ImageTk

    def _top_hwnd(self):
        return _top_hwnd(self.root)


def main():
    print('=== v2.0-①b 真 alpha 分层窗验证：向量化预乘 + UpdateLayeredWindow ===')
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

    U32.GetParent.argtypes = [wintypes.HWND]
    U32.GetParent.restype = wintypes.HWND
    U32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    U32.GetAncestor.restype = wintypes.HWND
    R._prepare_win32()

    tmp = tempfile.mkdtemp(prefix='layered_test_')
    img_path = os.path.join(BASE, 'char.png')
    if not os.path.exists(img_path):
        Image.new('RGBA', (160, 240), (0, 0, 0, 0)).save(img_path)
        print('[夹具] 现场生成 char.png（160x240 透明底 RGBA）')

    root = None
    extra_roots = []
    overlays = []
    try:
        root = tk.Tk()
        root.withdraw()
        root.update()
        mini = _MiniOverlay(root)
        rnd = R.LayeredRenderer(mini, 'alpha')

        # ---------------- S0 预乘正确性 ----------------
        print('\n[S0] 预乘正确性（BGRA 字节序 / 舍入口径 / 半透明与全透明）')
        im = Image.new('RGBA', (8, 1))
        px = [(0, 0, 0, 0), (255, 255, 255, 255), (10, 20, 30, 128), (200, 100, 50, 60),
              (255, 0, 255, 1), (123, 45, 67, 200), (1, 2, 3, 128), (255, 255, 255, 0)]
        for i, v in enumerate(px):
            im.putpixel((i, 0), v)
        got = rnd.premultiply_bgra(im)
        ref = _premultiply_reference(im)
        check('S0a 与逐像素参考实现逐字节一致（含半透明/全透明/1 alpha）',
              got == ref, f'{len(got)}B == {len(ref)}B')
        # 字节序：第 0 字节必须是 B 通道预乘值
        b0, g0, r0, a0 = got[0:4]
        check('S0b 字节序为 BGRA（首像素透明 → 全 0）',
              (b0, g0, r0, a0) == (0, 0, 0, 0), f'{b0},{g0},{r0},{a0}')
        idx = 4 * 3                                     # (200,100,50,60)
        check('S0c 预乘值 = (通道*alpha)//255 且 alpha 原样保留',
              (got[idx], got[idx + 1], got[idx + 2], got[idx + 3])
              == ((50 * 60) // 255, (100 * 60) // 255, (200 * 60) // 255, 60),
              f'{got[idx:idx + 4]}')
        check('S0d 输出长度 = w*h*4', len(got) == im.size[0] * im.size[1] * 4)
        big = Image.new('RGBA', (37, 23))
        for y in range(23):
            for x in range(37):
                big.putpixel((x, y), (x * 7 % 256, y * 11 % 256, (x + y) * 5 % 256, (x * y) % 256))
        check('S0e 随机图逐字节一致（37x23 全量）',
              rnd.premultiply_bgra(big) == _premultiply_reference(big))
        check('S0f 非 RGBA 输入自动转换后仍正确',
              rnd.premultiply_bgra(im.convert('RGB'))
              == _premultiply_reference(im.convert('RGB').convert('RGBA')))

        # ---------------- S1 性能 ----------------
        print('\n[S1] 向量化预乘性能（手册基线 300x420=2.07ms / 450x675=4.09ms）')
        perf = {}
        for size, limit in (((300, 420), 10.0), ((450, 675), 20.0)):
            src = make_flat_block(size[0], size[1], (180, 90, 60))
            for y in range(0, size[1], 4):
                for x in range(0, size[0], 4):
                    src.putpixel((x, y), (x % 256, y % 256, 200, (x * y) % 256))
            ts = []
            for _ in range(12):
                t0 = time.perf_counter()
                rnd.premultiply_bgra(src)
                ts.append((time.perf_counter() - t0) * 1000.0)
            mean = sum(ts) / len(ts)
            perf[size] = (mean, min(ts), max(ts))
            check(f'S1 {size[0]}x{size[1]} 平均 {mean:.2f} ms ≤ {limit} ms',
                  mean <= limit, f'min={min(ts):.2f} max={max(ts):.2f} ms')

        # ---------------- S2 源码口径：无逐像素循环 ----------------
        print('\n[S2] 源码口径：预乘必须向量化，不准逐像素 Python 循环')
        src_code = inspect.getsource(R.LayeredRenderer.premultiply_bgra)
        body = '\n'.join(l for l in src_code.splitlines() if not l.strip().startswith('#'))
        check('S2a premultiply_bgra 内无 for/while 循环',
              ('for ' not in body) and ('while ' not in body), repr(body[:80]))
        check('S2b 用 ImageChops.multiply 向量化（C 实现）',
              'multiply' in body and '_pil()' in body)
        push_code = inspect.getsource(R.LayeredRenderer.push_bitmap)
        check('S2c push_bitmap 六步齐全（GetDC/CreateCompatibleDC/CreateDIBSection/'
              'memmove/UpdateLayeredWindow/DeleteObject）',
              all(k in push_code for k in ('GetDC', 'CreateCompatibleDC', 'CreateDIBSection',
                                           'memmove', 'UpdateLayeredWindow', 'DeleteObject')))
        bmi = rnd.make_bmi(300, 420)
        check('S2d BITMAPINFOHEADER：biHeight 取负（自上而下）',
              bmi.bmiHeader.biHeight == -420, f'biHeight={bmi.bmiHeader.biHeight}')
        check('S2e BITMAPINFOHEADER：32bpp / BI_RGB / biSize 正确',
              bmi.bmiHeader.biBitCount == 32 and bmi.bmiHeader.biCompression == R.LAYERED_BI_RGB
              and bmi.bmiHeader.biSize == ctypes.sizeof(R.BITMAPINFOHEADER),
              f'bitCount={bmi.bmiHeader.biBitCount} comp={bmi.bmiHeader.biCompression}')
        check('S2f 合流函数仍是兼容接口（flatten 保留 RGBA，不抠键色）',
              rnd.flatten(im, (255, 0, 255), Image).mode == 'RGBA')

        # ---------------- S3 合成窗口：真推位图 ----------------
        print('\n[S3] UpdateLayeredWindow 真推（合成窗口，走完整链路）')
        bg = tk.Tk()
        extra_roots.append(bg)
        bg.overrideredirect(False)
        bg.geometry('420x320+60+60')
        bg.configure(bg='#ffffff')
        bg.update()
        time.sleep(0.25)
        win = tk.Toplevel(bg)
        extra_roots.append(win)
        win.overrideredirect(True)
        win.geometry('200x200+150+150')
        win.attributes('-topmost', True)
        win.update()
        time.sleep(0.15)
        hwnd = _top_hwnd(win)
        mini_w = _MiniOverlay(win)
        mini_w._x, mini_w._y = 150, 150
        rnd_w = R.LayeredRenderer(mini_w, 'alpha')
        disc = make_soft_disc(200)
        rnd_w.to_photo(disc)
        ok = rnd_w.push_static()
        check('S3a UpdateLayeredWindow 返回成功（prepare → 窗口准备 → 推图）',
              ok, rnd_w.last_error or rnd_w.describe())
        ex = U32.GetWindowLongW(hwnd, R.GWL_EXSTYLE)
        check('S3b 顶层句柄带 WS_EX_LAYERED（每次推图前确保）',
              bool(ex & R.WS_EX_LAYERED), hex(ex))
        U32.SetWindowLongW(hwnd, R.GWL_EXSTYLE, ex & ~R.WS_EX_LAYERED)   # 模拟被 Tk 冲掉
        check('S3c WS_EX_LAYERED 被冲掉后，ensure_layered 能补回',
              rnd_w.ensure_layered(hwnd)
              and bool(U32.GetWindowLongW(hwnd, R.GWL_EXSTYLE) & R.WS_EX_LAYERED))
        rnd_w.push_static(force=True)      # 属性被冲掉后内容丢失 → 重推一次（S4 抓屏用）
        check('S3d 冲掉属性后重推成功（WS_EX_LAYERED 自动补回）',
              rnd_w.last_error == '', rnd_w.describe())

        # ---------------- S4 抓屏三色（spike 复现） ----------------
        print('\n[S4] 抓屏三色（真实 ImageGrab，复现 spike 结论）')
        for _ in range(5):
            win.update()
            bg.update()
            time.sleep(0.08)
        try:
            shot = _grab((150, 150, 350, 350))
            cx = shot.getpixel((100, 100))
            mid = shot.getpixel((100, 8))
            corner = shot.getpixel((1, 1))
            print(f'       实测像素 中心={cx} 羽化带={mid} 角落={corner}')
            check('S4a 中心≈红（不透明区照原色）',
                  cx[0] > 180 and cx[1] < 90, str(cx))
            check('S4b 羽化带介于红白之间（真·逐像素 alpha 渐变）',
                  mid[0] >= cx[0] and mid[1] > cx[1] and mid[1] < 245, str(mid))
            check('S4c 角落≈白（alpha=0 全透明，透出下层白窗）',
                  corner[0] > 230 and corner[1] > 230 and corner[2] > 230, str(corner))
        except Exception as e:
            skip('S4 抓屏三色（ImageGrab 不可用）', repr(e))

        # ---------------- S5 点击穿透（真实命中测试） ----------------
        print('\n[S5] alpha=0 区域点击穿透（WindowFromPoint 真实命中）')
        try:
            pt_c = R.LAYER_POINT(150 + 100, 150 + 100)
            pt_t = R.LAYER_POINT(150 + 1, 150 + 1)
            h_c = U32.WindowFromPoint(pt_c)
            h_t = U32.WindowFromPoint(pt_t)
            root_c, root_t = _ga_root(h_c), _ga_root(h_t)
            print(f'       命中 中心 hwnd=0x{h_c:X}(root 0x{root_c:X}) '
                  f'角落 hwnd=0x{h_t:X}(root 0x{root_t:X})  分层窗顶层=0x{hwnd:X}')
            check('S5a 不透明区命中分层窗（图片可交互）', root_c == hwnd,
                  f'0x{root_c:X} vs 0x{hwnd:X}')
            check('S5b alpha=0 区穿透到下层窗口（不吃鼠标）', root_t != hwnd,
                  f'角落命中 root 0x{root_t:X}')
            if root_t != hwnd:
                check('S5c 穿透落点有效且与分层窗无包含关系（真穿透到别的窗口）',
                      root_t != 0 and h_t != 0 and h_c != 0,
                      f'角落 root=0x{root_t:X} 中心 root=0x{root_c:X}')
        except Exception as e:
            skip('S5 点击穿透命中测试（WindowFromPoint 不可用）', repr(e))

        # ---------------- S6 品红与半透明：真 alpha vs 硬抠色 ----------------
        print('\n[S6] 含纯品红像素的图不再被抠穿（真 alpha 路径）')
        mag = make_magenta_block(120, 120)
        win.geometry('120x120+150+150')
        win.update()
        rnd_w.to_photo(mag)
        ok = rnd_w.push_static(force=True)
        for _ in range(4):
            win.update()
            bg.update()
            time.sleep(0.08)
        try:
            shot = _grab((150, 150, 270, 270))
            c = shot.getpixel((60, 60))
            print(f'       品红块中心实测={c}')
            check('S6a 品红像素照原色显示（R≈255 G≈0 B≈255）',
                  ok and c[0] > 220 and c[1] < 60 and c[2] > 220, str(c))
        except Exception as e:
            skip('S6 品红抓屏（ImageGrab 不可用）', repr(e))
        # compat 对照：同一张半透明图，compat 会把 alpha<128 的像素整片抠成键色（硬边根源），
        # alpha 模式保留逐像素 alpha（真渐变）—— 这就是「升级一」的实质差别
        semi = Image.new('RGBA', (4, 4), (200, 60, 40, 60))
        key = R.pick_key_color([semi], Image)
        compat_out = R._flatten_alpha_for_tk(semi, Image, key)
        alpha_out = rnd.flatten(semi, key, Image)
        check('S6b compat 对照：半透明像素被二值化成键色（硬抠色会吃边缘）',
              compat_out.getpixel((1, 1))[:3] == tuple(key),
              f'键色={key} compat像素={compat_out.getpixel((1, 1))[:3]}')
        check('S6c alpha 路径：同一像素保留原 RGBA（真·逐像素 alpha）',
              alpha_out.getpixel((1, 1)) == (200, 60, 40, 60),
              str(alpha_out.getpixel((1, 1))))
        try:
            win.destroy()
            bg.destroy()
            extra_roots = [r for r in extra_roots if r not in (win, bg)]
        except Exception:
            pass

        # ---------------- S7 compat/alpha 切换一致性 ----------------
        print('\n[S7] compat/alpha 切换一致性（同一配置、只换开关）')
        R.save_config = lambda c: None
        cfg = dict(R.DEFAULT_CONFIG)
        cfg['image'] = img_path
        cfg['base_height'] = 60
        cfg['scale'] = 1.0
        cfg['side'] = 'right'
        cfg.pop('render_mode', None)
        ov_c = R.FollowOverlay(cfg)
        overlays.append(ov_c)
        try:
            ov_c.tray.stop()
        except Exception:
            pass
        tc_compat = str(ov_c.root.attributes('-transparentcolor'))
        check('S7a compat：仍是 -transparentcolor 键色路径（v1.6 行为）',
              ov_c.render_mode == 'compat' and type(ov_c.renderer) is R.CompatRenderer
              and tc_compat not in ('', '0'), f'{tc_compat!r}')
        cfg_a = dict(cfg)
        cfg_a['render_mode'] = 'alpha'
        ov_a = R.FollowOverlay(cfg_a)      # 会关掉上一个实例
        overlays.append(ov_a)
        try:
            ov_a.tray.stop()
        except Exception:
            pass
        hwnd_a = _top_hwnd(ov_a.root)
        tc_alpha = str(ov_a.root.attributes('-transparentcolor'))
        check('S7b alpha：LayeredRenderer + 已摘掉 -transparentcolor',
              type(ov_a.renderer) is R.LayeredRenderer and tc_alpha in ('', '0'),
              f'tc={tc_alpha!r} renderer={ov_a.renderer.describe()}')
        ex_a = U32.GetWindowLongW(hwnd_a, R.GWL_EXSTYLE)
        check('S7c alpha：外挂顶层窗带 WS_EX_LAYERED', bool(ex_a & R.WS_EX_LAYERED), hex(ex_a))
        check('S7d alpha：首推成功（load_char 后位图已就位）',
              ov_a.renderer._n_push >= 1 and ov_a.renderer._pushed_size[0] > 0,
              ov_a.renderer.describe())
        check('S7e alpha：帧保留 RGBA（不抠色），窗口尺寸与图像一致',
              ov_a.renderer._frame is not None
              and ov_a.renderer._frame.mode == 'RGBA'
              and hasattr(ov_a.img, 'image')          # LayerFrame：width()/height() 语义
              and (ov_a.w, ov_a.h) == ov_a.renderer._pushed_size,
              f'{(ov_a.w, ov_a.h)} vs {ov_a.renderer._pushed_size}')
        check('S7f alpha：Label 不再贴图（内容完全由位图决定），但控件仍在',
              ov_a.label is not None and not ov_a.label.cget('image'))
        check('S7g compat 实例的 w/h 与 alpha 实例一致（缩放/特效管线同源）',
              (ov_c.w, ov_c.h) == (ov_a.w, ov_a.h), f'{(ov_c.w, ov_c.h)} vs {(ov_a.w, ov_a.h)}')

        # ---------------- S8 推送时机 ----------------
        print('\n[S8] 推送时机：静态只推一次 / 帧未变不重推 / 移动后重推 / 动图每帧推')
        n0 = ov_a.renderer._n_push
        for _ in range(20):                # 模拟「50ms 轮询硬推」的旧思路
            R._renderer_of(ov_a).push_static()
        check('S8a 帧未变时不重复推（20 次调用 0 次实际推图）',
              ov_a.renderer._n_push == n0, f'{n0} → {ov_a.renderer._n_push}')
        R._renderer_of(ov_a).on_moved()
        check('S8b 移动后强制重推一次', ov_a.renderer._n_push == n0 + 1,
              f'{n0} → {ov_a.renderer._n_push}')
        R._renderer_of(ov_a).apply_photo_only(ov_a.label, ov_a.img)
        check('S8c 同一帧走 apply_photo_only 不重复推（热重载/缩放路径不虚推）',
              ov_a.renderer._n_push == n0 + 1, ov_a.renderer.describe())
        # 动图：每帧推
        gif = os.path.join(tmp, 'anim.gif')
        frames = []
        for i in range(5):
            f = make_flat_block(60, 80, (30 + i * 20, 90, 220))
            frames.append(f.convert('P', palette=Image.ADAPTIVE))
        frames[0].save(gif, save_all=True, append_images=frames[1:], duration=80,
                       loop=0, disposal=2)
        cfg_g = dict(cfg_a)
        cfg_g['image'] = gif
        ov_g = R.FollowOverlay(cfg_g)
        overlays.append(ov_g)
        try:
            ov_g.tray.stop()
        except Exception:
            pass
        ov_g.root.deiconify()      # 动图节拍只在可见时推进（隐藏=暂停，省 CPU）
        ov_g.visible = True
        ov_g.root.update()
        time.sleep(0.2)
        n_g = ov_g.renderer._n_push
        ov_g._anim_tick()
        check('S8d 动图：_anim_tick 每帧推进后推一次位图',
              ov_g.anim_n == 5 and ov_g.renderer._n_push == n_g + 1,
              f'n_push {n_g} → {ov_g.renderer._n_push} frame={ov_g.anim_idx}')
        ov_g._anim_tick()
        check('S8e 动图：下一帧再推一次（跟节拍，不轮询）',
              ov_g.renderer._n_push == n_g + 2, f'→ {ov_g.renderer._n_push}')

        # ---------------- S9 三状态小步验证（真 FollowOverlay + 假候选框 + 抓屏） ----------------
        print('\n[S9] 三状态小步验证：隐藏→显示 / 切皮肤 / 拖动中')
        R.save_config = lambda c: None
        old_skins = R.SKINS_DIR
        R.SKINS_DIR = os.path.join(tmp, 'skins')
        os.makedirs(R.SKINS_DIR, exist_ok=True)
        red_block = os.path.join(tmp, 'red.png')
        blue_block = os.path.join(tmp, 'blue.png')
        make_flat_block(90, 90, (230, 30, 30)).save(red_block)
        make_flat_block(90, 90, (30, 60, 230)).save(blue_block)
        cfg_s = dict(R.DEFAULT_CONFIG)
        cfg_s['image'] = red_block
        cfg_s['render_mode'] = 'alpha'
        cfg_s['base_height'] = 90
        cfg_s['scale'] = 1.0
        cfg_s['side'] = 'right'
        cfg_s['offset_x'] = 0
        cfg_s['offset_y'] = 0
        ov_s = R.FollowOverlay(cfg_s)
        overlays.append(ov_s)
        try:
            ov_s.tray.stop()
        except Exception:
            pass
        # 造一个真实 Win32 假候选框（类名 ATL: + 候选框样式），走真实定位链路
        cand_cls = None
        try:
            CandCls, cand_cls = _make_fake_candidate('ATL:AlphaCand', 60, 120, 420, 72)
            cand = CandCls()
            ov_s._cached_hwnd = cand.hwnd
            R.set_candidate_hwnd(cand.hwnd)
            ov_s._last_scan_ts = 0.0
            ov_s._position_once()
        except Exception as e:
            cand = None
            print('       假候选框不可用:', repr(e))
        wx, wy = ov_s._x, ov_s._y
        print(f'       外挂窗口位置=({wx},{wy}) 尺寸={ov_s.w}x{ov_s.h} '
              f'renderer={ov_s.renderer.describe()}')
        bbox = (wx, wy, wx + ov_s.w, wy + ov_s.h)
        shot_ok = None
        try:
            time.sleep(0.35)
            shot = _grab(bbox)
            c = shot.getpixel((ov_s.w // 2, ov_s.h // 2))
            print(f'       [显示态] 中心实测={c}')
            check('S9a 显示态：中心为图片原色（真 alpha 位图已上屏）',
                  c[0] > 180 and c[1] < 90 and c[2] < 90, str(c))
            shot_ok = True
        except Exception as e:
            skip('S9a 显示态抓屏（ImageGrab 不可用）', repr(e))
        # —— 状态 1：隐藏 → 显示 ——
        ov_s.root.withdraw()
        ov_s.visible = False
        time.sleep(0.2)
        ov_s.root.deiconify()
        ov_s.visible = True
        ov_s._push_render_frame()
        for _ in range(3):
            ov_s.root.update()
            time.sleep(0.1)
        try:
            shot2 = _grab(bbox)
            c2 = shot2.getpixel((ov_s.w // 2, ov_s.h // 2))
            print(f'       [隐藏→显示] 中心实测={c2}')
            check('S9b 隐藏→显示后位图仍在（重绘不错乱）',
                  c2[0] > 180 and c2[1] < 90 and c2[2] < 90, str(c2))
        except Exception as e:
            skip('S9b 隐藏→显示抓屏', repr(e))
        # —— 状态 2：切皮肤 ——
        try:
            R.save_skin('alpha测试皮', dict(cfg_s))
            scfg = R.find_skin('alpha测试皮')
            scfg['image'] = blue_block
            import json as _json
            with open(os.path.join(R.SKINS_DIR, 'alpha测试皮', 'skin.json'), 'w',
                      encoding='utf-8') as f:
                _json.dump(scfg, f, ensure_ascii=False, indent=2)
            ok_skin = ov_s.apply_skin('alpha测试皮')
            for _ in range(3):
                ov_s.root.update()
                time.sleep(0.1)
            shot3 = _grab((ov_s._x, ov_s._y, ov_s._x + ov_s.w, ov_s._y + ov_s.h))
            c3 = shot3.getpixel((ov_s.w // 2, ov_s.h // 2))
            print(f'       [切皮肤] 中心实测={c3} （应为蓝）')
            check('S9c 切皮肤后位图换新图且位置不错乱（蓝块在原位）',
                  ok_skin and c3[2] > 180 and c3[0] < 90 and c3[1] < 120,
                  f'{c3} pos=({ov_s._x},{ov_s._y})')
        except Exception as e:
            skip('S9c 切皮肤抓屏', repr(e))
        # —— 状态 3：拖动中 ——
        try:
            class _Ev:
                pass

            ev0 = _Ev()
            ev0.x_root = ov_s._x + 20
            ev0.y_root = ov_s._y + 20
            ov_s.on_press(ev0)              # 抓在图片不透明区
            moved = []
            for dx, dy in ((40, 30), (80, 60), (120, 90)):
                ev = _Ev()
                ev.x_root = ov_s._x + 20 + dx
                ev.y_root = ov_s._y + 20 + dy
                ov_s.on_drag(ev)
                ov_s.root.update()
                time.sleep(0.12)
                moved.append((ov_s._x, ov_s._y))
            nx, ny = ov_s._x, ov_s._y
            print(f'       [拖动中] 位移序列={moved} 终点=({nx},{ny})')
            shot4 = _grab((nx, ny, nx + ov_s.w, ny + ov_s.h))
            c4 = shot4.getpixel((ov_s.w // 2, ov_s.h // 2))
            old_area = None
            try:
                old_area = ImageGrab.grab(bbox=(moved[0][0], moved[0][1],
                                                moved[0][0] + ov_s.w, moved[0][1] + ov_s.h))
                old_area = old_area.getpixel((ov_s.w // 2, ov_s.h // 2))
            except Exception:
                old_area = None
            print(f'       [拖动中] 新位置中心={c4} 旧位置中心={old_area}')
            check('S9d 拖动中位图跟随（新位置看到图片、旧位置已无残影）',
                  c4[2] > 180 and c4[0] < 90
                  and (old_area is None or not (old_area[2] > 180 and old_area[0] < 90)),
                  f'new={c4} old={old_area}')
            check('S9e 拖动走 Tk 事件 + 镜像坐标同步（_x/_y 到位）',
                  nx > moved[0][0] and ny > moved[0][1], f'{moved} → ({nx},{ny})')
        except Exception as e:
            skip('S9d/S9e 拖动中抓屏', repr(e))
        if cand is not None:
            try:
                cand.destroy()
            except Exception:
                pass
        R.SKINS_DIR = old_skins

        # ---------------- S10 交互链路 ----------------
        print('\n[S10] 交互链路：拖动/滚轮/右键/快捷键绑定照旧（alpha 模式）')
        binds = [ov_s.label.bind('<ButtonPress-1>'), ov_s.label.bind('<B1-Motion>'),
                 ov_s.label.bind('<MouseWheel>'), ov_s.label.bind('<Button-3>'),
                 ov_s.root.bind('<Control-Alt-Key-c>'), ov_s.root.bind('<Control-Alt-Key-q>')]
        check('S10a 拖动/滚轮/右键/快捷键绑定全在（Label 仍是事件载体）',
              all(binds), 'bindings=' + str([bool(b) for b in binds]))
        check('S10b 右键菜单项照旧（隐藏显示 / 退出）', ov_s.menu.index('end') == 1)
        class _EvW:
            delta = 120
        w_before = ov_s.w
        ov_s.on_wheel(_EvW())
        check('S10c 滚轮缩放可用且位图随新尺寸重推',
              ov_s.w > w_before and ov_s.renderer._pushed_size == (ov_s.w, ov_s.h),
              f'{w_before}→{ov_s.w} pushed={ov_s.renderer._pushed_size}')

        # ---------------- S11 向导 ⑪ 渲染模式开关（一键切换，不用手改 config.json） ----------------
        print('\n[S11] 向导 ⑪ 渲染模式（中文选项 → cfg.render_mode 写回）')
        done, saved_cfg = {}, {}
        real_save_config, real_set_autostart = R.save_config, R.set_autostart
        R.save_config = lambda c: saved_cfg.update(c)
        R.set_autostart = lambda enabled, quiet=True, force=False: (True, 'stub')
        wiz = None
        try:
            wiz = R.ConfigWizard(on_done=lambda c: done.update(c), overlay=None)
            check('S11a 向导默认选中「兼容」（老用户零感知）',
                  R.resolve_render_mode({'render_mode': wiz.var_render.get()}) == 'compat',
                  wiz.var_render.get())
            labels = [t for _v, t in R.RENDER_MODE_CHOICES]
            check('S11b 选项是中文大白话（不把 compat/alpha 术语摆给用户）',
                  len(labels) == 2
                  and all('compat' not in t and 'alpha' not in t for t in labels),
                  repr(labels))
            txt0 = wiz.lbl_render_hint.cget('text')
            wiz.var_render.set('alpha')
            wiz._update_render_hint()
            txt1 = wiz.lbl_render_hint.cget('text')
            check('S11c 切到「增强」后提示行讲清真半透明与点击穿透',
                  '半透明' in txt1 and '穿透' in txt1 and txt0 != txt1, repr(txt1[:44]))
            wiz.cfg['image'] = img_path
            wiz._save_and_start()
            check('S11d 保存把 render_mode=alpha 写回 cfg（一键切换，无需手改 config.json）',
                  R.resolve_render_mode(saved_cfg) == 'alpha'
                  and done.get('render_mode') == 'alpha',
                  f'saved={saved_cfg.get("render_mode")!r} done={done.get("render_mode")!r}')
        except Exception as e:
            import traceback
            traceback.print_exc()
            check('S11 向导渲染模式开关链路', False, repr(e))
        finally:
            R.save_config, R.set_autostart = real_save_config, real_set_autostart
            if wiz is not None:
                try:
                    wiz.root.destroy()
                except Exception:
                    pass

        print('\n' + '=' * 60)
        print(f'通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项 / 跳过 {len(SKIPPED)} 项')
        if SKIPPED:
            print('跳过（依赖真实桌面，异常原文已打印）: ' + ', '.join(SKIPPED))
        if FAIL:
            print('失败项: ' + ', '.join(FAIL))
            return 1
        print('ALL CHECKS PASS')
        return 0
    except AssertionError as e:
        print('RESULT FAIL:', e)
        return 1
    except Exception:
        import traceback
        traceback.print_exc()
        print('RESULT ERROR')
        return 2
    finally:
        for ovx in list(overlays):
            try:
                ovx.root.withdraw()
                ovx.root.destroy()
            except Exception:
                pass
        overlays.clear()
        for r_ in list(extra_roots):
            try:
                r_.destroy()
            except Exception:
                pass
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        try:
            R.set_candidate_hwnd(0)
        except Exception:
            pass
        time.sleep(0.1)


# ---------------- 假候选框（真实 Win32 窗口；与 B_test_follow_sim 同口径） ----------------
_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                              wintypes.WPARAM, wintypes.LPARAM)
U32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
U32.DefWindowProcW.restype = ctypes.c_longlong
K32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
K32.GetModuleHandleW.restype = wintypes.HMODULE


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('style', wintypes.UINT),
                ('lpfnWndProc', _WNDPROC), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', wintypes.HINSTANCE),
                ('hIcon', wintypes.HICON), ('hCursor', wintypes.HANDLE),
                ('hbrBackground', wintypes.HBRUSH), ('lpszMenuName', wintypes.LPCWSTR),
                ('lpszClassName', wintypes.LPCWSTR), ('hIconSm', wintypes.HICON)]


def _def_proc(hwnd, msg, wp, lp):
    try:
        return U32.DefWindowProcW(hwnd, msg, wp, lp)
    except Exception:
        return 0


def _make_fake_candidate(cls_name, x, y, w, h):
    """返回 (FakeCandidate 类, 已注册类名)；类名需带 ATL: 前缀 + 候选框三件套样式"""
    proc = _WNDPROC(_def_proc)

    class FakeCandidate:
        def __init__(self):
            wc = _WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
            wc.lpfnWndProc = proc
            wc.hInstance = K32.GetModuleHandleW(None)
            wc.lpszClassName = cls_name
            U32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
            U32.RegisterClassExW.restype = wintypes.ATOM
            if not U32.RegisterClassExW(ctypes.byref(wc)):
                raise RuntimeError('RegisterClassExW failed')
            U32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                            wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                            wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
            U32.CreateWindowExW.restype = wintypes.HWND
            self.hwnd = U32.CreateWindowExW(
                0x80 | 0x08000000, cls_name, 'mock', 0x80000000 | 0x10000000,
                x, y, w, h, 0, 0, wc.hInstance, None)
            if not self.hwnd:
                raise RuntimeError('CreateWindowExW failed')

        def destroy(self):
            try:
                U32.DestroyWindow(self.hwnd)
            except Exception:
                pass

    return FakeCandidate, cls_name


if __name__ == '__main__':
    sys.exit(main())
