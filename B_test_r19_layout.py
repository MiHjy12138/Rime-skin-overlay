# -*- coding: utf-8 -*-
"""B_test_r19_layout.py —— 第六轮（R19）版型微调：⑪ 换列 / ① 绿字收短 / ④ 层号落行末

对照先生本轮原话（HANDOFF-2.5 之后）：
  ①「按图把真羽化换个位置，和 ⑧⑨⑩ 同一列，点选框放字后面。」
    ＋追问确认「11 增强（真羽化）…下一行…方框（和 9、10 对齐）后面跟 11 的说明」
    ＋「把说明里真羽化的部分挪下来直接显示，原本的位置直接显示 ⑩ 自己的说明，简化一下。」
  ②「导入图片后绿字过长，会拉长窗口，简短点：已导入、已预处理 等其他语句。」
     ＋追问确认「已导入 / 已预处理 / 已套用皮肤（不带皮肤名）」
  ③「图3，把框中的字换个位置，夹在当前的位置滑条不够整齐。」
     ＋追问确认「④ 行行末：`④ 缩放: [滑条] 1.0x 当前第 1 层`，单层灰、多层橙。」

红绿纪律：本脚本**先跑出红**（B 段 ① 绿字、C 段 ④ 层号尚未实现 → FAIL），
再改实现到绿；A 段（⑪ 换列）是同一批改动里已先行落地的部分，一并守回归。

红线：只读被测模块；不写真实 config.json / skin.json（find_skin / save_config 打桩）；
      图片预处理对话框与文件对话框全部打桩。

用法: python B_test_r19_layout.py
"""
import os
import sys
import shutil
import tempfile

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R          # noqa: E402

try:
    import tkinter as tk
    from PIL import Image
    PIL_OK = True
except Exception:
    tk = None
    Image = None
    PIL_OK = False

PASS, FAIL, SKIPPED = [], [], []

# 第八轮「新脚本一律设 R.HERE 指向 tempdir」口径：产品 _write_log 与
# ImagePreprocessDialog._apply 都在**调用时**取模块全局 HERE，不设就会写进真实程序目录。
_TRUE_HERE = R.HERE


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
        p = tk.Tk()
        p.withdraw()
        p.update()
        p.destroy()
        return True
    except Exception:
        return False


def _make_png(path, size=(120, 180), color=(220, 60, 60, 255)):
    im = Image.new('RGBA', size, (0, 0, 0, 0))
    w, h = size
    for y in range(int(h * 0.2), int(h * 0.8)):
        for x in range(int(w * 0.15), int(w * 0.85)):
            im.putpixel((x, y), color)
    im.save(path)
    return path


def _cfg1(img):
    """单图层配置（主层）"""
    return {'image': img, 'layout': 'horizontal_double', 'side': 'right',
            'scale': 1.0, 'offset_x': 0, 'offset_y': 0, 'layer': 'above',
            'corner_enabled': False, 'corner_radius': 24,
            'feather_enabled': False, 'feather_radius': 24, 'flip_h': False}


def _cfg2(img_a, img_b):
    """双图层配置（验「多层变明显」那一半配色口径）"""
    c = _cfg1(img_a)
    c['layers'] = [{'image': img_a, 'anchor': 'right_edge', 'scale': 1.0,
                    'flip': False, 'offset_x': 0, 'offset_y': 0},
                   {'image': img_b, 'anchor': 'left_edge', 'scale': 1.0,
                    'flip': False, 'offset_x': 0, 'offset_y': 0}]
    return c


def _wiz(cfg):
    saved = {}
    w = R.ConfigWizard(on_done=lambda c: saved.update(c), overlay=None)
    if cfg:
        w.cfg.update(cfg)
    w._layer_sync_from_cfg()
    w.root.update_idletasks()
    w.root.update()
    # R15 起高级设置默认折叠 → ⑧~⑭ 不 map、位置探针归零。本脚本量展开态排布。
    try:
        w._toggle_adv_collapse(False)
        w.root.update_idletasks()
        w.root.update()
    except Exception:
        pass
    w._saved = saved
    return w


def _kill(w):
    try:
        w.root.destroy()
    except Exception:
        pass


