# -*- coding: utf-8 -*-
"""B_test_r12_collapse.py —— ⚙ 高级设置：可折叠 + 大按钮 + 默认折叠

R12（`80762e7`）建立本脚本：用户第三轮原话「"高级设置"那个位置是否可做成折叠按钮，点一下弹出/折叠。」
→ ⚙ 高级设置（⑧~⑭）整块可折叠：点标题行展开/折叠；折叠后窗口需求高度明显下降，
  且折叠态不出滚动条、底部按钮行仍在窗内；再展开时 ②~⑭ 控件一个不少可操作。

第四轮 N1（用户原话「折叠按钮做大点；默认折叠状态。」）**改写了取样前提**：
  · 初态由「展开」改成「**折叠**」（向导打开就是矮的那一版）；
  · 标题按钮做成**够大的可点区域**（高度 ≥30px，面积相对 R12 实测基线 ≥ +40%）。
改写原则（沿用 R11/R12 的规矩）：**不删整段、不改恒真、不降判别力** ——
  ① 所有「折叠前/折叠后」对照先显式展开取基准（原来靠「初态即展开」这个隐含前提）；
  ② 「点一次按钮」的判据方向整体翻转（点一次 = 展开，再点一次 = 折叠）；
  ③ 新增 G 段（按钮尺寸）与 D 段的「两向往返各 2 次」；F 段判别力保留。
旧前提失效的证据由 `_evidence_r15/N1_btn/run_r12_premise_check.py` 给：
  同一份本脚本跑「R12 旧实现」必须 FAIL（新判据在旧实现下不成立），跑「新实现」必须 PASS。

验收段：
  A 就位：折叠按钮 / 内容容器 / 初态折叠 / 文案 ▸
  B 高度量化：折叠前后 body_inner、窗口需求高、adv_area 三段数字 + 折叠态窗口高不退化
  C 折叠态可用性：小屏 728 折叠后不出滚动条、底部按钮行仍在窗内、窗口变矮
  D 两向往返各 2 次：高度回初值（±2px）、状态位复位、无鬼影/空白、不粘滞
  E 展开态控件齐全：②~⑭ 一个不少、展开后全部可见可点、列数不变
  F 判别力：禁用折叠执行点后「高度明显下降」必须不成立（证明 B 段断言不是恒真）
  G 按钮尺寸：高度 ≥30px、面积相对 R12 基线 ≥ +40%、折叠态可见可点

红线：只读被测模块；不写真实 config.json / skin.json（save_config 打桩）；
      文件对话框与模态框全部打桩；R.HERE 指向临时目录（不碰项目 error.log）。

用法: python B_test_r12_collapse.py
"""
import os
import sys
import shutil
import tempfile

# 控制台编码保护：GBK 控制台下打印 ④/★ 等字符会 UnicodeEncodeError 并让脚本 exit≠0
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R          # noqa: E402

PASS, FAIL, SKIPPED = [], [], []

# --- R12 实测基线（本机 1080p / 96dpi，见 _evidence_r15/N1_btn/n1_btn_*.json）------
R12_BTN_H = 26            # R12 标题按钮高：9pt 无内边距 → 26px
R12_BTN_AREA = 7046       # R12 标题按钮面积：展开态 271×26 px²（折叠态 219×26 = 5694）
R12_BTN_W = 271           # R12 标题按钮宽（展开态文案）
R12_COLLAPSED_WIN_H = 590  # R12 折叠态窗口需求高
MIN_BTN_H = 30            # N1 验收：按钮高度 ≥ 30px
MIN_BTN_GAIN = 1.40       # N1 验收：面积相对 R12 基线 +40%


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


def _descendant(w, anc):
    """w 是否在 anc 的子树里（沿 master 链向上找）"""
    cur = w
    while cur is not None:
        if cur is anc:
            return True
        try:
            cur = cur.master
        except Exception:
            return False
    return False


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


def _first_y(wiz, prefix):
    """窗口里所有以 prefix 开头的控件的最小屏幕 y"""
    ys = []
    for w in _all_widgets(wiz.root):
        try:
            if w.winfo_class() in ('Label', 'Button', 'Checkbutton', 'Radiobutton'):
                if str(w.cget('text')).startswith(prefix):
                    ys.append(int(w.winfo_rooty()))
        except Exception:
            pass
    return min(ys) if ys else None


