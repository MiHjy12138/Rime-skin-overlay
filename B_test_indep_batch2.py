# -*- coding: utf-8 -*-
"""B_test_indep_batch2.py —— 批次二（R4/R5/R6）**独立验证** · verifier 专属

定位（不信实现者自评）：verifier 自建，不复用 B_test_r4_layout / B_test_r5_scheme /
B_test_r6_gif_preview 的断言，用「同口径前→后对照 + 用户真实通路 + 反例」复核：
  · E 段 R4：窗口需求高/宽、⚙ 高级设置块与列高、按钮行底边、②~⑭ 控件清单
            （对 a133e9a 逐项超集对照）、列数 vs 工作区宽、4 列假设的代价、
            release/config.json 端到端（含保存零漂移）。
  · F 段 R5：tempfile 上贴出 yaml 原文（空行 + 亮/暗两个分节标题）、幂等、
            真实 weasel.custom.yaml 只读副本的注释多重集与顺序、未保存皮肤时的
            提示与「拒绝即不生成」、切皮肤整套恢复、真机文件零触碰。
  · G 段 R6：大 GIF 打开耗时（对 103c97f 同口径对照）、打开后解码次数、播放节拍的
            每 tick 解码数与耗时、逐帧/回绕、销毁后的 after 残留与迟到回调、
            异尺寸帧归一、静态路径输出与改前逐像素一致（G7 独立复核）。
  · H 段 反例：小工作区（1366×768 / 800 宽）、未保存皮肤点生成、超大 GIF 连播 +
            手动翻帧 + 销毁后迟到 tick、改名重注入的 stale 清理、强制 1 列时控件不丢。

红线：只读被测代码；R5/R6 一律 tempfile + 可注入路径（WEASEL_CUSTOM / SCHEME_MANIFEST /
      SKINS_DIR / run_weasel_deployer 全部打桩到临时目录），绝不写 %APPDATA%\\Rime；
      不动 G:\\github成果\\。

用法: python B_test_indep_batch2.py [--sections E,F,G,H]
"""
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import rime_char_overlay as R          # noqa: E402

PASS, FAIL, SKIP = [], [], []
NUM_CHARS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭'


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f'  [PASS] {name}' + (f'   ({detail})' if detail else ''))
    else:
        FAIL.append(name)
        print(f'  [FAIL] {name}' + (f'   ({detail})' if detail else ''))


def note(msg):
    print(f'  [INFO] {msg}')


def section(title):
    print(f'\n{title}')
    print('-' * len(title))


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


# --------------------------------------------------------------------------
def extract_version(ref, tag, tmp):
    try:
        p = subprocess.run(['git', 'cat-file', 'blob', f'{ref}:rime_char_overlay.py'],
                           cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0 or not p.stdout:
            return None, p.stderr.decode('utf-8', 'replace')[:200]
        out = os.path.join(tmp, f'rc_{tag}.py')
        with open(out, 'wb') as f:
            f.write(p.stdout)
        return out, f'{len(p.stdout)} B'
    except Exception as e:
        return None, repr(e)


def load_module(path, name):
    import importlib.util
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def make_png(path, size=(200, 260), color=(200, 40, 40, 255)):
    from PIL import Image
    Image.new('RGBA', size, color).save(path)
    return path


def make_gif(path, size=(240, 320), n=8, noise=False):
    from PIL import Image, ImageDraw
    frames = []
    for i in range(n):
        im = Image.new('RGB', size, (235, 235, 235))
        if noise:
            nz = Image.effect_noise(size, 45).convert('RGB')
            im = Image.blend(im, nz, 0.18)
        d = ImageDraw.Draw(im)
        x = (i * 5) % max(1, size[0] - 70)
        d.rectangle((x, 30, x + 60, size[1] - 30), fill=(190 - i % 40, 40 + i % 60, 90))
        d.ellipse((15, 15, 110, 110), fill=(30, 60, 200))
        frames.append(im.convert('P'))
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=40, loop=0)
    return path


def make_odd_gif(path, first=(320, 240), n=4, noise=False):
    """异尺寸帧 GIF（第三方写入器场景）：首帧大、后续帧小 → 归一分支必须生效"""
    from PIL import Image, ImageDraw
    frames = []
    for i in range(n):
        size = first if i == 0 else (first[0] // 2, first[1] // 2)
        im = Image.new('RGB', size, (240, 240, 240))
        if noise:
            im = Image.blend(im, Image.effect_noise(size, 30).convert('RGB'), 0.15)
        d = ImageDraw.Draw(im)
        d.rectangle((5, 5, size[0] - 6, size[1] - 6), outline=(20, 20, 20), width=3)
        d.rectangle((10 + i * 4, 10, 40 + i * 4, size[1] - 12), fill=(200, 30, 60))
        frames.append(im.convert('P'))
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=60, loop=0)
    return path


def stub_module(M):
    """把写盘/弹窗类副作用打桩；返回 (saved_dict, restore_fn)。"""
    saved = {}
    real = {}
    real['save_config'] = M.save_config
    M.save_config = lambda cfg: saved.update(cfg)
    mb = M.messagebox
    real['mb'] = (mb.showinfo, mb.showwarning, mb.showerror, mb.askyesno)
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    mb.askyesno = lambda *a, **k: True
    real['set_autostart'] = M.set_autostart
    M.set_autostart = lambda *a, **k: (True, '（独立验证打桩）')

    def restore():
        M.save_config = real['save_config']
        (mb.showinfo, mb.showwarning, mb.showerror, mb.askyesno) = real['mb']
        M.set_autostart = real['set_autostart']
    return saved, restore


def make_wiz(M, cfg, saved, skins_dir, tmp):
    old = getattr(M, 'SKINS_DIR', None)
    M.SKINS_DIR = skins_dir
    wiz = M.ConfigWizard(on_done=lambda c: saved.update(c), overlay=None)
    if old is not None:
        M.SKINS_DIR = old
    if cfg:
        wiz.cfg.update(cfg)
    wiz._layer_sync_from_cfg()
    wiz.root.update_idletasks()
    wiz.root.update()
    return wiz


def kill_wiz(wiz):
    try:
        for aid in str(wiz.root.tk.call('after', 'info')).split():
            try:
                wiz.root.after_cancel(aid)
            except Exception:
                pass
    except Exception:
        pass
    try:
        wiz.root.destroy()
    except Exception:
        pass


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


def _var_attr_map(wiz):
    """Tk 变量对象 → 向导属性名（如 var_scale）。PY_VARn 每次实例不同，不能拿来对照。"""
    import tkinter as tk
    m = {}
    for k, v in vars(wiz).items():
        try:
            if isinstance(v, tk.Variable):
                m[str(v)] = k
        except Exception:
            pass
    return m


def inventory(wiz):
    """③~⑭ 相关控件的独立清单：交互控件 (类, 文案, 向导属性名) 多重集 + 变量绑定 + 编号标题"""
    vmap = _var_attr_map(wiz)
    inter, binds, titles = {}, {}, {}
    for w in _all_widgets(wiz.root):
        try:
            cls = w.winfo_class()
        except Exception:
            continue
        try:
            txt = str(w.cget('text'))
        except Exception:
            txt = ''
        try:
            var = str(w.cget('variable'))
        except Exception:
            var = ''
        key_var = vmap.get(var, var) if var else ''
        if cls in ('Radiobutton', 'Checkbutton', 'Scale', 'Button', 'Listbox', 'Entry', 'Canvas'):
            inter[(cls, txt, key_var)] = inter.get((cls, txt, key_var), 0) + 1
        if key_var:
            binds[key_var] = binds.get(key_var, 0) + 1
        # 编号标题：不限定控件类（⑫⑬ 是 Labelframe、⑭ 挂在 Checkbutton 上）
        if any(c in txt for c in NUM_CHARS):
            titles[txt] = titles.get(txt, 0) + 1
    return inter, binds, titles