def _select(w, i):
    w.layer_list.selection_clear(0, 'end')
    w.layer_list.selection_set(i)
    w._on_layer_select()
    w.root.update_idletasks()


def _txt(t):
    return str(t or '')


# ==========================================================================
# A. ⑪ 增强（真羽化）：换到 ⑧⑨⑩ 同一列 + 点选框放字后面 + 两段说明常驻
# ==========================================================================
def test_alpha_row(tmp):
    section('A. ⑪ 增强（真羽化）：与 ⑧⑨⑩ 同一列、标题在上方框在下、方框与 ⑨⑩ 对齐')
    img = _make_png(os.path.join(tmp, 'r19a.png'))
    w = _wiz(_cfg1(img))
    try:
        lbl = getattr(w, 'lbl_alpha_feather', None)
        chk = getattr(w, 'chk_alpha_feather', None)
        chk0 = getattr(w, 'chk_feather', None)
        check('A01 ★⑪ 的标题载体 lbl_alpha_feather 存在', lbl is not None)
        check('A02 ★chk_alpha_feather 存在且仍绑 var_alpha_feather',
              chk is not None and hasattr(w, 'var_alpha_feather')
              and _txt(chk.cget('variable')) == _txt(w.var_alpha_feather),
              f'var={getattr(w, "var_alpha_feather", None)}')
        if lbl is None or chk is None or chk0 is None:
            for nm in ('A03', 'A04', 'A05', 'A06', 'A07'):
                check(f'{nm}（前置控件缺失，不许静默跳过）', False, 'lbl/chk 未实现')
            return
        check('A03 ★标题文案 = 「⑪ 增强（真羽化）:」',
              _txt(lbl.cget('text')) == '⑪ 增强（真羽化）:', repr(_txt(lbl.cget('text'))))
        # 同列：⑩ 控件行、⑪ 控件行、⑪ 标题三者挂在**同一个 adv 列 Frame** 上
        par10, par11 = chk0.master, chk.master
        check('A04 ★⑪ 与 ⑧⑨⑩ 同处一个列卡片（挂同一个 adv 列 Frame）',
              par10 is not None and par11 is not None
              and par10.master is par11.master and lbl.master is par10.master,
              f'{par10.master} / {par11.master} / {lbl.master}')
        check('A05 ★⑪ 标题落在 ⑩ 控件行**下方**（⑧⑨⑩ 之后的新行）',
              lbl.winfo_rooty() > par10.winfo_rooty(),
              f'y={par10.winfo_rooty()} → {lbl.winfo_rooty()}')
        check('A06 ★点选框放字后面（chk 在标题下一行）',
              chk.winfo_rooty() > lbl.winfo_rooty(),
              f'y={lbl.winfo_rooty()} → {chk.winfo_rooty()}')
        dx = abs(int(chk.winfo_rootx()) - int(chk0.winfo_rootx()))
        check('A07 ★方框与 ⑩「启用」方框左边缘对齐（≤2px）', dx <= 2,
              f'x={chk0.winfo_rootx()} → {chk.winfo_rootx()} (Δ={dx})')
        check('A08 方框文案 = 「启用」（与 ⑨⑩ 同一控件形态）',
              _txt(chk.cget('text')) == '启用', repr(_txt(chk.cget('text'))))
        check('A09 方框可见、可点（state=normal）',
              bool(chk.winfo_ismapped()) and _txt(chk.cget('state')) == 'normal',
              f'mapped={chk.winfo_ismapped()} state={chk.cget("state")}')
        # ---- 两段说明常驻 ----
        l1 = getattr(w, 'lbl_feather_line', None)
        l2 = getattr(w, 'lbl_alpha_feather_line', None)
        check('A10 ★⑩ 自己的说明常驻显示（「边缘半透明：远看虚，近看有点点」）',
              l1 is not None and bool(l1.winfo_ismapped())
              and _txt(l1.cget('text')) == '边缘半透明：远看虚，近看有点点',
              repr(l1 and l1.cget('text')))
        check('A11 ★⑪ 的说明常驻显示且跟在方框后面（同一行）',
              l2 is not None and bool(l2.winfo_ismapped())
              and _txt(l2.cget('text')) == '真半透明、边缘更柔，透明处能点穿'
              and l2.master is chk.master
              and int(l2.winfo_rootx()) > int(chk.winfo_rootx()),
              f'{l2 and l2.cget("text")!r} master_same={l2 is not None and l2.master is chk.master}')
    finally:
        _kill(w)