def _radio_invoke(wiz, var, contains):
    """按文案点某个 Radiobutton（走真实 UI 通路）"""
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


def _in_body(wiz, w):
    try:
        return _descendant(w, wiz.body_inner)
    except Exception:
        return False


_SAVED_STUB = []


def _wiz_probe(work_h, work_w, cfg=None):
    """建向导（可注入工作区高/宽）→ 返回 (wiz, real_fn 元组)"""
    if not _SAVED_STUB:
        _SAVED_STUB.append((R.screen_work_area_height, R.screen_work_area,
                            R.screen_work_area_width))
    if work_h is not None:
        R.screen_work_area_height = lambda root=None: int(work_h)
        R.screen_work_area = lambda root=None: (0, int(work_h))
    if work_w is not None:
        R.screen_work_area_width = lambda root=None: int(work_w)
    done = {}
    wiz = R.ConfigWizard(on_done=lambda c: done.update(c), overlay=None)
    if cfg:
        wiz.cfg.update(cfg)
        wiz._layer_sync_from_cfg()
    wiz.root.update_idletasks()
    wiz.root.update()
    return wiz, _SAVED_STUB[0]


def _restore(real):
    (R.screen_work_area_height, R.screen_work_area, R.screen_work_area_width) = real


def _kill(wiz):
    try:
        wiz.root.destroy()
    except Exception:
        pass


def _packed(w):
    """控件是否被 pack 管理器持有（折叠 = pack_forget → info 为空 dict）"""
    try:
        return bool(w.pack_info())
    except Exception:
        return False


def _heights(wiz):
    """(body_inner, 窗口需求高, adv_area) 三段需求高度（控件缺失时该段记 0，不抛异常）"""
    wiz.root.update_idletasks()
    bi = getattr(wiz, 'body_inner', None)
    aa = getattr(wiz, 'adv_area', None)
    return (int(bi.winfo_reqheight()) if bi is not None else 0,
            int(wiz.root.winfo_reqheight()),
            int(aa.winfo_reqheight()) if aa is not None else 0)


def _toggle(wiz, collapse):
    """调用折叠开关：未实现/异常时返回 False（红阶段也要能跑完并报 FAIL，而不是崩）"""
    fn = getattr(wiz, '_toggle_adv_collapse', None)
    if fn is None:
        return False
    try:
        fn(bool(collapse))
        wiz.root.update_idletasks()
        return True
    except Exception:
        return False


def _btn_box(wiz):
    """折叠按钮的真实几何 (w, h)，未 map 时退回需求尺寸（红阶段也能给出数字）"""
    btn = getattr(wiz, 'btn_adv_toggle', None)
    if btn is None:
        return (0, 0)
    wiz.root.update_idletasks()
    w, h = int(btn.winfo_width()), int(btn.winfo_height())
    if w <= 1 or h <= 1:
        w, h = int(btn.winfo_reqwidth()), int(btn.winfo_reqheight())
    return (w, h)


def _btn_row_bottom(wiz):
    """底部按钮行的底边（客户区坐标）与窗口客户区底边"""
    wiz.root.update_idletasks()
    row = wiz.btn_row
    return (int(row.winfo_rooty()) + int(row.winfo_height()),
            int(wiz.root.winfo_rooty()) + int(wiz.root.winfo_height()))


