# -*- coding: utf-8 -*-
"""B_test_indep_batch3.py —— 第三轮（R7/R8/R9/R10/R11/R12/R13）**独立验证** · verifier 专属

定位（不信实现者自评）
----------------------
本脚本由 verifier 独立编写，**不复用** B_test_r7_preview / B_test_r8_prep_layout /
B_test_r9_layer_prep / B_test_r11_side / B_test_r12_collapse / B_test_r13_flip 的断言。
每条用户原话用「独立探针」复现，并且每条判据都配一条**判别力自检**（把实现打回旧行为，
判据必须 FAIL —— 证明不是恒真）：

  A 段 R7  预览纯色底：**画布上真正显示的那份 PhotoImage** 的角像素 == 画布底色，
           且合成图里不出现棋盘格深色；兼容/增强两档在纯色底上按「过渡带宽度」仍可辨。
  B 段 R10 ⑪ 渲染模式单选确已删（按变量绑定找控件，不看文案）：无绑 var_render 的
           Radiobutton、提示文案不残留「⑪」、⑩ 旁开关仍在且能写回 cfg['render_mode']。
  C 段 R11 ③ 位置（②<③<④ 的屏幕 y）+ 统一管所有图层（点一次全层 anchor 同步）。
  D 段 R12 ⚙ 高级设置折叠：窗口需求高度差、折叠后通用区 ③/预览画布仍在、连续 10 次往返稳定。
  E 段 R8  预处理对话框（自建动图夹具）逐控件「底边 ≤ 窗底」，应用/重置/取消真可点。
  F 段 R9  多图层选第 N 层 → 对话框打开的是该层图、结果写回该层、主图不动；缺图不打开。
  G 段 R13 水平翻转在通用区（⑫ 之上）+ 勾一次全层同步。
  H 段 端到端：release/config.json 的运行时读取通路（resolve_layers / plan_layer_layout）
           与向导保存写回（render_mode / side / flip_h / layers 都在，老字段零漂移）。
  I 段 冻结自检：跑前跑后 rime_char_overlay.py 的 sha256/mtime 必须一致，否则本轮不成立。

红线：只读被测代码；只写 tempfile；不写真实 config.json / skins/；不碰 %APPDATA%\\Rime；
      不动 G:\\github成果\\。

用法: python B_test_indep_batch3.py [--sections A,B,C]
"""
import copy
import hashlib
import json
import math
import os
import shutil
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

import tkinter as tk                                    # noqa: E402
import rime_char_overlay as R                            # noqa: E402

PASS, FAIL, NOTES = [], [], []
T0 = time.time()


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f'  [PASS] {name}' + (f'   ({detail})' if detail else ''))
    else:
        FAIL.append(name)
        print(f'  [FAIL] {name}' + (f'   ({detail})' if detail else ''))


def note(msg):
    NOTES.append(msg)
    print(f'  [INFO] {msg}')


def section(title):
    print(f'\n{title}')
    print('-' * max(3, len(title)))


def freeze_of(path):
    with open(path, 'rb') as f:
        raw = f.read()
    return hashlib.sha256(raw).hexdigest(), int(os.stat(path).st_mtime), len(raw)


