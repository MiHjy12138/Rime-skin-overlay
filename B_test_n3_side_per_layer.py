# -*- coding: utf-8 -*-
"""B_test_n3_side_per_layer.py —— v2.0-N3「③ 贴边方向 + 水平翻转 = 按当前选中层分别调」

用户第四轮原话（两次澄清，以此为准）：
  · 第一次「3扩展，同一套按钮，但用法分开，这个思路。」
  · 第二次（纠正「两处按钮」的误读）「**只出现一处**，单图时正常用，多图时根据图片
    数量分开调整每一个，这样子。」
  · 追加（2026-09-27）：「翻转也按当前选中层（一起改）」→ 一并推翻 R13 的统一语义。

本脚本固化 N3 的事实前提（推翻 R11/R13 的「一处统一管所有图层」）：
  ③ 与翻转仍在**通用区原位**、各**只出现一处**、形态不变（单选组 + 勾选框），
  作用对象 = **当前选中图层**，与 ④缩放 / ⑤水平 / ⑥垂直 完全同一种用法；
  切层时两者都**回显该层当前值**；撤掉两个统一入口（只留「主层保底归一」）。

验收段：
  A 结构：③ 与翻转各一处、在通用区、②③④ 顺序、图层区无第二套、文案标作用对象
  B ③ 每层独立：改第 i 层只动第 i 层 anchor（贴逐层前后值）
  C 翻转每层独立：改第 i 层只动第 i 层 flip（贴逐层前后值）
  D 切层回显：3 层值各不同，来回切 3 轮，③ 与翻转都回显该层值
  E R2 断头路不回归：主层（第 0 层）被选中时 ③ 与翻转都改得动
  F 统一入口撤干净：非 force 只信 cfg、绝不读 Tk 变量；别名不写全层
  G 保存：顶层键 side / flip_h 一律取**主层**值（第 5 个串层点）
  H 档案往返 / 切皮肤不归一 / 旧档案原样保留
  I _layer_add 新层 anchor 与 flip 都取主层当前值
  J 判别力：打桩回退臂（no-op 写回 / 退回统一语义）→ 本脚本核心断言必须 FAIL
  K 窗口高度三态（折叠 / 展开 / 小屏 728）不退化 —— 阈值 = N3 改前实测基线

断言口径（硬要求）：一律比对**持久值**（layers[i]['anchor'] / layers[i]['flip'] /
cfg['side'] / cfg['flip_h']），**不依赖预览像素** —— `_preview_specs` 会用 var_flip
覆盖选中层的 flip，只看预览会掩盖「没写回」。主层 flip 的权威是 cfg['flip_h']。

红线：只读被测模块；不写真实 config.json / skin.json（save_config 打桩、SKINS_DIR
      指临时目录）；文件对话框与模态框全部打桩；R.HERE 指临时目录。

用法: python B_test_n3_side_per_layer.py
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

# ---- K 段阈值：N3 改前实测基线（96 DPI, 1080p）----
BASE_COLLAPSED_H = 607      # 折叠态窗口需求高
BASE_EXPANDED_H = 930       # 展开态窗口需求高
BASE_TOP_BLOCK_H = 419      # 通用区（含 ③ 那一行）需求高


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f'  [PASS] {name}' + (f'  ({detail})' if detail else ''))
    else:
        FAIL.append(name)
        print(f'  [FAIL] {name}' + (f'  ({detail})' if detail else ''))


def section(title):
    print(f'\n--- {title} ---')


def _fmt(v):
    return '[' + ', '.join(str(x) for x in v) + ']'


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


def _check_invoke(wiz, var):
    """点绑到 var 的 Checkbutton（真实 UI 通路）"""
    name = str(var)
    for w in _all_widgets(wiz.root):
        try:
            if w.winfo_class() == 'Checkbutton' and str(w.cget('variable')) == name:
                w.invoke()
                return True
        except Exception:
            pass
    return False


def _first_y(wiz, prefix):
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


# ==========================================================================
# 持久值读取（断言口径：只比对持久值，不看预览像素）
# ==========================================================================
def _anchors(wiz):
    return [str(ld.get('anchor')) for ld in (wiz.cfg.get('layers') or [])]


def _flips(wiz):
    """每层 flip 的**权威值**：第 0 层 = cfg['flip_h']，其余层 = layers[i]['flip']"""
    out = []
    for i, ld in enumerate(wiz.cfg.get('layers') or []):
        out.append(bool(wiz.cfg.get('flip_h')) if i == 0 else bool(ld.get('flip')))
    return out


def _persist(wiz):
    """(每层权威 anchor, 每层权威 flip, cfg[side], cfg[flip_h]) —— 一次打全"""
    ls = wiz.cfg.get('layers') or []
    anc = []
    for i, ld in enumerate(ls):
        if i == 0:
            anc.append(R.anchor_from_side(wiz.cfg.get('side')))
        else:
            anc.append(str(ld.get('anchor')))
    return anc, _flips(wiz), wiz.cfg.get('side'), bool(wiz.cfg.get('flip_h'))


def _multi_cfg(tmp):
    """3 层夹具：anchor 与 flip **各层都不同**（否则「只有某层变」的断言无判别力）"""
    a = _make_png(os.path.join(tmp, 'n3a.png'), (120, 180), (220, 60, 60, 255))
    b = _make_png(os.path.join(tmp, 'n3b.png'), (80, 200), (60, 90, 220, 255))
    c = _make_png(os.path.join(tmp, 'n3c.png'), (60, 60), (60, 200, 90, 255))
    return {'image': a, 'side': 'right', 'scale': 1.0, 'offset_x': 0, 'offset_y': 0,
            'flip_h': False,
            'layers': [{'image': a, 'anchor': 'right_edge', 'flip': False, 'z': 0},
                       {'image': b, 'anchor': 'left_edge', 'flip': True, 'z': 1},
                       {'image': c, 'anchor': 'center', 'flip': False, 'z': 2}]}


def _make_wiz(cfg, saved, expand=False):
    wiz = R.ConfigWizard(on_done=lambda c: saved.update(c), overlay=None)
    if cfg:
        wiz.cfg.update(cfg)
    wiz._layer_sync_from_cfg()
    wiz.root.update_idletasks()
    wiz.root.update()
    if expand:
        # N1 后向导默认折叠：量 ③ 行布局与窗口高必须先展开（判据表达式不因此改变）
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
# A. 结构：③ 与翻转各一处、在通用区、形态不变、文案标作用对象
# ==========================================================================
def test_structure(tmp, saved):
    section('A. 结构：③ 与翻转各只一处（通用区原位），图层区无第二套，文案标作用对象')
    wiz = _make_wiz(_multi_cfg(tmp), saved, expand=True)
    try:
        side_r = _radio_texts(wiz, wiz.var_side)
        anc_r = _radio_texts(wiz, wiz.var_layer_anchor)
        check('A01 ★③ 贴边方向只出现一处（通用区单选组 3 个）', len(side_r) == 3,
              f'var_side 单选={side_r}')
        check('A02 ★图层区没有第二套贴边单选（var_layer_anchor 无控件；未被换成下拉框）',
              len(anc_r) == 0 and not hasattr(wiz, 'cb_side_anchor'), f'var_layer_anchor 单选={anc_r}')
        flip_ws = [w for w in _all_widgets(wiz.root)
                   if w.winfo_class() == 'Checkbutton'
                   and str(w.cget('variable')) == str(wiz.var_flip)]
        in_general = bool(flip_ws) and any(_descendant(w, wiz.top_block) for w in flip_ws)
        check('A03 ★水平翻转只出现一处（通用区勾选框），未被换成下拉框',
              len(flip_ws) == 1 and in_general, f'勾选框={len(flip_ws)} 在通用区={in_general}')
        y2, y3, y4 = _first_y(wiz, '②'), _first_y(wiz, '③'), _first_y(wiz, '④')
        check('A04 ★③ 仍在通用区原位（② 候选框类型 与 ④ 缩放 之间）',
              None not in (y2, y3, y4) and y2 < y3 < y4, f'y2={y2} y3={y3} y4={y4}')
        side_titles = _texts_like(wiz, '③ 贴边方向')
        check('A05 ★③ 标题标出作用对象 = 当前层（含「第 N 层」，不再写「所有图层」）',
              any(('第' in t and '层) ' in t) or ('第' in t and '层）' in t) for t in side_titles)
              and not any('所有图层' in t for t in side_titles), repr(side_titles))
        flip_titles = _texts_like(wiz, '翻转（')
        check('A06 ★翻转文案标出作用对象 = 当前层（含「第 N 层」，不再写「所有图层」）',
              any('第' in t and '层' in t for t in flip_titles)
              and not any('所有图层' in t for t in flip_titles), repr(flip_titles))
        check('A07 通用区 ④⑤⑥ 仍在（只改语义，不误删）',
              hasattr(wiz, 'var_scale') and hasattr(wiz, 'var_offx')
              and hasattr(wiz, 'var_offy'))
    finally:
        _kill(wiz)


# ==========================================================================
# B. ③ 每层独立
# ==========================================================================
def test_side_per_layer(tmp, saved):
    section('B. ③ 每层独立：改第 i 层只动第 i 层 anchor（逐层前后值）')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        b = _anchors(wiz)
        check('B00 前置：夹具 3 层 anchor 各不相同（否则断言无判别力）',
              len(b) == 3 and len(set(b)) == 3, _fmt(b))
        _select(wiz, 1)
        before = _anchors(wiz)
        ok = _radio_invoke(wiz, wiz.var_side, '中')
        after = _anchors(wiz)
        print(f'    ③ 改第 2 层：anchor {_fmt(before)} → {_fmt(after)}')
        check('B01 ★选中第 2 层点 ③「中间」→ 只有第 2 层 anchor 变 center，其余层不变',
              ok and before == ['right_edge', 'left_edge', 'center']
              and after == ['right_edge', 'center', 'center'],
              f'点中={ok} {_fmt(before)} → {_fmt(after)}')
        check('B02 ★cfg[side] 不被非主层操作带偏（仍 = 主层值 right）',
              wiz.cfg.get('side') == 'right', repr(wiz.cfg.get('side')))
        print(f'    持久值：anchors={_fmt(_anchors(wiz))} side={wiz.cfg.get("side")!r}')

        _select(wiz, 2)
        b2 = _anchors(wiz)
        ok2 = _radio_invoke(wiz, wiz.var_side, '右')
        a2 = _anchors(wiz)
        print(f'    ③ 改第 3 层：anchor {_fmt(b2)} → {_fmt(a2)}')
        check('B03 ★选中第 3 层点 ③「右侧」→ 只有第 3 层变 right_edge，其余层不变',
              ok2 and b2 == ['right_edge', 'center', 'center']
              and a2 == ['right_edge', 'center', 'right_edge'],
              f'点中={ok2} {_fmt(b2)} → {_fmt(a2)}')

        _select(wiz, 0)
        b3 = _anchors(wiz)
        ok3 = _radio_invoke(wiz, wiz.var_side, '左')
        a3 = _anchors(wiz)
        print(f'    ③ 改主层：anchor {_fmt(b3)} → {_fmt(a3)}  side={wiz.cfg.get("side")!r}')
        check('B04 ★选中第 1 层（主层）点 ③「左侧」→ 第 1 层变 left_edge 且 cfg[side]=left，'
              '其余层不变',
              ok3 and b3 == ['right_edge', 'center', 'right_edge']
              and a3 == ['left_edge', 'center', 'right_edge']
              and wiz.cfg.get('side') == 'left',
              f'点中={ok3} {_fmt(b3)} → {_fmt(a3)} side={wiz.cfg.get("side")!r}')
    finally:
        _kill(wiz)


# ==========================================================================
# C. 翻转每层独立
# ==========================================================================
def test_flip_per_layer(tmp, saved):
    section('C. 水平翻转每层独立：改第 i 层只动第 i 层 flip（逐层前后值）')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        f = _flips(wiz)
        check('C00 前置：夹具 3 层 flip 不完全相同（否则断言无判别力）',
              len(f) == 3 and len(set(f)) > 1, _fmt(f))
        _select(wiz, 1)
        check('C01 切到第 2 层 → 勾选框回显该层值 True',
              bool(wiz.var_flip.get()) is True, repr(wiz.var_flip.get()))
        b = _flips(wiz)
        # 真实点击：Tk 的 Checkbutton.invoke() 会**切换**变量（当前 True → False 后再调 command）
        ok = _check_invoke(wiz, wiz.var_flip)
        a = _flips(wiz)
        print(f'    翻转第 2 层（真实点击取消）：flip {_fmt(b)} → {_fmt(a)}  '
              f'var_flip={wiz.var_flip.get()!r}')
        check('C02 ★选中第 2 层点翻转（真实点击取消）→ 只有第 2 层 flip 变 False，其余层不变',
              ok and b == [False, True, False] and a == [False, False, False]
              and bool(wiz.var_flip.get()) is False,
              f'点击={ok} {_fmt(b)} → {_fmt(a)} var_flip={wiz.var_flip.get()!r}')
        check('C03 ★cfg[flip_h]（主层值）不被非主层操作带偏（仍 False）',
              bool(wiz.cfg.get('flip_h')) is False, repr(wiz.cfg.get('flip_h')))
        print(f'    持久值：flips={_fmt(_flips(wiz))} cfg[flip_h]={wiz.cfg.get("flip_h")!r}')

        _select(wiz, 2)
        b2 = _flips(wiz)
        wiz.var_flip.set(True)
        wiz._on_flip_change()
        a2 = _flips(wiz)
        print(f'    翻转第 3 层：flip {_fmt(b2)} → {_fmt(a2)}')
        check('C04 ★选中第 3 层勾上翻转 → 只有第 3 层 flip 变 True，其余层不变',
              b2 == [False, False, False] and a2 == [False, False, True],
              f'{_fmt(b2)} → {_fmt(a2)}')

        _select(wiz, 0)
        b3 = _flips(wiz)
        wiz.var_flip.set(True)
        wiz._on_flip_change()
        a3 = _flips(wiz)
        print(f'    翻转主层：flip {_fmt(b3)} → {_fmt(a3)}  cfg[flip_h]={wiz.cfg.get("flip_h")!r}')
        check('C05 ★选中第 1 层（主层）勾上翻转 → 第 1 层变 True 且 cfg[flip_h]=True，'
              '其余层不变',
              b3 == [False, False, True] and a3 == [True, False, True]
              and bool(wiz.cfg.get('flip_h')) is True,
              f'{_fmt(b3)} → {_fmt(a3)} cfg[flip_h]={wiz.cfg.get("flip_h")!r}')
    finally:
        _kill(wiz)


# ==========================================================================
# D. 切层回显（3 轮）
# ==========================================================================
def test_switch_echo(tmp, saved):
    section('D. 切层回显：3 层值各不同，来回切 3 轮，③ 与翻转都回显该层值')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    expect_side = ['right', 'left', 'center']
    expect_flip = [False, True, False]
    try:
        good = True
        for rnd in range(3):
            for i in (0, 1, 2):
                _select(wiz, i)
                vs, vf = wiz.var_side.get(), bool(wiz.var_flip.get())
                if (vs, vf) != (expect_side[i], expect_flip[i]):
                    good = False
                    print(f'    轮{rnd + 1} 第{i + 1}层 回显异常：var_side={vs!r} var_flip={vf!r}')
                print(f'    轮{rnd + 1} 第{i + 1}层：var_side={vs!r} var_flip={vf!r} '
                      f'（期望 {expect_side[i]!r}/{expect_flip[i]!r}）')
        check('D01 ★切层回显（3 轮 ×3 层）：③ 与翻转都等于该层的持久值', good,
              f'期望 side={_fmt(expect_side)} flip={_fmt(expect_flip)}')
        anc, fl, sd, fl0 = _persist(wiz)
        check('D02 ★来回切 3 轮后各层持久值一个都没被改写',
              anc == ['right_edge', 'left_edge', 'center'] and fl == expect_flip
              and sd == 'right' and fl0 is False,
              f'anchors={_fmt(anc)} flips={_fmt(fl)} side={sd!r} flip_h={fl0!r}')
        check('D03 切层后图层区回显镜像 var_layer_anchor = 该层 anchor',
              all((_select(wiz, i) or True) and wiz.var_layer_anchor.get()
                  == (R.anchor_from_side(wiz.cfg.get('side')) if i == 0
                      else str(wiz.cfg['layers'][i].get('anchor')))
                  for i in (0, 1, 2)),
              repr(wiz.var_layer_anchor.get()))
    finally:
        _kill(wiz)


# ==========================================================================
# E. R2 断头路不回归（主层可改）
# ==========================================================================
def test_main_layer(tmp, saved):
    section('E. R2 断头路不回归：主层被选中时 ③ 与翻转都改得动')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        _select(wiz, 0)
        ok = _radio_invoke(wiz, wiz.var_side, '中')
        anc = _anchors(wiz)
        check('E01 ★主层：点 ③「中间」→ cfg[side]=center 且 layers[0].anchor=center',
              ok and wiz.cfg.get('side') == 'center' and anc[0] == 'center',
              f'点中={ok} side={wiz.cfg.get("side")!r} anchors={_fmt(anc)}')
        ok2 = _radio_invoke(wiz, wiz.var_side, '左')
        anc2 = _anchors(wiz)
        check('E02 ★主层：再点 ③「左侧」→ cfg[side]=left 且 layers[0].anchor=left_edge',
              ok2 and wiz.cfg.get('side') == 'left' and anc2[0] == 'left_edge',
              f'点中={ok2} side={wiz.cfg.get("side")!r} anchors={_fmt(anc2)}')
        _select(wiz, 0)
        okf = _check_invoke(wiz, wiz.var_flip)   # 真实点击：False → True 后调 command
        check('E03 ★主层：点翻转勾选框（真实点击）→ cfg[flip_h] 变 True（主层改得动）',
              okf and bool(wiz.cfg.get('flip_h')) is True
              and bool(wiz.var_flip.get()) is True,
              f'点击={okf} cfg[flip_h]={wiz.cfg.get("flip_h")!r} var={wiz.var_flip.get()!r}')
        check('E04 ★主层操作不影响其余层（第 2 层仍是左锚点、第 3 层仍是中锚点）',
              anc2[1] == 'left_edge' and anc2[2] == 'center',
              _fmt(anc2))
    finally:
        _kill(wiz)


def test_main_layer_flip(tmp, saved):
    """E03 的直读版：单独一条，避免上一条把「点击态」与「持久态」混在一句里"""
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        _select(wiz, 0)
        before = _flips(wiz)
        wiz.var_flip.set(True)
        wiz._on_flip_change()
        after = _flips(wiz)
        print(f'    主层翻转：flip {_fmt(before)} → {_fmt(after)}  '
              f'cfg[flip_h]={wiz.cfg.get("flip_h")!r}')
        check('E05 ★主层（第 0 层）翻转落地：flip[0] 与 cfg[flip_h] 同步变 True，其余层不变',
              before == [False, True, False] and after == [True, True, False]
              and bool(wiz.cfg.get('flip_h')) is True,
              f'{_fmt(before)} → {_fmt(after)} cfg[flip_h]={wiz.cfg.get("flip_h")!r}')
    finally:
        _kill(wiz)


# ==========================================================================
# F. 统一入口撤干净
# ==========================================================================
def test_unified_removed(tmp, saved):
    section('F. 统一入口撤干净：非 force 只信 cfg、绝不读 Tk 变量；别名不写全层')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        # 只改 Tk 变量（不点按钮）→ 两条非 force 入口都不许跟着 Tk 变量写全层
        wiz.var_side.set('center')
        wiz.var_flip.set(True)
        b_anc, b_flip, _s, _f = _persist(wiz)
        wiz._sync_side_to_all_layers()
        m_anc, _m_flip, _s2, _f2 = _persist(wiz)
        wiz._sync_flip_to_all_layers()
        a_anc, a_flip, sd, fl0 = _persist(wiz)
        print(f'    非 force 同步：anchor {_fmt(b_anc)} → {_fmt(a_anc)}；'
              f'flip {_fmt(b_flip)} → {_fmt(a_flip)}')
        check('F01 ★非 force `_sync_side_to_all_layers()` 不按 var_side 写全层'
              '（其余层一个大字都不动）',
              m_anc[1:] == b_anc[1:] == ['left_edge', 'center'],
              f'{_fmt(b_anc)} → {_fmt(m_anc)}（var_side 被置成 center）')
        check('F02 ★非 force 只信 cfg[side]：主层保底归一 = 顶层值 right_edge，'
              '而不是 Tk 变量 center',
              a_anc[0] == 'right_edge' and sd == 'right',
              f'l0={a_anc[0]!r} side={sd!r}（var_side={wiz.var_side.get()!r}）')
        check('F03 ★非 force `_sync_flip_to_all_layers()` 不按 var_flip 写全层'
              '（其余层不动、主层只保底归一到 cfg[flip_h]=False）',
              a_flip[1:] == b_flip[1:] == [True, False] and a_flip[0] is False
              and fl0 is False,
              f'{_fmt(b_flip)} → {_fmt(a_flip)}（var_flip 被置成 True）')
        # 兼容别名：不得写全层
        wiz.var_side.set('left')
        wiz._sync_side_to_layer0()
        n_anc, _n_flip, _s3, _f3 = _persist(wiz)
        check('F04 ★兼容别名 `_sync_side_to_layer0()` 不写全层（其余层保持各自值）',
              n_anc[1:] == ['left_edge', 'center'], _fmt(n_anc))
        check('F05 ★两个统一入口仍存在（老调用点/老脚本不断）',
              callable(getattr(R.ConfigWizard, '_sync_side_to_all_layers', None))
              and callable(getattr(R.ConfigWizard, '_sync_flip_to_all_layers', None)),
              '')
    finally:
        _kill(wiz)


# ==========================================================================
# G. 保存：顶层键取主层值（第 5 个串层点）
# ==========================================================================
def test_save(tmp, saved):
    section('G. 保存：顶层 side / flip_h 取**主层**值（第 5 个串层点）')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    try:
        _select(wiz, 1)                      # 选中第 2 层（非主层）
        _radio_invoke(wiz, wiz.var_side, '中')
        wiz.var_flip.set(True)
        wiz._on_flip_change()
        print(f'    保存前界面/持久：anchors={_fmt(_anchors(wiz))} '
              f'flips={_fmt(_flips(wiz))} side={wiz.cfg.get("side")!r} '
              f'flip_h={wiz.cfg.get("flip_h")!r}')
        saved.clear()
        wiz._save_and_start()
        out = dict(saved)
        lay = out.get('layers') or []
        o_anc = [x.get('anchor') for x in lay]
        o_flip = [bool(x.get('flip')) for x in lay]
        print(f'    落盘：side={out.get("side")!r} flip_h={out.get("flip_h")!r} '
              f'anchors={_fmt(o_anc)} flips={_fmt(o_flip)}')
        check('G01 ★保存后顶层 side = **主层**值 right（不是选中层第 2 层的 center）',
              out.get('side') == 'right', repr(out.get('side')))
        check('G02 ★保存后顶层 flip_h = **主层**值 False（不是选中层第 2 层的 True）',
              bool(out.get('flip_h')) is False, repr(out.get('flip_h')))
        check('G03 ★各层 anchor 逐层落盘 = 各自的界面值（第 2 层 center 保住了）',
              len(lay) == 3 and o_anc == ['right_edge', 'center', 'center'],
              _fmt(o_anc))
        check('G04 ★各层 flip 逐层落盘 = 各自的值（第 2 层 True 保住了、其余不受牵连）',
              len(lay) == 3 and o_flip == [False, True, False], _fmt(o_flip))
        check('G05 保存后主层 offset 归零（F-V3 不翻倍）',
              int(lay[0].get('offset_x', 999)) == 0
              and int(lay[0].get('offset_y', 999)) == 0 if lay else False,
              repr((lay[0].get('offset_x'), lay[0].get('offset_y')) if lay else None))
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('G00 保存段未抛异常', False, repr(e))
    finally:
        _kill(wiz)


# ==========================================================================
# H. 档案往返 / 切皮肤不归一 / 旧档案原样保留
# ==========================================================================
def test_skin_roundtrip(tmp, saved):
    section('H. 皮肤往返：切皮肤不归一、旧档案原样保留')
    real_skins = R.SKINS_DIR
    tmp_skins = os.path.join(tmp, 'skins_n3')
    os.makedirs(tmp_skins, exist_ok=True)
    wiz = None
    try:
        R.SKINS_DIR = tmp_skins
        a = _make_png(os.path.join(tmp, 'n3a.png'), (120, 180), (220, 60, 60, 255))
        b = _make_png(os.path.join(tmp, 'n3b.png'), (80, 200), (60, 90, 220, 255))
        c = _make_png(os.path.join(tmp, 'n3c.png'), (60, 60), (60, 200, 90, 255))
        R.save_skin('N3 每层各自贴边', {
            'image': a, 'side': 'left', 'scale': 1.0, 'flip_h': False,
            'layers': [{'image': a, 'anchor': 'left_edge', 'flip': False, 'z': 0},
                       {'image': b, 'anchor': 'right_edge', 'flip': True, 'z': 1},
                       {'image': c, 'anchor': 'center', 'flip': True, 'z': 2}]})
        back = R.find_skin('N3 每层各自贴边') or {}
        blay = back.get('layers') or []
        check('H01 ★档案 API 不做隐式改写（逐层读回原值）',
              [x.get('anchor') for x in blay] == ['left_edge', 'right_edge', 'center']
              and [bool(x.get('flip')) for x in blay] == [False, True, True],
              f'anchors={_fmt([x.get("anchor") for x in blay])} '
              f'flips={_fmt([bool(x.get("flip")) for x in blay])}')

        # 切皮肤：先把向导置成别样（第 2 层贴中、勾选翻转），再切到档案
        wiz = _make_wiz(_multi_cfg(tmp), saved)
        _select(wiz, 1)
        _radio_invoke(wiz, wiz.var_side, '中')
        wiz.var_flip.set(True)
        wiz._on_flip_change()
        wiz.skin_var.set('N3 每层各自贴边')
        wiz._apply_skin_to_wizard()
        anc, fl, sd, fl0 = _persist(wiz)
        print(f'    切皮肤后：anchors={_fmt(anc)} flips={_fmt(fl)} side={sd!r} flip_h={fl0!r}')
        check('H02 ★切皮肤后各层 anchor 逐层 = 档案值（**不再归一**到顶层 side）',
              anc == ['left_edge', 'right_edge', 'center'], _fmt(anc))
        check('H03 ★切皮肤后各层 flip 逐层 = 档案值（**不再归一**到顶层 flip_h）',
              fl == [False, True, True], _fmt(fl))
        _select(wiz, 1)
        check('H04 ★切皮肤后切到第 2 层：③ 与翻转回显该层档案值'
              '（不含上一个配置的残留）',
              wiz.var_side.get() == 'right' and bool(wiz.var_flip.get()) is True,
              f'var_side={wiz.var_side.get()!r} var_flip={wiz.var_flip.get()!r}')
        _select(wiz, 0)
        check('H05 ★切皮肤后切到第 1 层：③ 回显档案顶层 side=left',
              wiz.var_side.get() == 'left' and bool(wiz.var_flip.get()) is False,
              f'var_side={wiz.var_side.get()!r} var_flip={wiz.var_flip.get()!r}')

        # 旧档案原样保留：打开向导 + 重绘预览都不许静默改写
        wiz2 = _make_wiz(_multi_cfg(tmp), {})
        wiz2.root.update_idletasks()
        for _ in range(3):
            wiz2._update_preview()
        anc2, fl2, sd2, fl02 = _persist(wiz2)
        print(f'    旧档案（各层 anchor/flip 都不同）+ 3 次重绘后：'
              f'anchors={_fmt(anc2)} flips={_fmt(fl2)}')
        check('H06 ★旧档案原样保留：打开 + 3 次重绘预览后逐层 anchor/flip 一个没改',
              anc2 == ['right_edge', 'left_edge', 'center'] and fl2 == [False, True, False]
              and sd2 == 'right' and fl02 is False,
              f'anchors={_fmt(anc2)} flips={_fmt(fl2)} side={sd2!r} flip_h={fl02!r}')
        check('H07 ★旧档案主层仍与顶层 side 保底一致（保底归一仍在，不多不少）',
              anc2[0] == 'right_edge' and str((wiz2.cfg['layers'] or [{}])[0].get('anchor'))
              == 'right_edge', _fmt(anc2))

        # v1.6 老档案（无 layers）
        R.save_skin('N3 老档案单层', {'image': a, 'side': 'left', 'scale': 1.0})
        wiz3 = _make_wiz(_multi_cfg(tmp), {})
        wiz3.skin_var.set('N3 老档案单层')
        wiz3._apply_skin_to_wizard()
        lay3 = wiz3.cfg.get('layers') or []
        check('H08 ★v1.6 老档案（无 layers/schema）加载不报错，主层 anchor 与 side 一致',
              len(lay3) == 1 and lay3[0].get('anchor') == 'left_edge', _fmt(
                  [x.get('anchor') for x in lay3]))
        _kill(wiz3)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('H00 皮肤往返段未抛异常', False, repr(e))
    finally:
        _kill(wiz) if wiz is not None else None
        R.SKINS_DIR = real_skins


# ==========================================================================
# I. _layer_add：新层 anchor 与 flip 都取主层当前值
# ==========================================================================
def test_layer_add(tmp, saved):
    section('I. 加图层：新层的 anchor 与 flip 都取**主层当前值**（只影响新建层）')
    wiz = _make_wiz(_multi_cfg(tmp), saved)
    real_ask = R.filedialog.askopenfilename
    try:
        # 主层锚点改到 center、翻转开 True（都走真实通路）
        _select(wiz, 0)
        _radio_invoke(wiz, wiz.var_side, '中')
        wiz.var_flip.set(True)
        wiz._on_flip_change()
        newp = _make_png(os.path.join(tmp, 'n3d.png'), (70, 70), (200, 200, 60, 255))
        R.filedialog.askopenfilename = lambda *a, **k: newp
        wiz._layer_add()
        lay = wiz.cfg.get('layers') or []
        last = lay[-1] if lay else {}
        print(f'    主层 side={wiz.cfg.get("side")!r} flip_h={wiz.cfg.get("flip_h")!r} → '
              f'新层 anchor={last.get("anchor")!r} flip={bool(last.get("flip"))}')
        check('I01 ★新层 anchor = 主层当前值 center（不再恒为「另一侧」、也不受选中层影响）',
              len(lay) == 4 and last.get('anchor') == 'center', repr(last.get('anchor')))
        check('I02 ★新层 flip = 主层当前值 True', len(lay) == 4
              and bool(last.get('flip')) is True, repr(bool(last.get('flip'))))
        check('I03 ★加层不改动已有各层（前 3 层 anchor/flip 逐层不变）',
              [x.get('anchor') for x in lay[:3]] == ['center', 'left_edge', 'center']
              and [bool(x.get('flip')) for x in lay[:3]] == [True, True, False]
              if len(lay) == 4 else False,
              f'{_fmt([x.get("anchor") for x in lay[:3]])} '
              f'{_fmt([bool(x.get("flip")) for x in lay[:3]])}')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('I00 加层段未抛异常', False, repr(e))
    finally:
        R.filedialog.askopenfilename = real_ask
        _kill(wiz)


# ==========================================================================
# J. 判别力：打桩回退臂
# ==========================================================================
def test_discriminating(tmp, saved):
    section('J. 判别力：打桩回退臂（no-op 写回 / 退回统一语义）→ 核心断言必须 FAIL')
    # J01：把写回路径打桩成 no-op → 「只有第 2 层变」不成立
    real_set = R.ConfigWizard._layer_set_params
    wiz = None
    try:
        R.ConfigWizard._layer_set_params = lambda self, *a, **k: False
        wiz = _make_wiz(_multi_cfg(tmp), saved)
        _select(wiz, 1)
        _radio_invoke(wiz, wiz.var_side, '中')
        anc = _anchors(wiz)
        print(f'    打桩 no-op 后点 ③：anchors={_fmt(anc)}')
        check('J01 ★判别力：`_layer_set_params` 打桩成 no-op →「只有第 2 层变 center」不成立'
              '（证明 B01 非恒真）',
              not (anc[1] == 'center'), _fmt(anc))
    except Exception as e:
        check('J01 ★判别力：`_layer_set_params` 打桩成 no-op →「只有第 2 层变 center」不成立'
              '（证明 B01 非恒真）', False, repr(e))
    finally:
        R.ConfigWizard._layer_set_params = real_set
        _kill(wiz) if wiz is not None else None

    # J02：把 ③ 的 command 退回「统一语义」（写全部层）→ 「其余层不变」不成立
    real_cmd = R.ConfigWizard._on_side_change

    def _legacy_unified(self):
        i = getattr(self, '_cur_layer_index', lambda: 0)()
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
        print(f'    退回统一语义后点 ③：anchors={_fmt(anc2)}')
        check('J02 ★判别力：③ 退回「写全部层」→「其余层不变」不成立（证明 B01 非恒真）',
              not (anc2[1:] == ['left_edge', 'center']), _fmt(anc2))
    except Exception as e:
        check('J02 ★判别力：③ 退回「写全部层」→「其余层不变」不成立（证明 B01 非恒真）',
              False, repr(e))
    finally:
        R.ConfigWizard._on_side_change = real_cmd
        _kill(wiz2) if wiz2 is not None else None

    # J03：把翻转退回「统一语义」→ 「其余层 flip 不变」不成立
    real_flip = R.ConfigWizard._on_flip_change

    def _legacy_flip(self):
        want = bool(self.var_flip.get())
        self.cfg['flip_h'] = want
        for ld in (self.cfg.get('layers') or []):
            ld['flip'] = want
        self._update_preview()

    wiz3 = None
    try:
        R.ConfigWizard._on_flip_change = _legacy_flip
        wiz3 = _make_wiz(_multi_cfg(tmp), saved)
        _select(wiz3, 1)
        before3 = _flips(wiz3)
        wiz3.var_flip.set(False)
        wiz3._on_flip_change()
        fl = _flips(wiz3)
        print(f'    退回统一翻转后：flips {_fmt(before3)} → {_fmt(fl)}')
        check('J03 ★判别力：翻转退回「写全部层」→「其余层 flip 不变」不成立'
              '（证明 C02 非恒真）',
              not (fl[1:] == before3[1:]), f'{_fmt(before3)} → {_fmt(fl)}')
    except Exception as e:
        check('J03 ★判别力：翻转退回「写全部层」→「其余层 flip 不变」不成立'
              '（证明 C02 非恒真）', False, repr(e))
    finally:
        R.ConfigWizard._on_flip_change = real_flip
        _kill(wiz3) if wiz3 is not None else None


# ==========================================================================
# K. 窗口高度三态（阈值 = 改前实测基线，不许变大）
# ==========================================================================
_SAVED_SCREEN = []


def _probe(work_h=None, work_w=None, cfg=None):
    if not _SAVED_SCREEN:
        _SAVED_SCREEN.append((R.screen_work_area_height, R.screen_work_area,
                              R.screen_work_area_width))
    if work_h is not None:
        R.screen_work_area_height = lambda root=None: int(work_h)
        R.screen_work_area = lambda root=None: (0, int(work_h))
    else:
        (R.screen_work_area_height, R.screen_work_area,
         R.screen_work_area_width) = _SAVED_SCREEN[0]
    if work_w is not None:
        R.screen_work_area_width = lambda root=None: int(work_w)
    saved = {}
    wiz = _make_wiz(cfg, saved)
    return wiz


def _restore_screen():
    if _SAVED_SCREEN:
        (R.screen_work_area_height, R.screen_work_area,
         R.screen_work_area_width) = _SAVED_SCREEN[0]


def _toggle(wiz, collapse):
    fn = getattr(wiz, '_toggle_adv_collapse', None)
    if fn is None:
        return False
    try:
        fn(collapse)
        wiz.root.update_idletasks()
        wiz.root.update()
        return True
    except Exception:
        return False


def test_heights(tmp, saved):
    section('K. 窗口高度三态（折叠 / 展开 / 小屏 728）：不许超过 N3 改前基线')
    cfg = _multi_cfg(tmp)
    wiz = None
    try:
        wiz = _probe(None, None, cfg)
        col = int(wiz.root.winfo_reqheight())          # N1 后默认折叠
        top_col = int(wiz.top_block.winfo_reqheight())
        ok = _toggle(wiz, False)
        exp = int(wiz.root.winfo_reqheight())
        top_exp = int(wiz.top_block.winfo_reqheight())
        _toggle(wiz, True)
        col2 = int(wiz.root.winfo_reqheight())
        print(f'    1080p 折叠={col}px（基线 {BASE_COLLAPSED_H}） 展开={exp}px'
              f'（基线 {BASE_EXPANDED_H}） 往返后折叠={col2}px')
        print(f'    通用区 top_block：折叠={top_col}px 展开={top_exp}px'
              f'（基线 {BASE_TOP_BLOCK_H}）')
        check('K01 ★折叠态窗口需求高不退化（≤ 改前基线 607px）', col <= BASE_COLLAPSED_H,
              f'{col} ≤ {BASE_COLLAPSED_H}')
        check('K02 ★展开态窗口需求高不退化（≤ 改前基线 930px）', ok and exp <= BASE_EXPANDED_H,
              f'{exp} ≤ {BASE_EXPANDED_H}')
        check('K03 ★折叠↔展开往返后折叠态回收（±2px 内回到初值）',
              abs(col2 - col) <= 2, f'{col} → {col2}')
        check('K04 ★③ 所在的通用区块高度不增（≤ 改前基线 419px，两态都算）',
              top_col <= BASE_TOP_BLOCK_H and top_exp <= BASE_TOP_BLOCK_H,
              f'折叠={top_col} 展开={top_exp} ≤ {BASE_TOP_BLOCK_H}')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('K00 高度段未抛异常', False, repr(e))
    finally:
        _kill(wiz) if wiz is not None else None
        _restore_screen()

    # 小屏 1366x768（工作区 728）
    wiz2 = None
    try:
        wiz2 = _probe(728, 1366, cfg)
        _toggle(wiz2, False)
        exp2 = int(wiz2.root.winfo_reqheight())
        need2 = bool(getattr(wiz2, '_scroll_needed', False))
        _toggle(wiz2, True)
        col3 = int(wiz2.root.winfo_reqheight())
        need3 = bool(getattr(wiz2, '_scroll_needed', False))
        print(f'    小屏 728：展开={exp2}px scroll_needed={need2}；'
              f'折叠={col3}px scroll_needed={need3}')
        check('K05 ★小屏 728 折叠态放得下且不滚动（≤ 728px 且 _scroll_needed=False）',
              col3 <= 728 and not need3, f'{col3}px scroll_needed={need3}')
        check('K06 ★判别力：小屏 728 展开态仍超出工作区（_scroll_needed=True，'
              '说明 K05 不是恒真）', exp2 > 728 and need2,
              f'{exp2}px scroll_needed={need2}')
        check('K07 ★小屏折叠态窗口高不退化（≤ 改前基线 607px）', col3 <= BASE_COLLAPSED_H,
              f'{col3} ≤ {BASE_COLLAPSED_H}')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('K05 ★小屏 728 折叠态放得下且不滚动', False, repr(e))
    finally:
        _kill(wiz2) if wiz2 is not None else None
        _restore_screen()


# ==========================================================================
def main():
    print('=== B_test_n3_side_per_layer：N3 ③ 贴边 + 水平翻转 = 按当前选中层分别调 ===')
    print('Python', sys.version.split()[0])
    tmp = tempfile.mkdtemp(prefix='n3_side_')
    R.HERE = tmp      # 只读约束（HANDOFF-2.1 §8.5）：日志/临时产物只落临时目录
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
            for t, cnt in (('A', 7), ('B', 4), ('C', 5), ('D', 3), ('E', 5), ('F', 5),
                           ('G', 5), ('H', 8), ('I', 3), ('J', 3), ('K', 7)):
                for i in range(1, cnt + 1):
                    SKIPPED.append(f'{t}{i:02d}')
                    print(f'  [SKIP] {t}{i:02d}  (无桌面环境（GUI 不可用）)')
        else:
            test_structure(tmp, saved)
            test_side_per_layer(tmp, saved)
            test_flip_per_layer(tmp, saved)
            test_switch_echo(tmp, saved)
            test_main_layer(tmp, saved)
            test_main_layer_flip(tmp, saved)
            test_unified_removed(tmp, saved)
            test_save(tmp, saved)
            test_skin_roundtrip(tmp, saved)
            test_layer_add(tmp, saved)
            test_discriminating(tmp, saved)
            test_heights(tmp, saved)
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