# ==========================================================================
# A. 就位与初态（N1：初态 = 折叠）
# ==========================================================================
def test_structure(tmp, saved):
    section('A. 就位：⚙ 高级设置折叠按钮 / 内容容器 / 初态折叠（N1）')
    wiz, real = _wiz_probe(None, None, {'image': _make_png(os.path.join(tmp, 'r12.png'))})
    try:
        btn = getattr(wiz, 'btn_adv_toggle', None)
        body = getattr(wiz, 'adv_body', None)
        check('A01 ★有「⚙ 高级设置」折叠按钮（btn_adv_toggle）',
              btn is not None and btn.winfo_class() == 'Button',
              f'class={btn.winfo_class() if btn is not None else None}')
        check('A02 ★有可折叠的内容容器（adv_body）', body is not None, '')
        # N1 改写（旧判据「初态是展开的」在默认折叠下必然不成立）
        check('A03 ★初态是折叠的（_adv_collapsed=True 且 adv_body 未 pack 未 map）',
              getattr(wiz, '_adv_collapsed', None) is True
              and body is not None and not _packed(body)
              and int(body.winfo_ismapped()) == 0,
              f'_adv_collapsed={getattr(wiz, "_adv_collapsed", None)} '
              f'packed={_packed(body) if body is not None else "?"} '
              f'mapped={int(body.winfo_ismapped()) if body is not None else "?"}')
        txt = str(btn.cget('text')) if btn is not None else ''
        check('A03b ★折叠态文案是 ▸ 态（点这里展开）',
              '▸' in txt and '展开' in txt, repr(txt))
        check('A04 折叠按钮文案带箭头与提示（点一下折叠/展开）',
              ('▾' in txt or '▸' in txt) and ('高级设置' in txt),
              repr(txt))
        check('A05 折叠按钮在可滚动内容里（跟内容一起滚，不会飘）',
              btn is not None and _in_body(wiz, btn), '')
        cols = list(getattr(wiz, 'adv_cols', []) or [])
        check('A06 各列容器挂在 adv_body 下面（折叠时一起收起）',
              bool(cols) and all(body is not None and _descendant(c, body) for c in cols),
              f'列数={len(cols)}')
        # 真实通路：点标题按钮一次 = 展开（N1 起初态是折叠）
        before = _packed(body)
        try:
            btn.invoke()
            wiz.root.update_idletasks()
        except Exception:
            pass
        after = _packed(body)
        check('A07 ★点标题按钮一次 = 展开（真实 UI 通路，不靠直接调方法）',
              not before and after,
              f'packed {before} → {after}；adv_body mapped={int(body.winfo_ismapped())}')
        check('A08 展开后按钮文案改成「点这里折叠」（▾ 态）',
              ('▾' in str(btn.cget('text')) and '折叠' in str(btn.cget('text')))
              if btn is not None else False,
              repr(str(btn.cget('text')) if btn is not None else ''))
        # 折叠态按钮行可见（N1 验收：按钮行在折叠态可见）
        _toggle(wiz, True)
        wiz.root.update_idletasks()
        wiz.root.update()
        check('A09 ★折叠态标题按钮仍可见可点（winfo_ismapped=1 / state=normal）',
              btn is not None and int(btn.winfo_ismapped()) == 1
              and str(btn.cget('state')) == 'normal',
              f'mapped={int(btn.winfo_ismapped()) if btn is not None else "?"} '
              f'state={str(btn.cget("state")) if btn is not None else "?"}')
        _toggle(wiz, False)
    finally:
        _restore(real)
        _kill(wiz)


# ==========================================================================
# B. 高度量化：折叠前后三段数字
# ==========================================================================
def test_heights(tmp, saved):
    section('B. 高度量化：折叠后窗口需求高度明显下降（打印前后数字）')
    wiz, real = _wiz_probe(None, None, {'image': _make_png(os.path.join(tmp, 'r12b.png'))})
    try:
        # N1 改写：先显式展开取「折叠前」基准（初态已是折叠）
        ok0 = _toggle(wiz, False)
        b0, r0, a0 = _heights(wiz)
        bw, bh = _btn_box(wiz)
        ok = _toggle(wiz, True)
        b1, r1, a1 = _heights(wiz)
        cw, ch = _btn_box(wiz)
        print(f'    折叠前：body_inner={b0}px  窗口需求高={r0}px  adv_area={a0}px  按钮={bw}×{bh}')
        print(f'    折叠后：body_inner={b1}px  窗口需求高={r1}px  adv_area={a1}px  按钮={cw}×{ch}')
        print(f'    收益：窗口 −{r0 - r1}px（{100.0 * (r0 - r1) / max(1, r0):.1f}%）  '
              f'内容 −{b0 - b1}px  adv −{a0 - a1}px')
        print(f'    R12 基线：折叠态窗口 {R12_COLLAPSED_WIN_H}px ｜ 按钮 {R12_BTN_W}×{R12_BTN_H} '
              f'（{R12_BTN_AREA} px²）')
        check('B01 ★折叠后内容需求高度明显下降（≥100px）',
              ok0 and ok and (b0 - b1) >= 100,
              f'{b0} → {b1}（−{b0 - b1}px） 折叠开关={ok0}/{ok}')
        check('B02 ★折叠后窗口需求高度明显下降（≥100px）', ok and (r0 - r1) >= 100,
              f'{r0} → {r1}（−{r0 - r1}px）')
        check('B03 ★折叠态 adv_area 只剩标题行（≤60px）', ok and 0 < a1 <= 60,
              f'adv={a1}px')
        check('B04 折叠态窗口需求高 ≤ 工作区（1040）', r1 <= 1040, f'{r1}px')
        # N1 验收：折叠态窗口高不退化（允许的增量 ≤ 按钮自身增高量）
        allow = R12_COLLAPSED_WIN_H + max(0, ch - R12_BTN_H)
        check('B05 ★折叠态窗口高不退化（≤ R12 基线 590px + 按钮增高量）',
              ok and r1 <= allow,
              f'折叠态窗口={r1}px ≤ 允许 {allow}px（R12 基线 {R12_COLLAPSED_WIN_H} + '
              f'按钮增高 {max(0, ch - R12_BTN_H)}）')
    finally:
        _restore(real)
        _kill(wiz)