# ==========================================================================
# 通用工具
# ==========================================================================
class Patches:
    """临时替换模块级名字（打桩写盘/弹窗/工作区），退出即还原。"""

    def __init__(self, **kw):
        self.kw = kw
        self.old = {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = getattr(R, k)
            setattr(R, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            setattr(R, k, v)
        return False


class MB:
    """messagebox 探针：只记录调用，不弹窗。"""

    def __init__(self):
        self.calls = []

    def showinfo(self, *a, **k):
        self.calls.append(('info',) + tuple(str(x) for x in a))

    def showwarning(self, *a, **k):
        self.calls.append(('warn',) + tuple(str(x) for x in a))

    def showerror(self, *a, **k):
        self.calls.append(('err',) + tuple(str(x) for x in a))

    def askyesno(self, *a, **k):
        self.calls.append(('ask',) + tuple(str(x) for x in a))
        return True

    def warns(self):
        return [c for c in self.calls if c[0] == 'warn']


def all_widgets(win):
    out = []

    def rec(w):
        for c in w.winfo_children():
            out.append(c)
            rec(c)
    rec(win)
    return out


def class_text(w):
    for attr in ('text',):
        try:
            v = w.cget(attr)
            if isinstance(v, str) and v:
                return v
        except Exception:
            pass
    return ''


def radio_of(wiz, var, key):
    """按「变量绑定 + 文案含 key」找 Radiobutton（不看实现者命名）"""
    name = str(var)
    for w in all_widgets(wiz.root):
        try:
            if w.winfo_class() == 'Radiobutton' and str(w.cget('variable')) == name \
                    and key in class_text(w):
                return w
        except Exception:
            pass
    return None


def radios_of(wiz, var):
    name = str(var)
    out = []
    for w in all_widgets(wiz.root):
        try:
            if w.winfo_class() == 'Radiobutton' and str(w.cget('variable')) == name:
                out.append(w)
        except Exception:
            pass
    return out


def y_of_prefix(wiz, ch):
    """窗口里所有以 ch 开头的可点/带字控件的最小屏幕 y（判编号行上下顺序）"""
    ys = []
    for w in all_widgets(wiz.root):
        try:
            if w.winfo_class() in ('Label', 'Button', 'Checkbutton', 'Radiobutton') \
                    and class_text(w).startswith(ch):
                ys.append(int(w.winfo_rooty()))
        except Exception:
            pass
    return min(ys) if ys else None


def px_of(tkimg, x, y):
    """从真实 PhotoImage 取像素（= 画布上显示的那一份）。"""
    try:
        v = tkimg.tk.call(str(tkimg), 'get', int(x), int(y))
    except Exception:
        return None
    if isinstance(v, str):
        v = v.split()
    if isinstance(v, (int, float)):
        return (int(v),) * 3
    try:
        t = tuple(int(c) for c in v)
    except Exception:
        return None
    return t[:3] if len(t) >= 3 else None


def parse_hex_rgb(s):
    s = str(s).strip().lstrip('#')
    try:
        if len(s) == 12:
            return tuple(int(s[i:i + 4], 16) >> 8 for i in (0, 4, 8))
        if len(s) == 6:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        pass
    return None


# ==========================================================================
# 夹具
# ==========================================================================
def make_feathered_png(path, size=(150, 150)):
    """自建夹具：不透明芯 + 8px 平滑 alpha 羽化环 + 全透明角（考两档可辨与纯色底）"""
    from PIL import Image
    im = Image.new('RGBA', size, (0, 0, 0, 0))
    px = im.load()
    cx, cy = size[0] / 2.0, size[1] / 2.0
    r_out = min(cx, cy) - 8
    r_in = r_out - 8
    for y in range(size[1]):
        for x in range(size[0]):
            d = math.hypot(x - cx, y - cy)
            if d <= r_in:
                px[x, y] = (200, 30, 40, 255)
            elif d <= r_out:
                t = (r_out - d) / max(1e-6, (r_out - r_in))
                px[x, y] = (200, 30, 40, int(round(255 * t)))
    im.save(path)
    return path


def make_static_png(path, size=(200, 260), color=(30, 120, 200, 255)):
    from PIL import Image
    Image.new('RGBA', size, color).save(path)
    return path


def make_gif(path, size=(200, 260), n=4):
    from PIL import Image
    frames = []
    for i in range(n):
        im = Image.new('RGBA', size, (0, 0, 0, 0))
        for y in range(30 + i * 6, size[1] - 30):
            for x in range(30, size[0] - 30):
                im.putpixel((x, y), (30 + i * 20, 120, 200, 255))
        frames.append(im.convert('P'))
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)
    return path


def layers_cfg(images, anchors, flips=None, **top):
    """造多图层 cfg（layers[i].image / anchor / flip）"""
    flips = flips or [False] * len(images)
    cfg = {
        'image': images[0], 'layout': 'horizontal_double', 'side': 'right',
        'layer': 'above', 'scale': 0.6, 'offset_x': -132, 'offset_y': -132,
        'base_height': 300, 'name': '独v3',
        'schema_version': R.LAYERS_SCHEMA_VERSION if hasattr(R, 'LAYERS_SCHEMA_VERSION') else 2,
        'flip_h': flips[0],
        'layers': [{'image': im, 'anchor': an, 'scale': 1.0, 'offset_x': 0,
                    'offset_y': 0, 'flip': fl} for im, an, fl in zip(images, anchors, flips)],
    }
    cfg.update(top)
    return cfg


def is_descendant(w, anc):
    """anc 是否是 w 的祖先（判「同一张卡片/容器内」）"""
    p = getattr(w, 'master', None)
    while p is not None:
        if p is anc:
            return True
        p = getattr(p, 'master', None)
    return False


def make_wiz(cfg, skins_dir, inject_cfg=True):
    """构造向导：打桩 SKINS_DIR / save_config / messagebox / set_autostart"""
    pat = Patches(SKINS_DIR=skins_dir,
                  save_config=lambda c: None,
                  set_autostart=lambda *a, **k: (True, 'stub'))
    pat.__enter__()
    try:
        wiz = R.ConfigWizard(on_done=lambda c: None, overlay=None)
    finally:
        pat.__exit__()
    if inject_cfg:
        wiz.cfg = dict(R.DEFAULT_CONFIG)
        if cfg:
            wiz.cfg.update(copy.deepcopy(cfg))   # 深拷贝：不许污染调用方的 cfg
        try:
            wiz.var_side.set(wiz.cfg.get('side', 'right'))
            wiz.var_flip.set(bool(wiz.cfg.get('flip_h', False)))
            wiz.var_render.set(R.resolve_render_mode(wiz.cfg))
            wiz._update_render_hint()      # 真实回显通路：开关状态与内部模式对齐
        except Exception:
            pass
        wiz._layer_sync_from_cfg()
    wiz.root.update_idletasks()
    wiz.root.update()
    # v2.0-R15（第四轮 N1）改写**取样前提**（HANDOFF-2.1 §6-13）：向导现在默认折叠
    # （`_adv_collapsed=True`）⇒ ⑧~⑭ 不 map，本脚本 B/C/D/G 段的坐标探针（③ 行、
    # ⑩ 旁增强开关、翻转勾选框、图层卡）全部量到 0；D 段的「折叠前后对照」也丢了
    # 展开态基准（旧前提「构造完即展开」被用户需求「默认折叠状态」推翻）。
    # 这里在取样前一次性显式展开，把取样条件恢复成与改写前逐位一致；
    # **判据表达式一条未改、强度未降**。
    # 判别力证据：注释掉下面三行（退回旧取样顺序）后 B03/C01/C02/D02/D03/G01 全部 FAIL。
    try:
        wiz._toggle_adv_collapse(False)
        wiz.root.update_idletasks()
        wiz.root.update()
    except Exception:
        pass
    return wiz


def kill_wiz(wiz):
    try:
        wiz.root.destroy()
    except Exception:
        pass


def save_via_wiz(wiz):
    """走真实保存通路（_save_and_start），打桩捕获写出的 cfg。

    注意：真实通路保存完会 destroy 向导（6952），**调用后再碰 wiz 控件必崩** —— 需要
    再保存一次时重新构造向导（保留脚本内记录，不改被测实现）。
    """
    saved = {}
    mb = MB()
    with Patches(save_config=lambda c: saved.update(c), messagebox=mb,
                 set_autostart=lambda *a, **k: (True, 'stub'),
                 _write_log=lambda *a, **k: None):
        try:
            wiz.root.wait_window = lambda *a, **k: None  # 防皮肤名询问窗阻塞
        except Exception:
            pass
        wiz._save_and_start()
    return saved, mb


# ==========================================================================
# A 段 · R7：预览纯色底 + 两档可辨
# ==========================================================================
def sec_A(tmp):
    section('A. R7 —— 向导预览纯色底（去棋盘格）+ 兼容/增强仍可辨')
    fig = make_feathered_png(os.path.join(tmp, 'fig_a.png'))
    factory = json.load(open(os.path.join(BASE, 'release', 'config.json'), encoding='utf-8'))
    factory_img = factory['image']
    wiz = make_wiz(dict(factory), tmp)
    try:
        from PIL import Image
        canvas_bg = parse_hex_rgb(wiz.canvas.cget('bg'))
        note(f'画布底色 cget(bg)={wiz.canvas.cget("bg")!r} → RGB={canvas_bg}；'
             f'模块 PREVIEW_BG_RGB={R.PREVIEW_BG_RGB}')
        check('A01 画布底色与合成口径同源（canvas bg == PREVIEW_BG_RGB）',
              canvas_bg == tuple(R.PREVIEW_BG_RGB),
              f'{canvas_bg} vs {tuple(R.PREVIEW_BG_RGB)}')

        # 独立合成：直接调预览合成函数（不含实现者测试的任何辅助）
        src = Image.open(fig).convert('RGBA')
        merged = wiz._preview_compose(src)
        w = merged.size[0]
        corners = [merged.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, merged.size[1] - 1),
                                                (w - 1, merged.size[1] - 1))]
        check('A02 合成图四个角 == 画布底色（透明区在预览里就是「融进底色」）',
              all(tuple(c[:3]) == tuple(canvas_bg) for c in corners), f'corners={corners}')
        dark = tuple(R.CHECKER_DARK)
        n_dark = sum(1 for c in merged.convert('RGB').getdata() if tuple(c) == dark)
        check('A03 合成图里不再出现棋盘格深色（像素级计数 = 0）', n_dark == 0,
              f'CHECKER_DARK={dark} 出现 {n_dark} 像素')

        # 画布上真正显示的那一份（用户眼睛看到的）
        wiz.var_render.set('compat')
        wiz._update_preview()
        wiz.root.update_idletasks()
        tkimg = wiz.tk_img
        items = [i for i in wiz.canvas.find_all() if wiz.canvas.type(i) == 'image']
        shown_names = [wiz.canvas.itemcget(i, 'image') for i in items]
        check('A04 预览画布上确有图像项，且显示的就是刚同步出来的 PhotoImage',
              bool(items) and any(str(n) == str(tkimg) for n in shown_names),
              f'canvas items={shown_names} tk_img={tkimg}')
        if tkimg is not None:
            iw = tkimg.width()
            ih = tkimg.height()
            shown_corners = [px_of(tkimg, 0, 0), px_of(tkimg, iw - 1, 0),
                             px_of(tkimg, 0, ih - 1), px_of(tkimg, iw - 1, ih - 1)]
            check('A05 显示图（画布 photo）四角 == 画布底色（用户看到的角不是棋盘格）',
                  all(c is not None and tuple(c) == tuple(canvas_bg) for c in shown_corners),
                  f'{shown_corners}')

        # 两档可辨：过渡带宽度（与底无关的形态学判据）
        def band_width(mode):
            wiz.var_render.set(mode)
            img = wiz._preview_compose(src).convert('RGB')
            W, H = img.size
            py = H // 2
            row = [img.getpixel((x, py)) for x in range(W)]
            dist = [math.dist(c, canvas_bg) for c in row]
            # 从左往右找第一段「近底 → 满色」的过渡
            i = 0
            while i < W and dist[i] < 8:
                i += 1
            peak = max(dist)
            start = i
            j = i
            while j < W and dist[j] < peak * 0.9:
                j += 1
            return j - start, peak, [round(dist[k]) for k in range(max(0, start - 3), min(W, j + 3))]

        wc, pc, prof_c = band_width('compat')
        wa, pa, prof_a = band_width('alpha')
        note(f'过渡带宽度：兼容={wc}px（峰值 {pc:.0f}）/ 增强={wa}px（峰值 {pa:.0f}）')
        note(f'兼容剖面={prof_c}')
        note(f'增强剖面={prof_a}')
        check('A06 兼容档 = 硬边（过渡带 ≤ 2px，1px 跳变）', wc <= 2, f'{wc}px')
        check('A07 增强档 = 平滑过渡（过渡带 ≥ 3px 且比兼容宽）', wa >= 3 and wa > wc,
              f'增强 {wa}px vs 兼容 {wc}px')

        # 出厂真实图做二次证据（不是自建夹具）
        if os.path.isfile(factory_img):
            real = Image.open(factory_img).convert('RGBA')
            wiz.var_render.set('compat')
            rc = wiz._preview_compose(real).convert('RGB')
            wiz.var_render.set('alpha')
            ra = wiz._preview_compose(real).convert('RGB')
            diff = sum(1 for a, b in zip(rc.getdata(), ra.getdata()) if a != b)
            dark_r = sum(1 for c in rc.getdata() if tuple(c) == dark)
            check('A08 真实出厂图：兼容/增强合成结果不同（两档在纯色底上仍可分）',
                  diff > 0, f'差异像素 {diff}')
            check('A09 真实出厂图：兼容档合成里也无棋盘格深色', dark_r == 0, f'{dark_r} 像素')
        else:
            check('A08 真实出厂图夹具存在', False, factory_img)

        # A10 判别力：把预览合成换回棋盘格 → A02/A03 的判据必须反转
        old = wiz._preview_compose
        wiz._preview_compose = lambda im: R.compose_on_checker(
            wiz._preview_render_mode_img(im), R.CHECKER_CELL, wiz._Image)
        try:
            back = wiz._preview_compose(src).convert('RGB')
            c2 = [back.getpixel(p) for p in ((0, 0), (back.size[0] - 1, 0))]
            n_dark2 = sum(1 for c in back.getdata() if tuple(c) == dark)
            check('A10 ★判别力：预览换回棋盘格后，A02/A03 判据必须失败（非恒真）',
                  (n_dark2 > 0) and any(tuple(c) != tuple(canvas_bg) for c in c2),
                  f'棋盘格下 深色={n_dark2} 角={c2}')
        finally:
            wiz._preview_compose = old
    finally:
        kill_wiz(wiz)


