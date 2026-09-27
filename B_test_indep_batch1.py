# -*- coding: utf-8 -*-
"""B_test_indep_batch1.py —— 批次一（R1/R2/R3）**独立验证** · verifier 专属

定位（不信实现者自评）
----------------------
本脚本由 verifier 独立编写，**不复用** B_test_r1_feather / B_test_r2_layer_side /
B_test_r3_follow_perf 的断言，而是用「用户真实通路 + 同口径前→后对照 + 反例」验证
R1/R2/R3 的**用户可见语义**：

  · A 段 R1：真实出厂图（release/config.json 指向的 891×1247 RGBA）走向导，从
             **画布上真正显示的 PhotoImage 像素**判定「兼容 = 硬边 / 增强 = 颜色到棋盘格
             的平滑过渡」；⑩ 旁开关与 ⑪ 渲染模式双向联动、置灰、保存一致性；运行时通路
             （apply_display_effects）真羽化有中间 alpha；并与 R1 之前（999bcbd）逐字节
             对照证明**兼容老路径零漂移**。
  · B 段 R2：release/config.json 端到端零漂移（含 F-V1 老坑 offset -132/-132 必须保留）；
             多图层主层贴边改动 → **落到运行时布局落点**（resolve_layers + plan_layer_layout，
             不只是看向导内部字段）；皮肤档案往返；窗口高度 R1/R2/HEAD 实测（判定 A06
             把 ≤1020 调成 ≤1038 是否由实测支撑）。
  · C 段 R3：自建假候选框 harness，**同一脚本**对 bc135b0（R3 前）与 HEAD（R3 后）跑同口径
             对照：稳态每帧文件 I/O 次数、单帧耗时 p50、以及「一帧内候选框又变宽」注入下的
             窗口/画面一致性（错位 px）。
  · D 段 反例：单↔多图层切换、动图↔静态切换（同路径换内容）、开关快速连切、皮肤档案
             （新档案 / v1.6 老档案）往返回显、极端输入（6 层 / 缺图 / 零尺寸）。

红线：只读被测代码；不写真实 config.json / skins/（save_config / SKINS_DIR 打桩或临时目录）；
      不碰 %APPDATA%\\Rime；不动 G:\\github成果\\。

用法: python B_test_indep_batch1.py [--sections A,B,C,D]
      python B_test_indep_batch1.py --sections A          # 只跑某几段（调试用）
"""
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import rime_char_overlay as R          # noqa: E402

PASS, FAIL, SKIP = [], [], []
NOTES = []


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f'  [PASS] {name}' + (f'   ({detail})' if detail else ''))
    else:
        FAIL.append(name)
        print(f'  [FAIL] {name}' + (f'   ({detail})' if detail else ''))


def note(msg):
    NOTES.append(msg)
    print(f'  [INFO] {msg}')


def section(title):
    print(f'\n{title}')
    print('-' * len(title))


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


# --------------------------------------------------------------------------
# 载入历史版本模块（同口径前→后对照用）
# --------------------------------------------------------------------------
def extract_version(ref, tag, tmp):
    """把历史提交里的 rime_char_overlay.py 提取成临时文件（LF 原始字节）。"""
    try:
        p = subprocess.run(['git', 'cat-file', 'blob', f'{ref}:rime_char_overlay.py'],
                           cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0 or not p.stdout:
            return None, p.stderr.decode('utf-8', 'replace')[:200]
        out = os.path.join(tmp, f'rc_{tag}.py')
        with open(out, 'wb') as f:
            f.write(p.stdout)
        return out, f'{len(p.stdout)} B'
    except Exception as e:
        return None, repr(e)


def load_module(path, name):
    import importlib.util
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# 通用夹具 / 打桩
# --------------------------------------------------------------------------
def make_png(path, size, color):
    from PIL import Image
    Image.new('RGBA', size, color).save(path)
    return path


def make_gif(path, size=(240, 320), n=8):
    from PIL import Image
    frames = []
    for i in range(n):
        im = Image.new('RGBA', size, (0, 0, 0, 0))
        for y in range(40 + i * 10, size[1] - 40 - i * 10):
            for x in range(40, size[0] - 40):
                im.putpixel((x, y), (200 - i * 10, 40 + i * 10, 60, 255))
        frames.append(im.convert('P'))
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=60, loop=0)
    return path


def load_factory_raw():
    """出厂配置原样读入（= 用户机器上 release/config.json 的通路）。"""
    with open(os.path.join(BASE, 'release', 'config.json'), encoding='utf-8') as f:
        return json.load(f)


def stub_module(M):
    """把写盘/弹窗类副作用打桩；返回 (saved_dict, restore_fn)。"""
    saved = {}
    real = {}
    names = ('save_config', 'messagebox', 'set_autostart')

    def patch(attr, val):
        real[attr] = getattr(M, attr)
        setattr(M, attr, val)

    patch('save_config', lambda cfg: saved.update(cfg))
    mb = M.messagebox
    real['_mb'] = (mb.showinfo, mb.showwarning, mb.showerror, mb.askyesno)
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    mb.askyesno = lambda *a, **k: True
    patch('set_autostart', lambda *a, **k: (True, '（独立验证打桩）'))

    def restore():
        for attr in names:
            if attr in real:
                setattr(M, attr, real[attr])
        (mb.showinfo, mb.showwarning, mb.showerror, mb.askyesno) = real['_mb']
    return saved, restore


def make_wiz(M, cfg, saved, skins_dir):
    old_skins = getattr(M, 'SKINS_DIR', None)
    M.SKINS_DIR = skins_dir
    wiz = M.ConfigWizard(on_done=lambda c: saved.update(c), overlay=None)
    if old_skins is not None:
        M.SKINS_DIR = old_skins
    if cfg:
        wiz.cfg.update(cfg)
    wiz._layer_sync_from_cfg()
    wiz.root.update_idletasks()
    wiz.root.update()
    return wiz


def kill_wiz(wiz):
    try:
        wiz.root.destroy()
    except Exception:
        pass


def photo_px(tkimg, x, y):
    """从真实 PhotoImage 取像素（渲染到用户眼睛里的那一份）。"""
    try:
        v = tkimg.tk.call(str(tkimg), 'get', int(x), int(y))
    except Exception:
        return None
    if isinstance(v, str):
        try:
            v = tuple(int(t) for t in v.split())
        except Exception:
            return None
    if isinstance(v, (int, float)):
        return (int(v),) * 3
    try:
        return tuple(int(t) for t in v)
    except Exception:
        return None


def row_pixels(tkimg, y, w):
    return [photo_px(tkimg, x, y) for x in range(w)]


def _near(c, t, tol=10):
    if c is None or t is None:
        return False
    return all(abs(int(c[i]) - int(t[i])) <= tol for i in range(3))


def _checker_profile(tkimg, y, n):
    """一行前 n 个像素「到最近棋盘色的距离」剖面（0=完全透明/露出棋盘，越大=越不透明）。

    与源图颜色无关 → 真实大图也能用来区分「硬边点阵（0 与高值交替）」与
    「平滑过渡（连续上升的斜坡）」。
    """
    out = []
    for x in range(n):
        c = photo_px(tkimg, x, y)
        if c is None:
            out.append(0)
            continue
        d = min(sum((int(c[i]) - int(t[i])) ** 2 for i in range(3)) ** 0.5
                for t in (R.CHECKER_LIGHT, R.CHECKER_DARK))
        out.append(int(round(d)))
    return out


def _max_run(prof, thr):
    """最长连续「不透明段」（>= thr 的连续像素数）：点阵会交替 → 短；平滑渐变 → 长。"""
    best = cur = 0
    for v in prof:
        cur = cur + 1 if v >= thr else 0
        best = max(best, cur)
    return best


def band_metrics(pixels, src_color, light, dark):
    """一行像素里「既不是源色也不是棋盘两色」的像素数 = 平滑过渡的中间色。"""
    mid = 0
    for c in pixels:
        if c is None:
            continue
        if _near(c, src_color) or _near(c, light, 3) or _near(c, dark, 3):
            continue
        mid += 1
    distinct = len({tuple(c) for c in pixels if c is not None})
    return mid, distinct