# ==========================================================================
# C. 折叠态可用性
# ==========================================================================
def test_collapsed_usable(tmp, saved):
    section('C. 折叠态可用性：不出滚动条 / 按钮行仍在窗内 / 窗口变矮')
    img = _make_png(os.path.join(tmp, 'r12c.png'))
    # 小屏 1366x768（工作区 728）：展开态放不下必出滚动条 → 折叠后必须收掉
    wiz, real = _wiz_probe(728, 1366, {'image': img})
    try:
        # N1 改写：先显式展开（初态折叠时「折叠后不该有滚动条」没有判别力）
        _toggle(wiz, False)
        wiz.root.update_idletasks()
        wiz.root.update()
        need_expand = getattr(wiz, '_scroll_needed', None)
        ok = _toggle(wiz, True)
        wiz.root.update_idletasks()
        wiz.root.update()
        need_collapse = getattr(wiz, '_scroll_needed', None)
        check('C00 前置：小屏 728 下展开态确实要滚动（否则本段无判别力）',
              need_expand is True, f'_scroll_needed={need_expand}')
        check('C01 ★折叠态不出滚动条（_scroll_needed=False）', ok and need_collapse is False,
              f'折叠开关={ok} _scroll_needed={need_collapse}')
        try:
            sb_mapped = bool(wiz.body_scrollbar.winfo_ismapped())
        except Exception:
            sb_mapped = None
        check('C02 ★折叠态滚动条未显示（未 map）', sb_mapped is False, f'mapped={sb_mapped}')
        rb, wb = _btn_row_bottom(wiz)
        check('C03 ★折叠态底部按钮行仍在窗内（按钮行底边 ≤ 客户区底边）', rb <= wb,
              f'row_bottom={rb} win_bottom={wb}')
    finally:
        _restore(real)
        _kill(wiz)

    # 1080p：折叠后窗口实际高度应比展开矮
    wiz2, real2 = _wiz_probe(None, None, {'image': img})
    try:
        _toggle(wiz2, False)
        wiz2.root.update_idletasks()
        wiz2.root.update()
        h_expand = int(wiz2.root.winfo_height())
        ok = _toggle(wiz2, True)
        wiz2.root.update_idletasks()
        wiz2.root.update()
        h_collapse = int(wiz2.root.winfo_height())
        check('C04 ★折叠后窗口实际高度变小（1080p）', ok and h_collapse < h_expand,
              f'{h_expand} → {h_collapse}（−{h_expand - h_collapse}px）')
        rb2, wb2 = _btn_row_bottom(wiz2)
        check('C05 折叠态按钮行仍在窗内（1080p）', rb2 <= wb2,
              f'row_bottom={rb2} win_bottom={wb2}')
    finally:
        _restore(real2)
        _kill(wiz2)