# ==========================================================================
# B 段 · R10：⑪ 单选确已删
# ==========================================================================
def sec_B(tmp):
    section('B. R10 —— ⑪ 渲染模式单选已删，⑩ 旁开关成唯一入口')
    fig = make_static_png(os.path.join(tmp, 'fig_b.png'))
    wiz = make_wiz(layers_cfg([fig], ['right_edge']), tmp)
    try:
        rb = radios_of(wiz, wiz.var_render)
        check('B01 不存在任何绑 var_render 的 Radiobutton（⑪ 单选确已删）', len(rb) == 0,
              f'找到 {len(rb)} 个')
        texts = [class_text(w) for w in all_widgets(wiz.root)]
        hit_11 = [t for t in texts if '⑪' in t]
        check('B02 界面文案不残留「⑪」引用（说明行也不指向已删的项）', len(hit_11) == 0
              or all('prepared' in t for t in hit_11), f'含⑪文案={hit_11}')

        chk = getattr(wiz, 'chk_alpha_feather', None)
        check('B03 ⑩ 旁「增强（真羽化）」开关仍在且可见', chk is not None and chk.winfo_ismapped(),
              f'{class_text(chk) if chk is not None else None}')

        # 唯一入口 → 写回 render_mode（保存会关窗，故每轮用新向导）
        chk.invoke()
        wiz.root.update_idletasks()
        r1 = R.resolve_render_mode({'render_mode': wiz.var_render.get()})
        saved1, _ = save_via_wiz(wiz)

        wiz1b = make_wiz(dict(saved1), tmp)
        chk1b = getattr(wiz1b, 'chk_alpha_feather', None)
        note(f'重新打开（render_mode={saved1.get("render_mode")}）时 var_render='
             f'{wiz1b.var_render.get()!r}')
        chk1b.invoke()
        wiz1b.root.update_idletasks()
        r2 = R.resolve_render_mode({'render_mode': wiz1b.var_render.get()})
        saved2, _ = save_via_wiz(wiz1b)
        note(f'开关勾上：内部状态={r1} 保存 render_mode={saved1.get("render_mode")}；'
             f'再点：内部状态={r2} 保存 render_mode={saved2.get("render_mode")}')
        check('B04 ★勾一次开关 = 唯一入口写回 render_mode=alpha', r1 == 'alpha'
              and saved1.get('render_mode') == 'alpha', f'{r1}/{saved1.get("render_mode")}')
        check('B05 ★再点一次 = 回到 compat（写回路径可逆）', r2 == 'compat'
              and saved2.get('render_mode') == 'compat', f'{r2}/{saved2.get("render_mode")}')

        # 老配置（无 render_mode）读取路径没断
        oldcfg = json.load(open(os.path.join(BASE, 'release', 'config.json'), encoding='utf-8'))
        check('B06 老配置（无 render_mode 键）→ 运行时判为 compat，不抛异常',
              'render_mode' not in oldcfg and R.resolve_render_mode(oldcfg) == 'compat',
              f'resolve={R.resolve_render_mode(oldcfg)}')

        # 判别力：把 ⑪ 单选注回去 → B01 必须失败
        wizB3 = make_wiz(dict(oldcfg), tmp)
        try:
            extra = tk.Radiobutton(wizB3.root, text='⑪ 渲染模式（注入）',
                                   variable=wizB3.var_render, value='alpha')
            extra.pack()
            wizB3.root.update_idletasks()
            rb2 = radios_of(wizB3, wizB3.var_render)
            check('B07 ★判别力：注回绑 var_render 的单选后 B01 判据必须失败（非恒真）',
                  len(rb2) >= 1, f'注入后 {len(rb2)} 个')
            extra.destroy()
        finally:
            kill_wiz(wizB3)
    finally:
        kill_wiz(wiz)


# ==========================================================================
# C 段 · R11：③ 位置 + 统一管所有图层
# ==========================================================================
def sec_C(tmp):
    section('C. N3（推翻 R11）—— ③ 只出现一处（②④ 之间）、但**按当前选中层**分别调')
    imgs = [make_static_png(os.path.join(tmp, f'fig_c{i}.png'), size=(120 + i * 10, 160),
                            color=(30 + i * 60, 120, 200, 255)) for i in range(3)]
    cfg = layers_cfg(imgs, ['left_edge', 'center', 'right_edge'], flips=[False, True, False])
    wiz = make_wiz(cfg, tmp)
    try:
        y2, y3, y4 = y_of_prefix(wiz, '②'), y_of_prefix(wiz, '③'), y_of_prefix(wiz, '④')
        note(f'编号行屏幕 y：②={y2} ③={y3} ④={y4}')
        check('C01 ★③ 在 ② 与 ④ 之间（②<③<④）',
              None not in (y2, y3, y4) and y2 < y3 < y4, f'{y2} < {y3} < {y4}')

        side_rb = radios_of(wiz, wiz.var_side)
        tops = [int(w.winfo_rooty()) for w in side_rb]
        lay_y = int(wiz.layer_list.winfo_rooty())
        same_row = bool(tops) and abs(min(tops) - y3) <= 6
        in_lay_card = bool(side_rb) and is_descendant(wiz.layer_list, side_rb[0].master)
        note(f'绑 var_side 的单选 {len(side_rb)} 个，屏幕 y={tops}（③ 行={y3}）；'
             f'图层列表 y={lay_y}，③ 与图层列表同卡片={in_lay_card}')
        check('C02 ★③ 的 3 个单选与 ③ 编号同一行、且不在图层卡内（不在 ⑫ 里）',
              len(side_rb) == 3 and same_row and not in_lay_card and lay_y > min(tops),
              f'单选={tops} ③行={y3} 同卡片={in_lay_card} 图层列表 y={lay_y}')

        # ---- N3（用户第四轮，推翻 R11）：点一次 ③ = **只写当前选中层**，其余层一个都不许动。----
        # 取样走用户真实通路（点通用区 ③ 的单选并 invoke），**不用 var.set + 预览** —— 后者靠的是
        # 「实现读 Tk 变量推全层」这条 N3 已明令禁止的行为（见 t11 契约第 3 条(iii)：那是假绿）。
        # 判据抽成闭包 c03_ok()：C03/C06/C06b 与就地负控 C09 共用**同一条表达式**，保证判别力段
        # 红的确实是这条判据本身（不是另写一条）。
        def snap_anchor():
            return [d.get('anchor') for d in wiz.cfg['layers']]

        def c03_ok(before, sel, want, expect_side):
            """N3 判据：点击后**只有第 sel 层**变成 want，其余层逐层 == 点击前的快照；
            sel==0（主层）时顶层 cfg['side'] 同步为 expect_side。
            回退成 R11/R13「一处统一管所有图层」后其余层会被一起改 → 本式必假（判别力见 C09）。"""
            exp = list(before)
            exp[sel] = want
            return snap_anchor() == exp and wiz.cfg.get('side') == expect_side

        _SIDE_WORD = {'left_edge': '贴左', 'right_edge': '贴右', 'center': '居中'}

        def rows_match_layers():
            """图层列表**逐行**一致性：每行文案里的方向词 == 该层 cfg 里的持久值。
            不比对字面文案措辞（措辞随需求变），只要求「界面说的」==「存档里的」——
            回退成「统一全层」而列表只刷当前行时，其余行的持久值已被改、文案却陈旧 → 必假。"""
            rws = [wiz.layer_list.get(i) for i in range(wiz.layer_list.size())]
            lyr = wiz.cfg['layers']
            if len(rws) != len(lyr):
                return False, rws
            ok = all(_SIDE_WORD.get(d.get('anchor'), '∅') in r for d, r in zip(lyr, rws))
            return ok, rws

        before = snap_anchor()
        note(f'fixture 各层 anchor={before}（选中层默认=第 1 层，主层）')
        radio_of(wiz, wiz.var_side, '中').invoke()
        wiz.root.update_idletasks()
        anchors = snap_anchor()
        rows = [wiz.layer_list.get(i) for i in range(wiz.layer_list.size())]
        _rows_ok, _rows_now = rows_match_layers()
        note(f'选中第 1 层点「中」后：side={wiz.cfg.get("side")} anchors={anchors} 行={rows}')
        check('C03 ★点一次 ③ = **只改当前选中层**（主层）：[center, center, right_edge] —— '
              '第 3 层保持 right_edge 不被统一',
              c03_ok(before, 0, 'center', 'center'), f'side={wiz.cfg.get("side")} anchors={anchors}')
        check('C04 ★图层列表**逐行**反映各层自己的持久值（第 1 行「居中」跟着刚改的主层走、'
              '第 3 行仍「贴右」；界面话 == 存档值，不是 3 行一律刷成同一个词）',
              _rows_ok and '居中' in _rows_now[0] and '贴右' in _rows_now[2],
              f'逐行一致={"是" if _rows_ok else "否"} 行={_rows_now}')
        check('C05 图层区回显镜像 == 当前选中层 anchor',
              str(wiz.var_layer_anchor.get()) == str(wiz.cfg['layers'][wiz._cur_layer_index()].get('anchor')),
              f'{wiz.var_layer_anchor.get()!r}')

        # 再点另一个方向「右」：仍只改当前选中层（不是一次性巧合）
        before = snap_anchor()
        radio_of(wiz, wiz.var_side, '右').invoke()
        wiz.root.update_idletasks()
        anchors2 = snap_anchor()
        note(f'再点「右」后：side={wiz.cfg.get("side")} anchors={anchors2}')
        check('C06 ★再点「右」仍只改当前选中层（不是一次性巧合）：[right_edge, center, right_edge]',
              c03_ok(before, 0, 'right_edge', 'right'),
              f'side={wiz.cfg.get("side")} anchors={anchors2}')

        # 选中**非主层**（第 3 层）点 ③：只改该层；顶层 side 与主层/第 2 层纹丝不动
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(2)
        wiz._on_layer_select()
        wiz.root.update_idletasks()
        before = snap_anchor()
        radio_of(wiz, wiz.var_side, '左').invoke()
        wiz.root.update_idletasks()
        anchors3 = snap_anchor()
        note(f'选中第 3 层点「左」后：side={wiz.cfg.get("side")} anchors={anchors3}')
        check('C06b ★选中第 3 层点「左」= 只改第 3 层；顶层 side 与主层/第 2 层纹丝不动'
              '（[right_edge, center, left_edge]）',
              c03_ok(before, 2, 'left_edge', 'right'),
              f'side={wiz.cfg.get("side")} anchors={anchors3}')
        # C06b 之后切回主层，保持 C07/C08/C09 的取样起点与改写前一致
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(0)
        wiz._on_layer_select()
        wiz.root.update_idletasks()

        # 老 v1.6 单层档案：无 layers 键
        wiz2 = make_wiz(dict([('image', imgs[0]), ('side', 'left'), ('scale', 0.6)]), tmp)
        try:
            radio_of(wiz2, wiz2.var_side, '右').invoke()
            wiz2.root.update_idletasks()
            check('C07 老单层配置（无 layers）点 ③ 不崩且归一为 1 层 anchor=right_edge',
                  [d.get('anchor') for d in wiz2.cfg['layers']] == ['right_edge'],
                  f"{[d.get('anchor') for d in wiz2.cfg['layers']]}")
        finally:
            kill_wiz(wiz2)

        # 反例：各层 anchor 不一致的老档案 → 只打开/预览不许静默改写其它层
        wiz3 = make_wiz(cfg, tmp)
        try:
            a_after_open = [d.get('anchor') for d in wiz3.cfg['layers']]
            wiz3._update_preview()
            wiz3.root.update_idletasks()
            a_after_prev = [d.get('anchor') for d in wiz3.cfg['layers']]
            note(f'打开向导后 anchors={a_after_open}；预览后={a_after_prev}（档案原值 '
                 f'left/center/right）')
            check('C08 ★反例：各层 anchor 不一致的老档案，只打开/预览不静默改写其它层',
                  a_after_prev[1] == 'center' and a_after_prev[2] == 'right_edge',
                  f'{a_after_prev}')
        finally:
            kill_wiz(wiz3)

        # C09 判别力（v2.0-N3 **重建**）：原注入点（打桩 _sync_side_to_all_layers）在 N3 后
        # **已不经过被测路径** —— _on_side_change 现在直接调 _layer_set_params，打桩那个入口
        # 对判据零影响 ⇒ 旧 C09 会「仍然绿但已不是判别力证据」（t11 契约第 3 条①最想防的形态）。
        # 改成把 _layer_set_params 打桩回**旧前提**「一处统一管所有图层」（R11/R13 语义），
        # 再用上面 C03/C06 **同一条判据表达式** c03_ok() 复核 —— 必须 FAIL。
        real_set = wiz._layer_set_params

        def _old_unified_set(i, scale=None, offset_x=None, offset_y=None, flip=None, anchor=None):
            r = real_set(i, scale=scale, offset_x=offset_x, offset_y=offset_y,
                         flip=flip, anchor=anchor)
            if anchor is not None:              # 旧语义：一处统一管所有图层
                for d in wiz.cfg['layers']:
                    d['anchor'] = wiz._layer_anchor_at(0)
            return r

        before = snap_anchor()
        wiz._layer_set_params = _old_unified_set
        try:
            radio_of(wiz, wiz.var_side, '中').invoke()
            wiz.root.update_idletasks()
        finally:
            wiz._layer_set_params = real_set
        a_bad = snap_anchor()
        check('C09 ★判别力：把「只写当前层」打桩回旧前提「一处统一管所有图层」（R11/R13 语义）'
              '→ C03/C06 同一条判据 c03_ok() 必须 FAIL',
              not c03_ok(before, 0, 'center', 'center'),
              f'回退前={before} 注入后={a_bad}')
    finally:
        kill_wiz(wiz)


