# -*- coding: utf-8 -*-
"""B_test_r2_layer_side.py —— v2.0-R2 「贴边方向纳入图层」验证
                                 + v2.0-R11 需求回退后的语义更新

对照用户实测反馈（HANDOFF-2.0 §3 R2）：
  · 「贴边方向③也应纳入图层范围（可进一步缩窗口）」→ ③ 从通用区移走，改为
    作用于**当前选中图层**的每图层参数（选中哪层调哪层）。
  · 「多图层时原图贴边方向无法更改，仅能调整翻转」→ 复现 + 修复：
    通用区 ③ 的 command 只是 `_update_preview`，而多图层预览 `_preview_specs()` 里
    主层锚点取的是图层区控件 var_layer_anchor（旧值），既不读 var_side、也不写
    cfg['side']/layers[0].anchor → 点 ③ 完全没反应（预览/列表/参数都不动）。

================== v2.0-R11 需求回退（本文件已按新需求改写） ==================
用户第三轮实测原话：「贴边做错了，贴边放回原位，24中间。」并确认语义选择为
**③ 统一管所有图层**（图层区不再有「选中层贴哪儿」）。
于是下面这些**旧前提被实测推翻**的断言按「需求回退」方式改写（不删整段、不改恒真）：
  · A01「通用区不再有 ③ 单选」   → 反转为「通用区恢复 3 个 ③ 单选」
  · A02「图层区有三个贴边选项」  → 反转为「⑫ 不再有绑定 var_layer_anchor 的单选组」
  · A03「图层区贴边行带编号 ③」  → 改为「③ 编号回到通用区，且在 ② 与 ④ 之间」
  · A04「选项文案」             → 判据从图层区单选改为通用区单选
  · B02/B03「改某层只影响该层」  → 反转为「点 ③ → 全部层与 cfg[side] 一起同步」
  · C04「其它层不被带偏」        → 反转为「其它层跟着 ③ 一起走」
  · C07「图层区改主层 → 同步」   → 图层区该入口已撤，改为「③ 反向改 → 各层一起回」
  · D03「保存后第 2 层不串层」   → 反转为「保存后第 2 层 anchor 与 ③ 一致」
  · D11（新增）真实切皮肤通路 → 各层统一到档案 ③（统一语义下的「不串层」）
**R2 修过的那条 bug 的守护断言（C 段）一条未删** —— 主层（第 0 层）贴边必须仍可改，
只是现在由「③ 一处驱动全部层（含主层）」实现；判别力：若回到 R2 之前那种
「③ 只刷预览、不写状态」，B02/B03/C01/C02/C04/D03 全部会红（改写前实测 8 FAIL）。

验收段：
  A 结构：③ 回通用区（② 与 ④ 之间）、⑫ 不再有贴边单选、窗口不加高
  B 统一语义：点 ③ → 全部层 anchor / cfg[side] / 列表文案 一起变
  C 主层可改（R2 修过的 bug 不许回归）：③ 通路落到 cfg['side'] / layers[0].anchor / 预览
  D 往返：保存 → 皮肤档案 → 重开向导 / 真实切皮肤，各层贴边与 ③ 一致
  E 单图层零漂移：仍走 v1.6 单层路径，三态贴边位置 left < center < right

红线：只读被测模块；不写真实 config.json / skin.json（save_config 打桩、SKINS_DIR 指临时目录）；
      文件对话框与模态框全部打桩。

用法: python B_test_r2_layer_side.py
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
    """窗口里所有绑到某个变量的 Radiobutton 的文案（用来验「控件在不在」）"""
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


def _img_xy(wiz):
    """预览画布上第一张图片的左上角坐标（单层路径的位置断言用）"""
    try:
        for i in wiz.canvas.find_all():
            if wiz.canvas.type(i) == 'image':
                c = wiz.canvas.coords(i)
                return (float(c[0]), float(c[1]))
    except Exception:
        pass
    return None


def _multi_cfg(tmp):
    a = _make_png(os.path.join(tmp, 'r2a.png'), (120, 180), (220, 60, 60, 255))
    b = _make_png(os.path.join(tmp, 'r2b.png'), (80, 200), (60, 90, 220, 255))
    return {'image': a, 'side': 'right', 'scale': 1.0, 'offset_x': 0, 'offset_y': 0,
            'layers': [{'image': a, 'anchor': 'right_edge', 'z': 0},
                       {'image': b, 'anchor': 'left_edge', 'z': 1}]}


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
# A. 结构：③ 搬进图层区
# ==========================================================================
def test_ui_move(tmp, saved):
    section('A. ③ 贴边方向回通用区原位（② 与 ④ 之间），⑫ 不再有贴边单选【R11 改写】')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        side_r = _radio_texts(wiz, wiz.var_side)
        anc_r = _radio_texts(wiz, wiz.var_layer_anchor)
        # R11 需求回退：旧 A01「通用区不再有 ③ 单选」的前提被用户实测推翻 → 反转
        check('A01 ★通用区恢复「③ 贴边方向」单选组（3 个）', len(side_r) == 3,
              f'var_side 单选={side_r}')
        check('A02 ★⑫ 图层区不再有「选中层贴哪儿」单选组（改为统一管所有图层）',
              len(anc_r) == 0, f'var_layer_anchor 单选={anc_r}')
        y2, y3, y4 = _first_y(wiz, '②'), _first_y(wiz, '③'), _first_y(wiz, '④')
        check('A03 ★③ 编号回到通用区，且落在 ② 候选框类型 与 ④ 缩放 之间',
              None not in (y2, y3, y4) and y2 < y3 < y4,
              f'y2={y2} y3={y3} y4={y4}')
        check('A04 选项文案讲清贴哪边',
              all(k in ''.join(side_r) for k in ('右', '左', '中')), repr(side_r))
        check('A05 通用区 ④⑤⑥ 仍在（只搬 ③，不误删）',
              hasattr(wiz, 'var_scale') and hasattr(wiz, 'var_offx')
              and hasattr(wiz, 'var_offy'))
        h = wiz.root.winfo_reqheight()
        check('A06 窗口需求高度仍远小于 R1 基线（R11 加回 ③ 一行后 ≤1038）', h <= 1038,
              f'reqheight={h}（R1 基线 1038；R4 横排后 867，R11 回退后 ~914）')
        check('A07 图层区仍有翻转控件（var_flip，作用于当前选中层）',
              hasattr(wiz, 'var_flip') and hasattr(wiz, 'var_layer_anchor'))
    finally:
        _kill(wiz)


# ==========================================================================
# B. 每图层参数：切层回显 / 改值只影响该层
# ==========================================================================
def test_per_layer(tmp, saved):
    section('B. 统一语义：点 ③ → 全部图层一起变【R11 改写，原「每层独立」】')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        _select(wiz, 1)
        check('B01 选中第 2 层 → 回显该层 anchor（var_layer_anchor 现为回显镜像）',
              wiz.var_layer_anchor.get() == 'left_edge', repr(wiz.var_layer_anchor.get()))
        # R11 需求回退：旧 B02「改选中层只写 layers[1]」的前提被推翻 → 反转为统一同步
        ok = _radio_invoke(wiz, wiz.var_side, '中')
        check('B02 ★点 ③「中间」→ 全部层（含第 2 层）anchor 同步 center',
              ok and [x.get('anchor') for x in wiz.cfg['layers']] == ['center'] * 2,
              f"点中={ok} anchors={[x.get('anchor') for x in wiz.cfg['layers']]}")
        check('B03 ★主层与顶层 side 一起同步（不再各管一层）',
              wiz.cfg['layers'][0].get('anchor') == 'center'
              and wiz.cfg.get('side') == 'center',
              f"l0={wiz.cfg['layers'][0].get('anchor')} side={wiz.cfg.get('side')}")
        check('B04 列表项文案跟着更新（贴哪边看得见）',
              all('居' in wiz.layer_list.get(i) for i in range(2)),
              repr([wiz.layer_list.get(i) for i in range(2)]))
        _select(wiz, 0)
        check('B05 ★切回主层 → 回显主层值（与 ③ 一致）',
              wiz.var_layer_anchor.get() == 'center', repr(wiz.var_layer_anchor.get()))
        check('B06 图层区说明行回显当前统一贴边（讲清统一口径）',
              ('统一' in str(wiz.lbl_side_target.cget('text')))
              and ('居' in str(wiz.lbl_side_target.cget('text'))),
              repr(str(wiz.lbl_side_target.cget('text'))))
    finally:
        _kill(wiz)


# ==========================================================================
# C. 主层（index 0）贴边可改 —— bug 复现 → 修复
# ==========================================================================
def test_main_layer_fix(tmp, saved):
    section('C. 主层贴边方向可改（③ 通路落到主层参数 + 预览 + 回显）')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        _select(wiz, 0)
        # 旧入口复现：③ 通路（var_side）过去完全落不了地
        wiz.var_side.set('center')
        wiz._update_preview()
        check('C01 ★主层贴边（③ 通路）落到 cfg[side]',
              wiz.cfg.get('side') == 'center', repr(wiz.cfg.get('side')))
        check('C02 ★主层贴边落到 layers[0].anchor',
              wiz.cfg['layers'][0].get('anchor') == 'center',
              repr(wiz.cfg['layers'][0].get('anchor')))
        check('C03 ★多图层预览里主层跟着走（_preview_specs）',
              len(wiz._preview_specs()) > 1 and wiz._preview_specs()[0]['anchor'] == 'center',
              str([x['anchor'] for x in wiz._preview_specs()]))
        check('C04 ★其它层跟着 ③ 一起同步 center（R11 统一语义）',
              wiz.cfg['layers'][1].get('anchor') == 'center',
              repr(wiz.cfg['layers'][1].get('anchor')))
        check('C05 ★图层区回显跟着走（回显镜像 = 当前层 anchor）',
              wiz.var_layer_anchor.get() == 'center', repr(wiz.var_layer_anchor.get()))
        check('C06 预览画布上确有图片（改动没把预览搞空）',
              len(wiz._preview_specs()) > 1 and _img_xy(wiz) is not None)
        # R11 需求回退：图层区的贴边单选取已撤（统一收归通用区 ③）→
        # 旧 C07「图层区改主层」改为「③ 反向改一次，各层一起回到 right_edge」
        ok = _radio_invoke(wiz, wiz.var_side, '右')
        check('C07 ★③ 反向改（贴右）→ cfg[side] 与各层一起回到 right_edge',
              ok and wiz.var_side.get() == 'right' and wiz.cfg.get('side') == 'right'
              and all(x.get('anchor') == 'right_edge' for x in wiz.cfg['layers']),
              f"点中={ok} var_side={wiz.var_side.get()} side={wiz.cfg.get('side')} "
              f"anchors={[x.get('anchor') for x in wiz.cfg['layers']]}")
        # 再走一次 ③ 通路（变量 + 重绘）：回显要跟上
        wiz.var_side.set('left')
        wiz._update_preview()
        check('C08 ★③ 通路改回贴左 → 图层区回显 left_edge',
              wiz.var_layer_anchor.get() == 'left_edge', repr(wiz.var_layer_anchor.get()))
    finally:
        _kill(wiz)


# ==========================================================================
# D. 保存 + 皮肤档案往返
# ==========================================================================
def test_roundtrip(tmp, saved):
    section('D. 保存与皮肤档案往返：各层 anchor 与 ③ 一致、切皮肤不串层【R11 改写】')
    real_skins = R.SKINS_DIR
    tmp_skins = os.path.join(tmp, 'skins_r2')
    os.makedirs(tmp_skins, exist_ok=True)
    wiz = None
    try:
        R.SKINS_DIR = tmp_skins
        cfg = _multi_cfg(tmp)
        wiz = _make_wiz(cfg, saved)
        _select(wiz, 0)
        # R11：③ 已回通用区且统一管所有图层 → 点一次就够，不再逐层设 anchor
        _radio_invoke(wiz, wiz.var_side, '中')
        _select(wiz, 1)
        saved.clear()
        wiz._save_and_start()
        out = dict(saved)
        lay = out.get('layers') or []
        check('D01 ★保存后顶层 side = 主层贴边（center）',
              out.get('side') == 'center', repr(out.get('side')))
        check('D02 ★保存后 layers[0].anchor = center（主层逐层还原）',
              len(lay) > 0 and lay[0].get('anchor') == 'center',
              repr(lay[0].get('anchor') if lay else None))
        # R11 需求回退：旧 D03 断言「第 2 层保持自己的 left_edge（不串层）」的前提被推翻
        # → 反转为「各层 anchor 与 ③ 一致」（统一语义下的「不串层」= 不留上个值）
        check('D03 ★保存后 layers[1].anchor = center（与 ③ 一致，R11 统一语义）',
              len(lay) > 1 and lay[1].get('anchor') == 'center',
              repr(lay[1].get('anchor') if len(lay) > 1 else None))
        check('D04 保存后顶层 image 指向主层图片',
              os.path.normpath(str(out.get('image', ''))) == os.path.normpath(str(lay[0].get('image', '')))
              if lay else False, f"{out.get('image')} vs {lay[0].get('image') if lay else None}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D00 往返段未抛异常', False, repr(e))
    finally:
        _kill(wiz) if wiz is not None else None

    # 皮肤档案：存 → 读回 → 重开向导
    wiz2 = None
    try:
        R.SKINS_DIR = tmp_skins
        a = _make_png(os.path.join(tmp, 'r2a.png'), (120, 180), (220, 60, 60, 255))
        b = _make_png(os.path.join(tmp, 'r2b.png'), (80, 200), (60, 90, 220, 255))
        R.save_skin('R2 贴边往返皮肤', {
            'image': a, 'side': 'center', 'scale': 1.0,
            'layers': [{'image': a, 'anchor': 'center', 'z': 0},
                       {'image': b, 'anchor': 'left_edge', 'z': 1}]})
        back = R.find_skin('R2 贴边往返皮肤')
        blay = (back or {}).get('layers') or []
        check('D05 ★皮肤档案读回：主层贴边 center',
              len(blay) > 0 and blay[0].get('anchor') == 'center',
              repr(blay[0].get('anchor') if blay else None))
        check('D06 ★档案 API 原样读回第 2 层 anchor（save/find 不做隐式改写）',
              len(blay) > 1 and blay[1].get('anchor') == 'left_edge',
              repr(blay[1].get('anchor') if len(blay) > 1 else None))
        check('D07 档案顶层 side 与主层锚点一致',
              (back or {}).get('side') == R.side_from_anchor(blay[0]['anchor'])
              if blay else False, repr((back or {}).get('side')))

        wiz2 = R.ConfigWizard(on_done=lambda c: None, overlay=None)
        wiz2.cfg.update(back or {})
        wiz2.var_side.set((back or {}).get('side', 'right'))   # 与 _apply_skin_to_wizard 同序
        wiz2._layer_sync_from_cfg()
        wiz2.root.update_idletasks()
        check('D08 ★重开向导：贴边方向回显 center（选中主层）',
              wiz2.var_layer_anchor.get() == 'center', repr(wiz2.var_layer_anchor.get()))
        check('D09 重开向导：var_side 与 cfg[side] 一致',
              wiz2.var_side.get() == 'center' and wiz2.cfg.get('side') == 'center',
              f'var={wiz2.var_side.get()} cfg={wiz2.cfg.get("side")}')
        _select(wiz2, 1)
        check('D10 ★手工装配（不走切皮肤通路）时回显该层档案原值 left_edge',
              wiz2.var_layer_anchor.get() == 'left_edge', repr(wiz2.var_layer_anchor.get()))
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D05 皮肤档案往返段未抛异常', False, repr(e))
    finally:
        _kill(wiz2) if wiz2 is not None else None

    # R11 新增：走**真实**切皮肤通路 → 各层 anchor 统一到档案 ③（统一语义下的「不串层」）
    wiz3 = None
    try:
        R.SKINS_DIR = tmp_skins
        wiz3 = R.ConfigWizard(on_done=lambda c: None, overlay=None)
        _radio_invoke(wiz3, wiz3.var_side, '右')     # 向导先置成「贴右」
        wiz3.skin_var.set('R2 贴边往返皮肤')
        wiz3._apply_skin_to_wizard()
        check('D11 ★真实切皮肤后各层 anchor 统一到档案 ③(center)，不留上一个值',
              [x.get('anchor') for x in (wiz3.cfg.get('layers') or [])] == ['center'] * 2
              and wiz3.var_side.get() == 'center',
              f"anchors={[x.get('anchor') for x in (wiz3.cfg.get('layers') or [])]} "
              f"var_side={wiz3.var_side.get()}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('D11 ★真实切皮肤后各层 anchor 统一到档案 ③(center)，不留上一个值',
              False, repr(e))
    finally:
        _kill(wiz3) if wiz3 is not None else None
        R.SKINS_DIR = real_skins


# ==========================================================================
# E. 单图层零漂移
# ==========================================================================
def test_single_layer(tmp, saved):
    section('E. 单图层路径零漂移（仍是 v1.6 单层口径）')
    a = _make_png(os.path.join(tmp, 'r2s.png'), (120, 180), (220, 60, 60, 255))
    wiz = _make_wiz({'image': a, 'side': 'right', 'scale': 1.0,
                     'offset_x': 0, 'offset_y': 0}, saved)
    try:
        check('E01 单层 → _preview_specs() 返回 []（走 v1.6 单层路径）',
              wiz._preview_specs() == [], str(wiz._preview_specs()))
        xs = {}
        for side in ('left', 'center', 'right'):
            wiz.var_side.set(side)
            wiz._update_preview()
            xy = _img_xy(wiz)
            xs[side] = None if xy is None else xy[0]
        check('E02 ★单层：贴左 < 居中 < 贴右（v1.6 位置公式不变）',
              all(v is not None for v in xs.values())
              and xs['left'] < xs['center'] < xs['right'], str(xs))
        wiz.var_side.set('left')
        wiz._update_preview()
        saved.clear()
        wiz._save_and_start()
        out = dict(saved)
        lay = out.get('layers') or []
        check('E03 单层保存：cfg[side]=left 且 layers[0].anchor=left_edge',
              out.get('side') == 'left' and len(lay) == 1
              and lay[0].get('anchor') == 'left_edge',
              f"side={out.get('side')} l0={lay[0].get('anchor') if lay else None}")
        check('E04 单层保存：offset 仍归零（顶层权威，不产生层内双计）',
              int(out.get('offset_x', 999)) == 0 and int(out.get('offset_y', 999)) == 0
              and (len(lay) == 1 and int(lay[0].get('offset_x', 999)) == 0),
              f"top=({out.get('offset_x')},{out.get('offset_y')}) "
              f"l0={lay[0].get('offset_x') if lay else None}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('E00 单层段未抛异常', False, repr(e))
    finally:
        _kill(wiz)


# ==========================================================================
def main():
    print('=== B_test_r2_layer_side：R2 贴边方向纳入图层 + 主层贴边 bug（R11 需求回退后改写）===')
    print('Python', sys.version.split()[0])
    tmp = tempfile.mkdtemp(prefix='r2_layer_side_')
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
            for t, cnt in (('A', 7), ('B', 6), ('C', 8), ('D', 11), ('E', 4)):
                for i in range(1, cnt + 1):
                    SKIPPED.append(f'{t}{i:02d}')
                    print(f'  [SKIP] {t}{i:02d}  (无桌面环境（GUI 不可用）)')
        else:
            test_ui_move(tmp, saved)
            test_per_layer(tmp, saved)
            test_main_layer_fix(tmp, saved)
            test_roundtrip(tmp, saved)
            test_single_layer(tmp, saved)
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