# ==========================================================================
# D. 两向往返各 2 次
# ==========================================================================
def test_round_trip(tmp, saved):
    section('D. 折叠 ⇄ 展开 两向往返各 2 次：回到原状，不粘滞、不留鬼影/空白')
    wiz, real = _wiz_probe(None, None, {'image': _make_png(os.path.join(tmp, 'r12d.png'))})
    try:
        # N1 改写：先展开取基准（初态折叠）
        _toggle(wiz, False)
        wiz.root.update_idletasks()
        wiz.root.update()
        b0, r0, a0 = _heights(wiz)
        hw0 = int(wiz.root.winfo_height())
        rounds = []
        both_ok = True
        for _i in range(2):
            ok1 = _toggle(wiz, True)
            wiz.root.update_idletasks()
            packed_c = _packed(getattr(wiz, 'adv_body', None))
            b1, r1, a1 = _heights(wiz)
            ok2 = _toggle(wiz, False)
            wiz.root.update_idletasks()
            wiz.root.update()
            b2, r2, a2 = _heights(wiz)
            both_ok = both_ok and ok1 and ok2
            rounds.append({'closed': (b1, r1, a1), 'closed_packed': packed_c,
                           'open': (b2, r2, a2)})
        print(f'    初值（展开）: ({b0},{r0},{a0})  窗口实际高={hw0}')
        for i, rd in enumerate(rounds, 1):
            print(f'    第 {i} 次往返：折叠 {rd["closed"]}（packed={rd["closed_packed"]}）'
                  f' → 展开 {rd["open"]}')
        o1, o2 = rounds[0]['open'], rounds[1]['open']
        check('D01 ★第 1 次往返：展开态三段高度回初值（±2px）',
              both_ok and abs(o1[0] - b0) <= 2 and abs(o1[1] - r0) <= 2 and abs(o1[2] - a0) <= 2,
              f'({b0},{r0},{a0}) → {o1}')
        check('D02 ★第 2 次往返：仍然回初值（±2px，不粘滞）',
              both_ok and abs(o2[0] - b0) <= 2 and abs(o2[1] - r0) <= 2 and abs(o2[2] - a0) <= 2,
              f'({b0},{r0},{a0}) → {o2}')
        check('D03 ★每次折叠都真的收起了内容区（pack_forget，无残留）',
              all(rd['closed_packed'] is False for rd in rounds),
              f'packed={[rd["closed_packed"] for rd in rounds]}')
        check('D04 ★末态状态位复位（_adv_collapsed=False）且内容容器重新 pack',
              getattr(wiz, '_adv_collapsed', None) is False
              and _packed(getattr(wiz, 'adv_body', None)),
              f'_adv_collapsed={getattr(wiz, "_adv_collapsed", None)} '
              f'packed={_packed(getattr(wiz, "adv_body", None))}')
        cols = list(getattr(wiz, 'adv_cols', []) or [])
        check('D05 展开后各列容器高度非零（真的画出来了）',
              bool(cols) and all(int(c.winfo_reqheight()) > 0 for c in cols),
              f'列高={[int(c.winfo_reqheight()) for c in cols]}')
        btn = getattr(wiz, 'btn_adv_toggle', None)
        check('D06 ★末态文案回到 ▾ 折叠态（两向往返不粘滞在错误文案上）',
              btn is not None and '▾' in str(btn.cget('text')) and '折叠' in str(btn.cget('text')),
              repr(str(btn.cget('text')) if btn is not None else ''))
        hw1 = int(wiz.root.winfo_height())
        check('D07 ★末态窗口实际高度回到展开态（±2px）', abs(hw1 - hw0) <= 2,
              f'{hw0} → {hw1}')
    finally:
        _restore(real)
        _kill(wiz)


