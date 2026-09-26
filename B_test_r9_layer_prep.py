# -*- coding: utf-8 -*-
"""B_test_r9_layer_prep.py —— R9「多图层时选中的图层可预处理」验证

用户第三轮实测原话（第 3 条）：
  「多图层时新加的图无法预处理。」
真 bug：`ConfigWizard._preprocess_image` 写死 `self.cfg['image']`（顶层主图），处理完调
`_set_main_image` 把结果盖回主图 —— 选中的图层根本没参与。多图层下新加的层没有裁剪/抠图
入口，硬做还会把结果盖到主图上（把用户的套层图改坏）。

本脚本验收：
  A 段 · 多图层：预处理作用于**当前选中图层**（打开该层的图 / 结果写回该层 / 主图不动）
  B 段 · 主层（第 0 层）行为与改前完全一致（cfg['image'] + layers[0] + ① 文案 + 列表文案）
  C 段 · 缺图明确提示，不静默失败（空路径 / 文件不存在 / 老 cfg 顶层无图）
  D 段 · 真端到端：真对话框 + 真 _apply，结果落到正确的那一层（含尺寸取证）
  E 段 · 预处理完成后图层列表文案与向导预览同步（不出现「列表还写旧文件名」）
  F 段 · 对话框标出「正在处理第几层」（用户知道自己在改哪一层）

红→绿：改前（54582cd）实测 A1/A2/A3/A5/A6/B4/C1/C2/C3/F1 共 11 条 FAIL / exit=1；
       改后全绿。判别力：C 段用「文件不存在」的层，改前会把主图路径喂给对话框（calls+1），
       改后必须 warning 且 calls 不动。

红线：只读被测模块；不写真实 config.json / skin.json（save_config 打桩）；预处理产物写
      临时目录（R.HERE 指向 tmp）；模态框全部打桩，且不真等用户输入。

用法: python B_test_r9_layer_prep.py
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
import tkinter as tk                   # noqa: E402
from PIL import Image                  # noqa: E402

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
        p = tk.Tk()
        p.withdraw()
        p.update()
        p.destroy()
        return True
    except Exception:
        return False


# ---------------- 夹具 ----------------
def _make_png(path, size=(120, 180), color=(220, 60, 60, 255)):
    im = Image.new('RGBA', size, (0, 0, 0, 0))
    w, h = size
    for y in range(int(h * 0.2), int(h * 0.8)):
        for x in range(int(w * 0.15), int(w * 0.85)):
            im.putpixel((x, y), color)
    im.save(path)
    return path


def _multi_cfg(tmp, n=3):
    """n 层配置：每层图尺寸不同（便于按尺寸取证是读了哪一层）"""
    sizes = [(120, 180), (130, 180), (140, 180)]
    colors = [(220, 60, 60, 255), (60, 90, 220, 255), (60, 200, 90, 255)]
    paths = [_make_png(os.path.join(tmp, f'r9_L{i}.png'), sizes[i % 3], colors[i % 3])
             for i in range(n)]
    layers = [R.normalize_layer({'image': p, 'anchor': 'right_edge', 'z': i})
              for i, p in enumerate(paths)]
    cfg = {'image': paths[0], 'side': 'right', 'scale': 1.0, 'offset_x': 0, 'offset_y': 0,
           'layers': layers}
    return cfg, paths


def _wiz(cfg):
    w = R.ConfigWizard(on_done=lambda c: None, overlay=None)
    if cfg:
        w.cfg.update(cfg)
    w._layer_sync_from_cfg()
    w.root.update_idletasks()
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


def _norm(p):
    return os.path.normpath(str(p or ''))


# ---------------- 打桩：假对话框 / 消息框 ----------------
class StubDlg(object):
    """假对话框：记录入参，按预设给出 result_path（None = 用户取消）。

    真 Toplevel + after 自毁，保证 `root.wait_window(dlg.root)` 能立刻返回。
    """
    calls = []
    result = None

    def __init__(self, master, image_path, layer_hint=None, **kw):
        StubDlg.calls.append({'path': image_path, 'layer_hint': layer_hint, 'kw': kw})
        self.src_path = image_path
        self.layer_hint = layer_hint
        self.result_path = StubDlg.result
        self.root = tk.Toplevel(master)
        self.root.withdraw()
        self.root.after(1, self.root.destroy)


MSGS = {'warn': [], 'err': [], 'info': []}


def _stub_msgs():
    R.messagebox.showwarning = lambda *a, **k: MSGS['warn'].append(a)
    R.messagebox.showerror = lambda *a, **k: MSGS['err'].append(a)
    R.messagebox.showinfo = lambda *a, **k: MSGS['info'].append(a)


def _reset_msgs():
    for v in MSGS.values():
        del v[:]


# ==========================================================================
# A 段 · 多图层：作用于当前选中层
# ==========================================================================
def test_a_selected_layer(tmp):
    section('A. 多图层：预处理作用于当前选中图层（主图不动）')
    cfg, paths = _multi_cfg(tmp, 3)
    out1 = _make_png(os.path.join(tmp, 'r9_out_layer2.png'), (40, 160), (200, 30, 30, 255))
    w = _wiz(cfg)
    real_cls = R.ImagePreprocessDialog
    try:
        _select(w, 1)
        StubDlg.calls = []
        StubDlg.result = out1
        R.ImagePreprocessDialog = StubDlg
        before1 = str(w._layers()[1].get('image') or '')      # 调用前的第 2 层图（写回后会被换掉）
        w._preprocess_image()
        w.root.update_idletasks()
        R.ImagePreprocessDialog = real_cls
        call = StubDlg.calls[-1] if StubDlg.calls else {}
        layers = w._layers()

        check('A1 ★对话框打开的是**选中层（第 2 层）**的图，不是主图',
              _norm(call.get('path')) == _norm(before1) and len(StubDlg.calls) == 1
              and _norm(before1) != _norm(cfg.get('image')),
              f"传入={os.path.basename(str(call.get('path')))} / 选中层原图="
              f"{os.path.basename(before1)} / 主图={os.path.basename(str(cfg.get('image')))}")
        check('A2 ★处理结果写回第 2 层',
              _norm(layers[1].get('image')) == _norm(out1),
              f"layers[1]={os.path.basename(str(layers[1].get('image')))}")
        check('A3 ★顶层 cfg[image]（主图）不被改写',
              _norm(w.cfg.get('image')) == _norm(paths[0]),
              f"cfg[image]={os.path.basename(str(w.cfg.get('image')))} / 原主图="
              f"{os.path.basename(paths[0])}")
        check('A4 其它层路径不受影响（第 1 / 第 3 层仍是原图）',
              _norm(layers[0].get('image')) == _norm(paths[0])
              and _norm(layers[2].get('image')) == _norm(paths[2]),
              f"L0={os.path.basename(str(layers[0].get('image')))} "
              f"L2={os.path.basename(str(layers[2].get('image')))}")
        check('A5 ★图层列表第 2 项文案同步成新文件名（不写旧名）',
              'r9_out_layer2.png' in str(w.layer_list.get(1)),
              repr(w.layer_list.get(1)))
        check('A6 写回后选中项仍是第 2 层（不跳回主层）',
              list(w.layer_list.curselection()) == [1] and int(w._layer_sel) == 1,
              f'curselection={list(w.layer_list.curselection())} _layer_sel={w._layer_sel}')
    finally:
        R.ImagePreprocessDialog = real_cls
        _kill(w)


# ==========================================================================
# B 段 · 主层行为不变
# ==========================================================================
def test_b_main_layer(tmp):
    section('B. 主层（第 0 层）：行为与改前完全一致')
    cfg, paths = _multi_cfg(tmp, 3)
    outm = _make_png(os.path.join(tmp, 'r9_out_main.png'), (50, 150), (30, 30, 200, 255))
    w = _wiz(cfg)
    real_cls = R.ImagePreprocessDialog
    try:
        _select(w, 0)
        StubDlg.calls = []
        StubDlg.result = outm
        R.ImagePreprocessDialog = StubDlg
        w._preprocess_image()
        w.root.update_idletasks()
        R.ImagePreprocessDialog = real_cls
        call = StubDlg.calls[-1] if StubDlg.calls else {}
        layers = w._layers()
        check('B1 ★主层：对话框打开的仍是 cfg[image]（原行为一字未改）',
              _norm(call.get('path')) == _norm(paths[0]), str(os.path.basename(str(call.get('path')))))
        check('B2 ★主层：顶层 image 与 layers[0] 一起更新（_set_main_image 口径）',
              _norm(w.cfg.get('image')) == _norm(outm)
              and _norm(layers[0].get('image')) == _norm(outm),
              f"top={os.path.basename(str(w.cfg.get('image')))} "
              f"l0={os.path.basename(str(layers[0].get('image')))}")
        check('B3 主层：① 图片文案 + 「（已预处理）」后缀',
              'r9_out_main.png' in str(w.lbl_img.cget('text'))
              and '已预处理' in str(w.lbl_img.cget('text')),
              repr(w.lbl_img.cget('text')))
        check('B4 ★主层：图层列表第 1 项文案同步（改前只有顶层 image 换了、列表还写旧名）',
              'r9_out_main.png' in str(w.layer_list.get(0)),
              repr(w.layer_list.get(0)))
        # 取消：不许改任何路径
        StubDlg.calls = []
        StubDlg.result = None
        R.ImagePreprocessDialog = StubDlg
        w._preprocess_image()
        w.root.update_idletasks()
        R.ImagePreprocessDialog = real_cls
        check('B5 取消对话框（result_path=None）→ 不改任何路径',
              _norm(w.cfg.get('image')) == _norm(outm)
              and _norm(w._layers()[1].get('image')) == _norm(paths[1]),
              f"top={os.path.basename(str(w.cfg.get('image')))}")
    finally:
        R.ImagePreprocessDialog = real_cls
        _kill(w)


# ==========================================================================
# C 段 · 缺图明确提示
# ==========================================================================
def test_c_missing(tmp):
    section('C. 缺图时明确提示，不静默失败（也不许把主图硬塞给对话框）')
    real_cls = R.ImagePreprocessDialog
    try:
        # C1 选中层没有图
        cfg, paths = _multi_cfg(tmp, 2)
        cfg['layers'][1]['image'] = ''
        w = _wiz(cfg)
        try:
            _select(w, 1)
            _reset_msgs()
            StubDlg.calls = []
            R.ImagePreprocessDialog = StubDlg
            w._preprocess_image()
            R.ImagePreprocessDialog = real_cls
            check('C1 ★选中层没有图 → 弹提示且不打开对话框（改前会拿主图去开）',
                  len(MSGS['warn']) == 1 and not StubDlg.calls and not MSGS['err'],
                  f"warn={len(MSGS['warn'])} err={len(MSGS['err'])} 对话框调用={len(StubDlg.calls)}")
        finally:
            R.ImagePreprocessDialog = real_cls
            _kill(w)

        # C2 选中层的文件不存在
        cfg2, paths2 = _multi_cfg(tmp, 2)
        gone = os.path.join(tmp, 'r9_gone.png')
        _make_png(gone, (90, 90), (10, 10, 10, 255))
        cfg2['layers'][1]['image'] = gone
        os.remove(gone)
        w2 = _wiz(cfg2)
        try:
            _select(w2, 1)
            _reset_msgs()
            StubDlg.calls = []
            R.ImagePreprocessDialog = StubDlg
            w2._preprocess_image()
            R.ImagePreprocessDialog = real_cls
            txt = ' '.join(str(a) for a in (MSGS['warn'][0] if MSGS['warn'] else ()))
            check('C2 ★选中层文件找不到 → 明确提示（含层号/路径），不打开对话框',
                  len(MSGS['warn']) == 1 and not StubDlg.calls
                  and ('2' in txt and 'r9_gone' in txt),
                  f"warn={MSGS['warn'][:1]} 对话框调用={len(StubDlg.calls)}")
        finally:
            R.ImagePreprocessDialog = real_cls
            _kill(w2)

        # C3 老 cfg：顶层与主层都没有图
        w3 = _wiz({'image': '', 'layers': [R.normalize_layer({'image': '', 'anchor': 'right_edge', 'z': 0})]})
        try:
            _reset_msgs()
            StubDlg.calls = []
            R.ImagePreprocessDialog = StubDlg
            w3._preprocess_image()
            R.ImagePreprocessDialog = real_cls
            check('C3 ★没有图时给明确提示（不静默失败）',
                  len(MSGS['warn']) == 1 and not StubDlg.calls and not MSGS['err'],
                  f"warn={len(MSGS['warn'])} err={len(MSGS['err'])}")
        finally:
            R.ImagePreprocessDialog = real_cls
            _kill(w3)
    finally:
        R.ImagePreprocessDialog = real_cls


# ==========================================================================
# D 段 · 真端到端（真对话框 + 真 _apply）
# ==========================================================================
def _auto_apply_cls(hold, crop, delay=120):
    real = R.ImagePreprocessDialog

    class AutoDlg(real):
        def __init__(self, *a, **k):
            real.__init__(self, *a, **k)
            hold['dlg'] = self
            try:
                self.crop = tuple(crop)
            except Exception:
                pass
            self.root.after(delay, self._auto_apply)

        def _auto_apply(self):
            try:
                self._apply()
            except Exception as e:
                hold['err'] = '%s: %s' % (type(e).__name__, e)

    return AutoDlg


def test_d_end_to_end(tmp):
    section('D. 真端到端：真对话框 + 真 _apply，结果落到正确的那一层')
    real_cls = R.ImagePreprocessDialog
    # D1 第 2 层
    cfg, paths = _multi_cfg(tmp, 3)
    w = _wiz(cfg)
    hold = {}
    try:
        _select(w, 1)
        R.ImagePreprocessDialog = _auto_apply_cls(hold, (10, 10, 60, 80))
        w._preprocess_image()
        R.ImagePreprocessDialog = real_cls
        w.root.update_idletasks()
        layers = w._layers()
        new1 = str(layers[1].get('image') or '')
        exists = os.path.isfile(new1)
        size = Image.open(new1).size if exists else None
        check('D1 ★真对话框处理第 2 层 → 新文件写到第 2 层，且尺寸 = 裁剪尺寸（50×70）',
              exists and 'preprocessed_' in os.path.basename(new1) and size == (50, 70),
              f'新路径={os.path.basename(new1)} size={size}')
        check('D2 ★主图与其它层路径一字未动',
              _norm(w.cfg.get('image')) == _norm(paths[0])
              and _norm(layers[0].get('image')) == _norm(paths[0])
              and _norm(layers[2].get('image')) == _norm(paths[2]),
              f"top={os.path.basename(str(w.cfg.get('image')))}")
        check('D3 列表第 2 项文案 = 新文件名（basename 一致）',
              os.path.basename(new1) in str(w.layer_list.get(1)),
              repr(w.layer_list.get(1)))
        check('D4 对话框实例被正常销毁（无残留 Toplevel）',
              not hold.get('err') and not [c for c in w.root.winfo_children()
                                           if c.winfo_class() == 'Toplevel'],
              f"err={hold.get('err')}")
    finally:
        R.ImagePreprocessDialog = real_cls
        _kill(w)

    # D2 主层
    cfg2, paths2 = _multi_cfg(tmp, 2)
    w2 = _wiz(cfg2)
    hold2 = {}
    try:
        _select(w2, 0)
        R.ImagePreprocessDialog = _auto_apply_cls(hold2, (5, 5, 45, 65))
        w2._preprocess_image()
        R.ImagePreprocessDialog = real_cls
        w2.root.update_idletasks()
        layers2 = w2._layers()
        new0 = str(w2.cfg.get('image') or '')
        check('D5 ★真对话框处理主层 → cfg[image] 与 layers[0] 都指向新文件（原行为）',
              os.path.isfile(new0) and 'preprocessed_' in os.path.basename(new0)
              and _norm(layers2[0].get('image')) == _norm(new0)
              and Image.open(new0).size == (40, 60),
              f"{os.path.basename(new0)} l0={os.path.basename(str(layers2[0].get('image')))} "
              f"size={Image.open(new0).size if os.path.isfile(new0) else None}")
        check('D6 主层处理不影响第 2 层路径',
              _norm(layers2[1].get('image')) == _norm(paths2[1]),
              os.path.basename(str(layers2[1].get('image'))))
    finally:
        R.ImagePreprocessDialog = real_cls
        _kill(w2)


# ==========================================================================
# E 段 · 预览与列表同步
# ==========================================================================
def test_e_sync(tmp):
    section('E. 预处理完成后图层列表文案与向导预览同步更新')
    cfg, paths = _multi_cfg(tmp, 2)
    out1 = _make_png(os.path.join(tmp, 'r9_sync_out.png'), (40, 160), (200, 30, 30, 255))
    w = _wiz(cfg)
    real_cls = R.ImagePreprocessDialog
    try:
        _select(w, 1)
        cnt = {'preview': 0, 'hint': 0}
        orig_pv = w._update_preview
        orig_hint = w._update_key_hint

        def _pv(*a, **k):
            cnt['preview'] += 1
            return orig_pv(*a, **k)

        def _hint(*a, **k):
            cnt['hint'] += 1
            return orig_hint(*a, **k)

        w._update_preview = _pv
        w._update_key_hint = _hint
        StubDlg.calls = []
        StubDlg.result = out1
        R.ImagePreprocessDialog = StubDlg
        w._preprocess_image()
        R.ImagePreprocessDialog = real_cls
        w.root.update_idletasks()
        check('E1 ★写回后刷新了向导预览（_update_preview 被调用）', cnt['preview'] >= 1,
              f"调用 {cnt['preview']} 次")
        check('E2 ★写回后刷新了抠色键提示（_update_key_hint 被调用，与主层路径同一套收尾）',
              cnt['hint'] >= 1, f"调用 {cnt['hint']} 次")
        specs = w._preview_specs()
        path_ok = len(specs) >= 2 and _norm(specs[1].get('image')) == _norm(out1)
        check('E3 ★预览取到的第 2 层路径就是处理结果（预览不再用旧图）', path_ok,
              f"specs[1]={os.path.basename(str(specs[1].get('image'))) if len(specs) > 1 else None}")
        # 硬证据：预览真把新文件读进来了（宽高比 = 新文件的 40:160，不是层 2 原图的 130:180）
        imgs = w._preview_layer_imgs(specs) if path_ok else []
        r_new = 40 / 160.0
        r_old = 130 / 180.0
        got = (imgs[1].width / float(imgs[1].height)) if len(imgs) > 1 and imgs[1] is not None else None
        check('E4 ★预览实际读的是新文件（宽高比 = 0.25，不是原层图的 0.72）',
              got is not None and abs(got - r_new) < 0.02 and abs(got - r_old) > 0.1,
              f'预览第 2 层宽高比={got}（新图 {r_new:.3f} / 旧图 {r_old:.3f}）')
    finally:
        R.ImagePreprocessDialog = real_cls
        _kill(w)


# ==========================================================================
# F 段 · 对话框标出层
# ==========================================================================
def test_f_layer_hint(tmp):
    section('F. 对话框标出「正在处理第几层」')
    cfg, paths = _multi_cfg(tmp, 3)
    w = _wiz(cfg)
    real_cls = R.ImagePreprocessDialog
    try:
        _select(w, 1)
        StubDlg.calls = []
        StubDlg.result = None
        R.ImagePreprocessDialog = StubDlg
        w._preprocess_image()
        R.ImagePreprocessDialog = real_cls
        hint2 = (StubDlg.calls[-1].get('layer_hint') or '') if StubDlg.calls else ''
        check('F1 ★选中第 2 层时对话框带上「第 2 层」标识（用户知道在改哪一层）',
              '第 2 层' in str(hint2), repr(hint2))
        _select(w, 0)
        StubDlg.calls = []
        R.ImagePreprocessDialog = StubDlg
        w._preprocess_image()
        R.ImagePreprocessDialog = real_cls
        hint0 = (StubDlg.calls[-1].get('layer_hint') or '') if StubDlg.calls else ''
        check('F2 选中主层时标识为「第 1 层（主图）」',
              '第 1 层' in str(hint0) and '主图' in str(hint0), repr(hint0))
    finally:
        R.ImagePreprocessDialog = real_cls
        _kill(w)


# ==========================================================================
def main():
    print('=== B_test_r9_layer_prep：多图层时选中的图层可预处理 ===')
    print('Python', sys.version.split()[0])
    tmp = tempfile.mkdtemp(prefix='r9_layer_prep_')
    gui_ok = _has_gui()
    print('GUI 可用:', gui_ok, '| 临时目录:', tmp)
    real = (R.save_config, R.messagebox.showwarning, R.messagebox.showerror,
            R.messagebox.showinfo, R.set_autostart)
    real_here = R.HERE
    R.save_config = lambda cfg: None
    R.set_autostart = lambda *a, **k: (True, '（测试打桩）')
    R.HERE = tmp                      # 预处理产物只落临时目录
    _stub_msgs()
    try:
        if not gui_ok:
            SKIPPED.extend(['A', 'B', 'C', 'D', 'E', 'F'])
            print('  [SKIP] 无桌面环境（GUI 不可用）')
        else:
            test_a_selected_layer(tmp)
            test_b_main_layer(tmp)
            test_c_missing(tmp)
            test_d_end_to_end(tmp)
            test_e_sync(tmp)
            test_f_layer_hint(tmp)
    finally:
        R.HERE = real_here
        (R.save_config, R.messagebox.showwarning, R.messagebox.showerror,
         R.messagebox.showinfo, R.set_autostart) = real
        shutil.rmtree(tmp, ignore_errors=True)
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
