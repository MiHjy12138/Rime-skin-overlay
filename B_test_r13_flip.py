# -*- coding: utf-8 -*-
"""B_test_r13_flip.py —— v2.0-R13「水平翻转搬回通用区 + 与 ③ 一样统一管所有图层」

用户第三轮追加原话：「符合，回通用区」——前半是对「多层套层皮肤改用 ⑤水平偏移 实现
左右夹持」的确认（本项只需保证 ⑤水平偏移 不被弄坏），后半要求把「水平翻转」也从
⑫ 图层区搬回通用区，形态与刚做完的 R11（③ 贴边方向回通用区、统一管所有图层）一致。

验收段：
  A 结构：翻转控件在通用区（③ 那一行或紧随其后，在 ④ 之前）、⑫ 图层区不再有翻转控件
  B 统一语义：勾/取消 → layers[*].flip 全部同步；预览图像真的翻转；保存后 cfg 与各层一致
  C 主层不回归：R2 时代「翻转天然有联动」——主层（第 0 层）与单层路径翻转都生效
  D 老档案策略：各层 flip 不一致时**读入不改写**（只回显），用户显式动作 / 保存 / 切皮肤才统一；
    v1.6 单层档案加载不报错
  E 判别力：把各层 flip 人为改乱 → 统一入口必须能把它们拉回一致；禁用统一入口则拉不回
  F ⑤水平偏移不被弄坏：勾/取消翻转不改 scale / offset_x / offset_y

红线：只读被测模块；不写真实 config.json / skin.json（save_config 打桩、SKINS_DIR 指临时目录）；
      文件对话框与模态框全部打桩。

用法: python B_test_r13_flip.py
"""
import os
import sys
import shutil
import tempfile

# 控制台编码保护：GBK 控制台下打印 ③/★ 等字符会 UnicodeEncodeError 并让脚本 exit≠0
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R          # noqa: E402
try:
    from PIL import Image as _PILImage      # 像素级镜像断言要用 FLIP_LEFT_RIGHT
except Exception:
    _PILImage = None

PASS, FAIL, SKIPPED = [], [], []


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f'  [PASS] {name}' + (f'  ({detail})' if detail else ''))
    else:
        FAIL.append(name)
        print(f'  [FAIL] {name}' + (f'  ({detail})' if detail else ''))


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


def _make_png(path, size=(120, 180), color=(220, 60, 60, 255)):
    """不对称图案（左侧竖条偏红、右侧偏蓝）——翻转与否在像素上必然不同"""
    from PIL import Image
    im = Image.new('RGBA', size, (0, 0, 0, 0))
    w, h = size
    for y in range(int(h * 0.15), int(h * 0.85)):
        for x in range(int(w * 0.10), int(w * 0.90)):
            im.putpixel((x, y), color)
    for y in range(int(h * 0.25), int(h * 0.55)):
        for x in range(int(w * 0.10), int(w * 0.35)):
            im.putpixel((x, y), (30, 30, 30, 255))
    im.save(path)
    return path


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


def _descendant(w, anc):
    cur = w
    while cur is not None:
        if cur is anc:
            return True
        try:
            cur = cur.master
        except Exception:
            return False
    return False


def _first_y(wiz, prefix):
    """窗口里所有以 prefix 开头的控件的最小屏幕 y（验 ③ / ④ 的上下顺序）"""
    ys = []
    for w in _all_widgets(wiz.root):
        try:
            if w.winfo_class() in ('Label', 'Button', 'Checkbutton', 'Radiobutton'):
                if str(w.cget('text')).startswith(prefix):
                    ys.append(int(w.winfo_rooty()))
        except Exception:
            pass
    return min(ys) if ys else None


def _flip_widgets(wiz):
    """窗口里所有绑 var_flip 的 Checkbutton（用来验「控件在不在」与走真实点击通路）"""
    out = []
    for w in _all_widgets(wiz.root):
        try:
            if (w.winfo_class() == 'Checkbutton'
                    and str(w.cget('variable')) == str(wiz.var_flip)):
                out.append(w)
        except Exception:
            pass
    return out


def _set_flip(wiz, want):
    """按目标值点翻转勾选框（真实通路：变量 + command 一起触发）；无控件返回 False"""
    ws = _flip_widgets(wiz)
    if not ws:
        return False
    try:
        if bool(wiz.var_flip.get()) != bool(want):
            ws[0].invoke()
        wiz.root.update_idletasks()
        return bool(wiz.var_flip.get()) == bool(want)
    except Exception:
        return False


def _flips(wiz):
    return [bool(ld.get('flip')) for ld in (wiz.cfg.get('layers') or [])]


