# -*- coding: utf-8 -*-
"""B_test_r1_feather.py —— v2.0-R1 「增强羽化」验证

对照用户实测反馈（HANDOFF-2.0 §3 R1）：
  · 「渲染增强没看见对应的预览」→ 向导预览是 Tk Canvas（不支持逐像素 alpha），
    以前直接把 RGBA 丢给 PhotoImage，alpha 被丢掉 → 兼容/增强预览长得一样。
    验收：B/C/E/I 段 —— 预览先垫棋盘格背景再把 RGBA 合成上去（对齐
    ImagePreprocessDialog._draw_checker 的做法），兼容 = 硬边、增强 = 颜色到棋盘格的平滑过渡。
  · 「我想的是放后面的开关」→ 真 alpha 以前只做在 ⑪「渲染模式」单选里。
    验收：F/G/H 段 —— ⑩ 点阵羽化 旁新增「增强（真羽化）」开关，与 ⑪ 双向联动，
    点阵勾选在增强模式下置灰 + 明确提示「点阵羽化 = 兼容模式下的近似」，切换即时重绘。

红绿纪律：本脚本先跑出红（缺 compose_on_checker / true_alpha / 新开关 → FAIL），再改实现到绿。

红线：只读被测模块；不写真实 config.json / skin.json（save_config 打桩）；
      文件对话框与模态框全部打桩。

用法: python B_test_r1_feather.py
"""
import os
import sys
import shutil
import tempfile

# 控制台编码保护：GBK 控制台下打印 ⑩/⑪/★ 等字符会 UnicodeEncodeError 并让脚本 exit≠0
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R          # noqa: E402

try:
    from PIL import Image
    PIL_OK = True
except Exception:
    Image = None
    PIL_OK = False

PASS, FAIL, SKIPPED = [], [], []


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f'  [PASS] {name}' + (f'  ({detail})' if detail else ''))
    else:
        FAIL.append(name)
        print(f'  [FAIL] {name}' + (f'  ({detail})' if detail else ''))


def skip(name, why=''):
    SKIPPED.append(name)
    print(f'  [SKIP] {name}' + (f'  ({why})' if why else ''))


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


def _grad_img(w=64, h=64, color=(200, 40, 40)):
    """水平 alpha 线性渐变（0 → 255）的 RGBA 测试图（验「真 alpha 保留 vs 二值化」）"""
    im = Image.new('RGBA', (w, h), color + (255,))
    px = im.load()
    den = max(1, w - 1)
    for y in range(h):
        for x in range(w):
            px[x, y] = color + (int(255 * x / den),)
    return im


def _solid_img(w=300, h=240, color=(200, 40, 40)):
    """完全不透明的 RGBA 测试图（= 用户真实图片的常态）。

    羽化半径 24 在 300×240 上属于「带窄于图」的正常比例 —— 64×64 小图上
    band 会顶到 min(w,h)//2，高斯糊平后整幅图退化成全透明，测不出差别。
    """
    return Image.new('RGBA', (w, h), color + (255,))