def inventory_by_var(wiz):
    """按「控件类 + 绑定变量」聚合的交互控件清单（**不看 text 文案**）。

    v2.0-R10/R11/R13：⑪ 渲染模式单选删除、图层区「选中层贴哪儿」单选撤销、翻转勾选框搬家 ——
    这几轮改的都是**文案或位置**，控件的类与变量绑定没变。E06/E07 的「控件一个不少」对照因此
    改走这条口径：只比 (类, 变量) 的多重集，文案改写不再误报「丢控件」；而控件真的消失
    （变量绑定数变少）仍会被抓出来。
    """
    vmap = _var_attr_map(wiz)
    inter, binds = {}, {}
    for w in _all_widgets(wiz.root):
        try:
            cls = w.winfo_class()
        except Exception:
            continue
        if cls not in ('Radiobutton', 'Checkbutton', 'Scale', 'Button', 'Listbox',
                       'Entry', 'Canvas'):
            continue
        try:
            var = str(w.cget('variable'))
        except Exception:
            var = ''
        key_var = vmap.get(var, var) if var else ''
        inter[(cls, key_var)] = inter.get((cls, key_var), 0) + 1
        if key_var:
            binds[key_var] = binds.get(key_var, 0) + 1
    return inter, binds


def _find_widget(wiz, cls=None, text_contains=None):
    for w in _all_widgets(wiz.root):
        try:
            if cls is not None and w.winfo_class() != cls:
                continue
            if text_contains is not None and text_contains not in str(w.cget('text')):
                continue
            return w
        except Exception:
            continue
    return None


def _btn_row_bottom(wiz):
    try:
        w = wiz.btn_row
        return int(w.winfo_rooty() - wiz.root.winfo_rooty() + w.winfo_height())
    except Exception:
        return -1


def _tmp_pngs(d):
    return set(f for f in os.listdir(d) if f.startswith('preprocessed_') and f.endswith('.png'))


def open_dialog(mod, root, path, stub_msgs=True):
    if stub_msgs:
        mod.messagebox.showinfo = lambda *a, **k: None
        mod.messagebox.showwarning = lambda *a, **k: None
        mod.messagebox.showerror = lambda *a, **k: None
    t0 = time.perf_counter()
    dlg = mod.ImagePreprocessDialog(root, path)
    dt = (time.perf_counter() - t0) * 1000.0
    return dlg, dt


def kill_dialog(dlg):
    try:
        dlg._alive = False
    except Exception:
        pass
    try:
        for aid in str(dlg.root.tk.call('after', 'info')).split():
            try:
                dlg.root.after_cancel(aid)
            except Exception:
                pass
    except Exception:
        pass
    try:
        dlg.root.destroy()
    except Exception:
        pass


