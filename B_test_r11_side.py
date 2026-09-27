# -*- coding: utf-8 -*-
"""B_test_r11_side.py —— ③ 贴边方向在通用区原位（位置：R11 回退；语义：N3 按当前选中层）

用户第三轮原话：「贴边做错了，贴边放回原位，24中间。」→ ③ 从 ⑫ 图层区搬回**通用区原位**，
位置自 R11 起固定（② 候选框类型 与 ④ 缩放 之间），本脚本 A 段守着「只出现一处 + 在原位」。

历史背景（别搞反）：R2 曾按上一轮要求把 ③ 搬进图层区做成每图层参数，并修了
「多图层时主层贴边改不动」的 bug（根因：通用区 ③ 只刷预览不写状态，而多图层
预览只认图层区控件）。

> v2.0-N3 语义回退（第四轮，2026-09-27，本文件已按新事实改写）：
> 用户实测「多图时不同图片贴边选择会被统一覆盖。无法每个图片单独选择」，并两次澄清
> 「**只出现一处**，单图时正常用，多图时根据图片数量分开调整每一个」；追加「翻转也按
> 当前选中层（一起改）」→ **推翻 R11/R13 的「一处统一管所有图层」**：③ 与同一行的水平
> 翻转都改成「按当前选中层调」（与 ④⑤⑥ 同一种用法）。于是这些**旧前提被实测推翻**的
> 断言按「需求回退」方式改写（不删整段、不改恒真）：
>   · A04「③ 标题写明统一管所有图层」 → 「标题标出作用对象 = 当前层（第 N 层）」
>   · A08「翻转统一管所有图层（含主层）」 → 「翻转按当前选中层（写该层、不动其余层）」
>   · A09「图层区说明行讲清统一口径」 → 「讲清贴边在通用区、按当前层调」
>   · B 段（统一语义） → 反转为「每层独立」：点 ③ 只写当前层，其余层逐层不变
>   · C02「保存后全部层 anchor 与 ③ 一致」 → 「各层 anchor 逐层落盘 = 各自界面值」
>   · C05/C06b「切皮肤后各层 anchor 统一」 → 「切皮肤后各层保留档案自己的 anchor」
>   · E01「禁用统一同步 → 全层不同步」 → 「打桩写回路径 →『只有第 i 层变』不成立」
> R2 修过的那条 bug 的守护断言（B05/C01/C02：主层贴边必须仍可改）**一条未删** ——
> N3 起 ③ 的写回入口是 `_layer_set_params(i, anchor=…)`，主层被选中时照样写 cfg['side']
> 与 layers[0].anchor；本文件把它改成走**真实点击通路**来守（更强）。
> 判别力：回到 R2 之前那种「③ 只刷预览、不写状态」→ B05/C01/C02 红；
> 回到 R11 的「一次写全部层」→ B01/B03/B06 红。

验收段：
  A 结构：③ 在通用区原位（② 与 ④ 之间）、⑫ 无贴边/翻转控件、文案标出当前层
  B 每层独立：点 ③ 只改当前层 anchor（逐层前后值）、cfg[side] 只在主层被选中时变
  C 保存与皮肤往返：各层 anchor 逐层落盘 = 界面值、切皮肤不归一、v1.6 老档案可读
  D 单图层零漂移：仍走 v1.6 单层路径，三态贴边位置 left < center < right
  E 判别力：打桩写回路径后「只有第 i 层变」必须不成立（证明不是恒真断言）

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


def _descendant(w, anc):
    """w 是否在 anc 的子树里（沿 master 链向上找）—— R13 起用来验「翻转控件在通用区」"""
    cur = w
    while cur is not None:
        if cur is anc:
            return True
        try:
            cur = cur.master
        except Exception:
            return False
    return False


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
    """3 层夹具：各层**故意给不同的 anchor**（用来证明「点 ③ 只改当前层」）"""
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
    # v2.0-R15（第四轮 N1）改写**取样前提**（HANDOFF-2.1 §6-13）：向导现在默认折叠，
    # ⑧~⑭ 不 map ⇒ 卡内/卡间坐标探针全归零（③ 行也会被 y_of_prefix 取 min 量成 0）。
    # 本脚本量的是「③ 在通用区、② 与 ④ 之间」这个**展开态**布局，故取样前显式展开；
    # **判据表达式一条未改、强度未降**。
    # 判别力证据：注释掉下面三行（退回旧取样顺序）后 A05 必 FAIL。
    try:
        wiz._toggle_adv_collapse(False)
        wiz.root.update_idletasks()
        wiz.root.update()
    except Exception:
        pass
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
        check('A03 ③ 标题带编号（在通用区，编号仍是 ③）',
              any(t.startswith('③') for t in titles), repr(titles))
        # N3 需求回退：旧 A04「③ 标题写明统一管所有图层」的前提被用户实测推翻 →
        # 反转为「标题标出作用对象 = 当前层（第 N 层）」
        check('A04 ★③ 标题标出作用对象 = 当前层（第 N 层，不再写「所有图层」）',
              any('第' in t and '层' in t for t in titles)
              and not any('所有图层' in t for t in titles), repr(titles))
        # v2.0-R16 前提过期改写（同 n3 A04）：④⑤⑥ 由「竖排在下」改成「挪到 ①②③ 右侧」⇒
        # 「②<③<④」不再成立。新口径：③ 在通用区左列第 3 行（② 正下方）+ 两列三行逐行对齐。
        ys = {k: _first_y(wiz, k) for k in '①②③④⑤⑥'}
        y1, y2, y3 = ys['①'], ys['②'], ys['③']
        y4, y5, y6 = ys['④'], ys['⑤'], ys['⑥']
        rows_ok = (None not in (y1, y2, y3, y4, y5, y6)
                   and abs(y1 - y4) <= 3 and abs(y2 - y5) <= 3 and abs(y3 - y6) <= 3)
        check('A05 ★③ 行仍在通用区原位（左列第 3 行 = ② 正下方），且两列三行逐行对齐'
              '（R16：①≈④ / ②≈⑤ / ③≈⑥；旧「②<③<④」前提作废）',
              rows_ok and y1 < y2 < y3,
              f'y1..y6={y1},{y2},{y3},{y4},{y5},{y6} 行对齐={rows_ok}')
        check('A06 选项文案讲清贴哪边（右/左/中）',
              all(k in ''.join(side_r) for k in ('右', '左', '中')), repr(side_r))
        check('A07 通用区 ④⑤⑥ 仍在（只搬 ③，不误删）',
              hasattr(wiz, 'var_scale') and hasattr(wiz, 'var_offx')
              and hasattr(wiz, 'var_offy'))
        # N3 需求回退：旧 A08「翻转统一管所有图层（含主层）」的前提被推翻 →
        # 反转为「翻转按当前选中层：写该层、其余层（含主层）不动」
        _select(wiz, 1)
        flip_ws = [w for w in _all_widgets(wiz.root)
                   if w.winfo_class() == 'Checkbutton'
                   and str(w.cget('variable')) == str(wiz.var_flip)]
        in_general = bool(flip_ws) and any(_descendant(w, wiz.top_block) for w in flip_ws)
        before_flip = [bool(x.get('flip')) for x in wiz.cfg['layers']]
        wiz.var_flip.set(True)
        wiz._on_flip_change()
        after_flip = [bool(x.get('flip')) for x in wiz.cfg['layers']]
        check('A08 ★N3：翻转控件在通用区且按当前选中层（写第 2 层、主层不动）',
              in_general and before_flip == [False, False, False]
              and after_flip == [False, True, False],
              f"在通用区={in_general} flip {before_flip} → {after_flip}")
        # N3 需求回退：旧 A09「说明行讲清统一口径」→ 讲清「在通用区、按当前层调」
        # v2.0-R16 前提过期改写：旧判据在**全窗文案**里找「通用区 / 切层自动切值」关键词，
        # 前提是「⑫ 图层区那行小字写着这两句」。R16 把四条小字改写成大白话短句
        # （「这层跟着候选框走：贴边、翻转看 ③ 那一行…」「③ 贴边（第 2 层）= 贴左，切层自动变」），
        # 关键词一换就假红。改按**属性名**定位两处说明，分别钉住两件事：
        #   · lbl_side_target（③ 那一行的行内提示）：带「第 N 层」+「切层」（= 按当前层调、切层自动变）
        #   · lbl_layer_hint2（图层区那行说明）：把用户指回 ③ 那一行 / 通用区
        side_hint = str(getattr(wiz, 'lbl_side_target', None).cget('text')) \
            if getattr(wiz, 'lbl_side_target', None) is not None else ''
        lay_hint = str(getattr(wiz, 'lbl_layer_hint2', None).cget('text')) \
            if getattr(wiz, 'lbl_layer_hint2', None) is not None else ''
        check('A09 ★两处说明讲清「贴边在通用区（③ 那一行）、按当前层调、切层自动变」',
              ('第' in side_hint and '层' in side_hint and '切层' in side_hint)
              and ('③' in lay_hint or '通用区' in lay_hint),
              f'③ 行内提示={side_hint!r}　图层区说明={lay_hint!r}')
    finally:
        _kill(wiz)


# ==========================================================================
# B. 统一语义：③ 一处驱动全部图层
# ==========================================================================
def test_unified(tmp, saved):
    section('B. 每层独立：点 ③ 只改当前选中层 anchor，其余层逐层不变【N3 回退，原「统一语义」】')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        n0 = len(wiz._layers())
        check('B00 前置：夹具是 3 层且各层 anchor 不同（否则本段无判别力）',
              n0 == 3 and len(set(_anchors(wiz))) == 3, repr(_anchors(wiz)))
        _select(wiz, 1)
        b = _anchors(wiz)
        ok = _radio_invoke(wiz, wiz.var_side, '中')
        a = _anchors(wiz)
        print(f'    ③ 改第 2 层：anchors {b} → {a}')
        check('B01 ★选中第 2 层点 ③「中间」→ 只有第 2 层 anchor 变 center，其余层不变',
              ok and b == ['right_edge', 'left_edge', 'center']
              and a == ['right_edge', 'center', 'center'],
              f'点中={ok} {b} → {a}')
        check('B02 ★cfg[side] 不被非主层操作带偏（仍 = 主层值 right）',
              wiz.cfg.get('side') == 'right', repr(wiz.cfg.get('side')))
        check('B03 ★图层列表只有该行文案变（第 2 行写「居」，第 1/3 行保持贴右/居中）',
              wiz.layer_list.size() == 3
              and '居' in wiz.layer_list.get(1)
              and '贴右' in wiz.layer_list.get(0)
              and '居中' in wiz.layer_list.get(2),
              repr([wiz.layer_list.get(i) for i in range(3)]))
        specs = wiz._preview_specs()
        check('B04 ★预览 spec 里也只有第 2 层 anchor = center（其余层各自值）',
              len(specs) == 3
              and [s.get('anchor') for s in specs] == ['right_edge', 'center', 'center'],
              repr([s.get('anchor') for s in specs]))

        # 主层（第 0 层）可改：R2 修过的 bug 不许回归 —— 走**真实点击**通路
        _select(wiz, 0)
        ok2 = _radio_invoke(wiz, wiz.var_side, '左')
        check('B05 ★主层（第 0 层）贴边仍可改（R2 修过的 bug 不回归）',
              ok2 and _anchors(wiz)[0] == 'left_edge' and wiz.cfg.get('side') == 'left',
              f'点中={ok2} l0={_anchors(wiz)[:1]} side={wiz.cfg.get("side")}')
        check('B06 其余层不被主层操作带走（第 2/3 层仍是中/中）',
              _anchors(wiz) == ['left_edge', 'center', 'center'], repr(_anchors(wiz)))

        # N3 新增守护：只 set 变量、不点控件 → 不写回任何层（与 ④⑤⑥ 同口径：command 才写回）
        _select(wiz, 1)
        wiz.var_side.set('right')
        wiz._update_preview()
        check('B07 ★只改 ③ 变量、不点控件 → 不写回任何层（非 force 只信 cfg，绝不读 Tk 变量）',
              _anchors(wiz) == ['left_edge', 'center', 'center']
              and wiz.cfg.get('side') == 'left',
              repr(_anchors(wiz)))
        check('B08 预览画布上确有图片（每层独立后预览不空）', _img_xy(wiz) is not None, '')
        _select(wiz, 2)
        check('B09 ★切到第 3 层 → ③ 回显该层值（居中）',
              wiz.var_side.get() == 'center', repr(wiz.var_side.get()))
        _select(wiz, 0)
        check('B12 ★切到第 1 层 → 回显主层值（贴左，与 cfg[side]=left 一致）',
              wiz.var_side.get() == 'left' and wiz.var_layer_anchor.get() == 'left_edge',
              f'var_side={wiz.var_side.get()!r} 镜像={wiz.var_layer_anchor.get()!r}')
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
        # N3：逐层各点一次 ③（每层各自贴边），最后一次是主层 → 顶层 side 跟主层走。
        # 判别力：R11 的统一语义下这里会落成 ['center']*3，本段的 C02 会红。
        _select(wiz, 1)
        _radio_invoke(wiz, wiz.var_side, '中')
        _select(wiz, 2)
        _radio_invoke(wiz, wiz.var_side, '左')
        _select(wiz, 0)
        _radio_invoke(wiz, wiz.var_side, '中')
        saved.clear()
        wiz._save_and_start()
        out = dict(saved)
        lay = out.get('layers') or []
        print(f"    保存落盘：side={out.get('side')!r} "
              f"anchors={[x.get('anchor') for x in lay]}")
        check('C01 ★保存后顶层 side=center（主层值）', out.get('side') == 'center', repr(out.get('side')))
        check('C02 ★保存后各层 anchor 逐层落盘 = 各自的界面值 [center, center, left_edge]'
              '（N3：不再统一）',
              len(lay) == 3
              and [x.get('anchor') for x in lay] == ['center', 'center', 'left_edge'],
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
        # N3 需求回退：旧 C05「各层统一到档案 ③」的前提被推翻（切皮肤不再归一）
        check('C05 ★切皮肤后各层 anchor 保留档案自己的值（N3：不再归一）',
              _anchors(wiz2) == ['left_edge', 'right_edge', 'center'], repr(_anchors(wiz2)))
        check('C06 切皮肤后 var_side 回显当前选中层（主层 = 档案顶层 side left）',
              wiz2.var_side.get() == 'left', repr(wiz2.var_side.get()))
        specs2 = wiz2._preview_specs()
        check('C06b ★切皮肤后预览 spec 里各层 anchor 也保持档案各自值（不再统一）',
              len(specs2) == 3
              and [s.get('anchor') for s in specs2] == ['left_edge', 'right_edge', 'center'],
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
    section('E. 判别力：打桩写回路径 / 退回统一语义后，B 段核心断言必须不成立')
    real = getattr(R.ConfigWizard, '_layer_set_params', None)
    if real is None:
        check('E01 ★判别力：实现提供 _layer_set_params 写回入口', False,
              '方法不存在（未实现 N3）')
        return
    wiz = None
    try:
        R.ConfigWizard._layer_set_params = lambda self, *a, **k: False
        wiz = _make_wiz(_multi_cfg(tmp), saved)
        _select(wiz, 1)
        _radio_invoke(wiz, wiz.var_side, '中')
        anc = _anchors(wiz)
        print(f'    打桩 _layer_set_params（no-op）后点 ③：anchors={anc}')
        check('E01 ★判别力：写回路径打桩成 no-op →「第 2 层 anchor 变 center」不成立'
              '（证明 B01 非恒真）',
              not (anc[1] == 'center'), f'anchors={anc}')
    except Exception as e:
        check('E01 ★判别力：写回路径打桩成 no-op →「第 2 层 anchor 变 center」不成立',
              False, repr(e))
    finally:
        R.ConfigWizard._layer_set_params = real
        _kill(wiz) if wiz is not None else None

    # E02：退回 R11 的「点一次写全部层」→「其余层不变」不成立
    real_cmd = R.ConfigWizard._on_side_change

    def _legacy_unified(self):
        anc = R.anchor_from_side(self.var_side.get())
        for ld in (self.cfg.get('layers') or []):
            ld['anchor'] = anc
        self.cfg['side'] = R.side_from_anchor(anc)
        self._update_preview()

    wiz2 = None
    try:
        R.ConfigWizard._on_side_change = _legacy_unified
        wiz2 = _make_wiz(_multi_cfg(tmp), saved)
        _select(wiz2, 1)
        _radio_invoke(wiz2, wiz2.var_side, '中')
        anc2 = _anchors(wiz2)
        print(f'    退回统一语义后点 ③：anchors={anc2}')
        check('E02 ★判别力：③ 退回「写全部层」→「其余层不变」不成立（证明 B01 非恒真）',
              not (anc2[1:] == ['left_edge', 'center']), f'anchors={anc2}')
    except Exception as e:
        check('E02 ★判别力：③ 退回「写全部层」→「其余层不变」不成立（证明 B01 非恒真）',
              False, repr(e))
    finally:
        R.ConfigWizard._on_side_change = real_cmd
        _kill(wiz2) if wiz2 is not None else None


# ==========================================================================
def main():
    print('=== B_test_r11_side：③ 在通用区原位（语义：N3 按当前选中层）===')
    print('Python', sys.version.split()[0])
    tmp = tempfile.mkdtemp(prefix='r11_side_')
    R.HERE = tmp          # 只读约束（HANDOFF-2.1 §8.5）：日志/临时产物只落临时目录，不碰项目 error.log
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
            for t, cnt in (('A', 9), ('B', 11), ('C', 9), ('D', 5), ('E', 2)):
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