# ==========================================================================
# B. ① 图片状态文字：简短（已导入 / 已预处理 / 已套用皮肤）
# ==========================================================================
class _StubPrepDlg(object):
    """假图片预处理对话框：记录入参、回给预设产物路径（None = 用户取消）。"""
    calls = []
    result = None

    def __init__(self, master, image_path, layer_hint=None, **kw):
        _StubPrepDlg.calls.append({'path': image_path, 'layer_hint': layer_hint})
        self.src_path = image_path
        self.result_path = _StubPrepDlg.result
        self.root = tk.Toplevel(master)
        self.root.withdraw()
        self.root.after(1, self.root.destroy)


def test_img_label(tmp):
    section('B. ① 图片状态文字：不再回显文件名（简短）')
    src = _make_png(os.path.join(tmp, 'r19_in_longname.png'))
    out = _make_png(os.path.join(tmp, 'preprocessed_1790498472762.png'))
    w = _wiz(_cfg1(src))
    try:
        # ---- ①-a 选图 ----
        w._set_main_image(src)
        w.root.update_idletasks()
        t = _txt(w.lbl_img.cget('text'))
        check('B01 ★选图后 ① 文案 == 「已导入」', t == '已导入', repr(t))
        check('B02 ★该文案不含文件名（长名不再撑宽窗口）',
              'r19_in_longname' not in t and '.png' not in t, repr(t))
        # ---- ①-b 预处理 ----
        real = R.ImagePreprocessDialog
        _StubPrepDlg.calls = []
        _StubPrepDlg.result = out
        R.ImagePreprocessDialog = _StubPrepDlg
        try:
            w._preprocess_image()
            w.root.update_idletasks()
        finally:
            R.ImagePreprocessDialog = real
        t2 = _txt(w.lbl_img.cget('text'))
        check('B03 ★预处理后 ① 文案 == 「已预处理」', t2 == '已预处理', repr(t2))
        check('B04 ★该文案不含预处理产物文件名',
              'preprocessed_' not in t2 and '.png' not in t2, repr(t2))
        # ---- ①-c 套皮肤 ----
        real_find = R.find_skin
        R.find_skin = lambda n: dict(_cfg1(out), image=out)
        try:
            w.skin_var.set('r19_skin')
            w._apply_skin_to_wizard()
            w.root.update_idletasks()
        finally:
            R.find_skin = real_find
        t3 = _txt(w.lbl_img.cget('text'))
        check('B05 ★套皮肤后 ① 文案 == 「已套用皮肤」（不带皮肤名）',
              t3 == '已套用皮肤', repr(t3))
        check('B06 ★该文案不含文件名与皮肤名',
              'preprocessed_' not in t3 and 'r19_skin' not in t3 and '.png' not in t3,
              repr(t3))
    finally:
        _kill(w)