# ==========================================================================
# D 段 · R12：⚙ 高级设置可折叠
# ==========================================================================
def sec_D(tmp):
    section('D. R12 —— ⚙ 高级设置可折叠（窗口需求高度实降）')
    fig = make_static_png(os.path.join(tmp, 'fig_d.png'))
    wiz = make_wiz(layers_cfg([fig], ['right_edge']), tmp)
    try:
        wiz.root.update_idletasks()
        h_open = int(wiz.root.winfo_reqheight())
        body_open = int(wiz.adv_body.winfo_reqheight())
        btn = wiz.btn_adv_toggle
        check('D01 折叠按钮存在且可见（标题本身就是开关）',
              btn is not None and btn.winfo_ismapped(), f'{class_text(btn)!r}')

        btn.invoke()
        wiz.root.update_idletasks()
        h_closed = int(wiz.root.winfo_reqheight())
        body_closed = int(wiz.adv_body.winfo_reqheight())
        mapped_closed = int(wiz.adv_body.winfo_ismapped())
        note(f'展开 reqheight={h_open}（adv_body={body_open}）→ 折叠 {h_closed}'
             f'（adv_body={body_closed}，ismapped={mapped_closed}）差 {h_open - h_closed}px')
        check('D02 ★折叠后窗口需求高度实降 ≥ 200px', h_open - h_closed >= 200,
              f'−{h_open - h_closed}px')
        check('D03 折叠 = 内容区不再参与布局（adv_body 未映射）', mapped_closed == 0,
              f'ismapped={mapped_closed}')

        # 折叠后通用区 ③ / 预览画布仍可用
        side_rb = radios_of(wiz, wiz.var_side)
        ok_side = bool(side_rb) and all(w.winfo_ismapped() for w in side_rb)
        check('D04 ★折叠只收 ⑧~⑭：通用区 ③ 仍可见可点、预览画布仍在',
              ok_side and wiz.canvas.winfo_ismapped(), f'③={len(side_rb)} canvas={wiz.canvas.winfo_ismapped()}')
        radio_of(wiz, wiz.var_side, '左').invoke()
        wiz.root.update_idletasks()
        check('D05 折叠态点 ③ 仍生效（cfg[side] 变为 left）',
              wiz.cfg.get('side') == 'left', f"{wiz.cfg.get('side')}")

        btn.invoke()
        wiz.root.update_idletasks()
        h_reopen = int(wiz.root.winfo_reqheight())
        check('D06 ★再展开：高度回到初值（±2px，无鬼影）', abs(h_reopen - h_open) <= 2,
              f'{h_open} → {h_reopen}')

        # 反例：连续 10 次折叠/展开
        heights = []
        for _ in range(10):
            btn.invoke()
            wiz.root.update_idletasks()
            heights.append(int(wiz.root.winfo_reqheight()))
        final = heights[-1]
        check('D07 ★反例：连续折叠/展开 10 次高度稳定（末态与初值 ±2px，无漂移）',
              abs(final - h_open) <= 2, f'末态={final} 初值={h_open} 序列={heights[:4]}…')

        # 反例：折叠态下重算窗口尺寸（分辨率/工作区变化）
        btn.invoke()      # 折起来
        wiz.root.update_idletasks()
        h_c = int(wiz.root.winfo_reqheight())
        old_scr = R.screen_work_area_height
        try:
            R.screen_work_area_height = lambda root=None: 600
            wiz._fit_window_height()
            wiz.root.update_idletasks()
            hh = int(wiz.root.winfo_height())
            ww = int(wiz.root.winfo_width())
            check('D08 ★反例：折叠态 + 小工作区（打桩 600）重算窗口不崩、窗口不高于工作区',
                  hh <= 604 and ww > 0, f'窗={ww}x{hh}')
        finally:
            R.screen_work_area_height = old_scr
        btn.invoke()
        wiz.root.update_idletasks()

        # D09 判别力：折叠执行点打成 no-op → D02 判据必须失败
        real_apply = wiz._apply_adv_collapsed
        wiz._apply_adv_collapsed = lambda: None
        try:
            before = int(wiz.root.winfo_reqheight())
            wiz._toggle_adv_collapse(True)
            wiz.root.update_idletasks()
            after = int(wiz.root.winfo_reqheight())
            check('D09 ★判别力：折叠执行点失效时 D02 判据必须失败（非恒真）',
                  before - after < 50, f'{before} → {after}')
        finally:
            wiz._apply_adv_collapsed = real_apply
            wiz._toggle_adv_collapse(False)
    finally:
        kill_wiz(wiz)