# ==========================================================================
# A 段 · R1 增强羽化开关 + 预览棋盘格
# ==========================================================================
def section_A(tmp):
    section('A 段 · R1 增强羽化：⑩ 旁开关 / 预览硬边 vs 平滑过渡 / 运行时真羽化')
    saved, restore = stub_module(R)
    skins = os.path.join(tmp, 'skins_A')
    os.makedirs(skins, exist_ok=True)
    # 纯色不透明图 + 小 scale：让预览**不被 fit 缩小**（缩放会把点阵混合成
    # 伪中间色 —— 见 dbg 记录：180→163 的 LANCZOS 预乘 alpha 会造出 275 种 RGB），
    # 这样「硬边 = 只有源色/棋盘两色」才是逐像素可判的。
    solid = make_png(os.path.join(tmp, 'A_solid.png'), (200, 200), (200, 40, 40, 255))
    raw = load_factory_raw()
    cfg = dict(R.DEFAULT_CONFIG)
    cfg.update(raw)
    cfg['image'] = solid          # 纯色不透明图：羽化带在预览里一眼可辨
    cfg['scale'] = 0.4
    cfg['offset_x'] = 0
    cfg['offset_y'] = 0
    cfg['corner_enabled'] = False
    cfg['feather_enabled'] = True
    cfg['feather_radius'] = 24
    wiz = None
    try:
        wiz = make_wiz(R, cfg, saved, skins)
        wiz.var_corner.set(False)
        wiz.var_render.set('compat')
        wiz._update_render_hint()
        wiz.var_feather_r.set(24)
        wiz.var_feather.set(True)      # 兼容档：用户勾了「点阵羽化」
        wiz._update_preview()

        # ---- A01/A02 控件存在且落在 ⑩ 那张卡所在的列 ----
        # 第六轮（R19）**需求反转**：先生「按图把真羽化换个位置，和 ⑧⑨⑩ 同一列，
        #   点选框放字后面」＋「下一行…方框（和 9、10 对齐）」⇒ ⑪ 不再是「⑩ 行末
        #   那个带 ⑪ 文案的开关」，而是「标题 Label 在上 + 方框在下」两件套、与
        #   ⑧⑨⑩ 同处一个 adv 列卡片。判别力：把 ⑪ 挪回 ⑩ 控件行末 → A02 必 FAIL。
        w = getattr(wiz, 'chk_alpha_feather', None)
        lbl11 = getattr(wiz, 'lbl_alpha_feather', None)
        check('A01 ★⑪ 增强（真羽化）控件在（标题 Label + 方框，方框文案 = 「启用」）',
              w is not None and lbl11 is not None
              and '增强' in str(lbl11.cget('text')) and '真羽化' in str(lbl11.cget('text'))
              and str(w.cget('text')) == '启用',
              '%r + %r' % (str(lbl11.cget('text')) if lbl11 is not None else None,
                           str(w.cget('text')) if w is not None else None))
        fe_parent = None
        try:
            fe_parent = str(wiz.chk_feather.master)
        except Exception:
            pass
        ok_parent = False
        try:
            ok_parent = (w is not None and lbl11 is not None
                         and w.master.master is wiz.chk_feather.master.master
                         and lbl11.master is wiz.chk_feather.master.master)
        except Exception:
            ok_parent = False
        check('A02 与 ⑧⑨⑩ 同处一个列卡片（⑪ 标题行与 ⑩ 控件行同父）',
              ok_parent,
              f'alpha.master={w and w.master} feather.master={fe_parent}')

        # ---- 预览像素：兼容档 ----
        ph_c = wiz.tk_img
        w0, h0 = ph_c.width(), ph_c.height()
        px_c = row_pixels(ph_c, h0 // 2, w0)
        mid_c, dis_c = band_metrics(px_c, (200, 40, 40), R.CHECKER_LIGHT, R.CHECKER_DARK)
        # 棋盘格确实垫在底下：图的四角是羽化到透明的 → 应露出棋盘两色
        corners = [photo_px(ph_c, 2, 2), photo_px(ph_c, 18, 2),
                   photo_px(ph_c, 2, 18), photo_px(ph_c, 18, 18)]
        # v2.0-R7（前提被需求推翻）：预览底从 R1 的棋盘格改回**画布底色** —— 用户实测把棋盘格
        # 看成了「不透明」。底色取模块常量（不硬编码白），并断言棋盘格深色**不再出现**；
        # 两条子条件都能在回退场景下抓红（把预览合成换回棋盘格 → has_bg/has_d 双双反转）。
        preview_bg = tuple(getattr(R, 'PREVIEW_BG_RGB', (255, 255, 255)))
        has_bg = all(_near(c, preview_bg, 3) for c in corners)
        has_d = any(_near(c, R.CHECKER_DARK, 3) for c in corners)
        check('A03 ★R7 后预览垫的是画布底色（角上 = PREVIEW_BG_RGB，不再出现棋盘格深色）',
              has_bg and not has_d,
              f'corners={corners} 底色={preview_bg} 深色出现={has_d}')
        check('A03b 预览未被 fit 缩小（1:1 → 像素判定才逐位可信）',
              (w0, h0) == (120, 120), f'预览={w0}x{h0}（期望 120x120）')
        check('A04 ★兼容档预览 = 硬边（羽化带无颜色混合，中间色≈0）',
              mid_c <= 2 and dis_c <= 5, f'中间色像素={mid_c} 行内色数={dis_c} 预览={w0}x{h0}')

        # ---- A05/A06/A09 勾上「增强」→ 联动 + 即时重绘 ----
        items_before = len(wiz.canvas.find_all())
        wiz.var_alpha_feather.set(True)
        wiz._on_alpha_feather_toggle()
        check('A05 ★⑩ 开关勾上 → ⑪ 渲染模式同步为增强（双向联动）',
              wiz.var_render.get() == 'alpha' and wiz._is_alpha_mode(),
              f'var_render={wiz.var_render.get()}')
        ph_a = wiz.tk_img
        w1, h1 = ph_a.width(), ph_a.height()
        px_a = row_pixels(ph_a, h1 // 2, w1)
        mid_a, dis_a = band_metrics(px_a, (200, 40, 40), R.CHECKER_LIGHT, R.CHECKER_DARK)
        check('A06 ★增强档预览 = 平滑过渡（颜色到棋盘格逐像素混合）',
              mid_a >= 15 and dis_a >= 30 and mid_a > 5 * max(1, mid_c),
              f'中间色像素={mid_a}（兼容档 {mid_c}）行内色数={dis_a}（兼容档 {dis_c}）')
        # 顺带记录「真实出厂大图 + 预览被 fit 缩小」时的一组数（缩放会把点阵混成伪中间色，
        # 故只做 INFO，不做判据；这一段与 R1 前后行为一致，非 R1 引入）
        note(f'（参考）1:1 预览行内：兼容 {dis_c} 色 / 增强 {dis_a} 色')
        check('A09 切换即时重绘（同一画布、像素确实变了，没有堆 item）',
              len(wiz.canvas.find_all()) == items_before and px_a != px_c,
              f'items {items_before}→{len(wiz.canvas.find_all())}')

        # ---- A07 置灰 + 文案 ----
        st = str(wiz.chk_feather.cget('state'))
        hint = str(wiz.lbl_feather_hint.cget('text'))
        check('A07 增强档「点阵羽化」勾选框置灰 + 文案讲清「点阵是兼容近似」',
              st == 'disabled' and ('近似' in hint or '兼容' in hint),
              f'state={st} hint={hint[:38]}…')

        # ---- A08 反向通路：⑪ 单选改回兼容 → 开关自动取消 ----
        wiz.var_render.set('compat')
        wiz._update_render_hint()
        ok_back = (wiz.var_alpha_feather.get() is False
                   and str(wiz.chk_feather.cget('state')) == 'normal'
                   and bool(wiz.var_feather.get()) is True)   # 用户原勾选被恢复
        check('A08 ★⑪ 改回兼容 → 开关自动取消 + 点阵勾选恢复原值 + 解灰', ok_back,
              f'alpha={wiz.var_alpha_feather.get()} state={wiz.chk_feather.cget("state")} '
              f'feather={wiz.var_feather.get()}')

        # ---- A10 保存一致性（两个模式各存一次）----
        saved.clear()
        wiz.var_render.set('alpha')
        wiz._update_render_hint()
        wiz._save_and_start()
        c1 = dict(saved)
        check('A10a 增强档保存：cfg[render_mode]=alpha 且 feather_enabled=True',
              c1.get('render_mode') == 'alpha' and bool(c1.get('feather_enabled')) is True,
              f"render_mode={c1.get('render_mode')} feather={c1.get('feather_enabled')}")
        # 兼容档：不勾羽化 → feather_enabled 必须为假（老口径不被真羽化污染）
        wiz2 = make_wiz(R, dict(cfg, feather_enabled=False), saved, skins)
        try:
            wiz2.var_render.set('compat')
            wiz2._update_render_hint()
            wiz2.var_feather.set(False)
            wiz2._update_preview()
            saved.clear()
            wiz2._save_and_start()
            c2 = dict(saved)
            check('A10b 兼容档保存：render_mode=compat 且未勾羽化 → feather_enabled=False',
                  c2.get('render_mode') == 'compat'
                  and bool(c2.get('feather_enabled')) is False,
                  f"render_mode={c2.get('render_mode')} feather={c2.get('feather_enabled')}")
        finally:
            kill_wiz(wiz2)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('A00 A 段未抛异常', False, repr(e))
    finally:
        if wiz is not None:
            kill_wiz(wiz)
        restore()

    # ---- A11 运行时通路（非向导）：真羽化 = 逐像素 alpha ----
    try:
        from PIL import Image as PILImage
        solid_rgba = PILImage.new('RGBA', (214, 300), (200, 40, 40, 255))
        real_img = load_factory_raw()['image']
        with PILImage.open(real_img) as im:
            real = im.convert('RGBA').resize((214, 300), PILImage.LANCZOS)
        # 受控实验：源图 alpha 二值化（消除真实图自带抗锯齿 alpha 的干扰）——
        # 这样 compat 与 alpha 的差别只剩「羽化实现」这一项
        real_bin = real.copy()
        real_bin.putalpha(real.split()[3].point(lambda v: 255 if v >= 128 else 0))
        base = {'feather_enabled': True, 'feather_radius': 24,
                'corner_enabled': False, 'corner_radius': 0}
        band = list(range(40))
        mid_s_true = sum(1 for x in band
                         if 0 < R.apply_display_effects(solid_rgba, dict(base, render_mode='alpha'),
                                                        PILImage).getpixel((x, 150))[3] < 255)
        mid_s_comp = sum(1 for x in band
                         if 0 < R.apply_display_effects(solid_rgba, dict(base),
                                                        PILImage).getpixel((x, 150))[3] < 255)
        t_real = R.apply_display_effects(real_bin, dict(base, render_mode='alpha'), PILImage)
        c_real = R.apply_display_effects(real_bin, dict(base), PILImage)
        mid_r_true = sum(1 for x in band if 0 < t_real.getpixel((x, 150))[3] < 255)
        mid_r_comp = sum(1 for x in band if 0 < c_real.getpixel((x, 150))[3] < 255)
        check('A11 ★运行时通路：alpha 档羽化带是逐像素真羽化，compat 档严格 0/255',
              mid_s_true >= 10 and mid_s_comp == 0 and mid_r_true >= 10 and mid_r_comp == 0,
              f'纯色图 中间 alpha：alpha档={mid_s_true} compat档={mid_s_comp}；'
              f'真实出厂图（alpha 二值化后）alpha档={mid_r_true} compat档={mid_r_comp}')
        chk_a = R.compose_on_checker(R.apply_display_effects(
            solid_rgba, dict(base, render_mode='alpha'), PILImage), R.CHECKER_CELL, PILImage)
        chk_c = R.compose_on_checker(R.apply_display_effects(
            solid_rgba, dict(base), PILImage), R.CHECKER_CELL, PILImage)
        ma, da = band_metrics([chk_a.getpixel((x, 150)) for x in band], (200, 40, 40),
                              R.CHECKER_LIGHT, R.CHECKER_DARK)
        mc, dc = band_metrics([chk_c.getpixel((x, 150)) for x in band], (200, 40, 40),
                              R.CHECKER_LIGHT, R.CHECKER_DARK)
        check('A11b ★合成到棋盘格后：alpha 档是颜色到棋盘的平滑过渡，compat 档只有硬边',
              ma >= 15 and da >= 30 and mc == 0 and dc <= 3,
              f'中间色像素 alpha档={ma}（色数 {da}） compat档={mc}（色数 {dc}）')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('A11 运行时通路段未抛异常', False, repr(e))

    # ---- A14 用户真实场景：出厂大图 + 预览被 fit 缩小 时是否仍看得出差别 ----
    try:
        raw = load_factory_raw()
        cfg = dict(R.DEFAULT_CONFIG)
        cfg.update(raw)
        cfg['corner_enabled'] = False
        cfg['feather_enabled'] = True
        cfg['feather_radius'] = 24
        saved2, restore2 = stub_module(R)
        w = None
        try:
            w = make_wiz(R, cfg, saved2, skins)
            w.var_corner.set(False)
            w.var_feather_r.set(24)
            w.var_render.set('compat')
            w._update_render_hint()
            w.var_feather.set(True)
            w._update_preview()
            phc = w.tk_img
            w0, h0 = phc.width(), phc.height()
            prof_c = _checker_profile(phc, h0 // 2, 60)
            w.var_alpha_feather.set(True)
            w._on_alpha_feather_toggle()
            pha = w.tk_img
            prof_a = _checker_profile(pha, pha.height() // 2, 60)
            note(f'（真实出厂图 891x1247，预览缩到 {w0}x{h0}）到「透明底」的距离剖面（中行前 40px，'
                 f'R7 后底 = 画布底色）:')
            note(f'   兼容 {prof_c[:40]}')
            note(f'   增强 {prof_a[:40]}')
            run_c, run_a = _max_run(prof_c, 20), _max_run(prof_a, 20)
            # 说明：真实出厂图自带透明留白，且预览被 fit 缩小后 LANCZOS 预乘会把点阵混合，
            # 「逐像素中间色/连续段」在这张图上都不是可靠判据（自测 zigzag 36 vs 29、
            # grain 34 vs 13，区分度不足）→ 这里只记录剖面作证据，判据压在 A04/A06（1:1）
            # 与 A11/A11b（运行时真羽化）上，不硬造阈值。
            note(f'   兼容最长连续不透明段={run_c}px / 增强={run_a}px（剖面对照见上）')
            # v2.0-R7：底由棋盘格改为画布底色（白）后，「露出棋盘」变成「露出底色」——
            # 判据改成与底色无关的形态学判据：兼容 = 边缘 1px 陡降回底色（硬边）；
            # 增强 = 连续非底色带（斜坡）。增强档若退化成硬边，min(prof_a[17:21]) 会掉到 ~0 → 红。
            check('A14 真实场景剖面（R7 口径：兼容=高值→底色 1px 陡降；增强=连续非底色带）',
                  prof_c[17] >= 40 and prof_c[18] < 10 and min(prof_a[17:21]) >= 10,
                  f'兼容 [17..20]={prof_c[17:21]}（17→18 直接掉回底色 = 硬边）；'
                  f'增强 [17..20]={prof_a[17:21]}（连续非底色 = 平滑过渡）')
        finally:
            if w is not None:
                kill_wiz(w)
            restore2()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('A14 真实场景段未抛异常', False, repr(e))

    # ---- A13 判定「64×64 → 300×240」口径调整是否由实测支撑 ----
    try:
        from PIL import Image as PILImage
        prof = {}
        for tag, size in (('64x64', (64, 64)), ('300x240', (300, 240))):
            src = PILImage.new('RGBA', size, (200, 40, 40, 255))
            base = {'feather_enabled': True, 'feather_radius': 24, 'corner_enabled': False}
            comp = R.apply_display_effects(src, dict(base), PILImage)
            true = R.apply_display_effects(src, dict(base, render_mode='alpha'), PILImage)
            y = size[1] // 2
            w = size[0]
            a_c = [comp.getpixel((x, y))[3] for x in range(w)]
            a_t = [true.getpixel((x, y))[3] for x in range(w)]
            opaque_c = sum(1 for v in a_c if v == 255)
            mid_c = sum(1 for v in a_c if 0 < v < 255)
            mid_t = sum(1 for v in a_t if 0 < v < 255)
            prof[tag] = (opaque_c, mid_c, mid_t)
        # 64×64 + 半径 24：中间行几乎没有不透明内核（band 吃满整幅），
        # 「硬边只有 0/255」的判据在那张图上无法成立 → 原前提被证伪
        check('A13 ★口径调整①（64×64 → 300×240）由实测支撑：小图中间行无足够不透明内核',
              prof['64x64'][0] <= 20 and prof['300x240'][0] >= 200,
              f"64x64 中间行不透明像素={prof['64x64'][0]}（中间 alpha compat={prof['64x64'][1]}/"
              f"真羽化={prof['64x64'][2]}）；300x240 不透明像素={prof['300x240'][0]}"
              f"（compat={prof['300x240'][1]}/真羽化={prof['300x240'][2]}）")
        check('A13b 300×240 上判据可判（compat 严格 0 中间 alpha，真羽化有梯度）',
              prof['300x240'][1] == 0 and prof['300x240'][2] >= 10,
              f"compat={prof['300x240'][1]} 真羽化={prof['300x240'][2]}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('A13 口径调整取证段未抛异常', False, repr(e))

    # ---- A12 兼容路径与 R1 之前逐字节一致（老路径零漂移）----
    try:
        p, info = extract_version('999bcbd', 'pre_r1', tmp)
        if not p:
            check('A12 能取到 R1 之前的模块做对照', False, str(info))
        else:
            OLD = load_module(p, 'rc_pre_r1')
            from PIL import Image as PILImage
            from PIL import ImageChops
            real_img = load_factory_raw()['image']
            with PILImage.open(real_img) as im:
                src = im.convert('RGBA').resize((214, 300), PILImage.LANCZOS)
            cases = [dict(feather_enabled=True, feather_radius=24, corner_enabled=False),
                     dict(feather_enabled=True, feather_radius=24, corner_enabled=True,
                          corner_radius=24),
                     dict(feather_enabled=False, feather_radius=0, corner_enabled=False),
                     dict(feather_enabled=True, feather_radius=24, corner_enabled=False,
                          flip_h=True)]
            worst = None
            for i, cc in enumerate(cases):
                o = OLD.apply_display_effects(src.copy(), dict(cc), PILImage)
                n = R.apply_display_effects(src.copy(), dict(cc), PILImage)
                if o.size != n.size or o.mode != n.mode:
                    worst = f'case{i} size/mode 不同 {o.size}/{n.size}'
                    break
                d = ImageChops.difference(o.convert('RGBA'), n.convert('RGBA'))
                if d.getbbox() is not None:
                    worst = f'case{i} 像素有差异 bbox={d.getbbox()}'
                    break
            check('A12 ★兼容模式（无 render_mode）与 R1 之前逐字节一致：老路径零漂移',
                  worst is None, worst or '4 组参数（羽化/圆角/翻转/全关）逐字节相同')
            del OLD
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('A12 零漂移对照段未抛异常', False, repr(e))


# ==========================================================================
# B 段 · R2 贴边方向纳入图层 + 主层 bug + 高度口径
# ==========================================================================
def section_B(tmp):
    section('B 段 · R2 贴边方向：出厂配置零漂移 / 主层贴边落到运行时落点 / 档案往返 / 高度')
    saved, restore = stub_module(R)
    skins = os.path.join(tmp, 'skins_B')
    os.makedirs(skins, exist_ok=True)
    raw = load_factory_raw()
    real_img = raw['image']
    real_gif = (sorted(__import__('glob').glob(
        os.path.join(BASE, 'release', 'skins', '*', 'image.gif'))) or [''])[0]

    # ---- B01 出厂配置端到端：什么都不动 → 保存零漂移（F-V1 老坑安全网） ----
    cfg = dict(R.DEFAULT_CONFIG)
    cfg.update(raw)
    before = {k: cfg.get(k) for k in ('image', 'side', 'scale', 'offset_x', 'offset_y',
                                      'base_height', 'layout', 'layer', 'name')}
    wiz = None
    try:
        wiz = make_wiz(R, cfg, saved, skins)
        saved.clear()
        wiz._save_and_start()
        out = dict(saved)
        drift = {k: (before[k], out.get(k)) for k in before if out.get(k) != before[k]}
        check('B01 ★release/config.json 端到端零漂移（含 offset -132/-132）',
              not drift, f'漂移项={drift or "无"}')
        lay = out.get('layers') or []
        check('B01b ★保存后 layers[0].anchor = 顶层 side 的映射，且主层 offset 归零',
              len(lay) == 1 and lay[0].get('anchor') == 'right_edge'
              and int(lay[0].get('offset_x', 9)) == 0 and int(lay[0].get('offset_y', 9)) == 0,
              f"anchor={lay[0].get('anchor') if lay else None} off=({lay[0].get('offset_x') if lay else None},{lay[0].get('offset_y') if lay else None})")
        rl = R.resolve_layers(out)
        check('B01c ★运行时通路确认：单层 offset 仍是 -132/-132（没被向导吞掉）',
              len(rl) == 1 and int(rl[0]['offset_x']) == -132 and int(rl[0]['offset_y']) == -132,
              f"resolve_layers[0].offset=({rl[0]['offset_x']},{rl[0]['offset_y']})")
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('B00 出厂配置段未抛异常', False, repr(e))
    finally:
        if wiz is not None:
            kill_wiz(wiz)

    # ---- B02~B06 多图层：主层贴边可改 + 落到运行时落点 ----
    cfg2 = dict(R.DEFAULT_CONFIG)
    cfg2.update(raw)
    cfg2['layers'] = [{'image': real_img, 'anchor': 'right_edge', 'z': 0},
                      {'image': real_gif or real_img, 'anchor': 'left_edge', 'z': 1}]
    wiz2 = None
    try:
        wiz2 = make_wiz(R, cfg2, saved, skins)
        # v2.0-R11（前提被需求推翻）：③ 从图层区搬回通用区并**统一管所有图层** ——
        # 定位只看**变量绑定**（不看文案/位置/容器）：③ = 绑 var_side 的 3 个单选；
        # 图层区不再有绑 var_layer_anchor 的单选。两条子条件都能在回退场景下抓红
        # （③ 被搬回图层区 → 第一条红；图层区又加回单选 → 第二条红）。
        side_radios = _radio_texts(wiz2, wiz2.var_side)
        lay_radios = _radio_texts(wiz2, wiz2.var_layer_anchor)
        check('B02 ★R11 后 ③ 在通用区（var_side 绑 3 个单选），图层区不再有贴边单选',
              len(side_radios) == 3 and len(lay_radios) == 0,
              f'通用区={side_radios} 图层区={lay_radios}')
        _select(wiz2, 0)
        # v2.0-N3 改写**取样通路**（HANDOFF-2.1 §6-13 + t11 契约第 3 条(iii)）：旧取样
        # `var_side.set('center') + _update_preview()` 靠的是「实现会读 Tk 变量统一全层」——
        # N3 已明令禁止该行为（_sync_side_to_all_layers 只信 cfg['side']），旧取样在新实现下
        # **不走用户通路**，留着它等于「改绿了但取样路径是假的」。换成用户真实通路：点 ③ 的单选。
        _side_rbs = _radio_widgets(wiz2, wiz2.var_side)
        _rb_mid = _radio_widget(wiz2, wiz2.var_side, '中')
        check('B03a ③ 的单选组按**变量绑定**定位（绑 var_side 的恰 3 个，其中一个含「中」）',
              len(_side_rbs) == 3 and _rb_mid is not None,
              f'{_radio_texts(wiz2, wiz2.var_side)}')
        _rb_mid.invoke()
        wiz2.root.update_idletasks()
        check('B03 ★主层（第 0 层）贴边改得动（点一次 ③「中」）：cfg[side] 与 layers[0].anchor 同步为 center',
              wiz2.cfg.get('side') == 'center'
              and (wiz2.cfg['layers'][0].get('anchor') == 'center'),
              f"side={wiz2.cfg.get('side')} l0={wiz2.cfg['layers'][0].get('anchor')}")
        # B03b 判别力（§6-13 + t11 契约第 5 条）：把写回打桩成「无论点什么恒写 right_edge」
        # → B03 的**同款**判据必须 FAIL（证明它不是在验一个恒真式）。测完恢复桩、把状态点回 center。
        _real_set0 = wiz2._layer_set_params

        def _bad_anchor_set(i, scale=None, offset_x=None, offset_y=None, flip=None, anchor=None):
            return _real_set0(i, scale=scale, offset_x=offset_x, offset_y=offset_y, flip=flip,
                              anchor=('right_edge' if anchor is not None else anchor))

        wiz2._layer_set_params = _bad_anchor_set
        try:
            _radio_widget(wiz2, wiz2.var_side, '中').invoke()
            wiz2.root.update_idletasks()
        finally:
            wiz2._layer_set_params = _real_set0
        _bad_l0 = wiz2.cfg['layers'][0].get('anchor')
        check('B03b ★判别力：把写回打桩成「恒写 right_edge」→ B03 同款判据必须 FAIL（非恒真）',
              not (wiz2.cfg.get('side') == 'center' and _bad_l0 == 'center'),
              f'注入后 side={wiz2.cfg.get("side")} l0={_bad_l0}')
        _radio_widget(wiz2, wiz2.var_side, '中').invoke()      # 恢复状态（层 0 回到 center）
        wiz2.root.update_idletasks()
        # 运行时落点（不复用实现者测试：走 resolve_layers + plan_layer_layout）
        from PIL import Image as PILImage
        rl = R.resolve_layers(wiz2.cfg)
        dims = [_disp_size(ld['image'], 300, ld.get('scale', 1.0)) for ld in rl]
        wx, wy, ww, wh, pl = R.plan_layer_layout(rl, dims, (0, 0, 460, 84))
        pos = {p[0]: (p[1], p[2]) for p in pl}
        exp0x = 0 + (460 - dims[0][0]) // 2 + int(wiz2.cfg.get('offset_x', 0))
        check('B04 ★主层贴边真的落到运行时画面落点（居中公式逐位一致）',
              abs((wx + pos[0][0]) - exp0x) <= 1,
              f'层0 屏幕 x={wx + pos[0][0]} 期望={exp0x}（画布 {ww}x{wh}）')
        # v2.0-N3（前提被需求推翻）：③ 的作用对象 = **当前选中层** —— 改主层时第 2 层必须纹丝
        # 不动（旧断言「第 2 层也同步为 center」固化的是 R11 的统一语义，已被用户第四轮推翻）。
        # 落点仍按**该层自己的锚点**独立复算（left_edge 公式），不是只查持久值。
        exp1x = 0 - dims[1][0] - R.DEFAULT_LAYER_GAP + int(rl[1].get('offset_x', 0))
        check('B05 ★N3 后 ③ 只作用于当前选中层：第 2 层 anchor 保持 left_edge（不被统一），'
              '落点按 left_edge 公式逐位一致',
              rl[1]['anchor'] == 'left_edge' and abs((wx + pos[1][0]) - exp1x) <= 1,
              f"l1.anchor={rl[1]['anchor']} x={wx + pos[1][0]} 期望={exp1x}")
        # 反向：选中第 2 层点 ③「右」→ 只动该层；主层与顶层 side 一个都不许被带偏
        _select(wiz2, 1)
        _radio_widget(wiz2, wiz2.var_side, '右').invoke()
        wiz2.root.update_idletasks()
        check('B06 选中第 2 层点 ③「右」：只动 layers[1]（→right_edge），主层保持 center、顶层 side 不被带偏',
              wiz2.cfg['layers'][1].get('anchor') == 'right_edge'
              and wiz2.cfg['layers'][0].get('anchor') == 'center'   # 主层此前被点成 center
              and wiz2.cfg.get('side') == 'center',
              f"l1={wiz2.cfg['layers'][1].get('anchor')} l0={wiz2.cfg['layers'][0].get('anchor')} "
              f"side={wiz2.cfg.get('side')}")
        # 切层回显（v2.0-N3 改写）：var_layer_anchor = **当前选中层** anchor 的镜像。
        # 旧断言「各层 anchor 一致」是 R11 的统一语义；新事实下各层本就允许不同，判据改为
        # 「镜像 == 当前层持久值」并**逐层各量一次**（两层值不同才算数）—— 镜像脱钩、切层不更新
        # 持久值、或把两层统一成同一个值，都会红。
        _select(wiz2, 0)
        anchors_now = [x.get('anchor') for x in (wiz2.cfg.get('layers') or [])]
        mirror0 = str(wiz2.var_layer_anchor.get())
        _select(wiz2, 1)
        anchors_now2 = [x.get('anchor') for x in (wiz2.cfg.get('layers') or [])]
        mirror1 = str(wiz2.var_layer_anchor.get())
        check('B06b ★切层回显：var_layer_anchor == 当前选中层 anchor 的镜像（主层/第 2 层各量一次，'
              '两层持久值不同才算数）',
              mirror0 == str(anchors_now[0]) and mirror1 == str(anchors_now2[1])
              and anchors_now == anchors_now2 and anchors_now[0] != anchors_now[1],
              f'主层: 镜像={mirror0!r}/持久={anchors_now[0]!r}；'
              f'第2层: 镜像={mirror1!r}/持久={anchors_now2[1]!r}；各层={anchors_now}')
        # B06c 判别力（§6-13 + t11 契约第 5 条）：把写回路径打桩回**旧前提**「一处统一管所有
        # 图层」（R11/R13 语义）→ 上面 B05/B06/B06b 的**同款**判据必须 FAIL。复用同一条表达式，
        # 不是另写一条恒真保护。
        def _anchors():
            return [x.get('anchor') for x in wiz2.cfg['layers']]

        def _only_sel_changed(before, sel, want, expect_side):
            exp = list(before)
            exp[sel] = want
            return _anchors() == exp and wiz2.cfg.get('side') == expect_side

        _real_set = wiz2._layer_set_params

        def _old_unified_set(i, scale=None, offset_x=None, offset_y=None, flip=None, anchor=None):
            r = _real_set(i, scale=scale, offset_x=offset_x, offset_y=offset_y,
                          flip=flip, anchor=anchor)
            if anchor is not None:              # 旧语义：一处统一管所有图层
                for d in wiz2.cfg['layers']:
                    d['anchor'] = wiz2._layer_anchor_at(0)
            return r

        _select(wiz2, 0)
        _before_b06c = _anchors()
        wiz2._layer_set_params = _old_unified_set
        try:
            _radio_widget(wiz2, wiz2.var_side, '左').invoke()
            wiz2.root.update_idletasks()
        finally:
            wiz2._layer_set_params = _real_set
        _bad_b06c = _anchors()
        check('B06c ★判别力：把「只写当前层」打桩回旧前提「一处统一管所有图层」'
              '→ B05/B06 同款判据 _only_sel_changed() 必须 FAIL',
              not _only_sel_changed(_before_b06c, 0, 'left_edge', 'left'),
              f'回退前={_before_b06c} 注入后={_bad_b06c}')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('B02 多图层段未抛异常', False, repr(e))
    finally:
        if wiz2 is not None:
            kill_wiz(wiz2)

    # ---- B07 皮肤档案往返（新档案带 layers）----
    try:
        old = R.SKINS_DIR
        R.SKINS_DIR = skins
        try:
            R.save_skin('indep_r2', {'image': real_img, 'side': 'center', 'scale': 0.6,
                                     'offset_x': -132, 'offset_y': -132,
                                     'layers': [{'image': real_img, 'anchor': 'center', 'z': 0},
                                                {'image': real_gif or real_img,
                                                 'anchor': 'left_edge', 'z': 1}]})
            back = R.find_skin('indep_r2') or {}
            blay = back.get('layers') or []
            check('B07 ★皮肤档案往返：逐层 anchor 还原（主层 center / 次层 left_edge）',
                  len(blay) == 2 and blay[0].get('anchor') == 'center'
                  and blay[1].get('anchor') == 'left_edge',
                  f'{[(x.get("anchor")) for x in blay]}')
            mig = R.migrate_skin_cfg(back)
            check('B07b 迁移后仍是 2 层且主层 offset 归零（顶层权威）',
                  len(mig.get('layers') or []) == 2
                  and int(mig['layers'][0].get('offset_x', 9)) == 0,
                  f"layers={len(mig.get('layers') or [])}")
        finally:
            R.SKINS_DIR = old
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('B07 档案往返段未抛异常', False, repr(e))

    # ---- B08 v1.6 老档案（release 里真实的老 skin.json，无 layers）----
    try:
        old_skin = None
        for d in sorted(os.listdir(os.path.join(BASE, 'release', 'skins'))):
            p = os.path.join(BASE, 'release', 'skins', d, 'skin.json')
            if os.path.exists(p):
                with open(p, encoding='utf-8') as f:
                    j = json.load(f)
                if not j.get('layers'):
                    old_skin = j
                    break
        if old_skin is None:
            check('B08 v1.6 老档案存在可测', False, 'release/skins 里没有无 layers 的老档案')
        else:
            mig = R.migrate_skin_cfg(old_skin)
            lay = mig.get('layers') or []
            check('B08 ★v1.6 老档案（无 layers）迁移后仍单层、anchor 与 side 一致',
                  len(lay) == 1 and lay[0].get('anchor') == R.anchor_from_side(old_skin.get('side')),
                  f"side={old_skin.get('side')} anchor={lay[0].get('anchor') if lay else None}")
    except Exception as e:
        check('B08 老档案段未抛异常', False, repr(e))

    # ---- B09 窗口需求高度：R1 / R2 / HEAD 三点实测 ----
    try:
        hs = {}
        for ref, tag in (('32bc932', 'r1'), ('bc135b0', 'r2')):
            p, info = extract_version(ref, tag, tmp)
            if not p:
                note(f'取不到 {ref} 做高度对照：{info}')
                continue
            M = load_module(p, f'rc_h_{tag}')
            saved2, restore2 = stub_module(M)
            w = None
            try:
                w = make_wiz(M, cfg2, saved2, skins)
                w.root.update_idletasks()
                hs[tag] = int(w.root.winfo_reqheight())
            finally:
                if w is not None:
                    kill_wiz(w)
                restore2()
        # HEAD（当前工作区）
        saved3, restore3 = stub_module(R)
        w = None
        try:
            w = make_wiz(R, cfg2, saved3, skins)
            w.root.update_idletasks()
            hs['head'] = int(w.root.winfo_reqheight())
        finally:
            if w is not None:
                kill_wiz(w)
            restore3()
        note(f'窗口需求高度实测（同一 2 图层 cfg）：R1={hs.get("r1")} R2={hs.get("r2")} '
             f'HEAD={hs.get("head")}（A06 阈值 1038）')
        ok_grow = (hs.get('r1') is not None and hs.get('r2') is not None
                   and hs['r2'] <= hs['r1'] and hs.get('head', 0) <= hs['r1']
                   and hs.get('head', 0) <= 1038)
        check('B09 ★A06 阈值 1038 由实测支撑：R2/HEAD 未比 R1 高，且 HEAD ≤ 1038',
              ok_grow, f'R1={hs.get("r1")} R2={hs.get("r2")} HEAD={hs.get("head")}')
        # 高度瓶颈在哪一栏：右栏（高级设置）才是决定窗口高度的那一栏 → 左栏删一行不影响总高
        saved4, restore4 = stub_module(R)
        w4 = None
        try:
            w4 = make_wiz(R, cfg2, saved4, skins)
            w4.root.update_idletasks()
            # v2.0-R12（容器类型变更）：高级设置外层由 LabelFrame 换成「Frame + 可点标题按钮 +
            # 内容区」——靠 text 查找容器会误命中 26px 的标题按钮（实测把 ha 量成 26）。改为
            # **属性定位**：adv_body = 内容区（展开态高度即「高级设置块」），
            # adv_area.master = 承载「预览/通用区（左）」与「高级设置（右）」两块的 body。
            adv_body = getattr(w4, 'adv_body', None)
            adv_area = getattr(w4, 'adv_area', None)
            left_col = None
            try:
                if adv_area is not None:
                    sibs = [x for x in adv_area.master.winfo_children() if x is not adv_area]
                    if sibs:
                        left_col = max(sibs, key=lambda x: x.winfo_reqheight())
            except Exception:
                pass
            ha = int(adv_body.winfo_reqheight()) if adv_body is not None else -1
            hl = int(left_col.winfo_reqheight()) if left_col is not None else -1
            note(f'两栏各自需求高度：右栏（高级设置）={ha}  左栏={hl}  窗口={hs.get("head")}')
            # R4 后事实：高级设置块被「横排三列」从竖排 901 压到 ~332 → 它**不再是**高度瓶颈
            # （现在是另一块 390 最高，R4 后那一块就是预览块）。R12 起该块还多出可点标题按钮
            # （26px），这里量的是**内容区 adv_body**（展开态）。判别力：
            #   ① 把横排放回竖排（高级设置块重新变高）→ 第一子条件必红；
            #   ② 窗口装不下任一块 → 第二子条件必红；
            #   ③ 窗口退回 R1 基线（R4 的缩窗被撤销）→ 第三子条件必红。
            top_blk = (int(w4.top_block.winfo_reqheight())
                       if getattr(w4, 'top_block', None) is not None else -1)
            tallest = max(hl, ha, top_blk)
            check('B09b ★R4 后高度事实：高级设置块不再是瓶颈（高级设置 < 其余块最高）'
                  ' 且 窗口 ≥ 各块最高',
                  hl > 0 and 0 < ha < hl and top_blk > 0
                  and hs.get('head', 0) >= tallest
                  and (hs.get('r1') is None or hs.get('head', 0) < hs['r1']),
                  f'高级设置块={ha} 其余块最高={hl} 预览块={top_blk} 窗口={hs.get("head")} '
                  f'最高块={tallest}（R1 基线窗口={hs.get("r1")}）')
        finally:
            if w4 is not None:
                kill_wiz(w4)
            restore4()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('B09 高度对照段未抛异常', False, repr(e))
    finally:
        restore()


def _disp_size(path, base_h, scale):
    from PIL import Image as PILImage
    with PILImage.open(path) as im:
        src = im.convert('RGBA')
    bh = base_h * float(scale or 1.0)
    if src.height <= 0:
        return (0, 0)
    r = bh / src.height
    return (max(1, int(src.width * r)), max(1, int(bh)))


def _all_widgets(win, out=None):
    out = [] if out is None else out
    try:
        kids = win.winfo_children()
    except Exception:
        return out
    for w in kids:
        out.append(w)
        _all_widgets(w, out)
    return out


def _radio_texts(wiz, var):
    name = str(var)
    out = []
    for w in _all_widgets(wiz.root):
        try:
            if w.winfo_class() == 'Radiobutton' and str(w.cget('variable')) == name:
                out.append(str(w.cget('text')))
        except Exception:
            pass
    return out


def _radio_widgets(wiz, var):
    """按**变量绑定**找单选按钮（不看文案措辞 / 位置 / 实现者命名）"""
    name = str(var)
    out = []
    for w in _all_widgets(wiz.root):
        try:
            if w.winfo_class() == 'Radiobutton' and str(w.cget('variable')) == name:
                out.append(w)
        except Exception:
            pass
    return out


def _radio_widget(wiz, var, key):
    """绑 var 的单选中「文案含 key」的那个（key 只作粗筛，判据本身不绑文案措辞）"""
    for w in _radio_widgets(wiz, var):
        try:
            if key in str(w.cget('text')):
                return w
        except Exception:
            pass
    return None


def _find_widget(wiz, cls=None, text_contains=None):
    for w in _all_widgets(wiz.root):
        try:
            if cls is not None and w.winfo_class() != cls:
                continue
            if text_contains is not None and text_contains not in str(w.cget('text')):
                continue
            return w
        except Exception:
            continue
    return None


def _select(wiz, i):
    wiz.layer_list.selection_clear(0, 'end')
    wiz.layer_list.selection_set(i)
    wiz._on_layer_select()


# ==========================================================================
# C 段 · R3 慢半拍 + 错位（同 harness 前→后对照）
# ==========================================================================
import ctypes                                     # noqa: E402
import ctypes.wintypes as wintypes                # noqa: E402

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('style', wintypes.UINT),
                ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', wintypes.HINSTANCE),
                ('hIcon', wintypes.HICON), ('hCursor', wintypes.HANDLE),
                ('hbrBackground', wintypes.HBRUSH), ('lpszMenuName', wintypes.LPCWSTR),
                ('lpszClassName', wintypes.LPCWSTR), ('hIconSm', wintypes.HICON)]


class FakeCandidate:
    """类名 ATL: 前缀的假候选框（与既有 harness 同款式，真实可见顶层窗口）。"""

    def __init__(self, M, cls='ATL:IndepCand', x=60, y=120, w=400, h=72):
        U = M.user32
        K = M.kernel32
        self.U = U
        U.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                     wintypes.LPARAM]
        U.DefWindowProcW.restype = ctypes.c_longlong
        K.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        K.GetModuleHandleW.restype = wintypes.HMODULE
        self.proc = WNDPROC(lambda h, m, wp, lp: U.DefWindowProcW(h, m, wp, lp))
        cls_w = WNDCLASSEXW()
        cls_w.cbSize = ctypes.sizeof(WNDCLASSEXW)
        cls_w.lpfnWndProc = self.proc
        cls_w.hInstance = K.GetModuleHandleW(None)
        cls_w.lpszClassName = cls
        U.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        U.RegisterClassExW.restype = wintypes.ATOM
        U.RegisterClassExW(ctypes.byref(cls_w))
        U.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                      wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                      wintypes.HINSTANCE, wintypes.LPVOID]
        U.CreateWindowExW.restype = wintypes.HWND
        self.cls_w = cls_w
        self.hwnd = U.CreateWindowExW(0x80 | 0x08000000, cls, 'mock',
                                      0x80000000 | 0x10000000, x, y, w, h, 0, 0,
                                      cls_w.hInstance, None)
        if not self.hwnd:
            raise RuntimeError('CreateWindowExW failed')

    def set_rect(self, x, y, w, h):
        self.U.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.U.SetWindowPos(self.hwnd, 0, int(x), int(y), int(w), int(h), 0x0010)

    def rect(self):
        r = wintypes.RECT()
        self.U.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.U.GetWindowRect(self.hwnd, ctypes.byref(r))
        return (int(r.left), int(r.top), int(r.right), int(r.bottom))

    def destroy(self):
        try:
            self.U.DestroyWindow(self.hwnd)
        except Exception:
            pass


class OpenCounter:
    """给 PIL.Image.open 计数（测「定位路径每帧做几次文件 I/O」）。"""

    def __init__(self):
        self.n = 0
        self._orig = None

    def __enter__(self):
        from PIL import Image as PILImage
        self._orig = PILImage.open

        def wrapper(*a, **k):
            self.n += 1
            return self._orig(*a, **k)

        PILImage.open = wrapper
        return self

    def __exit__(self, *exc):
        from PIL import Image as PILImage
        PILImage.open = self._orig
        return False


def _make_overlay(M, cfg):
    ov = M.FollowOverlay(cfg)
    try:
        ov.tray.stop()
    except Exception:
        pass
    return ov


def _kill_overlay(M, ov):
    try:
        ov._anim_on = False
    except Exception:
        pass
    # 先取消所有挂着的 after 回调（手工调 _anim_tick/_event_tick 会不断续排，
    # root 销毁后这些回调会在 Tcl 里报 invalid command name → 干扰退出码判定）
    try:
        for aid in str(ov.root.tk.call('after', 'info')).split():
            try:
                ov.root.after_cancel(aid)
            except Exception:
                pass
    except Exception:
        pass
    try:
        ov.root.withdraw()
        ov.root.destroy()
    except Exception:
        pass
    try:
        M._release_event_thread()
    except Exception:
        pass


def _win_size(M, ov):
    top = ov._top_hwnd()
    r = wintypes.RECT()
    M.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    M.user32.GetWindowRect(top, ctypes.byref(r))
    return (int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top))


def _r3_cfg(tmp, real_img, n_layer=3):
    cfg = dict(R.DEFAULT_CONFIG)
    cfg.update({'image': real_img, 'layout': 'horizontal_double', 'side': 'right',
                'layer': 'above', 'scale': 2.0, 'offset_x': 0, 'offset_y': 0,
                'base_height': 300, 'render_mode': 'compat'})
    anchors = ['right_edge', 'left_edge', 'right_edge', 'left_edge', 'right_edge', 'left_edge']
    cfg['layers'] = [{'image': real_img, 'anchor': anchors[i], 'z': i, 'scale': 2.0}
                     for i in range(n_layer)]
    return cfg


def _drive(M, ov, fake, frames, step=6, widen_at=None, widen_px=40, on_dims=None):
    """走真实事件链路：移动假候选框 → 注入 MOVE 事件 → _event_tick。
    widen_at: 在第 N 帧先把候选框加宽 (模拟打字变宽)；on_dims: 一帧内的注入钩子。"""
    lat = []
    opens = []
    for i in range(frames):
        r = fake.rect()
        fake.set_rect(r[0] + step, r[1], r[2] - r[0], r[3] - r[1])
        if widen_at is not None and i == widen_at:
            rr = fake.rect()
            fake.set_rect(rr[0], rr[1], (rr[2] - rr[0]) + widen_px, rr[3] - rr[1])
        M._EVT_MOVE_CNT += 1
        M._EVT_MOVE_TS = time.monotonic()
        M._EVT_CACHE_HWND = fake.hwnd
        with OpenCounter() as oc:
            t0 = time.perf_counter()
            ov._event_tick()
            dt = (time.perf_counter() - t0) * 1000.0
        lat.append(dt)
        opens.append(oc.n)
    return lat, opens


def section_C(tmp):
    section('C 段 · R3 多图层跟随：每帧文件 I/O / 单帧耗时 / 一帧内变宽的错位（前→后对照）')
    real_img = load_factory_raw()['image']

    # ---- C05 单层不回归（先测，快）----
    try:
        cfg1 = dict(R.DEFAULT_CONFIG)
        cfg1.update({'image': real_img, 'layout': 'horizontal_double', 'side': 'right',
                     'scale': 0.6, 'offset_x': -132, 'offset_y': -132, 'base_height': 300,
                     'render_mode': 'compat'})
        ov = _make_overlay(R, cfg1)
        fake = FakeCandidate(R, 'ATL:IndepCand1', 200, 200, 400, 72)
        try:
            ov._cached_hwnd = fake.hwnd
            R.set_candidate_hwnd(fake.hwnd)
            x, y, w, h, sc = ov._plan_targets(fake.rect())
            check('C05 单层路径不回归：_plan_targets 仍返回 w/h=None 且 size_changed=False',
                  w is None and h is None and sc is False, f'({x},{y},{w},{h},{sc})')
            r0 = _win_size(R, ov)
            ov.root.deiconify()
            ov.root.update()
            ov.visible = True
            r0 = _win_size(R, ov)
            ov._position_once()
            ov._position_once()
            r1 = _win_size(R, ov)
            check('C05b 单层窗口尺寸不变（走 SWP_NOSIZE 老行为）',
                  r1[2] == r0[2] and r1[3] == r0[3] and r0[2] > 1,
                  f'{r0[2]}x{r0[3]} → {r1[2]}x{r1[3]}')
        finally:
            fake.destroy()
            _kill_overlay(R, ov)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('C05 单层段未抛异常', False, repr(e))

    # ---- C01/C02/C03/C04：同一 harness 跑「R3 前」「HEAD」两版 ----
    results = {}
    for ref, tag in (('bc135b0', 'pre_r3'), ('HEAD', 'head')):
        try:
            if ref == 'HEAD':
                M = R
            else:
                p, info = extract_version(ref, 'pre_r3', tmp)
                if not p:
                    check(f'C00 取到 {ref} 模块', False, str(info))
                    continue
                M = load_module(p, 'rc_pre_r3')
            cfg = _r3_cfg(tmp, real_img, 3)
            ov = _make_overlay(M, cfg)
            fake = FakeCandidate(M, f'ATL:IndepCand_{tag.replace("_", "")}', 60, 120, 400, 72)
            res = {}
            try:
                ov._cached_hwnd = fake.hwnd
                M.set_candidate_hwnd(fake.hwnd)
                ov._last_scan_ts = 0.0
                ov._position_once()                      # 首贴（冷解码一轮）
                lat, opens = _drive(M, ov, fake, frames=10)     # 稳态 10 帧（纯平移）
                res['steady_lat'] = lat
                res['steady_opens'] = opens
                res['steady_p50'] = statistics.median(lat)
                res['cold'] = lat[0]
                # 变宽帧：候选框加宽 40 → 画布跟着换 + 重合成
                ws, os_ = _drive(M, ov, fake, frames=2, widen_at=0, widen_px=40)
                res['widen_lat'] = ws
                res['widen_opens'] = os_
                wr = _win_size(M, ov)
                cv = tuple(getattr(ov, '_canvas_size', None) or (0, 0))
                bmp = (int(getattr(ov, 'img').width()), int(getattr(ov, 'img').height()))
                res['win'] = wr
                res['canvas'] = cv
                res['bmp'] = bmp
                res['layers'] = len(M.resolve_layers(ov.cfg))
                res['dims'] = ov._layer_dims()
            finally:
                fake.destroy()
                _kill_overlay(M, ov)
            results[tag] = res
            if ref != 'HEAD':
                del M
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'C00 {tag} 段未抛异常', False, repr(e))

    if 'head' in results and 'pre_r3' in results:
        a, b = results['pre_r3'], results['head']
        note(f'稳态（纯平移 10 帧，3 层各约 {b["dims"][0][0]}x{b["dims"][0][1]}）：'
             f'改前 Image.open/帧={statistics.mean(a["steady_opens"]):.2f} '
             f'p50={a["steady_p50"]:.2f}ms | 改后={statistics.mean(b["steady_opens"]):.2f} '
             f'p50={b["steady_p50"]:.2f}ms')
        check('C01 ★稳态每帧不再逐层做文件 I/O（Image.open/帧 → 0）',
              statistics.mean(a['steady_opens']) >= 2.5
              and statistics.mean(b['steady_opens']) == 0,
              f'改前 {statistics.mean(a["steady_opens"]):.2f} → 改后 {statistics.mean(b["steady_opens"]):.2f}')
        check('C02 ★稳态单帧耗时大幅下降（≥5×，且 < 8ms）',
              b['steady_p50'] * 5 <= a['steady_p50'] and b['steady_p50'] < 8.0,
              f'改前 p50={a["steady_p50"]:.2f}ms → 改后 {b["steady_p50"]:.2f}ms')
        check('C03 变宽帧：窗口尺寸 = 显示位图尺寸（两侧图层拉开时不留半帧）',
              b['bmp'] == tuple(b['canvas']) and b['canvas'] == b['win'][2:],
              f'改前 win={a["win"][2:]} 位图={a["bmp"]}；改后 win={b["win"][2:]} 位图={b["bmp"]}')
        note(f'（对照）变宽帧同一 harness：改前 win={a["win"][2:]} 位图={a["bmp"]}；'
             f'改后 win={b["win"][2:]} 位图={b["bmp"]}')
    else:
        check('C01~C03 R3 前→后对照完整跑完', False, f'results={list(results)}')

    # ---- C04 注入式复现：一帧内两次读 rect 之间的错位（同 harness 前→后） ----
    injected = {}
    for ref, tag in (('bc135b0', 'pre_r3'), ('HEAD', 'head')):
        try:
            if ref == 'HEAD':
                M = R
            else:
                p, _info = extract_version(ref, 'pre_r3b', tmp)
                M = load_module(p, 'rc_pre_r3b') if p else None
                if M is None:
                    continue
            cfg = _r3_cfg(tmp, real_img, 3)
            ov = _make_overlay(M, cfg)
            fake = FakeCandidate(M, f'ATL:IndepInj_{tag}', 60, 200, 400, 72)
            got = {}
            try:
                ov._cached_hwnd = fake.hwnd
                M.set_candidate_hwnd(fake.hwnd)
                ov._last_scan_ts = 0.0
                ov._position_once()
                # 稳态两帧（纯平移）
                for _ in range(2):
                    rr = fake.rect()
                    fake.set_rect(rr[0] + 5, rr[1], rr[2] - rr[0], rr[3] - rr[1])
                    M._EVT_MOVE_CNT += 1
                    M._EVT_MOVE_TS = time.monotonic()
                    M._EVT_CACHE_HWND = fake.hwnd
                    ov._event_tick()
                # 注入帧：先变宽 60（plan 用这个 rect），再在解析尺寸期间又变宽 40
                rr = fake.rect()
                rect_a = (rr[0], rr[1], rr[0] + 460, rr[3])
                fake.set_rect(rr[0], rr[1], 460, rr[3] - rr[1])
                orig_dims = ov._layer_dims

                def hooked(Image=None, layers=None, _o=orig_dims, _f=fake, _rr=rr):
                    out = _o(Image, layers)
                    _f.set_rect(_rr[0], _rr[1], 500, _rr[3] - _rr[1])   # 解码期间候选框又变宽
                    return out

                ov._layer_dims = hooked
                M._EVT_MOVE_CNT += 1
                M._EVT_MOVE_TS = time.monotonic()
                M._EVT_CACHE_HWND = fake.hwnd
                ov._event_tick()
                ov._layer_dims = orig_dims
                wr = _win_size(M, ov)
                bmp = (int(ov.img.width()), int(ov.img.height()))
                dims = ov._layer_dims()
                plan_a = M.plan_layer_layout(M.resolve_layers(ov.cfg), dims, rect_a)
                got = {'win_w': wr[2], 'win_h': wr[3], 'bmp': bmp,
                       'misalign': abs(bmp[0] - wr[2]),
                       'plan_a': tuple(int(v) for v in plan_a[:4]),
                       'win_xy': wr[:2]}
            finally:
                fake.destroy()
                _kill_overlay(M, ov)
            injected[tag] = got
            if ref != 'HEAD':
                del M
        except Exception as e:
            import traceback
            traceback.print_exc()
            note(f'注入对照 {tag} 异常: {e!r}')

    if 'head' in injected and 'pre_r3' in injected:
        i0, i1 = injected['pre_r3'], injected['head']
        note(f'注入对照（一帧内候选框再变宽 40px）：改前 窗口宽 {i0["win_w"]} / 位图宽 '
             f'{i0["bmp"][0]} → 错位 {i0["misalign"]}px；改后 窗口宽 {i1["win_w"]} / '
             f'位图宽 {i1["bmp"][0]} → 错位 {i1["misalign"]}px')
        check('C04 ★注入式复现：改前错位（窗口与画面不是同一矩形）→ 改后一致',
              i0['misalign'] >= 20 and i1['misalign'] == 0,
              f'改前 {i0["misalign"]}px → 改后 {i1["misalign"]}px')
        check('C04b ★改后这一帧「窗口位置/尺寸 = 该帧矩形算出的计划」逐位一致（不偏位）',
              (i1['win_xy'][0], i1['win_xy'][1], i1['win_h']) == (i1['plan_a'][0], i1['plan_a'][1],
                                                                 i1['plan_a'][3])
              and i1['win_w'] == i1['plan_a'][2],
              f'窗口=({i1["win_xy"][0]},{i1["win_xy"][1]},{i1["win_w"]},{i1["win_h"]}) '
              f'计划={i1["plan_a"]}')
    else:
        check('C04 注入式前→后对照跑完', False, f'{list(injected)}')