def _anchor_xy(wiz):
    try:
        for i in wiz.canvas.find_all():
            if wiz.canvas.type(i) == 'image':
                c = wiz.canvas.coords(i)
                return (float(c[0]), float(c[1]))
    except Exception:
        pass
    return None


def _multi_cfg(tmp, top_flip=False, l1=False, l2=False):
    """3 层夹具：各层 flip 可分别指定（用来验「统一同步」与「老档案不被静默改写」）"""
    a = _make_png(os.path.join(tmp, 'r13a.png'), (120, 180), (220, 60, 60, 255))
    b = _make_png(os.path.join(tmp, 'r13b.png'), (80, 200), (60, 90, 220, 255))
    c = _make_png(os.path.join(tmp, 'r13c.png'), (60, 60), (60, 200, 90, 255))
    return {'image': a, 'side': 'right', 'scale': 1.0, 'offset_x': 0, 'offset_y': 0,
            'flip_h': top_flip,
            'layers': [{'image': a, 'anchor': 'right_edge', 'z': 0, 'flip': top_flip},
                       {'image': b, 'anchor': 'left_edge', 'z': 1, 'flip': l1},
                       {'image': c, 'anchor': 'center', 'z': 2, 'flip': l2}]}


def _make_wiz(cfg, saved):
    wiz = R.ConfigWizard(on_done=lambda c: saved.update(c), overlay=None)
    if cfg:
        wiz.cfg.update(cfg)
    wiz._layer_sync_from_cfg()
    wiz.root.update_idletasks()
    wiz.root.update()
    return wiz


def _kill(wiz):
    try:
        wiz.root.destroy()
    except Exception:
        pass


def _select(wiz, i):
    wiz.layer_list.selection_clear(0, 'end')
    wiz.layer_list.selection_set(i)
    wiz._on_layer_select()


# ==========================================================================
# A. 结构：翻转控件回通用区，⑫ 不再有翻转控件
# ==========================================================================
def test_structure(tmp, saved):
    section('A. 结构：水平翻转在通用区（③ 那一行或紧随其后）、⑫ 图层区不再有')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        ws = _flip_widgets(wiz)
        check('A01 ★绑 var_flip 的勾选框恰好 1 个，且在通用区（不是又留在图层区）',
              len(ws) == 1 and _descendant(ws[0], wiz.top_block),
              f'绑 var_flip={len(ws)} 在通用区='
              f'{bool(ws) and _descendant(ws[0], wiz.top_block)}')
        y3, y4 = _first_y(wiz, '③'), _first_y(wiz, '④')
        yf = int(ws[0].winfo_rooty()) if ws else None
        # 同一行的 Checkbutton 与 Label 基线差 1~2px（Tk 边框/padding），留 8px 容差
        check('A02 ★翻转控件落在 ③ 与 ④ 之间（③ 那一行或紧随其后）',
              None not in (y3, y4, yf) and (y3 - 8) <= yf < y4,
              f'y3={y3} y_flip={yf} y4={y4}')
        check('A03 翻转控件在通用区 top_block 里（不是又留在图层区）',
              bool(ws) and _descendant(ws[0], wiz.top_block), '')
        check('A04 翻转文案写明统一管所有图层',
              bool(ws) and ('所有图层' in str(ws[0].cget('text'))
                            or '统一' in str(ws[0].cget('text'))),
              repr(str(ws[0].cget('text')) if ws else ''))
        check('A05 ③ 贴边方向单选仍在（只加翻转，不误删）',
              len([w for w in _all_widgets(wiz.root)
                   if w.winfo_class() == 'Radiobutton'
                   and str(w.cget('variable')) == str(wiz.var_side)]) == 3, '')
        check('A06 图层区仍有贴边说明行（讲清统一口径）',
              '统一' in str(wiz.lbl_side_target.cget('text')),
              repr(str(wiz.lbl_side_target.cget('text'))))
    finally:
        _kill(wiz)


