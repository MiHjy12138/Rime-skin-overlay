# -*- coding: utf-8 -*-
"""B_test_r11_side.py —— v2.0-R11「③ 贴边方向搬回通用区 + 一处驱动全部图层」

用户第三轮实测原话：「贴边做错了，贴边放回原位，24中间。」
→ ③ 贴边方向从 ⑫ 图层区搬回**通用区原位（② 候选框类型 与 ④ 缩放 之间）**，
  语义 = **统一管所有图层**（图层区不再有「选中层贴哪儿」单选组，界面回到最简）。

历史背景（别搞反）：R2 曾按上一轮要求把 ③ 搬进图层区做成每图层参数，并修了
「多图层时主层贴边改不动」的 bug（根因：通用区 ③ 只刷预览不写状态，而多图层
预览只认图层区控件）。本轮是用户主动要求的**回退**，但那条 bug 的修复必须继续
成立 —— 现在由「③ 一处驱动全部图层的 anchor」同时满足简洁与正确：所以 B05/C 段
的主层守护断言保留（只是从「③ 落到主层」升级为「③ 落到全部层（含主层）」）。

验收段：
  A 结构：③ 回通用区（② 与 ④ 之间）、⑫ 不再有贴边单选、其余控件一个不少
  B 统一语义：改 ③ → 全部图层 anchor / cfg[side] / 图层列表文案 / 预览 四处一致
  C 保存与皮肤往返：存盘后各层 anchor 与 ③ 一致、切皮肤不串层、v1.6 老档案可读
  D 单图层零漂移：仍走 v1.6 单层路径，三态贴边位置 left < center < right
  E 判别力：禁用「统一同步」后 B 段核心断言必须不成立（证明不是恒真断言）

红线：只读被测模块；不写真实 config.json / skin.json（save_config 打桩、SKINS_DIR
      指临时目录）；文件对话框与模态框全部打桩。

用法: python B_test_r11_side.py
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
    from PIL import Image
    im = Image.new('RGBA', size, (0, 0, 0, 0))
    w, h = size
    for y in range(int(h * 0.2), int(h * 0.8)):
        for x in range(int(w * 0.15), int(w * 0.85)):
            im.putpixel((x, y), color)
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


def _radio_texts(wiz, var):
    """窗口里所有绑到某个变量的 Radiobutton 文案（验「控件在不在」）"""
    name = str(var)
    out = []
    for w in _all_widgets(wiz.root):
        try:
            if w.winfo_class() == 'Radiobutton' and str(w.cget('variable')) == name:
                out.append(str(w.cget('text')))
        except Exception:
            pass
    return out


def _radio_invoke(wiz, var, contains):
    """按文案点某个 Radiobutton（走**真实** UI 通路：变量 + command 一起触发）"""
    name = str(var)
    for w in _all_widgets(wiz.root):
        try:
            if (w.winfo_class() == 'Radiobutton' and str(w.cget('variable')) == name
                    and str(contains) in str(w.cget('text'))):
                w.invoke()
                return True
        except Exception:
            pass
    return False


def _first_y(wiz, prefix):
    """窗口里所有以 prefix 开头的控件的最小屏幕 y（验 ②③④ 的上下顺序）"""
    ys = []
    for w in _all_widgets(wiz.root):
        try:
            if w.winfo_class() in ('Label', 'Button', 'Checkbutton', 'Radiobutton'):
                if str(w.cget('text')).startswith(prefix):
                    ys.append(int(w.winfo_rooty()))
        except Exception:
            pass
    return min(ys) if ys else None


def _texts_like(wiz, needle):
    """窗口里文本含 needle 的控件文案列表（验标题/说明行）"""
    out = []
    for w in _all_widgets(wiz.root):
        try:
            if w.winfo_class() in ('Label', 'Button', 'Checkbutton', 'Radiobutton'):
                t = str(w.cget('text'))
                if needle in t:
                    out.append(t)
        except Exception:
            pass
    return out


def _anchors(wiz):
    return [str(ld.get('anchor')) for ld in (wiz.cfg.get('layers') or [])]


def _img_xy(wiz):
    try:
        for i in wiz.canvas.find_all():
            if wiz.canvas.type(i) == 'image':
                c = wiz.canvas.coords(i)
                return (float(c[0]), float(c[1]))
    except Exception:
        pass
    return None


def _multi_cfg(tmp, side='right', l1='left_edge', l2='center'):
    """3 层夹具：各层**故意给不同的 anchor**（用来证明「改 ③ 会统一全部层」）"""
    a = _make_png(os.path.join(tmp, 'r11a.png'), (120, 180), (220, 60, 60, 255))
    b = _make_png(os.path.join(tmp, 'r11b.png'), (80, 200), (60, 90, 220, 255))
    c = _make_png(os.path.join(tmp, 'r11c.png'), (60, 60), (60, 200, 90, 255))
    return {'image': a, 'side': side, 'scale': 1.0, 'offset_x': 0, 'offset_y': 0,
            'layers': [{'image': a, 'anchor': R.anchor_from_side(side), 'z': 0},
                       {'image': b, 'anchor': l1, 'z': 1},
                       {'image': c, 'anchor': l2, 'z': 2}]}


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
# A. 结构：③ 回通用区（② 与 ④ 之间），⑫ 不再有贴边单选
# ==========================================================================
def test_structure(tmp, saved):
    section('A. 结构：③ 回通用区原位（② 与 ④ 之间），⑫ 图层区不再有贴边单选')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        side_r = _radio_texts(wiz, wiz.var_side)
        anc_r = _radio_texts(wiz, wiz.var_layer_anchor)
        check('A01 ★通用区恢复「③ 贴边方向」单选组（3 个）',
              len(side_r) == 3, f'var_side 单选={side_r}')
        check('A02 ★⑫ 图层区不再有「选中层贴哪儿」单选组',
              len(anc_r) == 0, f'var_layer_anchor 单选={anc_r}')
        titles = _texts_like(wiz, '③ 贴边方向')
        check('A03 ③ 标题带编号（回通用区后编号仍是 ③）',
              any(t.startswith('③') for t in titles), repr(titles))
        check('A04 ③ 标题写明统一管所有图层',
              any(('所有图层' in t) or ('统一' in t) for t in titles), repr(titles))
        y2, y3, y4 = _first_y(wiz, '②'), _first_y(wiz, '③'), _first_y(wiz, '④')
        check('A05 ★③ 行在 ② 候选框类型 与 ④ 缩放 之间',
              None not in (y2, y3, y4) and y2 < y3 < y4,
              f'y2={y2} y3={y3} y4={y4}')
        check('A06 选项文案讲清贴哪边（右/左/中）',
              all(k in ''.join(side_r) for k in ('右', '左', '中')), repr(side_r))
        check('A07 通用区 ④⑤⑥ 仍在（只搬 ③，不误删）',
              hasattr(wiz, 'var_scale') and hasattr(wiz, 'var_offx')
              and hasattr(wiz, 'var_offy'))
        # 翻转仍是「当前选中层」参数（与 ④⑤⑥ 同族）——回退贴边时不动它
        _select(wiz, 1)
        wiz.var_flip.set(True)
        wiz._on_layer_flip()
        check('A08 图层区仍可调「当前层」水平翻转（写选中层，不写主层）',
              bool(wiz.cfg['layers'][1].get('flip')) is True
              and bool(wiz.cfg['layers'][0].get('flip')) is False,
              f"l1.flip={wiz.cfg['layers'][1].get('flip')} "
              f"l0.flip={wiz.cfg['layers'][0].get('flip')}")
        check('A09 图层区保留说明行（讲清贴边统一在通用区改）',
              any(('统一' in t) or ('通用区' in t) for t in _texts_like(wiz, '贴边')),
              repr(_texts_like(wiz, '贴边')))
    finally:
        _kill(wiz)


# ==========================================================================
# B. 统一语义：③ 一处驱动全部图层
# ==========================================================================
def test_unified(tmp, saved):
    section('B. 统一语义：改 ③ → 全部图层 anchor / cfg[side] / 列表文案 / 预览 四处一致')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        n0 = len(wiz._layers())
        check('B00 前置：夹具是 3 层且各层 anchor 不同（否则本段无判别力）',
              n0 == 3 and len(set(_anchors(wiz))) == 3, repr(_anchors(wiz)))
        ok = _radio_invoke(wiz, wiz.var_side, '中')
        check('B01 ★点 ③「中间」→ 全部 3 层 anchor 同步为 center',
              ok and _anchors(wiz) == ['center'] * 3, f'点中={ok} anchors={_anchors(wiz)}')
        check('B02 ★cfg[side] 同步为 center（顶层权威口径不变）',
              wiz.cfg.get('side') == 'center', repr(wiz.cfg.get('side')))
        check('B03 ★图层列表 3 行文案都写「居」（列表文案跟着变）',
              wiz.layer_list.size() == 3
              and all('居' in wiz.layer_list.get(i) for i in range(3)),
              repr([wiz.layer_list.get(i) for i in range(3)]))
        specs = wiz._preview_specs()
        check('B04 ★预览 spec 里全部层 anchor == center（预览跟着变）',
              len(specs) == 3 and all(s.get('anchor') == 'center' for s in specs),
              repr([s.get('anchor') for s in specs]))

        # 主层（第 0 层）可改：R2 修过的 bug 不许回归
        ok2 = _radio_invoke(wiz, wiz.var_side, '左')
        check('B05 ★主层（第 0 层）贴边仍可改（R2 修过的 bug 不回归）',
              ok2 and _anchors(wiz)[0] == 'left_edge' and wiz.cfg.get('side') == 'left',
              f'点中={ok2} l0={_anchors(wiz)[:1]} side={wiz.cfg.get("side")}')
        check('B06 其余层跟着 ③ 一起走（不止主层变）',
              _anchors(wiz) == ['left_edge'] * 3, repr(_anchors(wiz)))

        # 预览前归一这条通路（不走按钮 command 也要一致）
        wiz.var_side.set('right')
        wiz._update_preview()
        check('B07 ★直接改 ③ 变量后重绘预览 → 全部层仍同步为 right_edge',
              _anchors(wiz) == ['right_edge'] * 3 and wiz.cfg.get('side') == 'right',
              repr(_anchors(wiz)))
        check('B08 预览画布上确有图片（统一后预览不空）', _img_xy(wiz) is not None, '')
        check('B09 图层列表文案回到「贴右」',
              all('贴右' in wiz.layer_list.get(i) for i in range(3)),
              repr([wiz.layer_list.get(i) for i in range(3)]))
        check('B12 图层区说明行跟着 ③ 走（写当前统一贴边）',
              any(('统一' in t) and ('贴右' in t or '右' in t)
                  for t in _texts_like(wiz, '贴边')),
              repr(_texts_like(wiz, '贴边')))
    finally:
        _kill(wiz)

    # 向后兼容：没动 ③ 就不许静默改用户旧档案里其它层的 anchor
    wiz2 = _make_wiz(_multi_cfg(tmp, side='right', l1='left_edge', l2='center'), saved)
    try:
        wiz2.root.update_idletasks()
        wiz2._update_preview()
        check('B10 没动 ③ → 不静默改写旧档案其它层的 anchor（打开即可读）',
              _anchors(wiz2) == ['right_edge', 'left_edge', 'center'],
              repr(_anchors(wiz2)))
        check('B11 但主层仍与顶层 side 保持一致（保底归一不变）',
              _anchors(wiz2)[0] == 'right_edge' and wiz2.cfg.get('side') == 'right',
              f'l0={_anchors(wiz2)[:1]} side={wiz2.cfg.get("side")}')
    finally:
        _kill(wiz2)


# ==========================================================================
# C. 保存与皮肤档案往返
# ==========================================================================
def test_roundtrip(tmp, saved):
    section('C. 保存与皮肤往返：各层 anchor 与 ③ 一致、切皮肤不串层')
    real_skins = R.SKINS_DIR
    tmp_skins = os.path.join(tmp, 'skins_r11')
    os.makedirs(tmp_skins, exist_ok=True)
    wiz = None
    try:
        R.SKINS_DIR = tmp_skins
        wiz = _make_wiz(_multi_cfg(tmp), saved)
        _radio_invoke(wiz, wiz.var_side, '中')
        saved.clear()
        wiz._save_and_start()
        out = dict(saved)
        lay = out.get('layers') or []
        check('C01 ★保存后顶层 side=center', out.get('side') == 'center', repr(out.get('side')))
        check('C02 ★保存后全部层 anchor=center（与 ③ 一致）',
              len(lay) == 3 and all(x.get('anchor') == 'center' for x in lay),
              repr([x.get('anchor') for x in lay]))
        check('C03 保存后主层 offset 归零（F-V3 不翻倍）',
              int(lay[0].get('offset_x', 999)) == 0 and int(lay[0].get('offset_y', 999)) == 0
              if lay else False,
              repr((lay[0].get('offset_x'), lay[0].get('offset_y')) if lay else None))
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('C00 保存段未抛异常', False, repr(e))
    finally:
        _kill(wiz) if wiz is not None else None

    wiz2 = None
    try:
        R.SKINS_DIR = tmp_skins
        a = _make_png(os.path.join(tmp, 'r11a.png'), (120, 180), (220, 60, 60, 255))
        b = _make_png(os.path.join(tmp, 'r11b.png'), (80, 200), (60, 90, 220, 255))
        c = _make_png(os.path.join(tmp, 'r11c.png'), (60, 60), (60, 200, 90, 255))
        R.save_skin('R11 统一贴边皮肤', {
            'image': a, 'side': 'left', 'scale': 1.0,
            # 故意做成「R2 时代的多层档案」：第 2/3 层 anchor 与顶层 side 不一致
            # —— 统一语义下，用户把这份皮肤应用回向导后，各层必须统一到 ③(side)
            'layers': [{'image': a, 'anchor': 'left_edge', 'z': 0},
                       {'image': b, 'anchor': 'right_edge', 'z': 1},
                       {'image': c, 'anchor': 'center', 'z': 2}]})
        back = R.find_skin('R11 统一贴边皮肤')
        blay = (back or {}).get('layers') or []
        check('C04 ★档案 API 不做隐式改写（读回仍是存的 3 层，schema 完整）',
              len(blay) == 3 and all(x.get('image') for x in blay),
              repr([x.get('anchor') for x in blay]))

        wiz2 = _make_wiz(_multi_cfg(tmp), {})
        _radio_invoke(wiz2, wiz2.var_side, '右')      # 先把向导置成「贴右」
        wiz2.skin_var.set('R11 统一贴边皮肤')
        wiz2._apply_skin_to_wizard()                  # 真实切皮肤通路
        check('C05 ★切皮肤后全部层 anchor 统一回到 left_edge（不串层、不留上一个值）',
              _anchors(wiz2) == ['left_edge'] * 3, repr(_anchors(wiz2)))
        check('C06 切皮肤后 var_side 回显 left',
              wiz2.var_side.get() == 'left', repr(wiz2.var_side.get()))
        specs2 = wiz2._preview_specs()
        check('C06b ★切皮肤后预览 spec 里各层 anchor 也统一（预览与状态一致）',
              len(specs2) == 3 and all(s.get('anchor') == 'left_edge' for s in specs2),
              repr([s.get('anchor') for s in specs2]))

        # v1.6 老档案：单层、无 layers/schema
        R.save_skin('R11 老档案单层', {'image': a, 'side': 'left', 'scale': 1.0})
        wiz2.skin_var.set('R11 老档案单层')
        wiz2._apply_skin_to_wizard()
        lay2 = wiz2.cfg.get('layers') or []
        check('C07 ★v1.6 老档案（无 layers/schema）加载不报错，且 anchor 与 side 一致',
              len(lay2) == 1 and lay2[0].get('anchor') == 'left_edge',
              repr([x.get('anchor') for x in lay2]))
        check('C08 老档案加载后 ③ 回显 left',
              wiz2.var_side.get() == 'left', repr(wiz2.var_side.get()))
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('C04 皮肤往返段未抛异常', False, repr(e))
    finally:
        _kill(wiz2) if wiz2 is not None else None
        R.SKINS_DIR = real_skins


# ==========================================================================
# D. 单图层零漂移
# ==========================================================================
def test_single_layer(tmp, saved):
    section('D. 单图层路径零漂移（仍是 v1.6 单层口径）')
    a = _make_png(os.path.join(tmp, 'r11s.png'), (120, 180), (220, 60, 60, 255))
    wiz = _make_wiz({'image': a, 'side': 'right', 'scale': 1.0,
                     'offset_x': 0, 'offset_y': 0}, saved)
    try:
        check('D01 单层 → _preview_specs() 返回 []（走 v1.6 单层路径）',
              wiz._preview_specs() == [], str(wiz._preview_specs()))
        xs = {}
        for side, tag in (('left', '左'), ('center', '中'), ('right', '右')):
            if not _radio_invoke(wiz, wiz.var_side, tag):
                wiz.var_side.set(side)
                wiz._update_preview()
            xy = _img_xy(wiz)
            xs[side] = None if xy is None else xy[0]
        check('D02 ★单层：贴左 < 居中 < 贴右（v1.6 位置公式不变）',
              all(v is not None for v in xs.values())
              and xs['left'] < xs['center'] < xs['right'], str(xs))
        check('D03 单层：③ 与层内 anchor 始终一致',
              _anchors(wiz) == ['right_edge'] and wiz.cfg.get('side') == 'right',
              f'{_anchors(wiz)} side={wiz.cfg.get("side")}')
        saved.clear()
        wiz._save_and_start()
        out = dict(saved)
        lay = out.get('layers') or []
        check('D04 单层保存：cfg[side]=right 且 layers[0].anchor=right_edge',
              out.get('side') == 'right' and len(lay) == 1
              and lay[0].get('anchor') == 'right_edge',
              f"side={out.get('side')} l0={lay[0].get('anchor') if lay else None}")
        check('D05 单层保存：offset 仍归零（顶层权威，不产生层内双计）',
              int(out.get('offset_x', 999)) == 0 and int(out.get('offset_y', 999)) == 0
              and (len(lay) == 1 and int(lay[0].get('offset_x', 999)) == 0),
              f"top=({out.get('offset_x')},{out.get('offset_y')}) "
              f"l0={lay[0].get('offset_x') if lay else None}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D00 单层段未抛异常', False, repr(e))
    finally:
        _kill(wiz)


# ==========================================================================
# E. 判别力：证明 B 段断言不是恒真
# ==========================================================================
def test_discriminating(tmp, saved):
    section('E. 判别力：禁用「统一同步」后，B 段核心断言必须不成立')
    real = getattr(R.ConfigWizard, '_sync_side_to_all_layers', None)
    if real is None:
        check('E01 ★判别力：实现提供 _sync_side_to_all_layers 统一入口', False,
              '方法不存在（未实现 R11）')
        return
    wiz = None
    try:
        R.ConfigWizard._sync_side_to_all_layers = lambda self, *a, **k: False
        wiz = _make_wiz(_multi_cfg(tmp), saved)
        _radio_invoke(wiz, wiz.var_side, '中')
        same = all(x == 'center' for x in _anchors(wiz))
        check('E01 ★判别力：禁用统一同步后「全部层 anchor 同步」不成立（断言非恒真）',
              not same, f'anchors={_anchors(wiz)}')
    except Exception as e:
        check('E01 ★判别力：禁用统一同步后「全部层 anchor 同步」不成立（断言非恒真）',
              False, repr(e))
    finally:
        R.ConfigWizard._sync_side_to_all_layers = real
        _kill(wiz) if wiz is not None else None


# ==========================================================================
def main():
    print('=== B_test_r11_side：R11 ③ 贴边方向回通用区 + 统一管所有图层 ===')
    print('Python', sys.version.split()[0])
    tmp = tempfile.mkdtemp(prefix='r11_side_')
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
            for t, cnt in (('A', 9), ('B', 12), ('C', 9), ('D', 5), ('E', 1)):
                for i in range(1, cnt + 1):
                    SKIPPED.append(f'{t}{i:02d}')
                    print(f'  [SKIP] {t}{i:02d}  (无桌面环境（GUI 不可用）)')
        else:
            test_structure(tmp, saved)
            test_unified(tmp, saved)
            test_roundtrip(tmp, saved)
            test_single_layer(tmp, saved)
            test_discriminating(tmp, saved)
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