def _half_clear(w=40, h=40, color=(255, 0, 0, 255)):
    """左半不透明、右半完全透明的 RGBA 图（验棋盘格垫底）"""
    im = Image.new('RGBA', (w, h), color)
    for y in range(h):
        for x in range(w // 2, w):
            im.putpixel((x, y), color[:3] + (0,))
    return im


def _colors(im):
    try:
        return {c for _n, c in (im.convert('RGB').getcolors(maxcolors=1 << 24) or [])}
    except Exception:
        return set()


def _make_png(path, size=(120, 180), color=(220, 60, 60, 255)):
    im = Image.new('RGBA', size, (0, 0, 0, 0))
    w, h = size
    for y in range(int(h * 0.2), int(h * 0.8)):
        for x in range(int(w * 0.15), int(w * 0.85)):
            im.putpixel((x, y), color)
    im.save(path)
    return path


# ==========================================================================
# A. 接口清单（红阶段先列缺口）
# ==========================================================================
def test_api_surface():
    section('A. 接口清单：R1 本次要新增的符号')
    check('A01 模块级棋盘格底图符号存在（checker_background）',
          hasattr(R, 'checker_background'))
    check('A02 模块级 RGBA→棋盘格合成符号存在（compose_on_checker）',
          hasattr(R, 'compose_on_checker'))
    for s in ('_on_alpha_feather_toggle', '_sync_feather_widgets', '_checker_compose',
              '_preview_render_mode_img', '_is_alpha_mode'):
        check(f'A03 ConfigWizard.{s} 存在', hasattr(R.ConfigWizard, s))


# ==========================================================================
# B. 棋盘格背景 + RGBA 合成
# ==========================================================================
def test_checker():
    section('B. 棋盘格背景 + RGBA 合成（Tk 不支持逐像素 alpha → 先合成再显示）')
    ck = getattr(R, 'checker_background', None)
    cp = getattr(R, 'compose_on_checker', None)
    if ck is None or cp is None:
        check('B01 棋盘格底色只有两种且相邻格不同', False, 'checker_background 未实现')
        check('B02 合成图尺寸与输入一致', False, 'compose_on_checker 未实现')
        check('B03 不透明区保留图片颜色', False, 'compose_on_checker 未实现')
        check('B04 全透明区露出棋盘格', False, 'compose_on_checker 未实现')
        return
    bg = ck((40, 40), cell=8)
    cols = _colors(bg)
    check('B01 棋盘格底色只有两种且相邻格不同',
          len(cols) == 2 and bg.getpixel((2, 2)) != bg.getpixel((10, 2)),
          f'{len(cols)} 色')
    src = _half_clear()
    comp = cp(src, cell=8)
    check('B02 合成图尺寸与输入一致', comp.size == src.size, str(comp.size))
    check('B03 不透明区保留图片颜色（红）',
          comp.getpixel((5, 5)) == (255, 0, 0), str(comp.getpixel((5, 5))))
    check('B04 全透明区露出棋盘格（不是黑块/原色块）',
          comp.getpixel((30, 5)) in cols and comp.getpixel((38, 5)) in cols,
          str(comp.getpixel((30, 5))))


# ==========================================================================
# C. 真羽化（增强）vs 点阵羽化（兼容近似）
# ==========================================================================
def test_true_feather():
    section('C. 真羽化（增强）vs 点阵羽化（兼容模式的近似）')
    if not PIL_OK:
        skip('C', 'PIL 不可用')
        return
    src = _solid_img()
    base = {'feather_enabled': True, 'feather_radius': 24}
    dither = R.apply_display_effects(src, dict(base), Image)
    soft = R.apply_display_effects(src, dict(base, true_alpha=True), Image)
    a_d = [dither.getpixel((x, 120))[3] for x in range(300)]
    a_s = [soft.getpixel((x, 120))[3] for x in range(300)]
    mid_s = [a for a in a_s if 0 < a < 255]
    check('C01 兼容/点阵：带内 alpha 只有全透/全不透（0/255 两档）',
          set(a_d) <= {0, 255} and a_d.count(0) > 0 and a_d.count(255) > 0,
          str(sorted(set(a_d))[:8]))
    check('C02 ★增强：逐像素真羽化（带内出现中间 alpha 档）', len(mid_s) > 20,
          f'中间档像素数={len(mid_s)}')
    check('C03 ★真羽化结果 ≠ 点阵羽化结果',
          soft.tobytes() != dither.tobytes())
    check('C04 点阵/真羽化都只动 alpha，画面像素不变（红色不变）',
          soft.getpixel((150, 120))[:3] == (200, 40, 40)
          and dither.getpixel((150, 120))[:3] == (200, 40, 40))


# ==========================================================================
# D. 渲染模式自动决定羽化实现
# ==========================================================================
def test_render_mode_auto():
    section('D. 渲染模式自动决定羽化实现（compat=点阵 / alpha=真羽化）')
    if not PIL_OK:
        skip('D', 'PIL 不可用')
        return
    src = _solid_img()
    base = {'feather_enabled': True, 'feather_radius': 24}
    c = R.apply_display_effects(src, dict(base, render_mode='compat'), Image)
    a = R.apply_display_effects(src, dict(base, render_mode='alpha'), Image)
    n = R.apply_display_effects(src, dict(base), Image)
    ac = [c.getpixel((x, 120))[3] for x in range(300)]
    aa = [a.getpixel((x, 120))[3] for x in range(300)]
    an = [n.getpixel((x, 120))[3] for x in range(300)]
    check('D01 compat（默认）仍走点阵近似 → 老路径零变化', set(ac) <= {0, 255},
          str(sorted(set(ac))[:8]))
    check('D02 ★render_mode=alpha 自动走真羽化（无需额外字段）',
          len([v for v in aa if 0 < v < 255]) > 20,
          f'中间档={len([v for v in aa if 0 < v < 255])}')
    check('D03 缺 render_mode 键（老配置）按 compat 处理', set(an) <= {0, 255})


# ==========================================================================
# E. 合成后肉眼可辨（平滑 vs 硬边）
# ==========================================================================
def test_preview_difference():
    section('E. 合成到棋盘格后：兼容=硬边 / 增强=颜色到棋盘的平滑过渡')
    if not PIL_OK:
        skip('E', 'PIL 不可用')
        return
    cp = getattr(R, 'compose_on_checker', None)
    if cp is None:
        check('E01 兼容合成 = 硬边（颜色种类很少）', False, 'compose_on_checker 未实现')
        check('E02 增强合成 = 平滑过渡（大量中间色）', False, 'compose_on_checker 未实现')
        return
    src = _solid_img()
    base = {'feather_enabled': True, 'feather_radius': 24}
    dith = R.apply_display_effects(src, dict(base), Image)
    soft = R.apply_display_effects(src, dict(base, true_alpha=True), Image)
    cd, cs = _colors(cp(dith, cell=8)), _colors(cp(soft, cell=8))
    check('E01 兼容合成 = 硬边（图色 + 棋盘两色）', len(cd) <= 4, f'{len(cd)} 色')
    check('E02 ★增强合成 = 平滑过渡（大量中间色）', len(cs) > 20, f'{len(cs)} 色')
    check('E03 ★增强的过渡色数显著多于兼容', len(cs) > len(cd) * 3,
          f'{len(cd)} → {len(cs)} 色')


# ==========================================================================
# GUI 段
# ==========================================================================
def _make_wiz(cfg, saved):
    wiz = R.ConfigWizard(on_done=lambda c: saved.update(c), overlay=None)
    if cfg:
        wiz.cfg.update(cfg)
    wiz.root.update_idletasks()
    wiz.root.update()
    return wiz


def _kill(wiz):
    try:
        wiz.root.destroy()
    except Exception:
        pass


def test_wizard_widgets(tmp, saved):
    section('F. ⑩ 旁新增「增强（真羽化）」开关（同区、可见、在点阵之后）')
    img = _make_png(os.path.join(tmp, 'r1a.png'))
    wiz = _make_wiz({'image': img}, saved)
    try:
        check('F01 新开关变量 var_alpha_feather 存在', hasattr(wiz, 'var_alpha_feather'))
        check('F02 新开关控件 chk_alpha_feather 存在', hasattr(wiz, 'chk_alpha_feather'))
        if not (hasattr(wiz, 'var_alpha_feather') and hasattr(wiz, 'chk_alpha_feather')):
            check('F03 ★与⑩点阵羽化同区（同父容器）', False, '新开关未实现')
            check('F04 ★在⑩点阵羽化之后（放后面的开关）', False, '新开关未实现')
            check('F05 新开关可见且带勾选能力', False, '新开关未实现')
            check('F06 文案含「增强」与「真羽化」', False, '新开关未实现')
            return
        same = getattr(wiz.chk_alpha_feather, 'master', None) is \
            getattr(wiz.chk_feather, 'master', None)
        check('F03 ★与⑩点阵羽化同区（同父容器）', same)
        check('F04 ★在⑩点阵羽化之后（放后面的开关）',
              wiz.chk_alpha_feather.winfo_rootx() > wiz.chk_feather.winfo_rootx(),
              f'x={wiz.chk_feather.winfo_rootx()} → {wiz.chk_alpha_feather.winfo_rootx()}')
        check('F05 新开关可见且带勾选能力',
              bool(wiz.chk_alpha_feather.winfo_ismapped())
              and 'checkbutton' in str(wiz.chk_alpha_feather.winfo_class()).lower(),
              str(wiz.chk_alpha_feather.winfo_class()))
        txt = str(wiz.chk_alpha_feather.cget('text'))
        check('F06 文案含「增强」与「真羽化」', '增强' in txt and '真羽化' in txt, txt)
        check('F07 初始（兼容）时新开关未勾选',
              not bool(wiz.var_alpha_feather.get()), str(wiz.var_alpha_feather.get()))
    finally:
        _kill(wiz)


def test_toggle_link(tmp, saved):
    section('G. 双向联动：⑩ 旁开关 ↔ ⑪ 渲染模式（改一处另一处同步 + 即时重绘）')
    img = _make_png(os.path.join(tmp, 'r1b.png'))
    wiz = _make_wiz({'image': img}, saved)
    try:
        if not hasattr(wiz, '_on_alpha_feather_toggle'):
            check('G01 ★⑩ 旁开关 → ⑪ 同步为增强', False, '_on_alpha_feather_toggle 未实现')
            check('G02 ★切换后预览立即重绘', False, '_on_alpha_feather_toggle 未实现')
            check('G03 ★增强模式下点阵勾选置灰', False, '_on_alpha_feather_toggle 未实现')
            check('G04 提示文案讲清「点阵羽化 = 兼容模式下的近似」', False, '未实现')
            check('G05 ★⑪ 改回兼容 → ⑩ 旁开关同步为关', False, '未实现')
            check('G06 切回兼容后点阵勾选恢复可编辑', False, '未实现')
            return
        n = [0]
        real_up = wiz._update_preview

        def _counted():
            n[0] += 1
            return real_up()
        wiz._update_preview = _counted

        wiz.var_alpha_feather.set(True)
        wiz._on_alpha_feather_toggle()
        check('G01 ★⑩ 旁开关打开 → ⑪ 渲染模式同步为增强',
              R.resolve_render_mode({'render_mode': wiz.var_render.get()}) == 'alpha',
              repr(wiz.var_render.get()))
        check('G02 ★切换后预览立即重绘（无需拖滑条/重开窗口）', n[0] >= 1,
              f'重绘 {n[0]} 次')
        check('G03 ★增强模式下「点阵羽化」勾选框置灰（不可误勾）',
              str(wiz.chk_feather.cget('state')) == 'disabled',
              str(wiz.chk_feather.cget('state')))
        txt_alpha = str(wiz.lbl_feather_hint.cget('text'))
        check('G04 ★提示文案讲清「点阵羽化 = 兼容模式下的近似」+ 这里是真羽化',
              '近似' in txt_alpha and '真羽化' in txt_alpha, txt_alpha)
        n[0] = 0
        wiz.var_render.set('compat')
        wiz._update_render_hint()
        check('G05 ★⑪ 改回兼容 → ⑩ 旁开关同步为关',
              not bool(wiz.var_alpha_feather.get()), str(wiz.var_alpha_feather.get()))
        check('G06 切回兼容后点阵勾选恢复可编辑',
              str(wiz.chk_feather.cget('state')) == 'normal',
              str(wiz.chk_feather.cget('state')))
        check('G07 ★⑪ 改回兼容也立刻重绘预览', n[0] >= 1, f'重绘 {n[0]} 次')
        txt_cmp = str(wiz.lbl_feather_hint.cget('text'))
        check('G08 兼容模式提示给出「增强」指引', '近似' in txt_cmp and '增强' in txt_cmp,
              txt_cmp)
    finally:
        _kill(wiz)


def test_save_consistency(tmp, saved):
    section('H. 保存一致性：cfg[render_mode] 与 UI 一致')
    img = _make_png(os.path.join(tmp, 'r1c.png'))
    wiz = _make_wiz({'image': img}, saved)
    if not hasattr(wiz, '_on_alpha_feather_toggle'):
        check('H01 ★⑩ 旁开关打开 → 保存 render_mode=alpha', False, '未实现')
        check('H02 保存把羽化写回为开启（与预览口径一致）', False, '未实现')
        _kill(wiz)
        return
    try:
        wiz.var_alpha_feather.set(True)
        wiz._on_alpha_feather_toggle()
        saved.clear()
        wiz._save_and_start()
        check('H01 ★⑩ 旁开关打开 → 保存 render_mode=alpha',
              R.resolve_render_mode(saved) == 'alpha', repr(saved.get('render_mode')))
        check('H02 增强模式下羽化写回为开启（与预览口径一致）',
              bool(saved.get('feather_enabled')) is True,
              repr(saved.get('feather_enabled')))
    except Exception as e:
        check('H01 ★⑩ 旁开关打开 → 保存 render_mode=alpha', False, repr(e))
    finally:
        _kill(wiz)

    wiz2 = _make_wiz({'image': img}, saved)
    try:
        wiz2.var_render.set('compat')
        wiz2._update_render_hint()
        saved.clear()
        wiz2._save_and_start()
        check('H03 ★⑪ 选兼容 → 保存 render_mode=compat（两处口径一致）',
              R.resolve_render_mode(saved) == 'compat', repr(saved.get('render_mode')))
    except Exception as e:
        check('H03 ★⑪ 选兼容 → 保存 render_mode=compat（两处口径一致）', False, repr(e))
    finally:
        _kill(wiz2)


def test_preview_compose_modes(tmp, saved):
    section('I. 向导预览按渲染模式合成（兼容=硬边 / 增强=颜色到棋盘格平滑过渡）')
    img = _make_png(os.path.join(tmp, 'r1d.png'))
    wiz = _make_wiz({'image': img}, saved)
    try:
        if not hasattr(wiz, '_checker_compose'):
            check('I01 兼容模式预览合成 = 硬边', False, '_checker_compose 未实现')
            check('I02 ★增强模式预览合成 = 平滑过渡', False, '_checker_compose 未实现')
            check('I03 ★增强模式 _effects_cfg 走真羽化', False, '未实现')
            check('I04 兼容模式 _effects_cfg 不走真羽化', False, '未实现')
            return
        src = _grad_img(64, 64)
        wiz.var_render.set('compat')
        wiz._update_render_hint()
        c1 = wiz._checker_compose(src)
        wiz.var_render.set('alpha')
        wiz._update_render_hint()
        c2 = wiz._checker_compose(src)
        n1, n2 = len(_colors(c1)), len(_colors(c2))
        check('I01 兼容模式合成：alpha 二值化 → 硬边（颜色少）', n1 <= 4, f'{n1} 色')
        check('I02 ★增强模式合成：逐像素半透明 → 颜色到棋盘格的平滑过渡',
              n2 > 20, f'{n2} 色')
        check('I03 ★增强模式 _effects_cfg：羽化开启 + 走逐像素真羽化',
              bool(wiz._effects_cfg().get('feather_enabled'))
              and wiz._effects_cfg().get('true_alpha') is True,
              str(wiz._effects_cfg()))
        wiz.var_render.set('compat')
        wiz._update_render_hint()
        check('I04 兼容模式 _effects_cfg 不带真羽化（老路径零变化）',
              not wiz._effects_cfg().get('true_alpha'), str(wiz._effects_cfg()))
        check('I05 预览画布上确有图片项（预览没被合成搞空白）',
              _canvas_images(wiz) >= 1, str(_canvas_images(wiz)))
    finally:
        _kill(wiz)


def _canvas_images(wiz):
    try:
        n = 0
        for i in wiz.canvas.find_all():
            if wiz.canvas.type(i) == 'image':
                n += 1
        return n
    except Exception:
        return 0


# ==========================================================================
def main():
    print('=== B_test_r1_feather：R1 增强羽化（⑩ 旁开关 + ⑪ 双向联动 + 预览棋盘格真 alpha 合成）===')
    print('Python', sys.version.split()[0], '| PIL 可用:', PIL_OK)
    tmp = tempfile.mkdtemp(prefix='r1_feather_')
    gui_ok = _has_gui()
    print('GUI 可用:', gui_ok, '| 临时目录:', tmp)
    saved = {}
    real = (R.save_config, R.messagebox.showinfo, R.messagebox.showwarning,
            R.messagebox.showerror, R.messagebox.askyesno, R.set_autostart)
    R.save_config = lambda cfg: saved.update(cfg)
    R.messagebox.showinfo = lambda *a, **k: None
    R.messagebox.showwarning = lambda *a, **k: None
    R.messagebox.showerror = lambda *a, **k: None
    R.messagebox.askyesno = lambda *a, **k: True
    R.set_autostart = lambda *a, **k: (True, '（测试打桩）')
    try:
        test_api_surface()
        test_checker()
        test_true_feather()
        test_render_mode_auto()
        test_preview_difference()
        if not gui_ok:
            for t, cnt in (('F', 7), ('G', 8), ('H', 3), ('I', 5)):
                for i in range(1, cnt + 1):
                    skip(f'{t}{i:02d}', '无桌面环境（GUI 不可用）')
        else:
            test_wizard_widgets(tmp, saved)
            test_toggle_link(tmp, saved)
            test_save_consistency(tmp, saved)
            test_preview_compose_modes(tmp, saved)
    finally:
        (R.save_config, R.messagebox.showinfo, R.messagebox.showwarning,
         R.messagebox.showerror, R.messagebox.askyesno, R.set_autostart) = real
        shutil.rmtree(tmp, ignore_errors=True)
    return _summary()


def _summary():
    print('\n' + '=' * 66)
    print(f'通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项 / 跳过 {len(SKIPPED)} 项')
    if SKIPPED:
        print('跳过项: ' + ', '.join(SKIPPED))
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
