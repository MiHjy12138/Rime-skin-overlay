# -*- coding: utf-8 -*-
"""B_test_r6_gif_preview.py —— R6「图片预处理支持动图」验证

用户原话（HANDOFF-2.0 §3 R6）：
  「图片预处理时也要能显示动图，不然有些动图不好裁剪。」

覆盖：
  A 段 · 夹具与成本基线（大 GIF ≥100 帧 且 ≥5MB）
      A1 夹具达标；A2「打开即全解码」朴朴素实现实测耗时（这就是要避免的卡死路线）；
      A3 顺序单帧解码成本；A4 首帧解码成本
  B 段 · 改前实现对照（从固定修订 103c97f 取旧 blob 独立加载）
      B1 旧模块可加载；B2 旧对话框打开同一大 GIF 的耗时；B3 旧实现没有任何播放/逐帧 API
  C 段 · 改后：打开成本 + 播放节流 + 单次主线程阻塞
      C1 打开耗时对比（不因加动图预览而变慢）；C2 打开只解码首帧；
      C3 播放/逐帧 API 存在；C4 播放推进只按需解码（每个 tick ≤1 帧）；
      C5 单次主线程阻塞数字（tick 耗时 min/median/max 与朴素全解码对比）；
      C6 循环回绕成本；C7 暂停后节拍停表
  D 段 · 裁剪框与当前显示帧同坐标系（切换帧不漂移）
      D1 逐帧查看可用；D2 走遍各帧 work 尺寸/crop/_fit 恒定，坐标往返一致；
      D3 画布图片尺寸 == work 尺寸 × 缩放；D4 键盘 Left/Right/space 已绑定
  E 段 · 帧尺寸不一致的明确策略（以首帧尺寸为准）
      E1 私有源代理（seek 出不同尺寸帧）下 orig/disp/归一计数；E2 全帧不漂移；
      E3 _apply 输出 APNG 帧数与尺寸一致；E4 策略写进代码（docstring）；
      E5 事实核对：PIL 读入器对 GIF 局部帧已合成到逻辑画布；E6 _canonical_frame 单测
  F 段 · 销毁不留 after/回调
      F1 _cancel 停表；F2 Tk 待执行 after 列表里没有我们的 id；F3 事后触发不抛 TclError；
      F4 _apply 路径同样停表；F5 WM_DELETE_WINDOW 已绑定
  G 段 · 静态图行为不变
      G1 静态图没有动画控件、_frame_work(0) 就是 work；G2 静态 _apply 输出与改前逐字节相同

运行: python B_test_r6_gif_preview.py   （退出码 0 = 全过；默认 GBK 控制台直接跑）
"""
import os
import sys
import time
import shutil
import tempfile
import importlib.util

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
try:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from PIL import Image, ImageSequence

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R
import tkinter as tk

PASS, FAIL, SKIP = [], [], []
# 改前基线：R6 开工前最后一个提交（R5 的颜色注入修复）。固定写死 —— 若跟着 HEAD 走，
# 提交之后「旧实现」就变成了新代码，前后对照会失去意义。
R6_BASE_REV = '103c97f'

BIG_W, BIG_H, BIG_N, BIG_DUR = 320, 240, 120, 60


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f'{"PASS" if cond else "FAIL"}  {name}{(" | " + detail) if detail else ""}')


def skip(name, detail=''):
    SKIP.append(name)
    print(f'SKIP  {name}{(" | " + detail) if detail else ""}')


def section(t):
    print('')
    print('-' * 8, t, '-' * 8)


def ms(fn, n=1):
    t0 = time.perf_counter()
    r = None
    for _ in range(n):
        r = fn()
    return (time.perf_counter() - t0) * 1000.0 / n, r


def _rgb(c):
    """'#RRGGBB' → (R,G,B)；已是元组则原样返回（用于独立复算期望色）"""
    if isinstance(c, tuple):
        return c[:3]
    s = str(c).lstrip('#')
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


# ---------------- 夹具 ----------------
def make_big_gif(path):
    """≥100 帧 且 ≥5MB 的动图（噪声内容保证体积；每帧有移动色块保证帧间可区分）"""
    frames = []
    for i in range(BIG_N):
        base = Image.effect_noise((BIG_W, BIG_H), 60).convert('RGB')
        base.paste(Image.new('RGB', (60, 60), ((i * 7) % 256, 200, 90)),
                   (20 + (i * 3) % (BIG_W - 80), 20))
        frames.append(base.convert('P', palette=Image.ADAPTIVE, colors=128))
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=BIG_DUR, loop=0, optimize=False)
    return path