# ==========================================================================
# D 段 · 反例（边界 / 切换 / 往返 / 极端输入）
# ==========================================================================
def section_D(tmp):
    section('D 段 · 反例与边界尝试')
    real_img = load_factory_raw()['image']
    saved, restore = stub_module(R)
    skins = os.path.join(tmp, 'skins_D')
    os.makedirs(skins, exist_ok=True)

    # ---- D01 单层 ↔ 多图层切换 ----
    ov = None
    fake = None
    try:
        cfg = dict(R.DEFAULT_CONFIG)
        cfg.update({'image': real_img, 'layout': 'horizontal_double', 'side': 'right',
                    'scale': 0.6, 'offset_x': -132, 'offset_y': -132, 'base_height': 300,
                    'render_mode': 'compat'})
        ov = _make_overlay(R, cfg)
        fake = FakeCandidate(R, 'ATL:IndepD1', 100, 260, 400, 72)
        ov._cached_hwnd = fake.hwnd
        R.set_candidate_hwnd(fake.hwnd)
        seq = []
        for step_layers in (1, 2, 1, 3, 1):
            lay = [{'image': real_img, 'anchor': 'right_edge' if i % 2 == 0 else 'left_edge',
                    'z': i, 'scale': 0.6} for i in range(step_layers)]
            ov.cfg = dict(cfg)
            if step_layers > 1:
                ov.cfg['layers'] = lay
            ov.load_char()
            ov._position_once()
            wr = _win_size(R, ov)
            bmp = (int(ov.img.width()), int(ov.img.height()))
            seq.append((step_layers, ov._layers_active(), wr[2:], bmp,
                        len(getattr(ov, '_dims_cache', {}))))
        same = all((s[3] == s[2]) for s in seq if s[1])
        ok = all((s[1] is (s[0] > 1)) for s in seq)
        check('D01 ★单↔多图层来回切换：层数判定正确、多图层时窗口尺寸=位图尺寸、不抛异常',
              ok and same, f'序列(层数,active,窗口,位图,缓存条数)={seq}')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D01 单↔多图层段未抛异常', False, repr(e))
    finally:
        if fake is not None:
            fake.destroy()
        if ov is not None:
            _kill_overlay(R, ov)

    # ---- D02 动图 ↔ 静态：同路径换内容必须使尺寸缓存失效 ----
    try:
        gif = make_gif(os.path.join(tmp, 'D_anim.gif'), (240, 320), 8)
        png_path = os.path.join(tmp, 'D_swap.png')
        make_png(png_path, (240, 500), (30, 120, 200, 255))     # 尺寸不同：500 高
        cfg = dict(R.DEFAULT_CONFIG)
        cfg.update({'image': gif, 'layout': 'horizontal_double', 'side': 'right',
                    'scale': 1.0, 'offset_x': 0, 'offset_y': 0, 'base_height': 300,
                    'render_mode': 'compat'})
        cfg['layers'] = [{'image': gif, 'anchor': 'right_edge', 'z': 0},
                         {'image': png_path, 'anchor': 'left_edge', 'z': 1}]
        ov = _make_overlay(R, cfg)
        fake = FakeCandidate(R, 'ATL:IndepD2', 80, 300, 420, 72)
        try:
            ov._cached_hwnd = fake.hwnd
            R.set_candidate_hwnd(fake.hwnd)
            ov._position_once()
            anim_ok = True
            for _ in range(6):
                ov.visible = True
                ov._anim_tick()
                wr = _win_size(R, ov)
                if (int(ov.img.width()), int(ov.img.height())) != wr[2:]:
                    anim_ok = False
            check('D02 ★动图播放节拍下窗口尺寸始终 = 画面尺寸（换帧不脱钩）',
                  ov.anim_n > 1 and anim_ok, f'anim_n={ov.anim_n}')
            d0 = ov._layer_dims()
            shutil.copyfile(png_path, gif)          # 同路径换内容（GIF → 静态、尺寸也变）
            ov.load_char()
            ov._position_once()
            d1 = ov._layer_dims()
            wr = _win_size(R, ov)
            check('D02b ★同路径换内容 → 尺寸缓存失效、窗口重新贴合',
                  d0[0] != d1[0] or d0[0][1] != d1[0][1],
                  f'{d0[0]} → {d1[0]}')
            check('D02c 换图后窗口尺寸 = 画面尺寸',
                  (int(ov.img.width()), int(ov.img.height())) == wr[2:],
                  f'窗口 {wr[2:]} 画面 {(int(ov.img.width()), int(ov.img.height()))}')
        finally:
            fake.destroy()
            _kill_overlay(R, ov)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D02 动图↔静态段未抛异常', False, repr(e))

    # ---- D03 开关快速连续切换（两个入口交替）----
    try:
        cfg = dict(R.DEFAULT_CONFIG)
        cfg.update(load_factory_raw())
        cfg['image'] = make_png(os.path.join(tmp, 'D_sw.png'), (200, 260), (180, 60, 60, 255))
        cfg['corner_enabled'] = False
        cfg['feather_enabled'] = False
        cfg['feather_radius'] = 24
        wiz = make_wiz(R, cfg, saved, skins)
        try:
            wiz.var_render.set('compat')
            wiz._update_render_hint()
            wiz.var_feather.set(False)       # 兼容档用户原勾选 = 关
            bad = []
            for i in range(20):
                wiz.var_alpha_feather.set(True)
                wiz._on_alpha_feather_toggle()
                if not (wiz.var_render.get() == 'alpha' and wiz.var_feather.get() is True
                        and str(wiz.chk_feather.cget('state')) == 'disabled'):
                    bad.append(f'#{i} 开')
                wiz.var_render.set('compat')
                wiz._update_render_hint()
                if not (wiz.var_alpha_feather.get() is False
                        and wiz.var_feather.get() is False
                        and str(wiz.chk_feather.cget('state')) == 'normal'):
                    bad.append(f'#{i} 关')
            check('D03 ★两入口快速连切 20 轮：状态始终一致、用户原勾选被正确恢复',
                  not bad and wiz._feather_prev is None,
                  f'异常={bad or "无"} _feather_prev={wiz._feather_prev}')
            saved.clear()
            wiz._save_and_start()
            check('D03b 连切后保存：render_mode=compat（终态）与 UI 一致',
                  saved.get('render_mode') == 'compat',
                  f"render_mode={saved.get('render_mode')}")
        finally:
            kill_wiz(wiz)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D03 快速连切段未抛异常', False, repr(e))

    # ---- D04 皮肤档案往返（新档案带 layers + v1.6 老档案）经过向导下拉框 ----
    try:
        old = R.SKINS_DIR
        R.SKINS_DIR = skins
        real_gif = (sorted(__import__('glob').glob(
            os.path.join(BASE, 'release', 'skins', '*', 'image.gif'))) or [real_img])[0]
        try:
            R.save_skin('D_new', {'image': real_img, 'side': 'left', 'scale': 0.6,
                                  'offset_x': -132, 'offset_y': -132,
                                  'feather_enabled': False,
                                  'layers': [{'image': real_img, 'anchor': 'left_edge', 'z': 0},
                                             {'image': real_gif, 'anchor': 'right_edge', 'z': 1}]})
            R.save_skin('D_old', {'image': real_img, 'side': 'right', 'scale': 0.6,
                                  'offset_x': -132, 'offset_y': -132,
                                  'feather_enabled': False})
            cfg = dict(R.DEFAULT_CONFIG)
            cfg.update(load_factory_raw())
            wiz = make_wiz(R, cfg, saved, skins)
            try:
                wiz.skin_var.set('D_new')
                wiz._apply_skin_to_wizard()
                a1 = (wiz.var_side.get(), wiz.var_layer_anchor.get(),
                      [x.get('anchor') for x in (wiz.cfg.get('layers') or [])])
                wiz.skin_var.set('D_old')
                wiz._apply_skin_to_wizard()
                a2 = (wiz.var_side.get(), wiz.var_layer_anchor.get(),
                      len(wiz.cfg.get('layers') or []))
                wiz.skin_var.set('D_new')
                wiz._apply_skin_to_wizard()
                a3 = (wiz.var_side.get(), wiz.var_layer_anchor.get(),
                      [x.get('anchor') for x in (wiz.cfg.get('layers') or [])])
                # v2.0-N3（前提被需求推翻）：切皮肤**不再**把各层 anchor 统一到档案顶层 side，
                # 各层保留新档案自己的 anchor（用户要的就是「每张图各自贴边」）—— 只有第 0 层
                # （主层）由顶层 side 保底归一。旧断言固化的「统一成 ['left_edge','left_edge']」
                # 是 R11 语义，已被推翻；新断言改为**各层保持档案值 + 往返逐位一致**（强度不降：
                # 往返一致性、老档案 1 层、顶层 side 都照旧钉住；另加「第 2 层不许被统一」）。
                check('D04 ★皮肤下拉框往返（新档案 2 层 ↔ v1.6 老档案 1 层）：各层保持档案里'
                      '各自的 anchor（[left_edge, right_edge] 不被统一）、往返逐位一致',
                      a1 == ('left', 'left_edge', ['left_edge', 'right_edge'])
                      and a2[0] == 'right' and a2[2] == 1 and a3 == a1,
                      f'new={a1} old={a2} new2={a3}')
                # D04b 判别力（§6-13 + t11 契约第 5 条）：把切皮肤的两个「保底归一」入口打桩回
                # **旧前提**「一处统一管所有图层」（R11/R13 语义：读 Tk 变量推全层）→ 上面 D04 的
                # **同款**判据必须 FAIL。
                _real_side, _real_flip = (wiz._sync_side_to_all_layers,
                                          wiz._sync_flip_to_all_layers)

                def _old_sync_side(force=False):
                    for d in wiz.cfg.get('layers') or []:
                        d['anchor'] = R.anchor_from_side(str(wiz.var_side.get()))
                    return True

                def _old_sync_flip(force=False):
                    for d in wiz.cfg.get('layers') or []:
                        d['flip'] = bool(wiz.var_flip.get())
                    return True

                wiz._sync_side_to_all_layers = _old_sync_side
                wiz._sync_flip_to_all_layers = _old_sync_flip
                try:
                    wiz.skin_var.set('D_new')
                    wiz._apply_skin_to_wizard()
                finally:
                    wiz._sync_side_to_all_layers = _real_side
                    wiz._sync_flip_to_all_layers = _real_flip
                a_bad_d04 = (wiz.var_side.get(), wiz.var_layer_anchor.get(),
                             [x.get('anchor') for x in (wiz.cfg.get('layers') or [])])
                check('D04b ★判别力：把切皮肤打桩回旧前提「一处统一管所有图层」→ D04 同款判据必须 FAIL',
                      a_bad_d04 != ('left', 'left_edge', ['left_edge', 'right_edge']),
                      f'注入后={a_bad_d04}')
            finally:
                kill_wiz(wiz)
        finally:
            R.SKINS_DIR = old
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D04 皮肤往返段未抛异常', False, repr(e))

    # ---- D05 极端输入：6 层 / 缺图 / 零尺寸 ----
    ov = None
    try:
        cfg = dict(R.DEFAULT_CONFIG)
        cfg.update({'image': real_img, 'layout': 'horizontal_double', 'side': 'right',
                    'scale': 0.6, 'offset_x': 0, 'offset_y': 0, 'base_height': 300,
                    'render_mode': 'compat'})
        miss = os.path.join(tmp, 'D_missing.png')
        cfg['layers'] = ([{'image': real_img, 'anchor': 'right_edge', 'z': i} for i in range(6)]
                         + [{'image': miss, 'anchor': 'left_edge', 'z': 9}])
        rl = R.resolve_layers(cfg)
        check('D05 极端输入：层数按 MAX_LAYERS 截断、缺图不参与布局',
              len(rl) == R.MAX_LAYERS,
              f'resolve_layers={len(rl)} 上限={R.MAX_LAYERS}')
        ov = _make_overlay(R, cfg)
        fake = FakeCandidate(R, 'ATL:IndepD5', 120, 380, 380, 72)
        try:
            ov._cached_hwnd = fake.hwnd
            R.set_candidate_hwnd(fake.hwnd)
            d = ov._layer_dims()
            check('D05b 6 层尺寸能量出来（不抛异常、无零尺寸）',
                  len(d) == R.MAX_LAYERS and all(w > 0 and h > 0 for (w, h) in d),
                  f'dims={d}')
            z = R.plan_layer_layout([{'image': miss, 'anchor': 'right_edge'}], [(0, 0)],
                                    (0, 0, 460, 84))
            check('D05c 全零尺寸层 → plan 返回 0 尺寸（调用方必须保持窗口现状，不许 SetWindowPos 0）',
                  z[2] == 0 and z[3] == 0, f'plan={z[:4]}')
            cfgz = dict(cfg)
            cfgz['layers'] = [{'image': miss, 'anchor': 'right_edge', 'z': 0},
                              {'image': miss, 'anchor': 'left_edge', 'z': 1}]
            ov.cfg = cfgz
            ov.load_char()
            x, y, w, h, sc = ov._plan_targets(fake.rect())
            check('D05d 所有层都缺图 → w/h=None、size_changed=False（窗口不会被缩成 0）',
                  w is None and h is None and sc is False, f'({x},{y},{w},{h},{sc})')
            chk = fake.rect()
            ov._position_once()
            wr = _win_size(R, ov)
            check('D05e 缺图状态下窗口仍在（非 0 尺寸）',
                  wr[2] > 0 and wr[3] > 0, f'窗口 {wr[2]}x{wr[3]} rect={chk}')
        finally:
            fake.destroy()
            _kill_overlay(R, ov)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D05 极端输入段未抛异常', False, repr(e))
    finally:
        restore()


