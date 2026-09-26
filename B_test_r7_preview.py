# -*- coding: utf-8 -*-
"""B_test_r7_preview.py —— v2.0-R7 向导预览改回纯色底（去棋盘格）

对照用户第三轮实测反馈（原话）：
  「抠图后会变成这样，不再透明。」——先生截的是**向导预览区**：预览把透明区垫成了
  棋盘格，观感上像「不透明」。**用户明确要求：预览里改回纯色底（不要棋盘格）。**

本脚本验收：
  · A 段：模块级「RGBA → 纯色底」合成口径（透明区 = 画布底色，图上不再有棋盘格深色）；
  · B 段：真实向导预览抓屏（PhotoImage 逐像素）——透明区是画布底色、兼容=硬边 /
          增强=平滑过渡仍肉眼可辨、并落盘「改前(棋盘) vs 改后(纯色)」对比图。
  · C 段：cfg['render_mode'] 的读写路径不因删 ⑪ 而漂移（含 release/config.json 端到端）。

红绿纪律：本脚本先跑出红（缺 compose_on_solid / CV_BG / _preview_compose、
预览角上仍是棋盘格 → FAIL），再改实现到绿。R7（本文件 A/B 段）与 R10（C 段）
各一笔独立提交 —— C 段随 R10 追加。

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