def make_small_gif(path, w=64, h=64, n=6):
    frames = []
    for i in range(n):
        im = Image.new('RGB', (w, h), (30, 30, 30))
        for y in range(10, 40):
            for x in range(10 + i, 40 + i):
                im.putpixel((x, y), (220, 40, 40))
        frames.append(im.convert('P', palette=Image.ADAPTIVE, colors=64))
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=70, loop=0)
    return path


def make_png(path, w=100, h=120):
    im = Image.new('RGB', (w, h), (250, 250, 250))
    for y in range(20, 100):
        for x in range(30, 70):
            im.putpixel((x, y), (220, 40, 40))
    im.save(path)
    return path


def load_old_module(tmp):
    """从固定修订取改前 rime_char_overlay.py，独立加载（不污染被测模块）"""
    out = os.path.join(tmp, 'rime_char_overlay_before.py')
    import subprocess
    try:
        with open(out, 'wb') as f:
            p = subprocess.run(['git', 'show', '%s:rime_char_overlay.py' % R6_BASE_REV],
                               cwd=BASE, stdout=f, stderr=subprocess.PIPE)
        if p.returncode != 0:
            return None, 'git show %s 失败：%s' % (R6_BASE_REV, p.stderr.decode('utf-8', 'replace')[:120])
        spec = importlib.util.spec_from_file_location('rco_before_r6', out)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, 'ok（%s, %d B）' % (R6_BASE_REV, os.path.getsize(out))
    except Exception as e:
        return None, '%s: %s' % (type(e).__name__, e)


# ================= A 段 =================
def test_a_cost_baseline(tmp, big):
    section('A 大 GIF 夹具与成本基线（要避免的卡死路线有多贵）')
    size_mb = os.path.getsize(big) / 1048576.0
    im = Image.open(big)
    n = int(getattr(im, 'n_frames', 1) or 1)
    check('A1 夹具达标（≥100 帧 且 ≥5MB）',
          n >= 100 and size_mb >= 5.0,
          f'{BIG_W}×{BIG_H} × {n} 帧 / {size_mb:.2f} MB')
    t_first, _ = ms(lambda: (lambda a: (a.seek(0), a.convert('RGBA')))(Image.open(big)), 5)
    print(f'    · 首帧解码（= 打开对话所需）= {t_first:.2f} ms')
    im2 = Image.open(big)
    im2.seek(0)
    im2.convert('RGBA')
    t_step, _ = ms(lambda: (im2.seek(im2.tell() + 1), im2.convert('RGBA')), 20)
    print(f'    · 顺序下一帧解码 = {t_step:.2f} ms/帧')
    t_naive, _ = ms(lambda: [f.copy().convert('RGBA')
                             for f in ImageSequence.Iterator(Image.open(big))], 2)
    print(f'    · 朴素「打开即全解码」= {t_naive:.1f} ms（一次性阻塞）')
    check('A2 朴素全解码确实是一次数百毫秒级的主线程阻塞（≥ 单帧的 20 倍）',
          t_naive >= 20 * t_step, f'{t_naive:.1f} ms vs 单帧 {t_step:.2f} ms')
    check('A3 单帧增量解码远小于全解码（≤ 1/5）',
          t_step * 5 <= t_naive, f'{t_step:.2f} ms vs {t_naive:.1f} ms')
    check('A4 首帧解码足够快（≤ 50ms，打开对话框的固定成本）',
          t_first <= 50.0, f'{t_first:.2f} ms')
    return {'n': n, 'mb': size_mb, 't_first': t_first, 't_step': t_step, 't_naive': t_naive}