# ==========================================================================
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--sections', default='A,B,C,D')
    a = ap.parse_args()
    print('=' * 100)
    print('B_test_indep_batch1 —— 批次一（R1/R2/R3）独立验证（verifier 自建，不复用实现者测试）')
    print('=' * 100)
    gui = _has_gui()
    try:
        from PIL import Image  # noqa: F401
        pil = True
    except Exception:
        pil = False
    print(f'环境：Python {sys.version.split()[0]} | GUI={gui} | PIL={pil} | BASE={BASE}')
    if not gui or not pil:
        print('RESULT: FAIL（GUI/PIL 不可用 → 独立验证无法成立，禁止静默跳过）')
        return 1

    tmp = tempfile.mkdtemp(prefix='indep_batch1_')
    # 只读约束（HANDOFF-2.1 §8.5 · t11 契约第 7 条同款）：日志/临时产物只落临时目录，
    # 不再给项目 error.log 增行（实测：补前单跑 +1616 B / batch3 的 J 段子进程 +940 B）。
    R.HERE = tmp
    want = {s.strip().upper() for s in a.sections.split(',') if s.strip()}
    try:
        if 'A' in want:
            section_A(tmp)
        if 'B' in want:
            section_B(tmp)
        if 'C' in want:
            section_C(tmp)
        if 'D' in want:
            section_D(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('\n' + '=' * 100)
    print(f'通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项 / 跳过 {len(SKIP)} 项')
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
