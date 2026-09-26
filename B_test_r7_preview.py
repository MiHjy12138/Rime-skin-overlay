# -*- coding: utf-8 -*-
"""B_test_r7_preview.py —— v2.0-R7 向导预览改回纯色底（去棋盘格）+ R10 删 ⑪ 渲染模式单选

对照用户第三轮实测反馈（原话）：
  「抠图后会变成这样，不再透明。」——先生截的是**向导预览区**：预览把透明区垫成了
  棋盘格，观感上像「不透明」。**用户明确要求：预览里改回纯色底（不要棋盘格）。**
  「有增强按钮后渲染模式部分就可以取了」——⑪ 渲染模式单选删掉（⑩ 旁的增强开关已完全覆盖）。

本脚本验收：
  · A/B 段（R7）：模块级「RGBA → 纯色底」合成口径 + 真实向导预览抓屏（透明区 = 画布底色、
          兼容=硬边 / 增强=平滑过渡仍肉眼可辨、含判别力对照、落盘改前/改后对比图）；
  · C 段（R10）：窗口里没有「⑪」编号标题、没有绑 var_render 的 Radiobutton，
          ⑩ 旁「增强（真羽化）」开关是唯一入口，提示文案不再引用 ⑪ 且仍讲清点阵近似；
  · D 段（R10）：cfg['render_mode'] 读写语义不变 —— 老档案 compat/alpha 回显正确、
          保存正确、release/config.json 端到端零漂移（render_mode 之外的键逐键一致）。

红绿纪律：本脚本先跑出红（R7 段缺 compose_on_solid/CV_BG/_preview_compose；
R10 段 ⑪ 单选与标题仍在、compat 文案无「近似」），再改实现到绿。
R7（A/B 段）与 R10（C/D 段）各一笔独立提交。

红线：只读被测模块与 release/config.json（只读，不写）；不写真实 config.json / skin.json
（save_config 打桩）；文件对话框与模态框全部打桩；测试图一律 tempfile。

用法: python B_test_r7_preview.py
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
EVID_DIR = os.path.join(BASE, '_evidence_r7')


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


def note(msg):
    print(f'  [INFO] {msg}')


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
# 夹具与像素工具
# ==========================================================================
def _half_clear(w=40, h=40, color=(255, 0, 0, 255)):
    """左半不透明、右半全透明的 RGBA 图（验「透明区 = 底色」）"""
    im = Image.new('RGBA', (w, h), color)
    for y in range(h):
        for x in range(w // 2, w):
            im.putpixel((x, y), color[:3] + (0,))
    return im


def _soft_edge(w=200, h=200, color=(220, 60, 60, 255), radius=24):
    """不透明纯色块 + 逐像素真羽化边缘（预览里「透明带」的来源）"""
    src = Image.new('RGBA', (w, h), color)
    return R.apply_display_effects(src, {'feather_enabled': True,
                                         'feather_radius': radius,
                                         'true_alpha': True}, Image)


def _colors(im):
    try:
        return {c for _n, c in (im.convert('RGB').getcolors(maxcolors=1 << 24) or [])}
    except Exception:
        return set()


def _near(c, t, tol=3):
    if c is None or t is None:
        return False
    return all(abs(int(c[i]) - int(t[i])) <= tol for i in range(3))


def photo_px(tkimg, x, y):
    """从真实 PhotoImage 取像素（= 渲染到用户眼睛里的那一份）"""
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


def _make_png(path, size=(200, 200), color=(200, 40, 40, 255)):
    Image.new('RGBA', size, color).save(path)
    return path


def _bg_rgb():
    """当前实现里「画布底色」的 RGB"""
    rgb = getattr(R, 'PREVIEW_BG_RGB', None)
    return tuple(rgb) if rgb else None


# ==========================================================================
# A. 纯色底合成口径（模块级）
# ==========================================================================
def test_solid_compose():
    section('A. 预览纯色底合成：透明区 = 画布底色，图上不再有棋盘格深色')
    hexbg = getattr(R, 'PREVIEW_BG_HEX', None)
    rgbbg = getattr(R, 'PREVIEW_BG_RGB', None)
    cvbg = getattr(R.ConfigWizard, 'CV_BG', None)
    ck = getattr(R, 'compose_on_solid', None)
    check('A01 模块级纯色底常量存在（PREVIEW_BG_HEX + PREVIEW_BG_RGB）',
          isinstance(hexbg, str) and isinstance(rgbbg, (tuple, list)) and len(rgbbg) == 3,
          f'hex={hexbg!r} rgb={rgbbg!r}')
    check('A02 ★纯色底与画布底色同源（ConfigWizard.CV_BG == PREVIEW_BG_HEX）',
          hexbg is not None and cvbg == hexbg, f'CV_BG={cvbg!r} PREVIEW_BG_HEX={hexbg!r}')
    check('A03 ★模块级 RGBA→纯色底合成符号存在（compose_on_solid）', ck is not None)
    if ck is None or not PIL_OK:
        for n in ('A04', 'A05', 'A06'):
            check(f'{n} 合成行为（compose_on_solid）', False, 'compose_on_solid 未实现')
        return
    bg = _bg_rgb() or (255, 255, 255)
    src = _half_clear()
    comp = ck(src)
    check('A04 合成图尺寸与输入一致', comp.size == src.size, str(comp.size))
    # 右半全透明 → 应原样露出画布底色
    clear_px = [comp.getpixel((x, 5)) for x in range(30, 39)]
    check('A05 ★全透明区 = 画布底色（不是棋盘两色、不是黑块）',
          all(_near(c, bg) for c in clear_px), f'{clear_px[:4]} vs 底色{bg}')
    # 不透明区仍保留图片颜色
    check('A06 不透明区保留图片颜色（红）',
          comp.getpixel((5, 5)) == (255, 0, 0), str(comp.getpixel((5, 5))))
    # 整幅图里不许再出现棋盘格深色（R7 的核心诉求：预览里没有棋盘格）
    dark = getattr(R, 'CHECKER_DARK', (214, 214, 214))
    cols = _colors(comp)
    check('A07 ★合成图整幅不含棋盘格深色 CHECKER_DARK（预览不再垫棋盘）',
          not any(_near(c, dark) for c in cols), f'深色={dark} 出现={_near(dark, dark)}')
    # 判别力：同一张图走 R1 的棋盘格合成 → 深色必然出现（证明 A07 不是恒真）
    old = getattr(R, 'compose_on_checker', None)
    if old is None:
        check('A08 判别力：R1 棋盘格合成下深色必然出现', False, 'compose_on_checker 不存在')
    else:
        old_cols = _colors(old(src, cell=8))
        check('A08 ★判别力：同一张图走 R1 棋盘格合成 → 深色必然出现',
              any(_near(c, dark) for c in old_cols),
              f'棋盘合成色数={len(old_cols)} 含深色='
              f'{any(_near(c, dark) for c in old_cols)}')


# ==========================================================================
# B. 真实向导预览抓屏
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


def test_gui_preview(tmp, saved):
    section('B. 真实向导预览逐像素：透明区是画布底色 / 兼容硬边 vs 增强平滑')
    img = _make_png(os.path.join(tmp, 'r7_solid.png'))
    cfg = {'image': img, 'scale': 0.4, 'offset_x': 0, 'offset_y': 0,
           'corner_enabled': False, 'feather_enabled': True, 'feather_radius': 24}
    bg = _bg_rgb() or (255, 255, 255)
    dark = getattr(R, 'CHECKER_DARK', (214, 214, 214))
    wiz = _make_wiz(cfg, saved)
    try:
        if not hasattr(wiz, '_preview_compose'):
            check('B01 ★预览合成为纯色底（角上透明区 = 画布底色）', False,
                  '_preview_compose 未实现')
            check('B00 预览 1:1、未被 fit 缩小', False, '未实现')
            check('B02 兼容档预览 = 硬边（色少）', False, '未实现')
            check('B03 ★增强档预览 = 平滑过渡（色多）', False, '未实现')
            check('B04 ★两档在纯色底上仍肉眼可辨', False, '未实现')
            check('B05 预览画布上确有图片项', False, '未实现')
            return
        wiz.var_corner.set(False)
        wiz.var_render.set('compat')
        wiz._update_render_hint()
        wiz.var_feather.set(True)
        wiz.var_feather_r.set(24)
        wiz.var_scale.set(0.4)          # 200×200 图 ×0.4 → 120×120 预览（1:1，不被 fit 缩小）
        wiz.var_offx.set(0)
        wiz.var_offy.set(0)
        wiz._update_preview()
        ph_c = wiz.tk_img
        w0, h0 = ph_c.width(), ph_c.height()
        check('B00 预览 1:1、未被 fit 缩小（像素判定才逐位可信）',
              (w0, h0) == (120, 120), f'预览={w0}x{h0}（期望 120x120）')
        corners = [photo_px(ph_c, 2, 2), photo_px(ph_c, 18, 2),
                   photo_px(ph_c, 2, 18), photo_px(ph_c, 18, 18)]
        has_bg = all(_near(c, bg) for c in corners)
        has_dark = any(_near(c, dark) for c in corners)
        check('B01 ★预览角上透明区 = 画布底色（不再露出棋盘格深色）',
              has_bg and not has_dark,
              f'corners={corners} 底色{bg} 深色出现={has_dark}')

        # 兼容档：alpha 二值化 → 纯色底上只有「源色 + 底色」两色
        px_c = row_pixels(ph_c, h0 // 2, w0)
        dis_c = len({tuple(c) for c in px_c if c is not None})
        # 增强档：逐像素真羽化 → 源色到画布底色的连续混合
        wiz.var_alpha_feather.set(True)
        wiz._on_alpha_feather_toggle()
        ph_a = wiz.tk_img
        px_a = row_pixels(ph_a, ph_a.height() // 2, ph_a.width())
        dis_a = len({tuple(c) for c in px_a if c is not None})
        check('B02 兼容档预览 = 硬边（行内只有源色与底色，≤4 色）', dis_c <= 4, f'{dis_c} 色')
        check('B03 ★增强档预览 = 平滑过渡（行内大量中间色 > 20 档）', dis_a > 20,
              f'{dis_a} 色')
        check('B04 ★两档在纯色底上仍肉眼可辨（增强中间色 ≥ 3× 兼容）',
              dis_a > 3 * max(1, dis_c), f'兼容 {dis_c} 色 → 增强 {dis_a} 色')
        n_img = sum(1 for i in wiz.canvas.find_all() if wiz.canvas.type(i) == 'image')
        check('B05 预览画布上确有图片项（合成没把预览搞空白）', n_img >= 1, str(n_img))

        # ---- 判别力：换回 R1 的棋盘格合成，B01 的判据必须命中 ----
        real = R.ConfigWizard._preview_compose
        try:
            def _checker_again(self, im):
                try:
                    return R.compose_on_checker(self._preview_render_mode_img(im),
                                                R.CHECKER_CELL, self._Image)
                except Exception:
                    return im
            R.ConfigWizard._preview_compose = _checker_again
            wiz2 = _make_wiz(cfg, saved)
            try:
                wiz2.var_corner.set(False)
                wiz2.var_feather.set(True)
                wiz2.var_scale.set(0.4)
                wiz2._update_preview()
                c2 = [photo_px(wiz2.tk_img, 2, 2), photo_px(wiz2.tk_img, 18, 2)]
                check('B06 ★判别力：换回棋盘格合成后角上必然出现深色（B01 能抓回归）',
                      any(_near(c, dark) for c in c2), f'corners={c2}')
            finally:
                _kill(wiz2)
        finally:
            R.ConfigWizard._preview_compose = real
        return (wiz, ph_c, ph_a)
    finally:
        _kill(wiz)


def dump_compare_evidence(tmp, saved):
    """落盘「改前(棋盘格) vs 改后(纯色底)」对比图，供真人肉眼复核"""
    section('B9. 对比图落盘（改前棋盘格 vs 改后纯色底）')
    if not PIL_OK:
        skip('B09 对比图', 'PIL 不可用')
        return
    try:
        os.makedirs(EVID_DIR, exist_ok=True)
    except Exception as e:
        check('B09 对比图落盘', False, repr(e))
        return
    soft = _soft_edge()
    dith = R.apply_display_effects(
        Image.new('RGBA', (200, 200), (200, 40, 40, 255)),
        {'feather_enabled': True, 'feather_radius': 24}, Image)
    before = R.compose_on_checker(soft, R.CHECKER_CELL, Image) if hasattr(
        R, 'compose_on_checker') else None
    after_fn = getattr(R, 'compose_on_solid', None)
    after = after_fn(soft, Image=Image) if after_fn else None
    paths = []
    try:
        if before is not None:
            p = os.path.join(EVID_DIR, 'R7_before_checker_enhanced.png')
            before.save(p)
            paths.append(p)
            p2 = os.path.join(EVID_DIR, 'R7_before_checker_compat.png')
            R.compose_on_checker(dith, R.CHECKER_CELL, Image).save(p2)
            paths.append(p2)
        if after is not None:
            p = os.path.join(EVID_DIR, 'R7_after_solid_enhanced.png')
            after.save(p)
            paths.append(p)
            p2 = os.path.join(EVID_DIR, 'R7_after_solid_compat.png')
            after_fn(dith, Image=Image).save(p2)
            paths.append(p2)
        if before is not None and after is not None:
            gap = 12
            w, h = before.size
            canvas_im = Image.new('RGB', (w * 2 + gap, h), (120, 120, 120))
            canvas_im.paste(before.convert('RGB'), (0, 0))
            canvas_im.paste(after.convert('RGB'), (w + gap, 0))
            p3 = os.path.join(EVID_DIR, 'R7_side_by_side_before_after.png')
            canvas_im.save(p3)
            paths.append(p3)
    except Exception as e:
        check('B09 对比图落盘', False, repr(e))
        return
    check('B09 ★改前/改后对比图已落盘（左=棋盘格 右=纯色底）', len(paths) >= 4,
          ' | '.join(paths))
    for p in paths:
        note(f'对比图: {p}')


# ==========================================================================
# C. ⑪ 渲染模式单选已删（R10）
# ==========================================================================
def _walk(w):
    out = []
    try:
        for c in w.winfo_children():
            out.append(c)
            out.extend(_walk(c))
    except Exception:
        pass
    return out


def _radiobuttons(w):
    out = []
    for c in _walk(w):
        try:
            if c.winfo_class() == 'Radiobutton':
                out.append(c)
        except Exception:
            pass
    return out


def test_no_render_radio(tmp, saved):
    section('C. ⑪ 渲染模式单选已删：增强开关成唯一入口，cfg 口径不变')
    img = _make_png(os.path.join(tmp, 'r10.png'))
    wiz = _make_wiz({'image': img}, saved)
    try:
        rbs = _radiobuttons(wiz.root)
        # 注意：tkinter 的 cget('variable') 回的是 Tcl 变量名（PY_VARn），
        # 必须与 str(wiz.var_render) 比 —— 直接比 'var_render' 会恒真（抓不到）。
        want_v = str(wiz.var_render)
        bound = [r for r in rbs if str(r.cget('variable')) == want_v]
        check('C01 ★窗口里再没有绑 var_render 的 Radiobutton（⑪ 单选组已删）',
              not bound, f'仍存在 {len(bound)} 个（变量 {want_v}）')
        texts = []
        for c in _walk(wiz.root):
            try:
                t = c.cget('text')
            except Exception:
                continue
            if isinstance(t, str) and t:
                texts.append(t)
        hit = [t for t in texts if '⑪' in t]
        check('C02 ★窗口里再没有「⑪」编号标题', not hit, f'命中={hit}')
        check('C03 判别力：扫描器仍能抓到别的单选组（② 候选框类型 ≥2 个，不是恒空）',
              len(rbs) >= 2, f'Radiobutton 总数={len(rbs)}')
        chk = getattr(wiz, 'chk_alpha_feather', None)
        check('C04 ★⑩ 旁「增强（真羽化）」开关仍在且可点（唯一入口）',
              chk is not None and '增强' in str(chk.cget('text'))
              and str(chk.cget('state')) == 'normal',
              f'text={chk and chk.cget("text")!r} state={chk and chk.cget("state")!r}')

        wiz.var_alpha_feather.set(True)
        wiz._on_alpha_feather_toggle()
        check('C05 ★勾开关 → 内部 var_render=alpha（cfg 口径不变）',
              wiz.var_render.get() == 'alpha' and wiz._is_alpha_mode(),
              f'var_render={wiz.var_render.get()!r}')
        wiz.var_alpha_feather.set(False)
        wiz._on_alpha_feather_toggle()
        check('C06 取消勾选 → 内部 var_render 回 compat',
              wiz.var_render.get() == 'compat', f'var_render={wiz.var_render.get()!r}')

        t_cmp = str(wiz.lbl_render_hint.cget('text'))
        check('C07 ★提示文案不再引用「⑪」', '⑪' not in t_cmp, repr(t_cmp[:40]))
        check('C08 ★提示文案仍讲清「点阵羽化是兼容模式近似」',
              '点阵' in t_cmp and '近似' in t_cmp, repr(t_cmp[:60]))
        wiz.var_alpha_feather.set(True)
        wiz._on_alpha_feather_toggle()
        t_alp = str(wiz.lbl_render_hint.cget('text'))
        check('C09 增强态文案仍讲清真半透明与点击穿透（不退化）',
              '半透明' in t_alp and '穿透' in t_alp and '⑪' not in t_alp,
              repr(t_alp[:60]))
    finally:
        _kill(wiz)


# ==========================================================================
# D. cfg['render_mode'] 读写语义不变 + release/config.json 端到端零漂移（R10）
# ==========================================================================
def _release_cfg():
    p = os.path.join(BASE, 'release', 'config.json')
    try:
        import json
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def test_render_mode_roundtrip(tmp, saved):
    section('D. cfg[render_mode] 读写语义不变（老配置读入 / 保存 / release 端到端零漂移）')
    img = _make_png(os.path.join(tmp, 'r10b.png'))
    old_skins = getattr(R, 'SKINS_DIR', None)
    try:
        sk = os.path.join(tmp, 'skins_r10')
        os.makedirs(sk, exist_ok=True)
        R.SKINS_DIR = sk
        for mode in ('alpha', 'compat'):
            base = dict(R.DEFAULT_CONFIG)
            base.update({'image': img, 'render_mode': mode})
            R.save_skin('皮肤_%s' % mode, base)
        wiz = _make_wiz({'image': img}, saved)
        try:
            wiz.skin_var.set('皮肤_alpha')
            wiz._apply_skin_to_wizard()
            ok_a = (wiz.var_render.get() == 'alpha'
                    and bool(wiz.var_alpha_feather.get()))
            check('D01 ★老档案 render_mode=alpha → 向导回显增强（开关同步勾上）', ok_a,
                  f'var_render={wiz.var_render.get()!r} 开关={wiz.var_alpha_feather.get()}')
            wiz.skin_var.set('皮肤_compat')
            wiz._apply_skin_to_wizard()
            ok_c = (wiz.var_render.get() == 'compat'
                    and not bool(wiz.var_alpha_feather.get()))
            check('D02 ★老档案 render_mode=compat → 向导回显兼容（开关未勾）', ok_c,
                  f'var_render={wiz.var_render.get()!r} 开关={wiz.var_alpha_feather.get()}')
        finally:
            _kill(wiz)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D01/D02 皮肤档案回显段未抛异常', False, repr(e))
    finally:
        if old_skins is not None:
            R.SKINS_DIR = old_skins

    # D03 增强态保存 / D04 兼容态保存
    try:
        wiz = _make_wiz({'image': img}, saved)
        try:
            wiz.var_alpha_feather.set(True)
            wiz._on_alpha_feather_toggle()
            saved.clear()
            wiz._save_and_start()
            c_alpha = dict(saved)
            check('D03 ★增强态保存 → cfg[render_mode]=alpha',
                  c_alpha.get('render_mode') == 'alpha'
                  and R.resolve_render_mode(c_alpha) == 'alpha',
                  repr(c_alpha.get('render_mode')))
        finally:
            _kill(wiz)
        wiz = _make_wiz({'image': img}, saved)
        try:
            saved.clear()
            wiz._save_and_start()
            c_compat = dict(saved)
            check('D04 ★兼容态（未勾）保存 → cfg[render_mode]=compat',
                  c_compat.get('render_mode') == 'compat',
                  repr(c_compat.get('render_mode')))
        finally:
            _kill(wiz)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D03/D04 保存往返段未抛异常', False, repr(e))

    # D05 端到端：release/config.json
    rel = _release_cfg()
    if rel is None:
        skip('D05 端到端 release/config.json', 'release/config.json 不存在')
        return
    want = R.resolve_render_mode(rel)
    check('D05a release/config.json 读入语义正确（缺键 → compat）',
          want == 'compat' and 'render_mode' not in rel,
          f"raw={rel.get('render_mode')!r} → {want!r}")
    try:
        wiz = _make_wiz(rel, saved)
        try:
            saved.clear()
            wiz._save_and_start()
            c1 = dict(saved)
            check('D05b ★release/config.json 端到端：保存后 render_mode 语义零漂移',
                  R.resolve_render_mode(c1) == want,
                  f"缺键 → 保存 {c1.get('render_mode')!r}（语义 {R.resolve_render_mode(c1)!r}）")
        finally:
            _kill(wiz)
        rel2 = dict(rel)
        rel2['render_mode'] = 'alpha'
        wiz2 = _make_wiz(rel2, saved)
        try:
            check('D05c-a ★release 配置带 render_mode=alpha 时读入语义 = alpha（不回落 compat）',
                  R.resolve_render_mode(wiz2.cfg) == 'alpha',
                  f"cfg.render_mode={wiz2.cfg.get('render_mode')!r}")
            wiz2.var_alpha_feather.set(True)
            wiz2._on_alpha_feather_toggle()
            saved.clear()
            wiz2._save_and_start()
            c2 = dict(saved)
            check('D05c ★该配置经增强开关入口保存 → render_mode 仍 alpha（不被打回 compat）',
                  c2.get('render_mode') == 'alpha',
                  f"var_render={wiz2.var_render.get()!r} 保存={c2.get('render_mode')!r}")
            diff = [k for k in (set(c1) | set(c2))
                    if k != 'render_mode' and c1.get(k) != c2.get(k)]
            # 增强态保存会写 feather_enabled=True 且同步进 layers（R1 既定口径），故白名单放行这两键；
            # 白名单之外再出现差异即视为「render_mode 泄到别的字段」→ FAIL。
            check('D05d-pre ★增强开关只影响 render_mode/feather_enabled/layers（不泄到别的字段）',
                  set(diff) <= {'feather_enabled', 'layers'}, f'差异键={diff}')
        finally:
            _kill(wiz2)
        # D05d 纯 cfg 差异（UI 状态一致）：输入只差 render_mode → 保存结果只差 render_mode
        wiz3 = _make_wiz(rel2, saved)
        try:
            saved.clear()
            wiz3._save_and_start()
            c3 = dict(saved)
            diff2 = [k for k in (set(c1) | set(c3))
                     if k != 'render_mode' and c1.get(k) != c3.get(k)]
            check('D05d ★输入只差 render_mode 时其余键逐键一致（cfg 读写路径未漂移）',
                  not diff2 and c1.get('render_mode') == 'compat'
                  and c3.get('render_mode') == 'compat',
                  f'差异键={diff2}（两态 render_mode={c1.get("render_mode")!r}/'
                  f'{c3.get("render_mode")!r}）')
        finally:
            _kill(wiz3)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D05 release 端到端段未抛异常', False, repr(e))

    # D06 托盘重配路径：运行中的外挂 render_mode=alpha → 向导打开即回显增强（R1 既有逻辑，守护不丢）
    class _OvStub:
        render_mode = 'alpha'

    try:
        wiz3 = R.ConfigWizard(on_done=lambda c: saved.update(c), overlay=_OvStub())
        wiz3.root.update_idletasks()
        wiz3.root.update()
        try:
            check('D06 ★托盘重配（overlay.render_mode=alpha）→ 向导打开即回显增强',
                  wiz3.var_render.get() == 'alpha'
                  and bool(wiz3.var_alpha_feather.get()),
                  f'var_render={wiz3.var_render.get()!r} 开关={wiz3.var_alpha_feather.get()}')
        finally:
            _kill(wiz3)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D06 ★托盘重配（overlay.render_mode=alpha）→ 向导打开即回显增强',
              False, repr(e))


# ==========================================================================
def main():
    print('=== B_test_r7_preview：R7 向导预览改回纯色底（去棋盘格）===')
    print('Python', sys.version.split()[0], '| PIL 可用:', PIL_OK)
    tmp = tempfile.mkdtemp(prefix='r7_preview_')
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
        test_solid_compose()
        if not gui_ok:
            for t, cnt in (('B', 7),):
                for i in range(cnt + 1):
                    skip(f'{t}{i:02d}', '无桌面环境（GUI 不可用）')
        else:
            test_gui_preview(tmp, saved)
            test_no_render_radio(tmp, saved)
            test_render_mode_roundtrip(tmp, saved)
        dump_compare_evidence(tmp, saved)
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