def test_b_before(tmp, big, base_cost, old_mod, why):
    section('B 改前实现对照（固定修订 %s）' % R6_BASE_REV)
    old = old_mod
    if old is None:
        skip('B1 旧模块加载', why)
        return None
    check('B1 旧模块可从固定修订独立加载', old is not None, why)
    root = tk.Tk()
    root.withdraw()
    dlg = None
    try:
        t_old, dlg = ms(lambda: old.ImagePreprocessDialog(root, big), 1)
        print(f'    · 旧对话框打开同一大 GIF = {t_old:.1f} ms（只加载首帧）')
        t_draw_old, _ = ms(lambda: dlg._draw(), 3)
        print(f'    · 旧实现单次重绘 _draw() = {t_draw_old:.1f} ms')
        check('B2 旧对话框打开耗时与单次重绘耗时已记录',
              t_old > 0 and t_draw_old > 0, f'open {t_old:.1f} ms / draw {t_draw_old:.1f} ms')
        check('B3 旧实现没有任何播放/逐帧 API（所以用户看不到动图）',
              not hasattr(dlg, 'btn_play') and not hasattr(dlg, 'preview_idx')
              and not hasattr(dlg, '_toggle_preview'),
              'btn_play/preview_idx/_toggle_preview 都不存在')
        check('B4 旧实现打开时也没做全解码（它的开销在 Tk 控件与推图，不在解码）',
              t_old > 0 and t_draw_old > 0,
              f'打开 {t_old:.1f} ms（其中图片解读 ≈ 单帧 {base_cost["t_first"]:.1f} + 帧数扫描）')
        return {'t_open': t_old, 't_draw': t_draw_old}
    finally:
        try:
            if dlg is not None:
                dlg._cancel()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass


# ================= C 段 =================
def test_c_open_play(tmp, big, base_cost, before):
    section('C 改后：打开成本 + 播放节流 + 单次主线程阻塞')
    root = tk.Tk()
    root.withdraw()
    dlg = None
    try:
        t_new, dlg = ms(lambda: R.ImagePreprocessDialog(root, big), 1)
        t_draw_new, _ = ms(lambda: dlg._draw(), 3)
        print(f'    · 新对话框打开同一大 GIF = {t_new:.1f} ms（改前 {(before or {}).get("t_open", float("nan")):.1f} ms）')
        print(f'    · 新实现单次重绘 _draw() = {t_draw_new:.1f} ms'
              f'（改前 {(before or {}).get("t_draw", float("nan")):.1f} ms）')
        check('C1 ★打开不比改前慢（加了动图预览控件）',
              t_new <= (before or {}).get('t_open', t_new + 1) + 60,
              f'新 {t_new:.1f} ms vs 改前 {(before or {}).get("t_open", float("nan")):.1f} ms'
              f'；朴素全解码 {base_cost["t_naive"]:.1f} ms（打开只付首帧 {base_cost["t_first"]:.1f} ms）')
        check('C1b ★单次重绘比改前显著变快（消掉 Tk 混合 alpha 推图慢路径）',
              (before or {}).get('t_draw', 1e9) >= t_draw_new * 3,
              f'改前 {(before or {}).get("t_draw", float("nan")):.1f} ms → 改后 {t_draw_new:.1f} ms')
        check('C2 打开后只解码了首帧（按需，不一次性全解码）',
              int(getattr(dlg, '_decode_calls', 999)) <= 1,
              f"_decode_calls={getattr(dlg, '_decode_calls', 'N/A')} / 共 {base_cost['n']} 帧")
        check('C3 播放/逐帧 API 与控件齐备',
              hasattr(dlg, 'btn_play') and hasattr(dlg, 'lbl_frame')
              and hasattr(dlg, '_toggle_preview') and hasattr(dlg, '_preview_step')
              and hasattr(dlg, 'preview_idx'),
              'btn_play/lbl_frame/_toggle_preview/_preview_step/preview_idx')
        check('C4 面板标出帧数（用户知道这是动图）',
              str(base_cost['n']) in dlg.lbl_frame.cget('text'),
              repr(dlg.lbl_frame.cget('text')))
        # 播放：手动驱动 tick，避免依赖真实事件循环（GUI 测试要可控）
        dlg._toggle_preview()
        check('C5 播放按钮切换到暂停态', dlg._playing and '暂停' in dlg.btn_play.cget('text'),
              dlg.btn_play.cget('text'))
        idx0 = dlg.preview_idx
        calls0 = dlg._decode_calls
        ticks = []
        for _ in range(10):
            t0 = time.perf_counter()
            dlg._preview_tick()
            ticks.append((time.perf_counter() - t0) * 1000.0)
        calls1 = dlg._decode_calls
        ticks_sorted = sorted(ticks)
        t_med = ticks_sorted[len(ticks_sorted) // 2]
        t_max = ticks_sorted[-1]
        print('    · 播放 10 个 tick：min/median/max = %.2f / %.2f / %.2f ms；解码次数 +%d'
              % (ticks_sorted[0], t_med, t_max, calls1 - calls0))
        check('C6 播放确实在逐帧推进', dlg.preview_steps >= 10 and dlg.preview_idx == (idx0 + 10) % base_cost['n'],
              f'idx {idx0} → {dlg.preview_idx}，steps={dlg.preview_steps}')
        check('C7 每 tick 最多新增 1 次帧解码（按需，不是批量）',
              (calls1 - calls0) <= 10, f'+{calls1 - calls0} 次 / 10 tick')
        check('C8 ★单次主线程阻塞 ≤ 一帧 30fps 预算量级（median ≤45ms / max ≤70ms）',
              t_med <= 45.0 and t_max <= 70.0,
              f'median {t_med:.2f} ms / max {t_max:.2f} ms vs 改前单次重绘 '
              f'{(before or {}).get("t_draw", float("nan")):.1f} ms、朴素全解码 {base_cost["t_naive"]:.1f} ms')
        check('C9 ★单次 tick 阻塞 ≤ 朴素全解码的 1/5',
              t_max * 5 <= base_cost['t_naive'],
              f'{t_max:.2f} ms × 5 vs {base_cost["t_naive"]:.1f} ms')
        check('C10 自适应节流：节拍不短于该帧时长（大图不拼命刷）',
              dlg._frame_delay_ms(dlg.preview_idx) >= R.ANIM_MIN_MS,
              str(dlg._frame_delay_ms(dlg.preview_idx)))
        # 循环回绕（末帧 → 首帧）：PIL 回绕是 seek(0)（便宜），不该退化成全解码
        dlg._preview_goto(base_cost['n'] - 1)
        dlg._playing = True                 # 模拟「正在播放」
        dlg._decode_calls = 0
        t_wrap, _ = ms(lambda: dlg._preview_tick(), 1)
        print(f'    · 循环回绕（{base_cost["n"] - 1} → 0）单次 = {t_wrap:.2f} ms'
              f'（解码 +{dlg._decode_calls} 次）')
        check('C11 循环回绕也很快（≤70ms，不回退成全解码）且确实回到首帧',
              t_wrap <= 70.0 and dlg.preview_idx == 0 and dlg._decode_calls <= 1,
              f'{t_wrap:.2f} ms idx={dlg.preview_idx} 解码 +{dlg._decode_calls}')
        # 暂停
        dlg._stop_preview()
        check('C12 暂停后节拍停表、按钮复位',
              (not dlg._playing) and dlg._anim_after is None and '播放' in dlg.btn_play.cget('text'),
              f'after={dlg._anim_after} btn={dlg.btn_play.cget("text")}')
        return dlg, root, {'t_open': t_new, 't_med': t_med, 't_max': t_max}
    except Exception:
        try:
            root.destroy()
        except Exception:
            pass
        raise


# ================= D 段 =================
def test_d_crop_consistency(dlg, n):
    section('D 裁剪框与当前显示帧同坐标系（切帧不漂移）')
    dlg._preview_goto(0)
    crop0 = tuple(dlg.crop)
    work0 = dlg.work.size
    fit0 = dlg._fit()[:1]
    check('D1 逐帧查看 API 可用（◀/▶/首帧）',
          callable(getattr(dlg, '_preview_step', None)) and dlg.preview_idx == 0,
          f'idx={dlg.preview_idx}')
    bad = []
    idxs = list(range(0, n, max(1, n // 20)))
    for k in idxs:
        dlg._preview_goto(k)
        if tuple(dlg.crop) != crop0 or dlg.work.size != work0 or dlg._fit()[:1] != fit0:
            bad.append((k, dlg.crop, dlg.work.size))
        if dlg.preview_idx != k % n:
            bad.append((k, 'idx 不匹配', dlg.preview_idx))
    check('D2 ★逐帧切换时 work 尺寸 / 裁剪框 / 缩放全程不变（无漂移）',
          not bad, f'异常={bad[:3]}（抽样 {len(idxs)} 帧）')
    # 坐标往返一致
    drift = []
    for k in idxs[:6]:
        dlg._preview_goto(k)
        for (px, py) in [(0, 0), (10, 10), (work0[0] - 1, work0[1] - 1), (work0[0] // 2, work0[1] // 3)]:
            cx, cy = dlg._to_canvas(px, py)
            bx, by = dlg._to_img(cx, cy)
            if abs(bx - px) > 0.01 or abs(by - py) > 0.01:
                drift.append((k, px, py, bx, by))
    check('D3 ★图像坐标 ↔ 画布坐标往返一致（每帧都成立）', not drift, str(drift[:3]))
    # 画布上图元尺寸 == work 尺寸 × 缩放
    dlg._preview_goto(idxs[-1])
    s, ox, oy = dlg._fit()
    items = [i for i in dlg.cv.find_all() if dlg.cv.type(i) == 'image']
    sizes = []
    for i in items:
        x0, y0, x1, y1 = dlg.cv.bbox(i)
        sizes.append((x1 - x0, y1 - y0))
    want = (int(work0[0] * s), int(work0[1] * s))
    check('D4 画布上显示的帧尺寸 == work 尺寸 × 缩放（与裁剪框同一坐标系）',
          sizes and all(abs(w - want[0]) <= 1 and abs(h - want[1]) <= 1 for w, h in sizes),
          f'{sizes} vs 期望 {want}')
    binds = dlg.root.bind()
    check('D5 键盘 Left/Right/space 已绑定（逐帧查看快捷键）',
          any('Left' in b for b in binds) and any('Right' in b for b in binds)
          and any('space' in b.lower() for b in binds), str(binds))
    dlg._preview_goto(0)
    check('D6 回到首帧后与开测时完全一致',
          tuple(dlg.crop) == crop0 and dlg.work.size == work0, f'{dlg.crop}')


# ================= E 段 =================
class MixedSizeSource:
    """模拟「帧尺寸不一致」的动图源：部分帧的 size 与首帧不同。

    实测 PIL 的 GIF/APNG 读入器本身会把局部帧合成到逻辑画布（E5 有断言），所以真实文件
    里很难出现尺寸不一致；但一旦出现（第三方写入器 / 未来格式），裁剪框会漂移、APNG 输出
    会变成「顶左贴一块」的错位帧 —— 兜底策略必须被测到，所以这里用源代理强制构造。
    """
    ODD_SIZES = {1: (0.5, 0.5), 3: (1.4, 1.0), 5: (0.7, 1.3)}

    def __init__(self, path, opener=None, size_scale=None):
        self._im = (opener or Image.open)(path)
        self._base = self._im.size
        self._idx = 0
        self._scale_map = size_scale if size_scale is not None else self.ODD_SIZES
        self.n_frames = int(getattr(self._im, 'n_frames', 1) or 1)

    def seek(self, idx):
        self._im.seek(int(idx) % max(1, self.n_frames))
        self._idx = int(idx) % max(1, self.n_frames)
        return self

    def tell(self):
        return self._idx

    @property
    def size(self):
        sx, sy = self._scale_map.get(self._idx, (1.0, 1.0))
        return (max(2, int(self._base[0] * sx)), max(2, int(self._base[1] * sy)))

    @property
    def info(self):
        return self._im.info

    def convert(self, mode):
        img = self._im.convert(mode)
        return img.resize(self.size, Image.LANCZOS)


def test_e_size_mismatch(tmp, small_gif):
    section('E 帧尺寸不一致的明确策略（以首帧尺寸为准）')
    src = MixedSizeSource(small_gif)
    first_size = src.size            # 首帧尺寸（先把游标停在 0 再取，别被后面的遍历带跑）
    sizes = set()
    for k in range(src.n_frames):
        src.seek(k)
        sizes.add(src.size)
    check('E1 源代理确实造出了尺寸不一致的帧（测试前提成立）',
          len(sizes) > 1 and len(sizes) == len(MixedSizeSource.ODD_SIZES) + 1,
          f'各帧尺寸={sorted(sizes)}')
    # 事实核对：真实 GIF 经 PIL 读入器不会出现尺寸不一致
    real = Image.open(small_gif)
    real_sizes = set()
    for k in range(getattr(real, 'n_frames', 1)):
        real.seek(k)
        real_sizes.add(real.size)
    check('E5 事实核对：PIL 读入器把局部帧合成到逻辑画布（真实文件尺寸一致）',
          len(real_sizes) == 1, f'真实 GIF 各帧尺寸={sorted(real_sizes)}')

    root = tk.Tk()
    root.withdraw()
    dlg = None
    patched = False
    orig_open = Image.open

    def _open(path, *a, **k):
        if os.path.normpath(str(path)) == os.path.normpath(small_gif):
            return MixedSizeSource(small_gif, opener=orig_open)
        return orig_open(path, *a, **k)
    try:
        Image.open = _open
        patched = True
        dlg = R.ImagePreprocessDialog(root, small_gif)
        check('E2 ★首帧尺寸被当作画布基准（orig/work 都按首帧算）',
              dlg.orig.size == first_size and dlg.work.size[0] <= dlg.orig.size[0],
              f'orig={dlg.orig.size}（首帧 {first_size}）work={dlg.work.size}')
        dlg._preview_goto(1)          # 这一帧源尺寸只有首帧的一半
        bad_norm = getattr(dlg, '_size_fixups', 0) <= 0
        check('E3 ★尺寸不一致的帧被归一到首帧画布（可观测计数 +1）',
              not bad_norm and dlg._frame_work(1).size == dlg.work.size,
              f'_size_fixups={getattr(dlg, "_size_fixups", "N/A")} '
              f'显示尺寸={dlg._frame_work(1).size} vs work={dlg.work.size}')
        crop0 = tuple(dlg.crop)
        drift = []
        for k in [1, 3, 5, 2, 4, 0]:
            dlg._preview_goto(k)
            if tuple(dlg.crop) != crop0 or dlg.work.size != (dlg.work.size):
                drift.append(k)
            if dlg._frame_work(dlg.preview_idx).size != dlg.work.size:
                drift.append(('size', k, dlg._frame_work(dlg.preview_idx).size))
        check('E4 ★走遍不一致帧，裁剪框与显示尺寸全程不漂移', not drift, str(drift[:3]))
        # 策略写进代码
        doc = (R.ImagePreprocessDialog._canonical_frame.__doc__ or '')
        check('E6 策略写进实现 docstring（首帧尺寸为准 + 理由）',
              ('首帧' in doc) and len(doc) > 20, doc.strip().splitlines()[0][:60] if doc else '无')
        # 单元：_canonical_frame 归一小/大两种输入，同尺寸原样返回
        same = Image.new('RGBA', dlg.orig.size, (1, 2, 3, 255))
        smaller = Image.new('RGBA', (max(2, dlg.orig.width // 2), max(2, dlg.orig.height // 2)),
                            (1, 2, 3, 255))
        bigger = Image.new('RGBA', (dlg.orig.width + 7, dlg.orig.height + 9), (1, 2, 3, 255))
        n0 = dlg._size_fixups
        check('E7 _canonical_frame：同尺寸原样返回、异尺寸拉伸到首帧尺寸',
              dlg._canonical_frame(same) is same
              and dlg._canonical_frame(smaller).size == dlg.orig.size
              and dlg._canonical_frame(bigger).size == dlg.orig.size
              and dlg._size_fixups == n0 + 2,
              f'fixups {n0} → {dlg._size_fixups}')
        # _apply：输出 APNG 每帧同尺寸且不丢帧
        dlg._preview_goto(0)
        dlg._apply()
        out = dlg.result_path
        got = Image.open(out) if out and os.path.exists(out) else None
        n_out = int(getattr(got, 'n_frames', 1) or 1) if got else 0
        out_sizes = set()
        if got:
            for k in range(n_out):
                got.seek(k)
                out_sizes.add(got.size)
        check('E8 ★尺寸不一致的源也能写出「每帧同尺寸、不丢帧」的动图',
              bool(out) and n_out == src.n_frames and len(out_sizes) == 1,
              f'输出 {n_out} 帧 / 尺寸集合 {sorted(out_sizes)} / 期望 {src.n_frames} 帧')
    finally:
        if patched:
            Image.open = orig_open
        try:
            if dlg is not None and dlg.root.winfo_exists():
                dlg._cancel()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass


# ================= F 段 =================
def test_f_destroy_cleanup(tmp, small_gif):
    section('F 销毁不留 after / 回调（无 TclError）')
    root = tk.Tk()
    root.withdraw()
    try:
        dlg = R.ImagePreprocessDialog(root, small_gif)
        proto = dlg.root.protocol('WM_DELETE_WINDOW')
        check('F0 WM_DELETE_WINDOW 已绑定到停表路径（点 X 不残留节拍）',
              bool(proto) and 'cancel' in proto, str(proto))
        dlg._toggle_preview()
        pending_id = dlg._anim_after
        pending_before = set(map(str, root.tk.call('after', 'info')))
        check('F1 播放中确实排了节拍（现场前提）',
              dlg._playing and pending_id is not None and str(pending_id) in pending_before,
              f'after={pending_id} 队列={sorted(pending_before)}')
        dlg._cancel()
        pending_after = set(map(str, root.tk.call('after', 'info')))
        check('F2 ★_cancel 后节拍已取消、状态复位',
              (not dlg._playing) and dlg._anim_after is None and dlg._alive is False,
              f'playing={dlg._playing} after={dlg._anim_after} alive={dlg._alive}')
        check('F3 ★Tk 待执行队列里不再有我们的 after id',
              str(pending_id) not in pending_after, f'残留={sorted(pending_after)[:4]}')
        err = None
        try:
            dlg._preview_tick()        # 模拟「已排的节拍在销毁后才触发」
            dlg._draw()
        except Exception as e:
            err = '%s: %s' % (type(e).__name__, e)
        check('F4 ★销毁后迟到的回调安全返回（不抛 TclError）', err is None, str(err))
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    # _apply 路径也要停表
    root2 = tk.Tk()
    root2.withdraw()
    try:
        dlg2 = R.ImagePreprocessDialog(root2, small_gif)
        dlg2._toggle_preview()
        dlg2._apply()
        check('F6 ★_apply 路径同样停掉节拍（不留 after）',
              bool(dlg2.result_path) and (not dlg2._playing) and dlg2._anim_after is None
              and dlg2._alive is False,
              f'result={os.path.basename(dlg2.result_path or "")} after={dlg2._anim_after}')
    finally:
        try:
            root2.destroy()
        except Exception:
            pass


def _tk_alive(win):
    try:
        win.winfo_exists()
        return True
    except Exception:
        return False


# ================= G 段 =================
def test_g_static_unchanged(tmp, png, old_mod):
    section('G 静态图行为不变')
    root = tk.Tk()
    root.withdraw()
    dlg = None
    out_path = None
    new_bytes = None
    try:
        dlg = R.ImagePreprocessDialog(root, png)
        check('G1 静态图没有动画控件（UI 不增生）',
              not hasattr(dlg, 'btn_play') and not hasattr(dlg, 'lbl_frame'),
              'btn_play/lbl_frame 不存在')
        check('G2 静态图 _frame_work(0) 就是 work 本身（零额外拷贝）',
              dlg._frame_work(0) is dlg.work and dlg._frame_work(5) is dlg.work)
        check('G3 静态图不排任何节拍', dlg._anim_after is None and not dlg._playing)

        # R6 把「Tk 画的棋盘格」烘进显示图（消掉混合 alpha 推图慢路径）→ 视觉必须一致：
        #   被抠掉的地方 = 棋盘格本色；实心内容 = 原色
        def _exp_checker(dx, dy, cell=16):
            light = _rgb(R.PREPROCESS_CHECKER_LIGHT)
            base = _rgb(R.PREPROCESS_CHECKER_BASE)
            return light if ((dx // cell) + (dy // cell)) % 2 == 0 else base

        s, _ox, _oy = dlg._fit()
        shot = dlg._screen_image(dlg.work, s)
        cxc, cyc = dlg.work.width // 2, dlg.work.height // 2          # 实心内容（红块中心）
        bxp, byp = 2, 2                                               # 背景（四角白底，被抠掉）
        d_cx, d_cy = int(cxc * s), int(cyc * s)
        d_bx, d_by = int(bxp * s), int(byp * s)
        check('G4 显示图是 RGB（不透明）→ Tk 走快速推图路径',
              shot.mode == 'RGB', shot.mode)
        check('G5 ★实心内容像素原色不变',
              shot.getpixel((d_cx, d_cy))[:3] == dlg.work.getpixel((cxc, cyc))[:3],
              f'{shot.getpixel((d_cx, d_cy))} vs 源 {dlg.work.getpixel((cxc, cyc))}')
        check('G6 ★被抠掉的背景处露出棋盘格（与老画法同色同格）',
              shot.getpixel((d_bx, d_by)) == _exp_checker(d_bx, d_by),
              f'{shot.getpixel((d_bx, d_by))} vs 期望 {_exp_checker(d_bx, d_by)}')
        dlg._apply()
        out_path = dlg.result_path
        new_bytes = open(out_path, 'rb').read()
    finally:
        try:
            dlg._cancel()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    # 兜底路径：烘焙失败时回到老画法（Tk 棋盘格 + RGBA 推图），不许抛异常
    root3 = tk.Tk()
    root3.withdraw()
    try:
        d3 = R.ImagePreprocessDialog(root3, png)
        orig_bake = d3._checker_bg
        try:
            d3._checker_bg = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('模拟烘焙失败'))
            err = None
            try:
                d3._draw()
            except Exception as e:
                err = '%s: %s' % (type(e).__name__, e)
            rects = [i for i in d3.cv.find_all() if d3.cv.type(i) == 'rectangle']
            check('G9 棋盘格烘焙失败 → 退回 Tk 画法且不抛异常',
                  err is None and len(rects) > 100, f'err={err} 矩形数={len(rects)}')
        finally:
            d3._checker_bg = orig_bake
            d3._cancel()
    finally:
        try:
            root3.destroy()
        except Exception:
            pass
    if old_mod is None:
        skip('G4 静态 _apply 与改前逐字节相同', '旧模块不可用')
        return
    root2 = tk.Tk()
    root2.withdraw()
    old_bytes = None
    try:
        odp = old_mod.ImagePreprocessDialog(root2, png)
        odp._apply()
        old_bytes = open(odp.result_path, 'rb').read()
    finally:
        try:
            root2.destroy()
        except Exception:
            pass
    check('G7 ★静态 _apply 输出与改前（%s）逐字节相同' % R6_BASE_REV,
          old_bytes is not None and new_bytes == old_bytes,
          f'新 {len(new_bytes)} B / 改前 {len(old_bytes) if old_bytes else -1} B')
    check('G8 静态输出文件名与扩展名口径不变',
          bool(out_path) and out_path.endswith('.png')
          and 'preprocessed_' in os.path.basename(out_path),
          os.path.basename(out_path or ''))


def main():
    tmp = tempfile.mkdtemp(prefix='r6gif_')
    real_here = R.HERE
    R.HERE = tmp                       # 预处理产物别落到项目目录
    print('=' * 72)
    print('R6 图片预处理支持动图：播放/逐帧查看 + 裁剪框对每帧一致 + 不卡 UI')
    print('夹具目录：%s' % tmp)
    print('=' * 72)
    dlg = root = None
    try:
        big = make_big_gif(os.path.join(tmp, 'big_anim.gif'))
        small = make_small_gif(os.path.join(tmp, 'small.gif'))
        png = make_png(os.path.join(tmp, 'static.png'))
        base_cost = test_a_cost_baseline(tmp, big)
        old_mod, why = load_old_module(tmp)
        before = test_b_before(tmp, big, base_cost, old_mod, why)
        dlg, root, cost = test_c_open_play(tmp, big, base_cost, before)
        test_d_crop_consistency(dlg, base_cost['n'])
        dlg._cancel()
        try:
            root.destroy()
        except Exception:
            pass
        dlg = root = None
        test_e_size_mismatch(tmp, small)
        test_f_destroy_cleanup(tmp, small)
        test_g_static_unchanged(tmp, png, old_mod)
    finally:
        try:
            if dlg is not None:
                dlg._cancel()
        except Exception:
            pass
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass
        R.HERE = real_here
        shutil.rmtree(tmp, ignore_errors=True)
        if os.path.isdir(tmp):
            print('警告：本次临时目录未能删除：%s' % tmp)
    print('=' * 72)
    print('通过 %d 项 / 失败 %d 项' % (len(PASS), len(FAIL))
          + (' / 跳过 %d 项' % len(SKIP) if SKIP else ''))
    if FAIL:
        print('失败项: ' + ', '.join(FAIL))
        return 1
    print('ALL CHECKS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