# ==========================================================================
# E 段 · R8：预处理对话框不挤占下方功能
# ==========================================================================
def sec_E(tmp):
    section('E. R8 —— 预处理对话框（动图）下方控件不被挤占')
    gif = make_gif(os.path.join(tmp, 'fig_e.gif'))
    png = make_static_png(os.path.join(tmp, 'fig_e.png'), size=(200, 260))
    host = tk.Tk()
    host.geometry('1x1+0+0')      # 可见的宿主窗（withdraw 会让子对话框不 map，量不到真几何）
    host.update()

    def probe(path, tag):
        dlg = R.ImagePreprocessDialog(host, path, layer_hint='第 1 层（主图）')
        dl = time.time() + 3.0
        while time.time() < dl:
            dlg.root.update_idletasks()
            dlg.root.update()
            if int(dlg.root.winfo_height()) > 1 and int(dlg.root.winfo_ismapped()):
                break
            time.sleep(0.03)
        dlg.root.update_idletasks()
        dlg.root.update()
        win_top = int(dlg.root.winfo_rooty())
        win_h = int(dlg.root.winfo_height())
        win_bottom = win_top + win_h
        ws = all_widgets(dlg.root)
        mapped = [w for w in ws if w.winfo_ismapped()]
        over = []
        for w in mapped:
            try:
                b = int(w.winfo_rooty()) + int(w.winfo_height())
                if b > win_bottom + 1:
                    over.append((w.winfo_class(), class_text(w)[:18], int(w.winfo_rooty()),
                                 int(w.winfo_height()), b - win_bottom))
            except Exception:
                pass
        btns = {}
        for w in ws:
            t = class_text(w)
            if w.winfo_class() == 'Button' and t in ('应用', '重置', '取消'):
                btns[t] = (int(w.winfo_ismapped()), int(w.winfo_height()),
                           int(w.winfo_rooty()) + int(w.winfo_height()))
        note(f'{tag}: 窗高={win_h} 控件 {len(ws)} 个（mapped {len(mapped)}），'
             f'越界={len(over)}，按钮={btns}')
        if over:
            note(f'{tag} 越界明细={over[:6]}')
        return win_h, mapped, over, btns, dlg

    dlg = None
    try:
        win_h_gif, mapped_g, over_g, btns_g, dlg = probe(gif, '动图 200x260×4')
        check('E01 ★动图模式下没有任何已映射控件越出窗底（底边 ≤ 窗高）',
              len(over_g) == 0, f'越界 {len(over_g)} 个')
        ok_btns = all(v[0] == 1 and v[1] > 5 for v in btns_g.values()) and len(btns_g) == 3
        check('E02 ★应用/重置/取消三个按钮都可见且高度正常（>5px，可点击）', ok_btns,
              f'{btns_g}')
        cvh = 0
        for attr in ('cv', 'canvas', 'preview'):
            c = getattr(dlg, attr, None)
            if c is not None:
                try:
                    cvh = max(cvh, int(c.winfo_height()))
                except Exception:
                    pass
        check('E03 动图窗口高 ≥ 左画布高（预览没有被压扁）', win_h_gif >= cvh and cvh > 100,
              f'窗 {win_h_gif} ≥ 画布 {cvh}（右栏内容需求 {int(dlg.panel.winfo_reqheight())}）')
        # 滚动容器存在（内容超窗时的保底通道）
        has_scroll = all(hasattr(dlg, a) for a in ('panel_canvas', 'panel_sb'))
        check('E04 右栏有滚动容器（内容高于窗时仍可达）', has_scroll,
              f'panel_canvas={getattr(dlg, "panel_canvas", None) is not None}')
    finally:
        if dlg is not None:
            try:
                dlg.root.destroy()
            except Exception:
                pass

    # 静态图
    dlg2 = None
    try:
        win_h_png, mapped_p, over_p, btns_p, dlg2 = probe(png, '静态 200x260')
        check('E05 静态图窗口同样无控件越界', len(over_p) == 0, f'越界 {len(over_p)}')
    finally:
        if dlg2 is not None:
            try:
                dlg2.root.destroy()
            except Exception:
                pass

    # 反例：小工作区（打桩 600）→ 仍不越界
    dlg3 = None
    old_scr = R.screen_work_area_height
    try:
        R.screen_work_area_height = lambda root=None: 600
        dlg3 = R.ImagePreprocessDialog(host, gif, layer_hint='第 2 层')
        dl3 = time.time() + 3.0
        while time.time() < dl3:
            dlg3.root.update_idletasks()
            dlg3.root.update()
            if int(dlg3.root.winfo_height()) > 1 and int(dlg3.root.winfo_ismapped()):
                break
            time.sleep(0.03)
        wb = int(dlg3.root.winfo_rooty()) + int(dlg3.root.winfo_height())

        def overs(win):
            """越出窗底的已映射控件（**排除右栏滚动容器内**的 —— 它们靠滚动可达）"""
            out = []
            for w in all_widgets(win):
                try:
                    if not w.winfo_ismapped():
                        continue
                    if w is not dlg3.panel_canvas and is_descendant(w, dlg3.panel_canvas):
                        continue
                    b = int(w.winfo_rooty()) + int(w.winfo_height())
                    if b > wb + 1:
                        out.append((w.winfo_class(), class_text(w)[:18], b - wb))
                except Exception:
                    pass
            return out

        over3 = overs(dlg3.root)
        sb_mapped = int(dlg3.panel_sb.winfo_ismapped())
        btns3 = {}
        for w in all_widgets(dlg3.root):
            t = class_text(w)
            if w.winfo_class() == 'Button' and t in ('应用', '重置', '取消'):
                btns3[t] = (int(w.winfo_ismapped()), int(w.winfo_height()))
        win_h3 = int(dlg3.root.winfo_height())
        note(f'小工作区打桩 600：窗高={win_h3} 滚动条 mapped={sb_mapped} '
             f'容器外越界={len(over3)} 按钮={btns3}')
        check('E06 ★反例：小屏（工作区 600）窗口不越工作区、滚动条出现、容器外控件不越窗底',
              win_h3 <= 604 and sb_mapped == 1 and len(over3) == 0,
              f'窗高={win_h3} 滚动条={sb_mapped} 越界={over3[:4]}')
        check('E07 ★反例：小屏下应用/重置/取消仍在窗内可见可点（用户第 4 条原话）',
              len(btns3) == 3 and all(v[0] == 1 and v[1] > 5 for v in btns3.values()),
              f'{btns3}')
        dlg3.panel_canvas.yview_moveto(1.0)
        for _ in range(3):
            dlg3.root.update_idletasks()
            dlg3.root.update()
        over_after = overs(dlg3.root)
        ra = None
        for w in all_widgets(dlg3.root):
            if class_text(w) == '重新自动检测':
                ra = (int(w.winfo_ismapped()), int(w.winfo_rooty()) + int(w.winfo_height()))
        check('E08 ★反例续：滚到底后原先越出的控件全部进窗（滚动通道真的可达）',
              len(over_after) == 0 and ra is not None and ra[1] <= wb + 1,
              f'滚到底越界={len(over_after)} 重新自动检测={ra} 窗底={wb}')
    finally:
        R.screen_work_area_height = old_scr
        if dlg3 is not None:
            try:
                dlg3.root.destroy()
            except Exception:
                pass
        try:
            host.destroy()
        except Exception:
            pass


# ==========================================================================
# F 段 · R9：多图层时选中的图层可预处理
# ==========================================================================
class FakeDlg:
    instances = []
    next_result = None

    def __init__(self, master, image_path, layer_hint=None):
        self.master = master
        self.image_path = image_path
        self.layer_hint = layer_hint
        self.result_path = FakeDlg.next_result
        self.root = tk.Toplevel(master)
        self.root.withdraw()
        FakeDlg.instances.append(self)