# ==========================================================================
# E 段 · R4 窗口重排
# ==========================================================================
def section_E(tmp):
    section('E 段 · R4 窗口重排：需求尺寸 / 列高 / 按钮行 / ②~⑭ 清单 / 端到端')
    p, info = extract_version('a133e9a', 'pre_r4', tmp)
    PRE = load_module(p, 'rc_pre_r4') if p else None
    if PRE is None:
        check('E00 能取到 R4 之前的模块做对照', False, str(info))
        return
    skins = os.path.join(tmp, 'skins_E')
    os.makedirs(skins, exist_ok=True)
    a = make_png(os.path.join(tmp, 'E_a.png'), (120, 180), (220, 60, 60, 255))
    b = make_png(os.path.join(tmp, 'E_b.png'), (80, 200), (60, 90, 220, 255))
    cfg = {'image': a, 'side': 'right', 'scale': 1.0, 'offset_x': 0, 'offset_y': 0,
           'layers': [{'image': a, 'anchor': 'right_edge', 'z': 0},
                      {'image': b, 'anchor': 'left_edge', 'z': 1}]}
    try:
        s1, r1 = stub_module(PRE)
        w_pre = None
        try:
            w_pre = make_wiz(PRE, cfg, s1, skins, tmp)
            pre_h, pre_w = int(w_pre.root.winfo_reqheight()), int(w_pre.root.winfo_reqwidth())
        finally:
            if w_pre is not None:
                kill_wiz(w_pre)
            r1()
        s2, r2 = stub_module(R)
        w = None
        try:
            w = make_wiz(R, cfg, s2, skins, tmp)
            h, ww = int(w.root.winfo_reqheight()), int(w.root.winfo_reqwidth())
            note(f'窗口需求尺寸：R4 前 {pre_w}x{pre_h} → HEAD {ww}x{h}'
                 f'（高 {h - pre_h:+d} / 宽 {ww - pre_w:+d}）')
            adv = w.adv_area
            cols = list(getattr(w, 'adv_cols', []))
            col_h = [int(c.winfo_reqheight()) for c in cols]
            col_w = [int(c.winfo_reqwidth()) for c in cols]
            widest = 0
            col_child_max = []
            for c in cols:
                cmax = 0
                for child in list(c.winfo_children()):
                    try:
                        cmax = max(cmax, int(child.winfo_reqwidth()))
                    except Exception:
                        pass
                col_child_max.append(cmax)
                widest = max(widest, cmax)
            # v2.0-R11/R12（写死阈值的前提被推翻）：① 高度 +29px（③ 行 + 图层区说明行）；
            # ② R12 起 ⚙ 高级设置可折叠。单一的 900 已不成立 → 改为**两态**断言：
            # 展开态 < R4 前基线且 ≤ 工作区高（按钮行仍在窗内）；折叠态明显更矮、且能回到展开态。
            workh_e = int(R.screen_work_area_height(w.root) or 0)
            h_open = h
            h_closed = h_reopen = -1
            try:
                w._toggle_adv_collapse(True)
                w.root.update_idletasks()
                h_closed = int(w.root.winfo_reqheight())
                w._toggle_adv_collapse(False)
                w.root.update_idletasks()
                h_reopen = int(w.root.winfo_reqheight())
            except Exception as _e:
                note(f'（折叠两态测量失败：{_e!r}）')
            btm_open = _btn_row_bottom(w)
            check('E01 ★窗口两态：展开态 < R4 前基线且 ≤ 工作区（按钮行在窗内），'
                  '折叠态明显更矮且可回展开',
                  h_open < pre_h and 0 < h_open <= workh_e and h_closed > 0
                  and h_closed < h_open and abs(h_reopen - h_open) <= 2
                  and 0 < btm_open <= workh_e,
                  f'R4 前 {pre_h} → 展开 {h_open}（−{pre_h - h_open}）/ 折叠 {h_closed}'
                  f'（−{h_open - h_closed}）/ 再展开 {h_reopen}；工作区={workh_e} '
                  f'按钮行底={btm_open}')
            check('E02 ★窗口需求宽度也确实变小（横排后不被顶宽）',
                  ww < pre_w, f'R4 前 {pre_w} → HEAD {ww}（−{pre_w - ww}）')
            adv_block = int(adv.winfo_reqheight())
            check('E03 ⚙ 高级设置块高度 = 最高列高度 + 容器边距（横排生效，不是原竖排 901）',
                  bool(cols) and max(col_h) <= 340 and 0 <= adv_block - max(col_h) <= 40,
                  f'列数={len(cols)} 列高={col_h} adv块={adv_block}（差 {adv_block - max(col_h)}）')
            workh = int(R.screen_work_area_height(w.root) or 0)
            btm = _btn_row_bottom(w)
            check('E04 按钮行底边在屏幕工作区内（窗内可见，不用滚到底）',
                  0 < btm <= workh, f'底边={btm} 工作区高={workh}')
            check('E05 最高列高度 = 自报的 299 量级（3 列手工平衡成立）',
                  max(col_h) <= 340, f'列高={col_h}')
            # ②~⑭ 控件清单：对 R4 前做超集对照
            s3, r3 = stub_module(PRE)
            wp2 = None
            try:
                wp2 = make_wiz(PRE, cfg, s3, skins, tmp)
                _inter_pre, _binds_pre, _titles_pre = inventory(wp2)
                _inter_pre_v, _binds_pre_v = inventory_by_var(wp2)
            finally:
                if wp2 is not None:
                    kill_wiz(wp2)
                r3()
            inter, binds, titles = inventory(w)
            inter_v, binds_v = inventory_by_var(w)
            lost_titles = {k: v for k, v in _titles_pre.items() if titles.get(k, 0) < v}
            note(f'交互控件数：R4 前 {sum(_inter_pre.values())} → HEAD {sum(inter.values())}；'
                 f'变量绑定 {len(_binds_pre)} → {len(binds)}；编号标题 {len(_titles_pre)} → {len(titles)}')
            # v2.0-R10/R11（前提被需求推翻）：⑪ 渲染模式单选组删除（入口 → ⑩ 旁「增强（真羽化）」开关）、
            # 图层区「选中层贴哪儿」单选撤销（③ 回通用区统一管所有图层）。这两组控件是**需求主动删的**，
            # 超集对照里按 (控件类, 变量) 排除（不看文案）；随即用 E06b/E07b 独立核对
            # 「确实删了 + 功能入口仍在」——谁把它们加回来、或功能入口没了，都会红。
            REMOVED_BY_R10_R11 = {('Radiobutton', 'var_render'),
                                  ('Radiobutton', 'var_layer_anchor')}
            lost_inter_v = {k: v for k, v in _inter_pre_v.items()
                            if k not in REMOVED_BY_R10_R11 and inter_v.get(k, 0) < v}
            lost_binds_v = {k: v for k, v in _binds_pre_v.items()
                            if k not in ('var_render', 'var_layer_anchor')
                            and binds_v.get(k, 0) < v}
            check('E06 ★②~⑭ 控件一个不少（按「控件类 + 变量绑定」聚合，不看文案；'
                  'R10/R11 需求删项除外）',
                  not lost_inter_v,
                  f'丢失={lost_inter_v or "无"}（排除={sorted(map(str, REMOVED_BY_R10_R11))}）')
            check('E07 ★所有控件绑定的变量一份不少（同上，不看文案；无静默丢控件）',
                  not lost_binds_v, f'丢失={lost_binds_v or "无"}')
            has_alpha_chk = getattr(w, 'chk_alpha_feather', None) is not None
            check('E06b ★R10 后 ⑪ 单选确已删除（绑 var_render 的 Radiobutton = 0），'
                  '且功能入口仍在（⑩ 旁「增强（真羽化）」开关）',
                  binds_v.get('var_render', 0) == 0
                  and inter_v.get(('Radiobutton', 'var_render'), 0) == 0
                  and has_alpha_chk,
                  f"var_render 绑定={binds_v.get('var_render', 0)} 增强开关={has_alpha_chk}")
            check('E07b ★R11 后图层区贴边单选确已撤销（绑 var_layer_anchor 的 Radiobutton = 0），'
                  '③ 回通用区并绑 3 个单选',
                  inter_v.get(('Radiobutton', 'var_layer_anchor'), 0) == 0
                  and binds_v.get('var_side', 0) >= 3,
                  f"var_layer_anchor 单选={inter_v.get(('Radiobutton', 'var_layer_anchor'), 0)} "
                  f"var_side 绑定={binds_v.get('var_side', 0)}")
            # 编号标题：⑪ 按需求删除；③ 与图层区说明行的**文案**按 R11 改写（编号仍在）——
            # 故以「编号 ③ 的新标题仍在 + ⑪ 字样不再出现」守判别力，而不是逐字比对旧文案。
            LOST_OK = {k for k in _titles_pre
                       if '⑪' in k or '③ 贴边方向（当前层' in k or '都作用于它' in k}
            lost_titles_v = {k: v for k, v in _titles_pre.items()
                             if k not in LOST_OK and titles.get(k, 0) < v}
            has_11_left = [t for t in titles if '⑪' in t]
            has_3_new = [t for t in titles if '③' in t and '所有图层' in t]
            check('E08 编号标题（⑪ 已按 R10 删除；③ 文案按 R11 改写但编号仍在）',
                  not lost_titles_v and not has_11_left and bool(has_3_new),
                  f'丢失={lost_titles_v or "无"} ⑪残留={has_11_left or "无"} 新③标题={has_3_new or "无"}')
            note(f'新增编号标题（R4/R11 引入的说明行，允许）：'
                 f'{ {k: v for k, v in titles.items() if k not in _titles_pre} or "无"}')
            # 列数 vs 工作区宽度（可注入）
            real_saw = R.screen_work_area_width
            try:
                got = {}
                for width in (1920, 1366, 1024, 900, 800, 640):
                    R.screen_work_area_width = lambda root=None, _w=width: _w
                    got[width] = int(w._adv_column_count())
                exp = {1920: 3, 1366: 3, 1024: 2, 900: 2, 800: 1, 640: 1}
                calc = {k: max(1, min(3, (k - 60) // 380)) for k in got}
                check('E09 ★列数按工作区宽度自适应（实测 == 独立复算）',
                      got == exp == calc, f'实测={got} 期望={exp} 复算={calc}')
            finally:
                R.screen_work_area_width = real_saw
            # 除数 380 的正当性：最宽卡实测宽度 vs 800 宽下若按旧除数 330 得 2 列所需宽度
            avail_800_2col = (800 - 60) // 2
            old_div_cols = max(1, min(3, (800 - 60) // 330))
            check('E10 ★除数 330→380 由实测支撑：最宽卡宽度 > 800 宽按 2 列分到的列宽',
                  widest > avail_800_2col and old_div_cols == 2 and len(cols) >= 1,
                  f'最宽卡={widest}px；旧除数在 800 宽下得 {old_div_cols} 列 → 每列仅 {avail_800_2col}px '
                  f'< {widest}px（会挤/裁）')
            check('E11 每列列宽 ≥ 该列自己最宽卡（无裁切）',
                  all(cw + 2 >= cm for cw, cm in zip(col_w, col_child_max)),
                  f'列宽={col_w} 各列最宽卡={col_child_max}')
            # 最高列由哪张卡决定 + 867 是否已是「不动卡片/预览」前提下的结构下限
            tallest = (0, '')
            for c in cols:
                for child in list(c.winfo_children()):
                    try:
                        hh = int(child.winfo_reqheight())
                        txt = str(child.cget('text'))[:24]
                    except Exception:
                        continue
                    if hh > tallest[0]:
                        tallest = (hh, txt)
            top_h = int(w.top_block.winfo_reqheight())
            floor = h - (adv_block - (tallest[0] + 33))
            note(f'（分析）最高单卡 = {tallest[0]}px（{tallest[1]!r}）；预览块 top_block={top_h}px；'
                 f'adv 块={adv_block}px；窗口={h}px')
            note(f'（分析）结构下限估算 = 窗口 −(adv可压量) = {floor}px：adv 已压到'
                 f'「最高单卡+边距」= {tallest[0] + 33}px，再加列也压不动单卡 → '
                 f'在不拆卡/不缩预览块的前提下 867 已是下限（差 {h - floor}px）')
            check('E14 ★867 已是「不拆卡 / 不缩预览块」前提下的结构下限（差距 ≤ 60px）',
                  bool(tallest[0]) and (h - floor) <= 60,
                  f'最高单卡={tallest[0]}px（{tallest[1]!r}）adv={adv_block} 窗口={h} 下限={floor}')
            # 4 列假设的代价（分析用，不判红）：必须先改类方法再构造才会真的建 4 列
            try:
                real_cnt = R.ConfigWizard._adv_column_count
                R.ConfigWizard._adv_column_count = lambda self: 4
                s6, r6 = stub_module(R)
                w4 = None
                try:
                    w4 = make_wiz(R, cfg, s6, skins, tmp)
                    n4 = len(list(getattr(w4, 'adv_cols', [])))
                    c4 = [int(x.winfo_reqheight()) for x in list(getattr(w4, 'adv_cols', []))]
                    note(f'（分析）重建为 4 列骨架：列数={n4} 列高={c4} 窗口需求='
                         f'{int(w4.root.winfo_reqwidth())}x{int(w4.root.winfo_reqheight())}'
                         f'（3 列 {ww}x{h}）→ 第 4 列在 col_of 映射表外（当前表只覆盖 3 列），'
                         f'且 _adv_column_count 用 min(3,…) 封顶 → 生产里 4 列不可达')
                finally:
                    if w4 is not None:
                        kill_wiz(w4)
                    r6()
                    R.ConfigWizard._adv_column_count = real_cnt
            except Exception as e:
                note(f'（分析）4 列测量失败：{e!r}')
            # 端到端：release/config.json
            try:
                with open(os.path.join(BASE, 'release', 'config.json'), encoding='utf-8') as f:
                    raw = json.load(f)
                cfg2 = dict(R.DEFAULT_CONFIG)
                cfg2.update(raw)
                before = {k: cfg2.get(k) for k in ('image', 'side', 'scale', 'offset_x',
                                                   'offset_y', 'base_height', 'layout',
                                                   'layer', 'name')}
                s4, r4 = stub_module(R)
                w2 = None
                try:
                    w2 = make_wiz(R, cfg2, s4, skins, tmp)
                    h2, w2r = int(w2.root.winfo_reqheight()), int(w2.root.winfo_reqwidth())
                    has_img = bool(getattr(w2, 'tk_img', None)) or bool(w2._preview_specs())
                    inter2, binds2, titles2 = inventory(w2)
                    miss = {k: v for k, v in _titles_pre.items()
                            if k not in LOST_OK and titles2.get(k, 0) < v}
                    workh2 = int(R.screen_work_area_height(w2.root) or 0)
                    left_11 = [t for t in titles2 if '⑪' in t]
                    s4.clear()
                    w2._save_and_start()
                    out = dict(s4)
                    drift = {k: (before[k], out.get(k)) for k in before if out.get(k) != before[k]}
                    check('E12 ★端到端（release/config.json）：重排后预览与 ②~⑭ 齐全'
                          '（⑪ 已按 R10 删除）、保存零漂移、窗口 ≤ 工作区',
                          has_img and not miss and not drift and 0 < h2 <= workh2
                          and not left_11,
                          f'需求={w2r}x{h2} 预览={"有" if has_img else "无"} 缺标题={miss or "无"} '
                          f'漂移={drift or "无"} 工作区={workh2} ⑪残留={left_11 or "无"}')
                finally:
                    if w2 is not None:
                        kill_wiz(w2)
                    r4()
            except Exception as e:
                import traceback
                traceback.print_exc()
                check('E12 端到端段未抛异常', False, repr(e))
            # 小工作区模拟（1366×768 → 工作区高 728）
            try:
                real_h = R.screen_work_area_height
                R.screen_work_area_height = lambda root=None: 728
                s5, r5 = stub_module(R)
                w3 = None
                try:
                    w3 = make_wiz(R, cfg, s5, skins, tmp)
                    btm3 = _btn_row_bottom(w3)
                    check('E13 小工作区（1366×768，工作区 728）：出滚动条且按钮行底边 ≤ 728',
                          bool(getattr(w3, '_scroll_needed', False)) and 0 < btm3 <= 728,
                          f'scroll_needed={getattr(w3, "_scroll_needed", None)} 底边={btm3}')
                finally:
                    if w3 is not None:
                        kill_wiz(w3)
                    r5()
                R.screen_work_area_height = real_h
            except Exception as e:
                check('E13 小工作区段未抛异常', False, repr(e))
        finally:
            if w is not None:
                kill_wiz(w)
            r2()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('E00 E 段未抛异常', False, repr(e))
    del PRE


# ==========================================================================
# F 段 · R5 配色注入
# ==========================================================================
def _fake_fields(prefix):
    return {f: ('%s-%s' % (prefix, f)) for f in R.SCHEME_FIELDS}


def section_F(tmp):
    section('F 段 · R5 配色注入：yaml 分节原文 / 幂等 / 未存皮肤先提示 / 切皮肤恢复')
    yml = os.path.join(tmp, 'F_custom.yaml')
    # 「紧贴上一块」的用户现场输入（无空行、无本工具标题）
    base_txt = (
        'patch:\r\n'
        '  # ===== 柚子橙 🍊 亮色 =====\r\n'
        '  "preset_color_schemes/yuzu_orange/name": "柚子橙"\r\n'
        '  "preset_color_schemes/yuzu_orange/back_color": [255, 255, 255, 255]\r\n'
        '  "style/color_scheme": "yuzu_orange"\r\n'
    )
    with open(yml, 'w', encoding='utf-8', newline='') as f:
        f.write(base_txt)
    light, dark = _fake_fields('#111'), _fake_fields('#222')
    # 用户真实通路生成字段（出厂图 → 主题 → 21 字段），比手搓夹具更接近现场
    try:
        from PIL import Image as PILImage
        raw = json.load(open(os.path.join(BASE, 'release', 'config.json'), encoding='utf-8'))
        frames, meta = R.collect_scheme_frames(raw['image'], PILImage)
        theme = R.extract_scheme_theme(frames, PILImage)
        names = R.make_scheme_names('阿芙')
        light = R.build_scheme_fields('阿芙', theme, dark=False, scheme=names[0])
        dark = R.build_scheme_fields('阿芙', theme, dark=True, scheme=names[1])
        note(f'真实生成的字段名 {len(light)} 个；样例三行：')
        for f in list(R.SCHEME_FIELDS)[:3]:
            note(f'   {R._format_scheme_line(names[0], f, light[f]).strip()}')
        risky = [f for f, v in list(light.items()) + list(dark.items())
                 if str(v).startswith('#')]
        note(f'（边界）真实生成字段里以 # 开头的裸值：{risky or "无"}；'
             f'_format_scheme_line 对这类字符串不加引号（合成夹具用 #111-* 会产出 YAML 注释 → '
             f'非幂等，属工具既有格式化口径，真实生成路径不触发）')
    except Exception as e:
        note(f'真实字段生成失败，退回合成字段：{e!r}')
        names = ('阿芙', '阿芙_dark')
    plan = R.plan_scheme_injection(yml, skin='阿芙', light=light, dark=dark,
                                   scheme_light=names[0], scheme_dark=names[1])
    check('F01 注入计划成功（tempfile，绝不碰真机）', bool(plan.get('ok')), plan.get('msg'))
    new_lines = plan['new_text'].splitlines()
    hi = new_lines.index('  # ===== 阿芙 =====') if '  # ===== 阿芙 =====' in new_lines else -1
    di = (new_lines.index('  # ===== 阿芙 · 深色 =====')
          if '  # ===== 阿芙 · 深色 =====' in new_lines else -1)
    note('注入后新块附近原文：')
    for j in range(max(0, hi - 2), min(len(new_lines), hi + 4)):
        note(f'   行{j + 1:>3}: {new_lines[j]}')
    for j in range(max(0, di - 2), min(len(new_lines), di + 3)):
        note(f'   行{j + 1:>3}: {new_lines[j]}')
    check('F02 ★亮色块前有分节标题且标题前有空行（不再与上一个皮肤并在一起）',
          hi > 0 and new_lines[hi - 1].strip() == ''
          and new_lines[hi - 2].strip().startswith('"style/color_scheme"'),
          f'标题行号={hi + 1} 上一行={new_lines[hi - 1]!r}')
    check('F03 ★深色块同样有分节标题（亮/暗两个标题都在）',
          di > hi, f'亮标题={hi + 1} 暗标题={di + 1}')
    # 实测用户自己文件的约定：12 个分节标题里 11 个紧贴上一行键（亮→暗之间不留空行）
    check('F04 深色标题紧贴自己的第一行键（与用户文件现有写法同形）',
          di > 0 and f'preset_color_schemes/{names[1]}/' in new_lines[di + 1],
          f'暗标题后一行={new_lines[di + 1][:60]!r}')
    note(f'（对照）用户自己 weasel.custom.yaml 的 12 个分节标题中，亮→暗之间留空行的有 1 个、'
         f'不留空行的有 11 个 → 本工具「同一皮肤亮/暗连排、只在皮肤块前留空行」与其一致')
    check('F06 原文件注释一条不丢（柚子橙标题仍在且顺序不变）',
          new_lines.index('  # ===== 柚子橙 🍊 亮色 =====') == 1,
          f'索引={new_lines.index("  # ===== 柚子橙 🍊 亮色 =====")}')
    # 幂等
    res = R.apply_scheme_injection(plan)
    after1 = open(yml, encoding='utf-8', newline='').read()
    baks1 = sorted(f for f in os.listdir(tmp) if f.startswith('F_custom.yaml.bak-'))
    last_key = di + 1 + len(R.SCHEME_FIELDS) - 1
    check('F05 新块之后留有空行（后面还有既存内容时不相贴）',
          last_key + 1 >= len(new_lines) or new_lines[last_key + 1].strip() == '',
          f'末键行号={last_key + 1} 下行={new_lines[last_key + 1][:40]!r}'
          if last_key + 1 < len(new_lines) else '块在文件末尾')
    plan2 = R.plan_scheme_injection(yml, skin='阿芙', light=light, dark=dark,
                                    scheme_light=names[0], scheme_dark=names[1])
    check('F07 ★幂等：第二次注入 diff 为空（不重复写标题/键）',
          plan2.get('ok') and not plan2.get('diff') and plan2['new_text'] == after1,
          f'diff 行数={len(plan2.get("diff") or [])} 首条={(plan2.get("diff") or [""])[0][:80]!r}')
    res2 = R.apply_scheme_injection(plan2)
    after2 = open(yml, encoding='utf-8', newline='').read()
    baks2 = sorted(f for f in os.listdir(tmp) if f.startswith('F_custom.yaml.bak-'))
    check('F08 ★幂等：第二次不落盘、不新增 .bak',
          after2 == after1 and len(baks2) == len(baks1),
          f'内容一致={after2 == after1} .bak {len(baks1)}→{len(baks2)}')
    # 真实文件只读副本
    try:
        real_yaml = os.path.join(os.environ.get('APPDATA', ''), 'Rime', 'weasel.custom.yaml')
        cp = os.path.join(tmp, 'F_real_copy.yaml')
        shutil.copyfile(real_yaml, cp)
        orig = open(cp, encoding='utf-8', newline='').read()
        pl = R.plan_scheme_injection(cp, skin='独立验证皮肤', light=light, dark=dark,
                                     scheme_light='独立验证皮肤', scheme_dark='独立验证皮肤_dark')
        import collections
        cmt = lambda t: collections.Counter(l.strip() for l in t.splitlines()
                                           if l.strip().startswith('#'))
        d_new = cmt(pl['new_text']) - cmt(orig)
        d_lost = cmt(orig) - cmt(pl['new_text'])
        orig_cmts = [l.strip() for l in orig.splitlines() if l.strip().startswith('#')]
        new_cmts = [l.strip() for l in pl['new_text'].splitlines() if l.strip().startswith('#')]
        keep = [c for c in new_cmts if c in set(orig_cmts)]
        check('F09 ★真实 weasel.custom.yaml 副本：原注释一条不丢（多重集差集为空）',
              not d_lost, f'丢失={list(d_lost.elements())[:5]}')
        check('F10 ★真实文件：新增注释恰好 2 个分节标题（亮 + 深色）',
              set(d_new) == {'# ===== 独立验证皮肤 =====', '# ===== 独立验证皮肤 · 深色 ====='}
              and sum(d_new.values()) == 2, f'新增={dict(d_new)}')
        check('F11 真实文件：原有注释相对顺序不变（是子序列）',
              keep == orig_cmts, f'原 {len(orig_cmts)} 条 / 保留 {len(keep)} 条')
        lines = pl['new_text'].splitlines()
        hi2 = lines.index('  # ===== 独立验证皮肤 =====')
        check('F12 真实文件：新块标题前有空行、标题后紧贴自己的第一行键',
              lines[hi2 - 1].strip() == '' and 'preset_color_schemes/独立验证皮肤/' in lines[hi2 + 1],
              f'前一行={lines[hi2 - 1]!r} 后一行={lines[hi2 + 1][:60]!r}')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('F09 真实副本段未抛异常', False, repr(e))
    # 向导：未保存皮肤先提示（真实通路）
    real_custom, real_manifest, real_skin_dir = R.WEASEL_CUSTOM, R.SCHEME_MANIFEST, R.SKINS_DIR
    real_deploy, real_bind = R.run_weasel_deployer, R.apply_rime_scheme_binding
    skins = os.path.join(tmp, 'skins_F')
    os.makedirs(skins, exist_ok=True)
    wiz_yaml = os.path.join(tmp, 'F_wiz.yaml')
    shutil.copyfile(yml, wiz_yaml)
    try:
        R.WEASEL_CUSTOM = wiz_yaml
        R.SCHEME_MANIFEST = os.path.join(tmp, 'F_manifest.json')
        R.SKINS_DIR = skins
        R.run_weasel_deployer = lambda **k: {'ok': True, 'msg': '（打桩）', 'exe': 'stub',
                                            'rc': 0, 'timed_out': False}
        R.apply_rime_scheme_binding = lambda *a, **k: {'ok': True, 'msg': '（打桩）'}
        img = make_png(os.path.join(tmp, 'F_char.png'), (200, 260), (30, 120, 200, 255))
        cfg = {'image': img, 'side': 'right', 'scale': 1.0, 'offset_x': 0, 'offset_y': 0}
        saved, restore = stub_module(R)
        w = None
        try:
            w = make_wiz(R, cfg, saved, skins, tmp)
            before_txt = open(wiz_yaml, encoding='utf-8', newline='').read()
            before_bak = sorted(f for f in os.listdir(tmp) if f.startswith('F_wiz.yaml.bak-'))
            R.messagebox.askyesno = lambda *a, **k: False       # 用户点「否」= 先不生成
            res_no = w._generate_scheme(auto=False)
            after_txt = open(wiz_yaml, encoding='utf-8', newline='').read()
            after_bak = sorted(f for f in os.listdir(tmp) if f.startswith('F_wiz.yaml.bak-'))
            check('F13 ★未保存皮肤时点生成配色 → 先提示保存（needs_skin），拒绝则零落盘',
                  res_no.get('needs_skin') and not res_no.get('ok')
                  and after_txt == before_txt and len(after_bak) == len(before_bak)
                  and not os.listdir(skins),
                  f"needs_skin={res_no.get('needs_skin')} msg={res_no.get('msg')[:40]!r} "
                  f"档案数={len(os.listdir(skins))}")
            # 同意保存 → 生成 + 绑定
            R.messagebox.askyesno = lambda *a, **k: True
            R.simpledialog.askstring = lambda *a, **k: '阿芙'
            res_yes = w._generate_scheme(auto=False)
            skins_now = os.listdir(skins)
            sj = os.path.join(skins, '阿芙', 'skin.json')
            bound = json.load(open(sj, encoding='utf-8')) if os.path.exists(sj) else {}
            check('F14 ★同意保存 → 建档案 + 生成配色 + 档案绑定配色名',
                  res_yes.get('ok') and '阿芙' in skins_now and bound.get('rime_scheme')
                  and bound.get('rime_scheme') == res_yes.get('scheme_light'),
                  f"ok={res_yes.get('ok')} 档案={skins_now} 绑定={bound.get('rime_scheme')} "
                  f"亮方案={res_yes.get('scheme_light')}")
            check('F15 ★方案名由皮肤名确定性派生（同名同方案、异名异方案）',
                  res_yes.get('scheme_light') == R.make_scheme_names('阿芙')[0]
                  and res_yes.get('scheme_dark') == R.make_scheme_names('阿芙')[1]
                  and R.make_scheme_names('阿芙')[0] != R.make_scheme_names('乙皮肤')[0],
                  f"{res_yes.get('scheme_light')} / {res_yes.get('scheme_dark')}"
                  f"（make_scheme_names('阿芙')={R.make_scheme_names('阿芙')}；"
                  f"乙皮肤={R.make_scheme_names('乙皮肤')}）")
            note('（说明）Rime 方案名走 ASCII 安全字符（中文皮肤名 → rime_skin<crc32>，'
                 'make_scheme_names 的既有设计，R5 未改）；用户在 yaml 里靠分节标题'
                 '「# ===== 阿芙 =====」认块 → 可读性诉求由标题承担')
            check('F16 生成后写入的 yaml 里带分节标题',
                  '  # ===== 阿芙 =====' in open(wiz_yaml, encoding='utf-8').read(),
                  '已写入')
            # 切皮肤整套恢复
            R.save_skin('乙皮肤', {'image': img, 'side': 'left', 'scale': 0.8,
                                   'offset_x': -20, 'offset_y': -10, 'rime_scheme': '乙皮肤',
                                   'rime_scheme_dark': '乙皮肤_dark'})
            w.skin_var.set('阿芙')
            w._apply_skin_to_wizard()
            a1 = (w.cfg.get('rime_scheme'), w.var_side.get())
            w.skin_var.set('乙皮肤')
            w._apply_skin_to_wizard()
            a2 = (w.cfg.get('rime_scheme'), w.var_side.get())
            w.skin_var.set('阿芙')
            w._apply_skin_to_wizard()
            a3 = (w.cfg.get('rime_scheme'), w.var_side.get())
            check('F17 ★切皮肤整套恢复（配色名跟随皮肤，不串）',
                  a2[0] == '乙皮肤' and a2[1] == 'left' and a3[0] == a1[0] and a1[1] == 'right',
                  f'A={a1} B={a2} A2={a3}')
        finally:
            if w is not None:
                kill_wiz(w)
            restore()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('F13 向导段未抛异常', False, repr(e))
    finally:
        R.WEASEL_CUSTOM, R.SCHEME_MANIFEST, R.SKINS_DIR = real_custom, real_manifest, real_skin_dir
        R.run_weasel_deployer, R.apply_rime_scheme_binding = real_deploy, real_bind


# ==========================================================================
# G 段 · R6 动图预览
# ==========================================================================
def section_G(tmp):
    section('G 段 · R6 预处理动图：打开耗时 / 按需解码 / 节拍 / 销毁 / 静态零漂移')
    import tkinter
    big = make_gif(os.path.join(tmp, 'G_big.gif'), (320, 240), 120, noise=True)
    small = make_gif(os.path.join(tmp, 'G_small.gif'), (240, 320), 8)
    odd = make_odd_gif(os.path.join(tmp, 'G_odd.gif'), (320, 240), 4)
    png = make_png(os.path.join(tmp, 'G_static.png'), (240, 320), (60, 160, 90, 255))
    note(f'夹具：大 GIF {os.path.getsize(big) / 1e6:.2f} MB / 120 帧；'
         f'小 GIF {os.path.getsize(small)} B / 8 帧；异尺寸 GIF 4 帧')
    root = tkinter.Tk()
    root.withdraw()
    dlg_pre = dlg = None
    try:
        # 大 GIF：打开耗时对 103c97f 同口径对照
        pre_path, info = extract_version('103c97f', 'pre_r6', tmp)
        PRE = load_module(pre_path, 'rc_pre_r6') if pre_path else None
        t_pre = None
        if PRE is not None:
            dlg_pre, t_pre = open_dialog(PRE, root, big)
        dlg, t_new = open_dialog(R, root, big)
        note(f'大 GIF 打开耗时：改前 {t_pre and round(t_pre, 1)} ms → HEAD {round(t_new, 1)} ms')
        check('G01 ★大 GIF 打开不再一次性全解码（打开后解码次数 = 0 或 1）',
              int(getattr(dlg, '_decode_calls', 99)) <= 1,
              f'decode_calls={getattr(dlg, "_decode_calls", None)}')
        check('G02 ★大 GIF 打开耗时显著低于改前（同口径同机对照）',
              t_pre is None or (t_new < t_pre * 0.6),
              f'改前 {t_pre and round(t_pre, 1)} ms → 改后 {round(t_new, 1)} ms')
        check('G03 打开耗时绝对值可接受（≤ 1500 ms，10 MB 级 120 帧）',
              t_new <= 1500, f'{round(t_new, 1)} ms')
        # 播放节拍
        d0 = int(dlg._decode_calls)
        dlg._toggle_preview()
        ticks = []
        decs = []
        for _ in range(10):
            t0 = time.perf_counter()
            dlg._preview_tick()
            ticks.append((time.perf_counter() - t0) * 1000.0)
            decs.append(int(dlg._decode_calls) - d0)
            d0 = int(dlg._decode_calls)
        dlg._stop_preview(reset=False)
        note(f'播放 10 tick：单 tick p50={statistics.median(ticks):.1f} ms / max={max(ticks):.1f} ms；'
             f'每 tick 解码增量={decs}')
        check('G04 ★每 tick 至多解一帧（按需解码，绝不一次性全解）',
              all(x <= 1 for x in decs), f'解码增量序列={decs}')
        check('G05 单 tick 耗时 ≤ 100 ms（不卡 UI 的量级）',
              statistics.median(ticks) <= 100, f'p50={statistics.median(ticks):.1f} ms')
        # 逐帧 + 回绕
        dlg._preview_goto(3)
        i3 = dlg.preview_idx
        d_calls = int(dlg._decode_calls)
        dlg._preview_step(-1)
        i2 = dlg.preview_idx
        dlg._preview_goto(0)
        d_after_wrap = int(dlg._decode_calls)
        check('G06 逐帧/跳帧正确，且回到首帧不重复解码（首帧复用静态 work）',
              i3 == 3 and i2 == 2 and dlg.preview_idx == 0 and d_after_wrap == d_calls,
              f'goto(3)={i3} step(-1)={i2} goto(0)={dlg.preview_idx} 解码 {d_calls}→{d_after_wrap}')
        # 销毁清理
        pend_before = set(str(root.tk.call('after', 'info')).split())
        dlg._toggle_preview()
        after_id = dlg._anim_after
        dlg._cancel()
        pend_after = set(str(root.tk.call('after', 'info')).split())
        pend_s = ' '.join(sorted(pend_after))
        leftover = [x for x in (pend_after - pend_before)
                    if x.strip('[],') and str(after_id) not in x]
        check('G07 ★关闭对话框：停表 + after 句柄被取消 + 标记不再碰 Tk',
              getattr(dlg, '_alive', True) is False and dlg._anim_after is None
              and dlg._playing is False
              and (after_id is None or str(after_id) not in pend_s) and not leftover,
              f'alive={getattr(dlg, "_alive", None)} after={dlg._anim_after} '
              f'playing={dlg._playing} 新增未清回调={leftover or "无"}')
        late_ok = True
        try:
            dlg._preview_tick()
        except Exception as e:
            late_ok = False
            note(f'迟到 tick 抛异常：{e!r}')
        check('G08 销毁后迟到的节拍回调安全返回（不碰已销毁 Tk）', late_ok)
        # 异尺寸帧归一
        dlg2, t2 = open_dialog(R, root, odd)
        try:
            from PIL import Image as PILImage
            sizes = {dlg2._frame_work(k).size for k in range(dlg2.n_frames)}
            check('G09 ★动图各帧 work 尺寸一致（裁剪框坐标系稳定）',
                  len(sizes) == 1 and sizes == {dlg2.work.size},
                  f'各帧 work 尺寸={sizes}（首帧画布 {dlg2.work.size}）')
            # 兜底分支独立探针：第三方写入器给出异尺寸帧时 _canonical_frame 必须归一
            before = dlg2._size_fixups
            probe = dlg2._canonical_frame(PILImage.new('RGBA', (100, 100), (1, 2, 3, 255)))
            check('G09b ★异尺寸帧兜底归一分支可用（_canonical_frame 拉伸回首帧画布）',
                  probe.size == dlg2.orig.size and dlg2._size_fixups == before + 1,
                  f'探针 100x100 → {probe.size}；归一次数 {before}→{dlg2._size_fixups}'
                  f'（本夹具 PIL 读回已同尺寸，故正常路径不触发）')
            # apply 输出的动图各帧尺寸也必须一致
            outd = os.path.join(tmp, 'G_odd_out')
            os.makedirs(outd, exist_ok=True)
            old_here = R.HERE
            R.HERE = outd
            dd = None
            try:
                dd, _ = open_dialog(R, root, odd)
                dd._apply()
            finally:
                if dd is not None:
                    kill_dialog(dd)
                R.HERE = old_here
            files = sorted(_tmp_pngs(outd))
            if files:
                im2 = PILImage.open(os.path.join(outd, files[-1]))
                fsizes = set()
                for k in range(int(getattr(im2, 'n_frames', 1) or 1)):
                    try:
                        im2.seek(k)
                    except Exception:
                        pass
                    fsizes.add(im2.size)
                check('G09c ★应用（导出）后各帧画布尺寸一致（APNG 要求同画布）',
                      len(fsizes) == 1, f'导出帧尺寸集合={fsizes} 帧数={getattr(im2, "n_frames", 1)}')
            else:
                check('G09c 异尺寸动图导出成功', False, '未产出文件')
            dlg2._preview_goto(dlg2.n_frames - 1)
            check('G09d 异尺寸帧也能翻到最后一帧并绘制',
                  dlg2.preview_idx == dlg2.n_frames - 1, f'idx={dlg2.preview_idx}')
        finally:
            kill_dialog(dlg2)
        # 静态图：UI 一字不变 + apply 输出与改前逐像素一致
        dlg3, _ = open_dialog(R, root, png)
        try:
            check('G10 ★静态图不出现动图预览区（UI 一字不变）',
                  not hasattr(dlg3, 'lbl_frame') and not hasattr(dlg3, 'btn_play')
                  and int(dlg3.n_frames) == 1,
                  f'n_frames={dlg3.n_frames}')
        finally:
            kill_dialog(dlg3)
        if PRE is not None:
            outs = {}
            for mod, tag in ((PRE, 'pre'), (R, 'head')):
                d = os.path.join(tmp, f'G_out_{tag}')
                os.makedirs(d, exist_ok=True)
                old_here = mod.HERE
                mod.HERE = d
                dd = None
                try:
                    dd, _ = open_dialog(mod, root, png)
                    dd._apply()
                finally:
                    if dd is not None:
                        kill_dialog(dd)
                    mod.HERE = old_here
                files = sorted(_tmp_pngs(d))
                outs[tag] = os.path.join(d, files[-1]) if files else None
            if outs.get('pre') and outs.get('head'):
                from PIL import Image, ImageChops
                a1 = Image.open(outs['pre']).convert('RGBA')
                a2 = Image.open(outs['head']).convert('RGBA')
                diff = ImageChops.difference(a1, a2).getbbox()
                b1 = open(outs['pre'], 'rb').read()
                b2 = open(outs['head'], 'rb').read()
                check('G11 ★静态路径 apply 输出与改前逐像素一致（_screen_image 改动零漂移）',
                      a1.size == a2.size and diff is None,
                      f'改前 {a1.size} / 改后 {a2.size} 像素差异={diff}；字节一致={b1 == b2}')
                note(f'（参考）PNG 字节一致={b1 == b2}（大小 {len(b1)} vs {len(b2)}）')
            else:
                check('G11 静态 apply 对照跑成功', False, f'{outs}')
        # 端到端：release 真实资产（出厂静态图 + 真实动图皮肤）
        try:
            import glob
            with open(os.path.join(BASE, 'release', 'config.json'), encoding='utf-8') as f:
                real_png = json.load(f)['image']
            d_st, _ = open_dialog(R, root, real_png)
            try:
                ok_static = (int(d_st.n_frames) == 1 and not hasattr(d_st, 'lbl_frame')
                             and d_st.work is not None and not hasattr(d_st, 'btn_play'))
                n_static = int(d_st.n_frames)
            finally:
                kill_dialog(d_st)
            gifs = sorted(glob.glob(os.path.join(BASE, 'release', 'skins', '*', 'image.gif')))
            ok_gif, n_gif = None, 0
            if gifs:
                d_g, _ = open_dialog(R, root, gifs[0])
                try:
                    n_gif = int(d_g.n_frames)
                    ok_gif = (n_gif > 1 and hasattr(d_g, 'lbl_frame') and hasattr(d_g, 'btn_play'))
                    if ok_gif:
                        d_g._toggle_preview()
                        d_g._preview_tick()
                        ok_gif = d_g.preview_idx == 1 and int(d_g._decode_calls) >= 1
                        d_g._stop_preview(reset=False)
                finally:
                    kill_dialog(d_g)
            check('G12 ★端到端（release 真实资产）：出厂静态图无动图区；真实 GIF 有播放区且能推进',
                  ok_static and (ok_gif is None or ok_gif),
                  f'出厂静态图 n_frames={n_static}（无动图区={ok_static}）；'
                  f'release GIF n_frames={n_gif} 播放可用={ok_gif}')
        except Exception as e:
            import traceback
            traceback.print_exc()
            check('G12 端到端段未抛异常', False, repr(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('G00 G 段未抛异常', False, repr(e))
    finally:
        for d in (dlg, dlg_pre):
            if d is not None:
                kill_dialog(d)
        try:
            root.destroy()
        except Exception:
            pass


# ==========================================================================
# H 段 · 反例
# ==========================================================================
def section_H(tmp):
    section('H 段 · 反例与边界尝试')
    skins = os.path.join(tmp, 'skins_H')
    os.makedirs(skins, exist_ok=True)
    img = make_png(os.path.join(tmp, 'H_char.png'), (120, 180), (200, 60, 60, 255))
    cfg = {'image': img, 'side': 'right', 'scale': 1.0, 'offset_x': 0, 'offset_y': 0}
    # H01 小工作区 / 窄屏
    try:
        saved, restore = stub_module(R)
        w = None
        real_w, real_h = R.screen_work_area_width, R.screen_work_area_height
        try:
            R.screen_work_area_width = lambda root=None: 800
            R.screen_work_area_height = lambda root=None: 600
            w = make_wiz(R, cfg, saved, skins, tmp)
            n1 = len(list(getattr(w, 'adv_cols', [])))
            btm = _btn_row_bottom(w)
            inter, binds, titles = inventory(w)
            R.screen_work_area_width = real_w
            R.screen_work_area_height = real_h
            w4 = None
            try:
                w4 = make_wiz(R, cfg, saved, skins, tmp)
                _inter3, _binds3, _titles3 = inventory(w4)
            finally:
                if w4 is not None:
                    kill_wiz(w4)
            check('H01 ★窄屏 800：列数退到 1 列、出滚动条、②~⑭ 仍一个不少',
                  n1 == 1 and bool(getattr(w, '_scroll_needed', False))
                  and not {k: v for k, v in _titles3.items() if titles.get(k, 0) < v},
                  f'列数={n1} scroll={getattr(w, "_scroll_needed", None)} 底边={btm} '
                  f'缺标题={ {k: v for k, v in _titles3.items() if titles.get(k, 0) < v} or "无"}')
        finally:
            if w is not None:
                kill_wiz(w)
            R.screen_work_area_width, R.screen_work_area_height = real_w, real_h
            restore()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('H01 窄屏段未抛异常', False, repr(e))
    # H02 R5：未保存皮肤 + 非法名 → 零落盘
    try:
        real_custom, real_manifest, real_skin_dir = R.WEASEL_CUSTOM, R.SCHEME_MANIFEST, R.SKINS_DIR
        real_deploy, real_bind = R.run_weasel_deployer, R.apply_rime_scheme_binding
        y = os.path.join(tmp, 'H_custom.yaml')
        with open(y, 'w', encoding='utf-8', newline='') as f:
            f.write('patch:\n  "preset_color_schemes/x/name": "x"\n')
        R.WEASEL_CUSTOM = y
        R.SCHEME_MANIFEST = os.path.join(tmp, 'H_manifest.json')
        R.SKINS_DIR = skins
        R.run_weasel_deployer = lambda **k: {'ok': True, 'msg': '（打桩）', 'exe': 'stub',
                                            'rc': 0, 'timed_out': False}
        R.apply_rime_scheme_binding = lambda *a, **k: {'ok': True, 'msg': '（打桩）'}
        saved, restore = stub_module(R)
        w = None
        try:
            w = make_wiz(R, cfg, saved, skins, tmp)
            b0 = open(y, encoding='utf-8').read()
            R.messagebox.askyesno = lambda *a, **k: True      # 同意保存，但名字空
            R.simpledialog.askstring = lambda *a, **k: '   '
            r_empty = w._generate_scheme(auto=False)
            b1 = open(y, encoding='utf-8').read()
            R.simpledialog.askstring = lambda *a, **k: 'x/../坏名字'
            r_bad = w._generate_scheme(auto=False)
            b2 = open(y, encoding='utf-8').read()
            check('H02 ★未保存皮肤两点异常路径（空名 / 非法名）都零落盘、不建档案',
                  not r_empty.get('ok') and not r_bad.get('ok') and b0 == b1 == b2
                  and not os.listdir(skins),
                  f"空名 ok={r_empty.get('ok')} 非法名 ok={r_bad.get('ok')} "
                  f"yaml变化={b0 != b2} 档案={os.listdir(skins)}")
        finally:
            if w is not None:
                kill_wiz(w)
            restore()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('H02 段未抛异常', False, repr(e))
    finally:
        try:
            R.WEASEL_CUSTOM, R.SCHEME_MANIFEST, R.SKINS_DIR = real_custom, real_manifest, real_skin_dir
            R.run_weasel_deployer, R.apply_rime_scheme_binding = real_deploy, real_bind
        except Exception:
            pass
    # H03 R6：大 GIF 连播 + 手动翻帧穿插 + 销毁后迟到 tick
    try:
        import tkinter
        big = make_gif(os.path.join(tmp, 'H_big.gif'), (320, 240), 80, noise=True)
        root = tkinter.Tk()
        root.withdraw()
        dlg = None
        try:
            dlg, _ = open_dialog(R, root, big)
            # 手工驱动 30 拍：先让节拍不再自我重排（真实使用只有节拍自己排下一次，
            # 手工连调会堆出 N 个 pending timer，属测试夹具行为，不是产品行为）
            real_sched = dlg._schedule_tick
            dlg._schedule_tick = lambda ms: None
            ok = True
            dec = []
            for i in range(30):
                if i % 7 == 3:
                    dlg._preview_step(2)
                elif i % 7 == 5:
                    dlg._preview_goto(dlg.n_frames - 1)
                else:
                    dlg._preview_tick()
                dec.append(int(dlg._decode_calls))
            ok = all(dec[i] >= dec[i - 1] for i in range(1, len(dec)))
            dlg._schedule_tick = real_sched
            dlg._cancel()
            late_ok = True
            try:
                dlg._preview_tick()
                dlg._draw()
            except Exception as ee:
                late_ok = False
                note(f'迟到回调抛异常：{ee!r}')
            check('H03 ★大 GIF 连播 30 拍 + 手动翻帧穿插：解码单调、无异常；销毁后迟到回调安全',
                  ok and late_ok and dec[-1] <= 80,
                  f'解码累计={dec[-1]}（帧数 {dlg.n_frames}）迟到回调安全={late_ok}')
        finally:
            if dlg is not None:
                kill_dialog(dlg)
            root.destroy()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('H03 段未抛异常', False, repr(e))
    try:
        y = os.path.join(tmp, 'H_retitle.yaml')
        with open(y, 'w', encoding='utf-8', newline='') as f:
            f.write('patch:\n')
        l1, d1 = _fake_fields('#a'), _fake_fields('#b')
        p1 = R.plan_scheme_injection(y, skin='旧名', light=l1, dark=d1,
                                     scheme_light='旧名', scheme_dark='旧名_dark')
        R.apply_scheme_injection(p1)
        p2 = R.plan_scheme_injection(y, skin='新名', light=l1, dark=d1,
                                     scheme_light='新名', scheme_dark='新名_dark',
                                     stale_schemes=['旧名', '旧名_dark'])
        R.apply_scheme_injection(p2)
        txt = open(y, encoding='utf-8').read()
        light_hdr = [l for l in txt.splitlines() if l.strip() == '# ===== 新名 =====']
        check('H04 ★改名重注入：旧标题与旧键一起清掉（不留孤儿注释）',
              '旧名' not in txt and len(light_hdr) == 1 and '新名_dark' in txt,
              f'旧名残留={txt.count("旧名")} 新名亮标题={len(light_hdr)} 条')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('H04 段未抛异常', False, repr(e))
    # H05 R4：强制 1 列时控件不丢
    try:
        saved, restore = stub_module(R)
        w = None
        real_cnt = R.ConfigWizard._adv_column_count
        try:
            R.ConfigWizard._adv_column_count = lambda self: 1
            w = make_wiz(R, cfg, saved, skins, tmp)
            inter, binds, titles = inventory(w)
            # v2.0-R10：⑪ 渲染模式单选组按需求删除 → 编号 ⑪ 不再作为「必须存在的标题」；
            # 但功能入口（⑩ 旁「增强（真羽化）」开关）必须在，且 ⑪ 字样不许再出现（两条都能抓红）。
            need = set()
            for c in '②③④⑤⑥⑦⑧⑨⑩⑫⑬⑭':
                need.add(c)
            missing = [c for c in need if not any(c in t for t in titles)]
            left_11 = [t for t in titles if '⑪' in t]
            has_alpha_chk = getattr(w, 'chk_alpha_feather', None) is not None
            check('H05 ★强制 1 列（最窄屏退路）：②~⑭ 标题齐全（⑪ 已按 R10 删除）'
                  '，⑩ 旁增强开关仍在',
                  not missing and len(list(getattr(w, 'adv_cols', []))) == 1
                  and not left_11 and has_alpha_chk,
                  f'缺={missing or "无"} 列数={len(list(getattr(w, "adv_cols", [])))} '
                  f'⑪残留={left_11 or "无"} 增强开关={has_alpha_chk}')
        finally:
            if w is not None:
                kill_wiz(w)
            R.ConfigWizard._adv_column_count = real_cnt
            restore()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('H05 段未抛异常', False, repr(e))


# ==========================================================================
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--sections', default='E,F,G,H')
    a = ap.parse_args()
    print('=' * 100)
    print('B_test_indep_batch2 —— 批次二（R4/R5/R6）独立验证（verifier 自建，不复用实现者测试）')
    print('=' * 100)
    gui, pil = _has_gui(), False
    try:
        from PIL import Image  # noqa: F401
        pil = True
    except Exception:
        pass
    print(f'环境：Python {sys.version.split()[0]} | GUI={gui} | PIL={pil} | BASE={BASE}')
    if not gui or not pil:
        print('RESULT: FAIL（GUI/PIL 不可用 → 独立验证无法成立，禁止静默跳过）')
        return 1
    tmp = tempfile.mkdtemp(prefix='indep_batch2_')
    want = {s.strip().upper() for s in a.sections.split(',') if s.strip()}
    try:
        if 'E' in want:
            section_E(tmp)
        if 'F' in want:
            section_F(tmp)
        if 'G' in want:
            section_G(tmp)
        if 'H' in want:
            section_H(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('\n' + '=' * 100)
    print(f'通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项 / 跳过 {len(SKIP)} 项')
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