# ==========================================================================
# E. 展开态控件齐全可操作
# ==========================================================================
def test_expanded_inventory(tmp, saved):
    section('E. 展开态：②~⑭ 一个不少、展开后全部可见可点、列数不变')
    wiz, real = _wiz_probe(None, None, {'image': _make_png(os.path.join(tmp, 'r12e.png'))})
    try:
        _toggle(wiz, False)      # N1：初态折叠 → 先展开
        wiz.root.update_idletasks()
        wiz.root.update()
        names = ('var_layout', 'var_side', 'var_scale', 'var_offx', 'var_offy',
                 'var_layer', 'var_corner', 'var_corner_r', 'var_feather', 'var_feather_r',
                 'var_alpha_feather', 'var_render', 'layer_list', 'btn_layer_add',
                 'btn_layer_del', 'var_lay_follow', 'skin_cb', 'btn_scheme',
                 'var_autostart')
        miss = [n for n in names if not hasattr(wiz, n)]
        check('E01 ★展开态关键控件一个不少（19 个）', not miss, f'缺={miss}')
        widgets = ('canvas', 'layer_list', 'skin_cb', 'chk_feather', 'lbl_autostart',
                   'btn_adv_toggle')
        try:
            wids = [getattr(wiz, n) for n in widgets]
        except Exception as e:
            wids = []
            check('E02 ★关键控件都在滚动内容里', False, repr(e))
        if wids:
            check('E02 ★关键控件都在滚动内容里（不是游离在窗口外）',
                  all(_in_body(wiz, w) for w in wids), '')
        n_cols = len(list(getattr(wiz, 'adv_cols', []) or []))
        want = int(wiz._adv_column_count())
        check('E03 ★列数与 _adv_column_count 一致（折叠不改变横排布局）',
              n_cols == want, f'{n_cols} vs {want}')
        btn = getattr(wiz, 'btn_adv_toggle', None)
        try:
            st = str(btn.cget('state')) if btn is not None else ''
        except Exception:
            st = ''
        check('E04 折叠按钮可点（state=normal）', st == 'normal', st)
        # N1 新增：展开后 ⑧~⑭ 的控件必须**真的可见**（不是「存在但收着」）
        cols = list(getattr(wiz, 'adv_cols', []) or [])
        mapped = [sum(1 for ch in c.winfo_children() if int(ch.winfo_ismapped())) for c in cols]
        total = sum(len(c.winfo_children()) for c in cols)
        check('E05 ★展开后各列子控件全部可见（winfo_ismapped=1）',
              total > 0 and sum(mapped) == total,
              f'可见/总数={sum(mapped)}/{total} 分列={mapped}')
        # 折叠 → 展开后控件仍可操作（列表可选中、滑条可写）
        ok = _toggle(wiz, True)
        ok2 = _toggle(wiz, False)
        wiz.root.update_idletasks()
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(0)
        wiz._on_layer_select()
        wiz.var_offy.set(12)
        wiz._on_main_slider()
        check('E06 折叠再展开后控件仍可操作（列表可选中 + 滑条可写）',
              ok and ok2 and int(wiz.cfg.get('offset_y', 0)) == 12,
              f'折叠={ok}/{ok2} offset_y={wiz.cfg.get("offset_y")}')
        # R11 × R12 交互：折叠只收 ⑧~⑭，通用区 ②~⑦（含 ③ 贴边方向）仍可用
        ok3 = _toggle(wiz, True)
        y3 = _first_y(wiz, '③')
        rid = _radio_invoke(wiz, wiz.var_side, '中')
        check('E07 ★折叠态：通用区 ③ 贴边方向仍在且可点（折叠只收 ⑧~⑭）',
              ok3 and y3 is not None and rid and wiz.cfg.get('side') == 'center',
              f'折叠={ok3} y3={y3} 点中={rid} side={wiz.cfg.get("side")}')
        check('E08 折叠态：预览画布仍在（②~⑦ 不受折叠影响）',
              _in_body(wiz, getattr(wiz, 'canvas', None))
              if getattr(wiz, 'canvas', None) is not None else False, '')
        _toggle(wiz, False)
    finally:
        _restore(real)
        _kill(wiz)


# ==========================================================================
# F. 判别力
# ==========================================================================
def test_discriminating(tmp, saved):
    section('F. 判别力：禁用折叠执行点后「高度明显下降」必须不成立')
    real_apply = getattr(R.ConfigWizard, '_apply_adv_collapsed', None)
    if real_apply is None:
        check('F01 ★判别力：实现提供折叠执行点 _apply_adv_collapsed', False,
              '方法不存在（未实现 R12）')
        return
    wiz, real = _wiz_probe(None, None, {'image': _make_png(os.path.join(tmp, 'r12f.png'))})
    try:
        # N1 改写：先把内容展开（否则从折叠态出发，本段没有「下降」可测）
        _toggle(wiz, False)
        b0, r0, _a0 = _heights(wiz)
        R.ConfigWizard._apply_adv_collapsed = lambda self: None
        ok = _toggle(wiz, True)
        b1, r1, _a1 = _heights(wiz)
        check('F01 ★判别力：禁用折叠执行点后高度不下降（B 段断言非恒真）',
              ok and not ((b0 - b1) >= 100 or (r0 - r1) >= 100),
              f'body {b0}→{b1}  窗口 {r0}→{r1}')
    finally:
        R.ConfigWizard._apply_adv_collapsed = real_apply
        _restore(real)
        _kill(wiz)