def sec_F(tmp):
    section('F. R9 —— 多图层：选中第 N 层 → 对话框打开该层的图、结果写回该层')
    a = make_static_png(os.path.join(tmp, 'fig_f0.png'), size=(150, 200), color=(200, 60, 60, 255))
    b = make_static_png(os.path.join(tmp, 'fig_f1.png'), size=(160, 210), color=(60, 160, 60, 255))
    c = make_static_png(os.path.join(tmp, 'fig_f2.png'), size=(170, 220), color=(60, 60, 200, 255))
    res = make_static_png(os.path.join(tmp, 'fig_f_res.png'), size=(120, 160),
                          color=(240, 240, 40, 255))
    cfg = layers_cfg([a, b, c], ['right_edge', 'right_edge', 'right_edge'])
    wiz = make_wiz(cfg, tmp)
    mb = MB()
    try:
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(1)
        wiz._on_layer_select()
        wiz.root.update_idletasks()
        FakeDlg.instances = []
        FakeDlg.next_result = res
        with Patches(ImagePreprocessDialog=FakeDlg, messagebox=mb):
            wiz.root.wait_window = lambda *x, **k: None
            wiz._preprocess_image()
        wiz.root.update_idletasks()
        got = FakeDlg.instances[-1] if FakeDlg.instances else None
        check('F01 ★选中第 2 层 → 对话框收到的是第 2 层的图（不是主图）',
              got is not None and os.path.abspath(got.image_path) == os.path.abspath(b),
              f'收到={getattr(got, "image_path", None)} 期望={b}')
        check('F02 对话框标题带层号（第 2 层）',
              got is not None and str(got.layer_hint or '').startswith('第 2 层'),
              f'{getattr(got, "layer_hint", None)!r}')
        check('F03 ★结果写回第 2 层（layers[1].image 变为处理结果）',
              os.path.abspath(str(wiz.cfg['layers'][1].get('image'))) == os.path.abspath(res),
              f"{wiz.cfg['layers'][1].get('image')}")
        check('F04 ★主图与其它层未被改动（cfg[image] / 层 1 / 层 3 原值）',
              os.path.abspath(str(wiz.cfg.get('image'))) == os.path.abspath(a)
              and os.path.abspath(str(wiz.cfg['layers'][0].get('image'))) == os.path.abspath(a)
              and os.path.abspath(str(wiz.cfg['layers'][2].get('image'))) == os.path.abspath(c),
              f"主图={wiz.cfg.get('image')}")
        row = wiz.layer_list.get(1)
        check('F05 图层列表第 2 行文案跟着换成新文件名（不写旧名）',
              os.path.basename(res) in str(row), f'{row!r}')

        # 第 0 层走原行为
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(0)
        wiz._on_layer_select()
        wiz.root.update_idletasks()
        FakeDlg.instances = []
        with Patches(ImagePreprocessDialog=FakeDlg, messagebox=mb):
            wiz.root.wait_window = lambda *x, **k: None
            wiz._preprocess_image()
        wiz.root.update_idletasks()
        got0 = FakeDlg.instances[-1] if FakeDlg.instances else None
        check('F06 ★选第 1 层（主图）→ 对话框收到主图，结果落到 cfg[image]（原行为不变）',
              got0 is not None and os.path.abspath(got0.image_path) == os.path.abspath(a)
              and os.path.abspath(str(wiz.cfg.get('image'))) == os.path.abspath(res),
              f'收到={getattr(got0, "image_path", None)} 主图→{wiz.cfg.get("image")}')

        # 反例：缺图图层 → 明确提示且不打开对话框
        wiz.cfg['layers'][1]['image'] = ''
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(1)
        wiz._on_layer_select()
        wiz.root.update_idletasks()
        FakeDlg.instances = []
        mb.calls = []
        with Patches(ImagePreprocessDialog=FakeDlg, messagebox=mb):
            wiz.root.wait_window = lambda *x, **k: None
            wiz._preprocess_image()
        warns = mb.warns()
        check('F07 ★反例：该层没图 → 弹明确提示且**不打开**对话框（不拿别的图顶上）',
              len(FakeDlg.instances) == 0 and len(warns) == 1
              and ('2' in ' '.join(warns[0])), f'对话框={len(FakeDlg.instances)} 提示={warns}')

        # 反例：文件被移走
        gone = os.path.join(tmp, 'fig_f_gone.png')
        make_static_png(gone)
        wiz.cfg['layers'][1]['image'] = gone
        os.remove(gone)
        FakeDlg.instances = []
        mb.calls = []
        with Patches(ImagePreprocessDialog=FakeDlg, messagebox=mb):
            wiz.root.wait_window = lambda *x, **k: None
            wiz._preprocess_image()
        warns = mb.warns()
        check('F08 ★反例：该层图文件已不在 → 提示带上层号与路径，不打开对话框',
              len(FakeDlg.instances) == 0 and len(warns) == 1 and 'gone' in ' '.join(warns[0]),
              f'{warns}')

        # 反例：多图层 + 动图（第 2 层是 GIF）→ 对话框真开、控件仍不越界
        gif = make_gif(os.path.join(tmp, 'fig_f1.gif'), size=(180, 240), n=3)
        wiz.cfg['layers'][1]['image'] = gif
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(1)
        wiz._on_layer_select()
        wiz.root.update_idletasks()
        real_dlg = None
        try:
            d = R.ImagePreprocessDialog(wiz.root, gif, layer_hint='第 2 层')
            real_dlg = d
            d.root.update_idletasks()
            d.root.update()
            wb = int(d.root.winfo_rooty()) + int(d.root.winfo_height())
            over = [w for w in all_widgets(d.root) if w.winfo_ismapped()
                    and int(w.winfo_rooty()) + int(w.winfo_height()) > wb + 1]
            check('F09 ★反例：多图层选中的层是动图 → 对话框正常打开且无控件越界',
                  len(over) == 0, f'越界={len(over)}')
        finally:
            if real_dlg is not None:
                try:
                    real_dlg.root.destroy()
                except Exception:
                    pass

        # F10 判别力：让取层索引恒为 0 → F01/F03 判据必须失败
        wiz.cfg['layers'][1]['image'] = b
        real_idx = wiz._cur_layer_index
        wiz._cur_layer_index = lambda: 0
        FakeDlg.instances = []
        FakeDlg.next_result = res
        try:
            with Patches(ImagePreprocessDialog=FakeDlg, messagebox=mb):
                wiz.root.wait_window = lambda *x, **k: None
                wiz._preprocess_image()
            got2 = FakeDlg.instances[-1] if FakeDlg.instances else None
            same_as_layer1 = got2 is not None and os.path.abspath(got2.image_path) == os.path.abspath(b)
            check('F10 ★判别力：取层索引恒 0（改前写死主图的行为）时 F01 判据必须失败',
                  not same_as_layer1, f'收到={getattr(got2, "image_path", None)}')
        finally:
            wiz._cur_layer_index = real_idx
    finally:
        kill_wiz(wiz)


# ==========================================================================
# G 段 · R13：水平翻转在通用区 + 统一管所有图层
# ==========================================================================
def sec_G(tmp):
    section('G. N3（推翻 R13）—— 水平翻转在通用区一处、但**按当前选中层**分别调')
    imgs = [make_static_png(os.path.join(tmp, f'fig_g{i}.png'), size=(120, 160),
                            color=(40, 90 + i * 40, 200, 255)) for i in range(3)]
    # fixture 的 flip 初始值刻意**不是全 False**（t11 契约第 3 条②）：全 False 时「勾一次再取消」
    # 之后仍全 False，判据区分不出「只改当前层」与「全层同步」= 判别力被掏空。这里把第 3 层
    # 预置 True，它就成「未被选中的层不许被改写」的活体对照。
    cfg = layers_cfg(imgs, ['right_edge'] * 3, flips=[False, False, True])
    wiz = make_wiz(cfg, tmp)
    try:
        chk = getattr(wiz, 'chk_flip', None)
        y_flip = int(chk.winfo_rooty()) if chk is not None else None
        y3 = y_of_prefix(wiz, '③')
        lay_y = int(wiz.layer_list.winfo_rooty())
        in_lay_card = chk is not None and is_descendant(wiz.layer_list, chk.master)
        note(f'chk_flip y={y_flip}（③ 行 y={y3}；图层列表 y={lay_y}，'
             f'与图层列表同卡片={in_lay_card}）')
        check('G01 ★翻转勾选框在通用区（与 ③ 同一行、在图层列表之上、不在图层卡内）',
              chk is not None and y3 is not None and abs(y_flip - y3) <= 8
              and y_flip < lay_y and not in_lay_card,
              f'flip={y_flip} ③={y3} 图层列表={lay_y} 同卡片={in_lay_card}')
        # G02 改写（t11 契约第 4 条：按**控件层级 / 变量绑定**定位，不绑文案措辞）：
        # 旧判据 `'图层' in text` 固化的是 R13「所有图层统一」的文案，已被 N3 推翻；
        # 新判据 = 控件按变量绑定唯一存在（形态仍是勾选框、仍只有一处）+ 文案**随选中层更新**
        # （第 1 层 ↔ 第 3 层）—— 换措辞不会红，少一处/多了第二处/不随层更新都会红。
        flip_ws = [w for w in all_widgets(wiz.root)
                   if w.winfo_class() == 'Checkbutton'
                   and str(w.cget('variable')) == str(wiz.var_flip)]
        t1_text = class_text(flip_ws[0]) if flip_ws else ''
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(2)
        wiz._on_layer_select()
        wiz.root.update_idletasks()
        t3_text = class_text(flip_ws[0]) if flip_ws else ''
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(0)
        wiz._on_layer_select()
        wiz.root.update_idletasks()
        note(f'绑 var_flip 的 Checkbutton {len(flip_ws)} 个；文案：主层={t1_text!r} 第 3 层={t3_text!r}')
        check('G02 ★翻转控件按**变量绑定**定位（恰 1 个绑 var_flip 的 Checkbutton）、'
              '文案随选中层更新（主层写「第 1 层」/ 第 3 层写「第 3 层」）',
              len(flip_ws) == 1 and '第 1 层' in t1_text and '第 3 层' in t3_text
              and '第 1 层' in class_text(flip_ws[0]),
              f'控件数={len(flip_ws)} 主层文案={t1_text!r} 第3层文案={t3_text!r}')
        # G02b 判别力（§6-13）：把「控件文案随层更新」的入口打桩成 no-op → 切到第 3 层后文案
        # 仍停留在「第 1 层」→ G02 的「文案随选中层更新」判据必须 FAIL（测完还原）。
        _real_titles = wiz._sync_side_widget_titles
        wiz._sync_side_widget_titles = lambda *a, **k: None
        try:
            wiz.layer_list.selection_clear(0, 'end')
            wiz.layer_list.selection_set(2)
            wiz._on_layer_select()
            wiz.root.update_idletasks()
            _t3_frozen = class_text(flip_ws[0]) if flip_ws else ''
        finally:
            wiz._sync_side_widget_titles = _real_titles
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(0)
        wiz._on_layer_select()
        wiz.root.update_idletasks()
        check('G02b ★判别力：把文案随层更新的入口打桩成 no-op → 「文案随选中层更新」判据必须 FAIL（非恒真）',
              '第 3 层' not in _t3_frozen, f'注入后第 3 层文案={_t3_frozen!r}')

        def snap_flip():
            return [bool(d.get('flip')) for d in wiz.cfg['layers']]

        def g03_ok(before, sel, want, expect_top):
            """N3 判据（G03/G05 与就地负控 G07 共用**同一条**表达式）：勾 / 取消之后
            **只有第 sel 层**变成 want，其余层逐层 == 操作前的快照；sel==0（主层）时顶层
            cfg['flip_h'] 同步。回退成 R13「一处统一管所有图层」后其余层会被一起改 → 本式必假。"""
            exp = list(before)
            exp[sel] = want
            return snap_flip() == exp and bool(wiz.cfg.get('flip_h')) is bool(expect_top)

        before = snap_flip()
        note(f'勾选前各层 flip={before}（选中层=主层；第 3 层的 True 是活体对照）')
        n = {'c': 0}
        real_prev = wiz._update_preview
        wiz._update_preview = lambda *a, **k: (n.__setitem__('c', n['c'] + 1), real_prev(*a, **k))[1]
        try:
            chk.invoke()
            wiz.root.update_idletasks()
        finally:
            wiz._update_preview = real_prev
        flips = snap_flip()
        note(f'勾一次后：顶层 flip_h={wiz.cfg.get("flip_h")} 各层={flips} 预览重绘={n["c"]}')
        check('G03 ★勾一次 = **只改当前选中层**（主层）：[True, False, True] —— '
              '第 2 层保持 False、第 3 层保持 True，都不许被统一',
              g03_ok(before, 0, True, True), f'flip_h={wiz.cfg.get("flip_h")} 各层={flips}')
        check('G04 ★勾一次立刻重绘预览（用户能马上看到）', n['c'] >= 1, f'重绘 {n["c"]} 次')

        before = snap_flip()
        chk.invoke()
        wiz.root.update_idletasks()
        flips2 = snap_flip()
        note(f'再取消后：顶层 flip_h={wiz.cfg.get("flip_h")} 各层={flips2}')
        check('G05 ★取消勾选 = **只把当前选中层**（主层）回到 False：第 3 层的 True 必须保住 '
              '（旧 fixture 全 False 时区分不出这一点，故本段 fixture 预置第 3 层 True）',
              g03_ok(before, 0, False, False), f'flip_h={wiz.cfg.get("flip_h")} 各层={flips2}')

        # 反例：各层 flip 不一致的老档案 → 只打开不许静默改写其它层
        cfg2 = layers_cfg(imgs, ['right_edge'] * 3, flips=[False, True, False])
        wiz2 = make_wiz(cfg2, tmp)
        try:
            f_open = [d.get('flip') for d in wiz2.cfg['layers']]
            wiz2._update_preview()
            wiz2.root.update_idletasks()
            f_prev = [d.get('flip') for d in wiz2.cfg['layers']]
            note(f'各层 flip 不一致档案：打开={f_open} 预览后={f_prev}')
            check('G06 ★反例：各层 flip 不一致的老档案，打开/预览不静默改写其它层',
                  f_prev[1] is True and f_prev[2] is False, f'{f_prev}')
        finally:
            kill_wiz(wiz2)

        # G07 判别力（v2.0-N3 **重建**）：原注入点（打桩 _sync_flip_to_all_layers）在 N3 后
        # 已不经过被测路径（_on_flip_change 直接调 _layer_set_params）⇒ 旧 G07 会「仍然绿但
        # 已不是判别力证据」。改成把 _layer_set_params 打桩回旧前提「一处统一管所有图层」
        # （翻转推全层），再用上面 G03/G05 **同一条**判据表达式 g03_ok() 复核 —— 必须 FAIL。
        real_set = wiz._layer_set_params

        def _old_unified_flip(i, scale=None, offset_x=None, offset_y=None, flip=None, anchor=None):
            r = real_set(i, scale=scale, offset_x=offset_x, offset_y=offset_y,
                         flip=flip, anchor=anchor)
            if flip is not None:                # 旧语义：一处统一管所有图层（翻转推全层）
                for d in wiz.cfg['layers']:
                    d['flip'] = bool(wiz.cfg.get('flip_h', False))
            return r

        before = snap_flip()
        wiz._layer_set_params = _old_unified_flip
        try:
            chk.invoke()
            wiz.root.update_idletasks()
        finally:
            wiz._layer_set_params = real_set
        f_bad = snap_flip()
        check('G07 ★判别力：把「只写当前层」打桩回旧前提「一处统一管所有图层」（R13 语义）'
              '→ G03/G05 同一条判据 g03_ok() 必须 FAIL',
              not g03_ok(before, 0, True, True), f'回退前={before} 注入后={f_bad}')
    finally:
        kill_wiz(wiz)