# ==========================================================================
# B. 统一语义：勾/取消 → 全部层同步
# ==========================================================================
def test_unified(tmp, saved):
    section('B. 统一语义：勾/取消 → layers[*].flip 全部同步（预览 + 保存三处一致）')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        check('B00 前置：夹具 3 层 flip 全 False（否则本段无判别力）',
              _flips(wiz) == [False, False, False], repr(_flips(wiz)))
        ok = _set_flip(wiz, True)
        check('B01 ★勾选翻转 → 全部 3 层 flip 同步为 True',
              ok and _flips(wiz) == [True, True, True], f'点中={ok} flips={_flips(wiz)}')
        check('B02 ★cfg[flip_h] 同步 True（顶层权威口径不变）',
              wiz.cfg.get('flip_h') is True, repr(wiz.cfg.get('flip_h')))
        specs = wiz._preview_specs()
        check('B03 ★预览 spec 里各层 flip 一致（都 True）',
              len(specs) == 3 and all(bool(s.get('flip')) for s in specs),
              repr([s.get('flip') for s in specs]))
        ok2 = _set_flip(wiz, False)
        check('B04 ★取消翻转 → 全部层回到 False（可反复切换）',
              ok2 and _flips(wiz) == [False, False, False] and wiz.cfg.get('flip_h') is False,
              f'点中={ok2} flips={_flips(wiz)}')
        # 预览图像真的镜像（不是只改了状态）
        _set_flip(wiz, False)
        imgs0 = wiz._preview_layer_imgs(wiz._preview_specs())
        _set_flip(wiz, True)
        imgs1 = wiz._preview_layer_imgs(wiz._preview_specs())
        try:
            mirror_ok = []
            for a, b in zip(imgs0, imgs1):
                if a is None or b is None:
                    mirror_ok.append(False)
                    continue
                mirror_ok.append(b.tobytes()
                                 == a.transpose(_PILImage.FLIP_LEFT_RIGHT).tobytes())
            check('B05 ★预览里每层图像确实左右镜像（不只改状态）',
                  bool(mirror_ok) and all(mirror_ok), repr(mirror_ok))
        except Exception as e:
            check('B05 ★预览里每层图像确实左右镜像（不只改状态）', False, repr(e))
        # 保存：cfg 与各层一致
        saved.clear()
        wiz._save_and_start()
        out = dict(saved)
        lay = out.get('layers') or []
        check('B06 ★保存后 cfg[flip_h] 与 layers[*].flip 四处一致（都 True）',
              out.get('flip_h') is True and len(lay) == 3
              and all(bool(x.get('flip')) for x in lay),
              f"top={out.get('flip_h')} layers={[x.get('flip') for x in lay]}")
    finally:
        _kill(wiz)


# ==========================================================================
# C. 主层不回归（R2 时代「翻转天然有联动」）
# ==========================================================================
def test_main_layer(tmp, saved):
    section('C. 主层翻转不回归：多层 + 单层路径都生效')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        _select(wiz, 1)                    # 先选中第 2 层，再勾翻转
        ok = _set_flip(wiz, True)
        check('C01 ★选中第 2 层时勾翻转 → 主层（第 0 层）也翻转（统一语义）',
              ok and bool(wiz.cfg['layers'][0].get('flip')) is True
              and wiz.cfg.get('flip_h') is True,
              f"l0={wiz.cfg['layers'][0].get('flip')} top={wiz.cfg.get('flip_h')}")
        check('C02 运行时口径：resolve_layers 主层 flip 跟随顶层 flip_h',
              bool(R.resolve_layers(wiz.cfg)[0].get('flip')) is True, '')
    finally:
        _kill(wiz)

    # 单层路径：翻转仍然生效（v1.6 口径不变）
    a = _make_png(os.path.join(tmp, 'r13s.png'), (120, 180), (220, 60, 60, 255))
    wiz2 = _make_wiz({'image': a, 'side': 'right', 'scale': 1.0,
                      'offset_x': 0, 'offset_y': 0, 'flip_h': False}, saved)
    try:
        base = wiz2._get_preview_img()
        out0 = wiz2._image_effects(base)
        ok = _set_flip(wiz2, True)
        out1 = wiz2._image_effects(wiz2._get_preview_img())
        check('C03 ★单层：勾翻转 → cfg[flip_h]=True 且图像左右镜像',
              ok and wiz2.cfg.get('flip_h') is True
              and out1.tobytes() == out0.transpose(_PILImage.FLIP_LEFT_RIGHT).tobytes(),
              f"flip_h={wiz2.cfg.get('flip_h')}")
        check('C04 单层：layers[0].flip 与顶层一致（保存口径）',
              bool(wiz2.cfg['layers'][0].get('flip')) is True, '')
    finally:
        _kill(wiz2)