# ==========================================================================
# G. 按钮尺寸（N1 新增）
# ==========================================================================
def test_button_size(tmp, saved):
    section('G. 按钮尺寸：高度 ≥30px、面积相对 R12 基线 ≥ +40%、折叠态可见可点')
    wiz, real = _wiz_probe(None, None, {'image': _make_png(os.path.join(tmp, 'r12g.png'))})
    try:
        btn = getattr(wiz, 'btn_adv_toggle', None)
        if btn is None:
            check('G01 ★折叠按钮存在', False, 'btn_adv_toggle 不存在')
            return
        _toggle(wiz, False)
        wiz.root.update_idletasks()
        wiz.root.update()
        w_e, h_e = _btn_box(wiz)
        _toggle(wiz, True)
        wiz.root.update_idletasks()
        wiz.root.update()
        w_c, h_c = _btn_box(wiz)
        area_e, area_c = w_e * h_e, w_c * h_c
        gain = area_e / float(max(1, R12_BTN_AREA))
        print(f'    R12 基线：{R12_BTN_W}×{R12_BTN_H}px = {R12_BTN_AREA} px²'
              f'（折叠态文案 {219}×{R12_BTN_H} = 5694 px²）')
        print(f'    现在：展开态 {w_e}×{h_e}px = {area_e} px²（{gain:.2f}×，'
              f'{(gain - 1) * 100:+.1f}%）｜折叠态 {w_c}×{h_c}px = {area_c} px²')
        check('G01 ★按钮高度 ≥ 30px（展开态与折叠态都量）',
              h_e >= MIN_BTN_H and h_c >= MIN_BTN_H,
              f'展开 {h_e}px / 折叠 {h_c}px，阈值 {MIN_BTN_H}px')
        check('G02 ★按钮面积相对 R12 基线 ≥ +40%', gain >= MIN_BTN_GAIN,
              f'{area_e} px² vs 基线 {R12_BTN_AREA} px² = {gain:.2f}×（阈值 {MIN_BTN_GAIN}×）')
        check('G03 按钮宽度不小于 R12 基线（变大不缩水）', w_e >= R12_BTN_W and w_c >= 219,
              f'展开 {w_e}px（R12 {R12_BTN_W}）/ 折叠 {w_c}px（R12 219）')
        check('G04 ★折叠态按钮可见且可点（mapped=1 / state=normal）',
              int(btn.winfo_ismapped()) == 1 and str(btn.cget('state')) == 'normal',
              f'mapped={int(btn.winfo_ismapped())} state={str(btn.cget("state"))}')
        _toggle(wiz, False)
    finally:
        _restore(real)
        _kill(wiz)


# ==========================================================================
def main():
    print('=== B_test_r12_collapse：⚙ 高级设置可折叠（N1：大按钮 + 默认折叠）===')
    print('Python', sys.version.split()[0])
    tmp = tempfile.mkdtemp(prefix='r12_collapse_')
    R.HERE = tmp          # 只读约束：写日志/临时产物只落临时目录
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
            for t, cnt in (('A', 10), ('B', 5), ('C', 6), ('D', 7), ('E', 8), ('F', 1), ('G', 4)):
                for i in range(1, cnt + 1):
                    SKIPPED.append(f'{t}{i:02d}')
                    print(f'  [SKIP] {t}{i:02d}  (无桌面环境（GUI 不可用）)')
        else:
            test_structure(tmp, saved)
            test_heights(tmp, saved)
            test_collapsed_usable(tmp, saved)
            test_round_trip(tmp, saved)
            test_expanded_inventory(tmp, saved)
            test_discriminating(tmp, saved)
            test_button_size(tmp, saved)
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