# ==========================================================================
# C. ④ 缩放：层号落行末（单层灰、多层橙）+ 三条滑条左端对齐
# ==========================================================================
def test_scale_layer(tmp):
    section('C. ④ 缩放：层号移到行末，④⑤⑥ 三条滑条左端对齐')
    img = _make_png(os.path.join(tmp, 'r19c.png'))
    w = _wiz(_cfg1(img))
    try:
        lb = getattr(w, 'lbl_scale_layer', None)
        check('C01 ★层号新家 lbl_scale_layer 存在', lb is not None)
        check('C02 ★④ 标题不再夹层号（文案回到「④ 缩放:」）',
              _txt(w.lbl_slider_target.cget('text')) == '④ 缩放:',
              repr(_txt(w.lbl_slider_target.cget('text'))))
        if lb is None:
            check('C03（层号控件缺失，不许静默跳过）', False, 'lbl_scale_layer 未实现')
        else:
            check('C03 ★单层：文案「当前第 1 层」+ 灰色 #888',
                  _txt(lb.cget('text')) == '当前第 1 层'
                  and _txt(lb.cget('fg')).lower() == '#888',
                  f'{lb.cget("text")!r} fg={lb.cget("fg")}')
            # 层号在 ④ 行内、且在滑条/数值之后（行末）
            check('C04 ★层号落在 ④ 行末（在滑条右侧）',
                  int(lb.winfo_rootx()) > int(w.scl_scale.winfo_rootx())
                  and lb.master is w.lbl_slider_target.master,
                  f'slider_x={w.scl_scale.winfo_rootx()} label_x={lb.winfo_rootx()}')
        xs = [int(w.scl_scale.winfo_rootx()), int(w.scl_offx.winfo_rootx()),
              int(w.scl_offy.winfo_rootx())]
        check('C05 ★④⑤⑥ 三条滑条左边缘对齐（极差 ≤2px）',
              max(xs) - min(xs) <= 2, f'x={xs} 极差={max(xs) - min(xs)}')
    finally:
        _kill(w)

    # ---- 多层：层号跟着选中层走，且变醒目色 ----
    section('C. 多层：层号随选中层更新 + 由灰转醒目')
    a = _make_png(os.path.join(tmp, 'r19c1.png'), color=(200, 40, 40, 255))
    b = _make_png(os.path.join(tmp, 'r19c2.png'), color=(40, 40, 200, 255))
    w2 = _wiz(_cfg2(a, b))
    try:
        lb = getattr(w2, 'lbl_scale_layer', None)
        if lb is None:
            check('C06（层号控件缺失）', False, 'lbl_scale_layer 未实现')
            check('C07（层号控件缺失）', False, 'lbl_scale_layer 未实现')
        else:
            _select(w2, 1)
            check('C06 ★多层：层号随选中层更新（当前第 2 层）',
                  _txt(lb.cget('text')) == '当前第 2 层', repr(_txt(lb.cget('text'))))
            check('C07 ★多层：层号变醒目（不再用灰 #888）',
                  _txt(lb.cget('fg')).lower() != '#888',
                  f'fg={lb.cget("fg")}')
            _select(w2, 0)
            check('C08 ★切回第 1 层：文案回到「当前第 1 层」',
                  _txt(lb.cget('text')) == '当前第 1 层', repr(_txt(lb.cget('text'))))
    finally:
        _kill(w2)


# ==========================================================================
# D. 版型不撑高：⑩ 卡片列高 + 三列极差（D04 判据同口径）
# ==========================================================================
def test_column_balance(tmp):
    section('D. 版型：⑩ 卡片所在列的高度与三列极差（B_test_r4_layout D04 同口径）')
    img = _make_png(os.path.join(tmp, 'r19d.png'))
    w = _wiz(_cfg1(img))
    try:
        cols = list(getattr(w, 'adv_cols', []) or [])
        if not cols:
            check('D01 高级设置列骨架存在', False, 'adv_cols 为空')
            return
        hs = [int(c.winfo_reqheight()) for c in cols]
        spread = max(hs) - min(hs)
        check('D01 列高可量（≥2 列）', len(hs) >= 2, f'列高={hs}')
        check('D02 ★三列极差 ≤80px（D04 阈值不放宽）', spread <= 80,
              f'列高={hs} 极差={spread}')
        card = getattr(w, 'lbl_alpha_feather', None)
        if card is not None:
            col_h = int(card.master.winfo_reqheight())
            check('D03 ★⑪ 所在列高度已量（供交接单记账）', col_h > 0, f'col_h={col_h}')
    finally:
        _kill(w)


def main():
    if not PIL_OK:
        print('PIL 不可用 → 全部跳过')
        return 2
    if not _has_gui():
        print('无 GUI（tkinter 起不来）→ 全部跳过')
        return 2
    tmp = tempfile.mkdtemp(prefix='r19_')
    R.HERE = tmp
    try:
        test_alpha_row(tmp)
        test_img_label(tmp)
        test_scale_layer(tmp)
        test_column_balance(tmp)
    finally:
        R.HERE = _TRUE_HERE
        shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n=== B_test_r19_layout：{len(PASS)} PASS / {len(FAIL)} FAIL'
          + (f' / {len(SKIPPED)} SKIP' if SKIPPED else '') + ' ===')
    if FAIL:
        print('FAIL 明细：')
        for f in FAIL:
            print(f'  · {f}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