# ==========================================================================
# D. 老档案策略
# ==========================================================================
def test_legacy(tmp, saved):
    section('D. 老档案：读入不改写（只回显），显式动作/保存/切皮肤才统一')
    # D 组：各层 flip 人为不一致（模拟 R2 时代的多层档案）
    wiz = _make_wiz(_multi_cfg(tmp, top_flip=False, l1=True, l2=False), saved)
    try:
        wiz.root.update_idletasks()
        _select(wiz, 1)
        _select(wiz, 0)
        wiz._update_preview()
        check('D01 ★打开向导 + 切层 + 重绘预览后，各层历史 flip 不被静默改写',
              _flips(wiz) == [False, True, False], repr(_flips(wiz)))
        check('D02 但主层仍与顶层 flip_h 保持一致（主层保底归一不变）',
              bool(wiz.cfg['layers'][0].get('flip')) is bool(wiz.cfg.get('flip_h')),
              f"l0={wiz.cfg['layers'][0].get('flip')} top={wiz.cfg.get('flip_h')}")
        _select(wiz, 1)
        check('D03 切层只回显、不写回（切到第 2 层后各层 flip 仍是原值）',
              _flips(wiz) == [False, True, False], repr(_flips(wiz)))
        ok = _set_flip(wiz, False)       # 用户显式取消 → 统一
        check('D04 ★用户显式动作（点翻转）→ 全部层统一，老档案随之归一',
              ok and _flips(wiz) == [False, False, False], repr(_flips(wiz)))
    finally:
        _kill(wiz)

    # v1.6 单层老档案（无 layers / 无 schema）：走「老配置载入」真实路径
    # （先清掉向导构造期生成的 layers，再 update 老字段并重新 migrate —— 与 load_config 同序）
    a = _make_png(os.path.join(tmp, 'r13legacy.png'), (120, 180), (220, 60, 60, 255))
    wiz2 = _make_wiz(None, saved)
    try:
        wiz2.cfg.pop('layers', None)
        wiz2.cfg.update({'image': a, 'side': 'left', 'flip_h': True, 'scale': 1.0})
        wiz2._layer_sync_from_cfg()
        wiz2.root.update_idletasks()
        lay = wiz2.cfg.get('layers') or []
        check('D05 ★v1.6 单层老档案（无 layers/schema）加载不报错，主层 flip 正确',
              len(lay) == 1 and bool(lay[0].get('flip')) is True,
              repr([x.get('flip') for x in lay]))
        check('D06 老档案加载后翻转控件回显 True',
              bool(wiz2.var_flip.get()) is True, repr(wiz2.var_flip.get()))
    finally:
        _kill(wiz2)

    # 切皮肤（真实通路）→ 各层统一到档案主层 flip
    real_skins = R.SKINS_DIR
    tmp_skins = os.path.join(tmp, 'skins_r13')
    os.makedirs(tmp_skins, exist_ok=True)
    wiz3 = None
    try:
        R.SKINS_DIR = tmp_skins
        b = _make_png(os.path.join(tmp, 'r13b.png'), (80, 200), (60, 90, 220, 255))
        R.save_skin('R13 翻转皮肤', {
            'image': a, 'side': 'right', 'scale': 1.0, 'flip_h': True,
            'layers': [{'image': a, 'anchor': 'right_edge', 'z': 0, 'flip': True},
                       {'image': b, 'anchor': 'left_edge', 'z': 1, 'flip': False}]})
        wiz3 = _make_wiz(_multi_cfg(tmp, top_flip=False, l1=True), {})
        _set_flip(wiz3, False)
        wiz3.skin_var.set('R13 翻转皮肤')
        wiz3._apply_skin_to_wizard()      # 真实切皮肤通路
        check('D07 ★切皮肤后各层 flip 统一到档案主层 flip（True）',
              _flips(wiz3) == [True, True] and wiz3.cfg.get('flip_h') is True,
              f'flips={_flips(wiz3)} top={wiz3.cfg.get("flip_h")}')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D07 ★切皮肤后各层 flip 统一到档案主层 flip（True）', False, repr(e))
    finally:
        _kill(wiz3) if wiz3 is not None else None
        R.SKINS_DIR = real_skins