# ==========================================================================
# H 段 · 端到端：release/config.json 读写路径
# ==========================================================================
def sec_H(tmp):
    section('H. 端到端 —— release/config.json 运行时读取 + 向导保存写回')
    factory_path = os.path.join(BASE, 'release', 'config.json')
    factory = json.load(open(factory_path, encoding='utf-8'))
    note(f'出厂配置字段={sorted(factory.keys())}')

    # 运行时读取通路（R10/R11/R13 搬家后不许断）
    layers = R.resolve_layers(dict(factory), skin_dir=os.path.dirname(factory_path))
    note(f'resolve_layers → {[(os.path.basename(str(d.get("image"))), d.get("anchor"), d.get("flip")) for d in layers]}')
    check('H01 老配置（无 layers / 无 render_mode）→ resolve_layers 归一为 1 层且 anchor=right_edge',
          len(layers) == 1 and layers[0].get('anchor') == 'right_edge',
          f'{layers[0].get("anchor")}')
    from PIL import Image as _I
    sizes = []
    for d in layers:
        try:
            with _I.open(d['image']) as im:
                sizes.append((im.size[0], im.size[1]))
        except Exception:
            sizes.append((460, 675))
    try:
        laid = R.plan_layer_layout(layers, sizes, (0, 0, 460, 84), gap=R.DEFAULT_LAYER_GAP,
                                   main_off=(factory['offset_x'], factory['offset_y']))
        note(f'plan_layer_layout → {laid}')
        check('H02 运行时布局通路可用（贴边 right_edge 落点 x 靠右半宽）', bool(laid),
              f'{laid[0] if laid else None}')
    except Exception as e:
        check('H02 运行时布局通路可用（plan_layer_layout 不抛异常）', False, repr(e))

    # 向导侧：加载老配置 → 改 ③/翻转/⑩ 开关 → 保存 → 老字段零漂移
    wiz = make_wiz(dict(factory), tmp)
    try:
        keep = ('image', 'layout', 'layer', 'scale', 'offset_x', 'offset_y',
                'base_height', 'name')
        before = {k: wiz.cfg.get(k) for k in keep}
        radio_of(wiz, wiz.var_side, '左').invoke()
        wiz.chk_flip.invoke()
        wiz.chk_alpha_feather.invoke()
        wiz.root.update_idletasks()
        saved, mb = save_via_wiz(wiz)
        note(f'保存后 render_mode={saved.get("render_mode")} side={saved.get("side")} '
             f'flip_h={saved.get("flip_h")} layers={[(d.get("anchor"), d.get("flip")) for d in (saved.get("layers") or [])]}')
        drift = {k: (before[k], saved.get(k)) for k in keep if before[k] != saved.get(k)}
        check('H03 ★老字段零漂移（image/layout/layer/scale/offset_x/offset_y/base_height/name）'
              '—— 含 F-V1 老坑 offset_x=-132',
              not drift and saved.get('offset_x') == -132 and saved.get('offset_y') == -132,
              f'漂移={drift}')
        check('H04 ★R11 写入路径通：保存出的 side=left 且各层 anchor=left_edge',
              saved.get('side') == 'left'
              and [d.get('anchor') for d in (saved.get('layers') or [])] == ['left_edge'],
              f"{saved.get('side')} / {[d.get('anchor') for d in (saved.get('layers') or [])]}")
        check('H05 ★R13 写入路径通：保存出的 flip_h=True 且各层 flip 全 True',
              saved.get('flip_h') is True
              and [bool(d.get('flip')) for d in (saved.get('layers') or [])] == [True],
              f"{saved.get('flip_h')} / {[d.get('flip') for d in (saved.get('layers') or [])]}")
        check('H06 ★R10 写入路径通：保存出的 render_mode=alpha（⑪ 删掉后仍写得出）',
              saved.get('render_mode') == 'alpha', f"{saved.get('render_mode')}")

        # 往返：保存出的 cfg 再喂一次 → 关键字段一致
        wiz2 = make_wiz(dict(saved), tmp)
        try:
            saved2, _ = save_via_wiz(wiz2)
            same = all(saved2.get(k) == saved.get(k) for k in
                       ('image', 'layout', 'layer', 'scale', 'offset_x', 'offset_y',
                        'base_height', 'name', 'side', 'flip_h', 'render_mode'))
            check('H07 ★往返稳定：保存→再加载→再保存，关键字段逐字一致', same,
                  f'{[(k, saved.get(k), saved2.get(k)) for k in ("side", "flip_h", "render_mode") if saved.get(k) != saved2.get(k)]}')
        finally:
            kill_wiz(wiz2)
    finally:
        kill_wiz(wiz)

    # 老 v1.6 皮肤档案（release/skins/芙芙/skin.json）走真实通路
    skin_dir = os.path.join(BASE, 'release', 'skins', '芙芙')
    skin_json = os.path.join(skin_dir, 'skin.json')
    if os.path.isfile(skin_json):
        raw = json.load(open(skin_json, encoding='utf-8'))
        note(f'老皮肤档案字段={sorted(raw.keys())}')
        wiz3 = make_wiz(layers_cfg([factory['image']], ['right_edge']), tmp)
        try:
            old_skins = R.SKINS_DIR
            R.SKINS_DIR = os.path.join(BASE, 'release', 'skins')
            try:
                wiz3.skin_var.set('芙芙')
                wiz3._apply_skin_to_wizard()
                wiz3.root.update_idletasks()
            finally:
                R.SKINS_DIR = old_skins
            a = [d.get('anchor') for d in wiz3.cfg['layers']]
            saved3, _ = save_via_wiz(wiz3)
            check('H08 ★老 v1.6 单层皮肤档案走真实切皮肤通路：不崩、1 层、anchor 与 side 一致',
                  len(wiz3.cfg['layers']) >= 1
                  and all(x == R.anchor_from_side(saved3.get('side', 'right')) for x in a),
                  f'anchors={a} side={saved3.get("side")}')
        finally:
            kill_wiz(wiz3)
    else:
        check('H08 老皮肤档案夹具存在', False, skin_json)