# ==========================================================================
# E. 判别力：改乱后统一入口必须能拉回一致
# ==========================================================================
def test_discriminating(tmp, saved):
    section('E. 判别力：各层 flip 人为改乱 → 统一入口必须拉回一致')
    real = getattr(R.ConfigWizard, '_sync_flip_to_all_layers', None)
    if real is None:
        check('E01 ★判别力：实现提供统一入口 _sync_flip_to_all_layers', False,
              '方法不存在（未实现 R13）')
        return
    wiz = None
    try:
        wiz = _make_wiz(_multi_cfg(tmp), saved)
        _set_flip(wiz, True)

        def _mess_up(w):
            ls = w.cfg.get('layers') or []
            for k, ld in enumerate(ls):
                ld['flip'] = bool(k % 2)        # False/True/False 搅乱
            w.cfg['flip_h'] = True
            try:
                w.var_flip.set(False)
            except Exception:
                pass

        _mess_up(wiz)
        check('E00 前置：改乱后各层 flip 确实不一致（否则本段无判别力）',
              len(set(_flips(wiz))) > 1, repr(_flips(wiz)))
        wiz._sync_flip_to_all_layers(force=True)
        check('E01 ★改乱后调统一入口（force）→ 各层 flip 全部拉回一致',
              len(set(_flips(wiz))) == 1 and _flips(wiz)[0] is bool(wiz.var_flip.get())
              and wiz.cfg.get('flip_h') is bool(wiz.var_flip.get()),
              f'flips={_flips(wiz)} var_flip={wiz.var_flip.get()} '
              f'top={wiz.cfg.get("flip_h")}')

        # 判别力：禁用统一入口 → 走真实点击也拉不回
        R.ConfigWizard._sync_flip_to_all_layers = lambda self, *a, **k: False
        _mess_up(wiz)
        ok = _set_flip(wiz, True)
        same = len(set(_flips(wiz))) == 1
        check('E02 ★判别力：禁用统一入口后，点勾选框拉不回一致（断言非恒真）',
              ok and not same, f'点中={ok} flips={_flips(wiz)}')
    finally:
        R.ConfigWizard._sync_flip_to_all_layers = real
        _kill(wiz) if wiz is not None else None


# ==========================================================================
# F. ⑤水平偏移 / 缩放不被弄坏
# ==========================================================================
def test_offset_untouched(tmp, saved):
    section('F. 勾/取消翻转不改 ④缩放 / ⑤水平 / ⑥垂直（多层左右夹持改走偏移）')
    cfg = _multi_cfg(tmp)
    cfg['layers'][1]['offset_x'] = -40
    cfg['layers'][1]['scale'] = 0.9
    cfg['offset_y'] = -12
    wiz = _make_wiz(cfg, saved)
    try:
        before = [(round(float(ld.get('scale', 1.0)), 2), int(ld.get('offset_x', 0)),
                   int(ld.get('offset_y', 0))) for ld in wiz.cfg['layers']]
        top_before = (round(float(wiz.cfg.get('scale', 1.0)), 2),
                      int(wiz.cfg.get('offset_x', 0)), int(wiz.cfg.get('offset_y', 0)))
        _set_flip(wiz, True)
        _set_flip(wiz, False)
        after = [(round(float(ld.get('scale', 1.0)), 2), int(ld.get('offset_x', 0)),
                  int(ld.get('offset_y', 0))) for ld in wiz.cfg['layers']]
        top_after = (round(float(wiz.cfg.get('scale', 1.0)), 2),
                     int(wiz.cfg.get('offset_x', 0)), int(wiz.cfg.get('offset_y', 0)))
        check('F01 ★翻转开关不动各层 scale / offset（左右夹持改走 ⑤水平偏移）',
              before == after and top_before == top_after,
              f'{before} → {after}｜top {top_before} → {top_after}')
        check('F02 第 2 层的水平偏移仍是 -40（没被翻转带偏）',
              int(wiz.cfg['layers'][1].get('offset_x', 0)) == -40,
              repr(wiz.cfg['layers'][1].get('offset_x')))
    finally:
        _kill(wiz)


# ==========================================================================
def main():
    print('=== B_test_r13_flip：R13 水平翻转回通用区 + 统一管所有图层 ===')
    print('Python', sys.version.split()[0])
    tmp = tempfile.mkdtemp(prefix='r13_flip_')
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
        if not gui_ok:
            for t, cnt in (('A', 6), ('B', 6), ('C', 4), ('D', 7), ('E', 3), ('F', 2)):
                for i in range(1, cnt + 1):
                    SKIPPED.append(f'{t}{i:02d}')
                    print(f'  [SKIP] {t}{i:02d}  (无桌面环境（GUI 不可用）)')
        else:
            test_structure(tmp, saved)
            test_unified(tmp, saved)
            test_main_layer(tmp, saved)
            test_legacy(tmp, saved)
            test_discriminating(tmp, saved)
            test_offset_untouched(tmp, saved)
    finally:
        (R.save_config, R.messagebox.showinfo, R.messagebox.showwarning,
         R.messagebox.showerror, R.messagebox.askyesno, R.set_autostart) = real
        shutil.rmtree(tmp, ignore_errors=True)
    return _summary()


def _summary():
    print('\n' + '=' * 66)
    print(f'通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项 / 跳过 {len(SKIPPED)} 项')
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