# ==========================================================================
# J 段 · 判别力复现：把实现打回旧行为 → t6 改写后的断言必须 FAIL
# ==========================================================================
WRAP_TPL = '''# -*- coding: utf-8 -*-
import os
import runpy
import sys
BASE = %(base)r
sys.path.insert(0, BASE)
import rime_char_overlay as R


def _rec(w, fn):
    for c in list(w.winfo_children()):
        fn(c)
        _rec(c, fn)


%(inject)s

mod = os.path.join(BASE, %(target)r)
sys.argv = [mod, '--sections', %(secs)r]
rc = 0
try:
    runpy.run_path(mod, run_name='__main__')
except SystemExit as e:
    rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
print('WRAPPER_RC=%%s' %% rc)
sys.exit(rc)
'''

INJ_CHECKER = '''def _pc(self, img):
    try:
        return R.compose_on_checker(self._preview_render_mode_img(img),
                                    R.CHECKER_CELL, self._Image)
    except Exception:
        return img.convert('RGB')


R.ConfigWizard._preview_compose = _pc
'''

INJ_NO_SIDE_RADIO = '''_orig_build = R.ConfigWizard._build_ui


def _nb(self):
    _orig_build(self)

    def kill(c):
        try:
            if (c.winfo_class() == 'Radiobutton'
                    and str(c.cget('variable')) == str(self.var_side)):
                c.destroy()
        except Exception:
            pass
    _rec(self.root, kill)


R.ConfigWizard._build_ui = _nb
'''

INJ_FORCE_HARD_EDGE = '''def _hard(self, img):
    a = img.split()[3].point(lambda v: 255 if v >= 128 else 0)
    out = img.copy()
    out.putalpha(a)
    return out


R.ConfigWizard._preview_render_mode_img = _hard
'''

INJ_ADD_RENDER_RADIO = '''_orig_build = R.ConfigWizard._build_ui


def _nb(self):
    _orig_build(self)
    import tkinter as tk
    tk.Radiobutton(self.root, text='⑪ 渲染模式（注入回退）',
                   variable=self.var_render, value='alpha').pack()


R.ConfigWizard._build_ui = _nb
'''

INJ_COLLAPSE_OFF = '''R.ConfigWizard._apply_adv_collapsed = lambda self: None
R.ConfigWizard._toggle_adv_collapse = (
    lambda self, collapse=None: setattr(self, '_adv_collapsed', bool(collapse)))
'''

# v2.0-N3（第四轮）：把写回路径打桩回**旧前提**「一处统一管所有图层」（R11/R13 语义）——
# ③ 与翻转都推全层。用 t11 改写后的新断言（C03/C04/C06/C06b/G03/G05）跑，必须 FAIL。
INJ_OLD_UNIFIED_LAYERS = '''_real_set = R.ConfigWizard._layer_set_params


def _old_unified(self, i, scale=None, offset_x=None, offset_y=None, flip=None, anchor=None):
    r = _real_set(self, i, scale=scale, offset_x=offset_x, offset_y=offset_y,
                  flip=flip, anchor=anchor)
    if anchor is not None:
        for d in self.cfg['layers']:
            d['anchor'] = self._layer_anchor_at(0)
    if flip is not None:
        for d in self.cfg['layers']:
            d['flip'] = bool(self.cfg.get('flip_h', False))
    return r


R.ConfigWizard._layer_set_params = _old_unified
'''


def sec_J(tmp):
    section('J. 判别力复现（独立复核 t6 的改写断言：回退场景下必须 FAIL）')
    cases = [
        ('S1 预览换回棋盘格', 'B_test_indep_batch1.py', 'A', INJ_CHECKER, 'A03'),
        ('S2 通用区 ③ 单选被撤（旧位置）', 'B_test_indep_batch1.py', 'B',
         INJ_NO_SIDE_RADIO, 'B02'),
        ('S3 增强档退化为硬边', 'B_test_indep_batch1.py', 'A', INJ_FORCE_HARD_EDGE, 'A14'),
        ('S4 ⑪ 单选被注回', 'B_test_indep_batch2.py', 'E', INJ_ADD_RENDER_RADIO, 'E06b'),
        ('S5 折叠执行点失效', 'B_test_indep_batch2.py', 'E', INJ_COLLAPSE_OFF, 'E01'),
        # v2.0-N3（第四轮）：t11 改写后的**新断言**必须能被「回退成 R11/R13 旧前提」打红。
        # 这里不是另写判据，而是回退产品写回路径后跑 t11 改好的那几条断言本身。
        ('S6 ③ 回退成「一处统一管所有图层」', 'B_test_indep_batch3.py', 'C',
         INJ_OLD_UNIFIED_LAYERS, ('C03', 'C04', 'C06', 'C06b')),
        ('S7 翻转回退成「一处统一管所有图层」', 'B_test_indep_batch3.py', 'G',
         INJ_OLD_UNIFIED_LAYERS, ('G03', 'G05')),
    ]
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    for tag, target, secs, inj, key in cases:
        wp = os.path.join(tmp, 'wrap_%s.py' % tag.split()[0])
        with open(wp, 'w', encoding='utf-8') as f:
            f.write(WRAP_TPL % {'base': BASE, 'target': target, 'secs': secs, 'inject': inj})
        try:
            p = subprocess.run([sys.executable, wp], cwd=BASE, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=300)
            rc = p.returncode
            out = p.stdout.decode('utf-8', 'replace')
        except Exception as e:
            rc, out = None, repr(e)
        keys = (key,) if isinstance(key, str) else tuple(key)
        hit = {k: ('[FAIL] %s' % k) in out for k in keys}
        miss = [k for k, v in hit.items() if not v]
        tail = [ln.strip() for ln in out.splitlines()
                if ln.strip().startswith('[FAIL]') or 'WRAPPER_RC' in ln or 'RESULT:' in ln]
        note(f'{tag} → {target} --sections {secs}：exit={rc}，期望 FAIL={list(keys)}；'
             f'尾部={tail[-3:]}')
        check(f'J·{tag}：回退场景下 {" / ".join(keys)} 判据必须 FAIL、该段 exit≠0（非恒真）',
              rc not in (0, None) and not miss, f'exit={rc} 命中={hit} 漏红={miss or "无"}')


# ==========================================================================
# 主流程
# ==========================================================================
def main():
    secs = 'A,B,C,D,E,F,G,H,J'
    if '--sections' in sys.argv:
        secs = sys.argv[sys.argv.index('--sections') + 1]
    want = [s.strip().upper() for s in secs.split(',') if s.strip()]

    impl = os.path.join(BASE, 'rime_char_overlay.py')
    f0 = freeze_of(impl)
    print('=' * 96)
    print('B_test_indep_batch3 —— 第三轮独立验证（R7/R8/R9/R10/R11/R12/R13）')
    print(f'被测实现：{impl}')
    print(f'跑前冻结：sha256={f0[0][:16]}… 字节={f0[2]} mtime={f0[1]}')
    print('=' * 96)

    tmp = tempfile.mkdtemp(prefix='indep3_')
    # 只读约束（HANDOFF-2.1 §8.5 · t11 契约第 7 条）：日志/临时产物只落临时目录，
    # 不再给项目 error.log 增行。R.HERE 是调用时取模块全局（产品 _write_log 定义 :8485 /
    # 写盘 :8492），运行期改这一处即可，不必碰产品代码。
    R.HERE = tmp
    try:
        for s, fn in (('A', sec_A), ('B', sec_B), ('C', sec_C), ('D', sec_D),
                      ('E', sec_E), ('F', sec_F), ('G', sec_G), ('H', sec_H),
                      ('J', sec_J)):
            if s in want:
                fn(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    f1 = freeze_of(impl)
    section('I. 冻结自检（跑前跑后被测实现不许变）')
    check('I01 被试文件 sha256/mtime/字节 跑前跑后一致（本轮有效）', f0 == f1,
          f'{f0[0][:12]}…/{f0[1]}/{f0[2]}B → {f1[0][:12]}…/{f1[1]}/{f1[2]}B')

    print('\n' + '=' * 96)
    print(f'RESULT: PASS={len(PASS)} FAIL={len(FAIL)} 用时 {time.time() - T0:.1f}s')
    if FAIL:
        print('FAIL 明细：')
        for f in FAIL:
            print(f'  - {f}')
    print('=' * 96)
    print('RESULT: ' + ('PASS' if not FAIL else 'FAIL'))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
