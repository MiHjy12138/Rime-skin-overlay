# -*- coding: utf-8 -*-
"""B_test_indep_batch4.py —— 第四轮（R15）验证者独立探针

规矩（HANDOFF-2.1 §6-13 / §6-14）：
  · 只走用户真实通路（自己构造 ConfigWizard、自己点/自己量），不复用实现者断言；
  · 脚本自建、判据自拟；出现红必须当场定性（真回归 / 过时前提）；
  · R.HERE 指向 tempdir，产物不进项目目录；控制台 utf-8。
  · 唯一测试运行者；跑前跑后验 `git hash-object rime_char_overlay.py` == `HEAD:rime_char_overlay.py`。

用法：python B_test_indep_batch4.py [A] [B]
      A = N1（折叠按钮做大 + 向导默认折叠）
      B = N2（预览里带 alpha 的图不再盖住模拟候选框；t8 独立验证并入）

B 段口径（与 gate/_evidence_r15 下的实现者量测都不同源）：
  · 量「候选框区域被显示位图遮盖的像素数」——按**源 alpha**分档（α==0 档必须 0 遮盖；
    α>0 档必须 100% 遮盖 = 不误伤图体）；掩膜用产品自己的 _preview_render_mode_img()。
  · 反向断言：显示位图 RGB 与 _preview_compose() 的 RGB **逐位**相同（掩膜只改 alpha）。
  · 全程不抓屏（窗口 DC / ImageGrab 都不用）⇒ 不会被别的窗口遮挡成假红（t7 的教训）。
  · B07 是**就地负控**：把显示端那一步 monkeypatch 回「不装掩膜」，同一批判据必须翻红。
"""
import json
import os
import subprocess
import sys
import tempfile
from importlib.machinery import SourceFileLoader

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'rime_char_overlay.py')
TMP = tempfile.mkdtemp(prefix='r15_b4_')
R12_COMMIT = '80762e7'          # R12 折叠按钮的旧实现（上一版，用来做判别力臂）
FAILED = []


def chk(tag, ok, detail=''):
    print('  [%s] %s %s' % ('PASS' if ok else 'FAIL', tag, detail))
    if not ok:
        FAILED.append((tag, detail))
    return bool(ok)


def load_module(path, name):
    import importlib.util
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    mod.HERE = TMP                                   # 纪律：日志/产物写 tempdir
    try:
        mod.CONFIG_PATH = os.path.join(TMP, 'config.json')
    except Exception:
        pass
    return mod


def extract_commit_file(commit, rel, subdir):
    os.makedirs(subdir, exist_ok=True)
    dst = os.path.join(subdir, rel)
    p = subprocess.run(['git', 'show', '%s:%s' % (commit, rel)], cwd=HERE,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError('git show 失败: %s' % p.stderr.decode('utf-8', 'replace'))
    with open(dst, 'wb') as f:
        f.write(p.stdout)
    return dst


# ---------------------------------------------------------------- 量测原语
def build_wizard(mod):
    wiz = mod.ConfigWizard(lambda *a: None, None)
    wiz.root.update_idletasks()
    wiz.root.update()
    return wiz


def close_wizard(wiz):
    try:
        wiz.root.destroy()
    except Exception:
        pass


def btn_box(wiz):
    """折叠标题按钮真实几何；未 map 时退回需求尺寸（红阶段也要能出数字）。"""
    btn = getattr(wiz, 'btn_adv_toggle', None)
    if btn is None:
        return (0, 0, 0, 0)
    wiz.root.update_idletasks()
    w, h = int(btn.winfo_width()), int(btn.winfo_height())
    if w <= 1 or h <= 1:
        w, h = int(btn.winfo_reqwidth()), int(btn.winfo_reqheight())
    return (w, h, int(btn.winfo_rootx()), int(btn.winfo_rooty()))


def win_metrics(wiz):
    """窗口三量：需求高（内容驱动）/ 实际高 / 滚动条是否需要。"""
    wiz.root.update_idletasks()
    wiz.root.update()
    return {'req_h': int(wiz.root.winfo_reqheight()),
            'req_w': int(wiz.root.winfo_reqwidth()),
            'win_h': int(wiz.root.winfo_height()),
            'win_w': int(wiz.root.winfo_width()),
            'scroll_needed': bool(getattr(wiz, '_scroll_needed', False)),
            'scrollbar_mapped': int(getattr(wiz, 'body_scrollbar', None).winfo_ismapped())
            if getattr(wiz, 'body_scrollbar', None) is not None else -1}


def body_state(wiz):
    body = getattr(wiz, 'adv_body', None)
    if body is None:
        return {'packed': None, 'mapped': None, 'manager': None}
    wiz.root.update_idletasks()
    return {'packed': body.winfo_manager() == 'pack',
            'mapped': int(body.winfo_ismapped()),
            'manager': body.winfo_manager()}


def find_bottom_row(wiz):
    """折叠态必须可见的底部按钮行：含「保存并启动」的那个按钮的父 frame。"""
    import tkinter as tk
    hits = []

    def walk(w):
        for c in w.winfo_children():
            try:
                if isinstance(c, tk.Button) and '保存并启动' in str(c.cget('text')):
                    hits.append(c)
            except Exception:
                pass
            walk(c)
    walk(wiz.root)
    if not hits:
        return None, None
    btn = hits[0]
    return btn, btn.master


def adv_body_children_mapped(wiz):
    """展开态 ⑧~⑭ 区间：adv_body 下所有叶子控件的 map 统计。"""
    import tkinter as tk
    body = getattr(wiz, 'adv_body', None)
    if body is None:
        return 0, 0
    leaf_types = (tk.Label, tk.Button, tk.Checkbutton, tk.Radiobutton, tk.Scale,
                  tk.Listbox, tk.Entry, tk.Canvas, tk.Spinbox)
    total = mapped = 0

    def walk(w):
        nonlocal total, mapped
        for c in w.winfo_children():
            try:
                if isinstance(c, leaf_types):
                    total += 1
                    if int(c.winfo_ismapped()) == 1:
                        mapped += 1
                else:
                    walk(c)
            except Exception:
                pass
    walk(body)
    return mapped, total


def scenario(wiz):
    """三态量测：默认（=构造完）→ 显式展开 → 再折叠。"""
    out = {}
    out['default'] = {'collapsed': bool(getattr(wiz, '_adv_collapsed', None)),
                      'body': body_state(wiz), 'btn': btn_box(wiz)[:2],
                      'text': str(wiz.btn_adv_toggle.cget('text')),
                      'win': win_metrics(wiz)}
    wiz._toggle_adv_collapse(False)          # 真实通路：展开（按钮 command 走同一方法）
    wiz.root.update_idletasks()
    wiz.root.update()
    out['expanded'] = {'collapsed': bool(wiz._adv_collapsed), 'body': body_state(wiz),
                       'btn': btn_box(wiz)[:2], 'text': str(wiz.btn_adv_toggle.cget('text')),
                       'win': win_metrics(wiz), 'adv_children': adv_body_children_mapped(wiz)}
    wiz._toggle_adv_collapse(True)           # 再折叠
    wiz.root.update_idletasks()
    wiz.root.update()
    out['recollapsed'] = {'collapsed': bool(wiz._adv_collapsed), 'body': body_state(wiz),
                          'btn': btn_box(wiz)[:2], 'text': str(wiz.btn_adv_toggle.cget('text')),
                          'win': win_metrics(wiz)}
    return out


def measure(mod, tag):
    wiz = build_wizard(mod)
    try:
        sc = scenario(wiz)
        btn = getattr(wiz, 'btn_adv_toggle', None)
        sc['bottom_visible_collapsed'] = None
        sc['bottom_visible_expanded'] = None
        b, row = find_bottom_row(wiz)
        if b is not None:
            wiz._toggle_adv_collapse(True)
            wiz.root.update_idletasks()
            wiz.root.update()
            lim = wiz.root.winfo_rooty() + wiz.root.winfo_height()
            sc['bottom_visible_collapsed'] = {'mapped': int(row.winfo_ismapped()),
                                              'btn_mapped': int(b.winfo_ismapped()),
                                              'row_bottom': int(row.winfo_rooty() + row.winfo_height()),
                                              'win_bottom': int(lim)}
            wiz._toggle_adv_collapse(False)
            wiz.root.update_idletasks()
            wiz.root.update()
        sc['btn_exists'] = btn is not None
        sc['btn_state'] = str(btn.cget('state')) if btn is not None else '?'
        sc['tag'] = tag
        return sc
    finally:
        close_wizard(wiz)


# ---------------------------------------------------------------- A 段
def section_A():
    print('=== A 段 · N1 独立验证（折叠按钮做大 + 向导默认折叠）===')
    print('独立构造 ConfigWizard，自己取值、自己量几何；不读实现者测试的任何数字。\n')
    mod = load_module(SRC, 'rco_A')
    cur = measure(mod, 'current(29162ac)')
    print('  [当前实现三态]')
    for k in ('default', 'expanded', 'recollapsed'):
        s = cur[k]
        print('    %-12s collapsed=%-5s body=%-7s mapped=%s btn=%sx%s text=%r win(req_h=%s,win_h=%s)'
              % (k, s['collapsed'], s['body']['manager'], s['body']['mapped'],
                 s['btn'][0], s['btn'][1], s['text'], s['win']['req_h'], s['win']['win_h']))

    # ---- 我自己量 R12 基线（不引用实现者数字）----
    r12_path = extract_commit_file(R12_COMMIT, 'rime_char_overlay.py', os.path.join(TMP, 'r12'))
    r12 = measure(load_module(r12_path, 'rco_A_r12'), 'R12(%s,独立量)' % R12_COMMIT)
    r12_btn_exp = r12['expanded']['btn']
    r12_btn_col = r12['recollapsed']['btn']
    r12_win_col = r12['recollapsed']['win']['req_h']
    print('  [R12 基线（本脚本独立量）] 展开态按钮=%sx%s 折叠态按钮=%sx%s 折叠态窗口需求高=%s'
          % (r12_btn_exp[0], r12_btn_exp[1], r12_btn_col[0], r12_btn_col[1], r12_win_col))
    print('  [R12 三态] default.collapsed=%s expanded.req_h=%s recollapsed.req_h=%s'
          % (r12['default']['collapsed'], r12['expanded']['win']['req_h'],
             r12['recollapsed']['win']['req_h']))

    cur_btn_col = cur['recollapsed']['btn']
    cur_btn_exp = cur['expanded']['btn']
    cur_win_col = cur['recollapsed']['win']['req_h']
    grow = max(0, cur_btn_col[1] - r12_btn_col[1])          # 按钮自身增高量

    print('\n  ---- 判据 ----')
    chk('A01 ★向导构造完成后就是折叠态（_adv_collapsed is True，自己取值）',
        cur['default']['collapsed'] is True, 'got=%r' % cur['default']['collapsed'])
    chk('A02 ★默认折叠：adv_body 未 pack 且未 map',
        cur['default']['body']['packed'] is False and cur['default']['body']['mapped'] == 0,
        'manager=%r mapped=%s' % (cur['default']['body']['manager'],
                                  cur['default']['body']['mapped']))
    chk('A03 ★默认折叠：标题文案是 ▸ 态（含「展开」）',
        '▸' in cur['default']['text'] and '展开' in cur['default']['text'],
        repr(cur['default']['text']))
    chk('A04 ★按钮可点区域：折叠态按钮高 ≥ 30px（真实几何）',
        cur_btn_col[1] >= 30, '%sx%s px' % (cur_btn_col[0], cur_btn_col[1]))
    area_col = cur_btn_col[0] * cur_btn_col[1]
    r12_area_col = r12_btn_col[0] * r12_btn_col[1]
    chk('A05 ★按钮可点区域：折叠态面积相对 R12 基线 ≥ +40%',
        area_col >= r12_area_col * 1.4,
        '%d px² vs R12 %d px²（%.1f%%）' % (area_col, r12_area_col,
                                            (area_col / float(r12_area_col) - 1) * 100))
    area_exp = cur_btn_exp[0] * cur_btn_exp[1]
    r12_area_exp = r12_btn_exp[0] * r12_btn_exp[1]
    chk('A06 ★按钮可点区域：展开态面积相对 R12 基线 ≥ +40%',
        area_exp >= r12_area_exp * 1.4,
        '%d px² vs R12 %d px²（%.1f%%）' % (area_exp, r12_area_exp,
                                            (area_exp / float(r12_area_exp) - 1) * 100))
    allow = r12_win_col + grow
    chk('A07 ★折叠态窗口高不退化（豁免口径：≤ R12 基线 + 按钮自身增高量）',
        cur_win_col <= allow,
        '实测 %dpx ≤ 允许 %dpx（R12 %d + 按钮增高 %d）'
        % (cur_win_col, allow, r12_win_col, grow))
    print('      · 裸口径对照：R12 折叠态 %dpx → 现在 %dpx（+%dpx，+%.1f%%）'
          % (r12_win_col, cur_win_col, cur_win_col - r12_win_col,
             (cur_win_col / float(r12_win_col) - 1) * 100))
    bvc = cur.get('bottom_visible_collapsed')
    chk('A08 ★折叠态底部按钮行可见且在窗内',
        bool(bvc) and bvc['mapped'] == 1 and bvc['btn_mapped'] == 1
        and bvc['row_bottom'] <= bvc['win_bottom'] + 2,
        json.dumps(bvc, ensure_ascii=False) if bvc else '未找到「保存并启动」按钮行')
    m, t = cur['expanded']['adv_children']
    chk('A09 ★展开后 ⑧~⑭ 子控件全部可见（winfo_ismapped=1 全中）',
        t >= 10 and m == t, 'mapped %d / total %d' % (m, t))
    chk('A10 ★往返两轮后回初值：折叠态三量（按钮高/窗口高/状态位）±2px',
        abs(cur['recollapsed']['btn'][1] - cur_btn_col[1]) <= 2
        and abs(cur['recollapsed']['win']['req_h'] - cur_win_col) <= 2
        and cur['recollapsed']['collapsed'] is True,
        'btn %s→%s win %s→%s collapsed=%s'
        % (cur_btn_col[1], cur['recollapsed']['btn'][1], cur_win_col,
           cur['recollapsed']['win']['req_h'], cur['recollapsed']['collapsed']))
    # 展开态 ②~⑭ 的主体仍在（折叠只收 ⑧~⑭）
    chk('A11 展开态窗口高 > 折叠态（展开确实把内容放回来）',
        cur['expanded']['win']['req_h'] > cur_win_col + 100,
        '%d vs %d' % (cur['expanded']['win']['req_h'], cur_win_col))

    # ---- 判别力臂 ----
    print('\n  ---- 判别力（把新事实改回旧事实，同一条判据必须翻红）----')
    arms = {}
    # 臂 P1：只把「初态折叠」改回 R12 的展开（按钮保持新的大尺寸）→ 只该红 A01/A02/A03
    src = open(SRC, encoding='utf-8').read()
    old_line = 'self._adv_collapsed = True'
    n_occ = src.count(old_line)
    p1 = os.path.join(TMP, 'arm_p1_expanded_init.py')
    with open(p1, 'w', encoding='utf-8') as f:
        f.write(src.replace(old_line, 'self._adv_collapsed = False'))
    m1 = measure(load_module(p1, 'rco_A_p1'), 'armP1(初态改回展开)')
    p1_bad = []
    if not (m1['default']['collapsed'] is True):
        p1_bad.append('A01')
    if not (m1['default']['body']['packed'] is False and m1['default']['body']['mapped'] == 0):
        p1_bad.append('A02')
    if not ('▸' in m1['default']['text'] and '展开' in m1['default']['text']):
        p1_bad.append('A03')
    m1_btn_ok = m1['recollapsed']['btn'][1] >= 30
    arms['armP1_初态改回展开'] = {'FAIL': p1_bad, '按钮判定仍 PASS': m1_btn_ok}
    print('    臂P1（只把 `%s` 改成 False，出现 %d 处）：A01/A02/A03 → %s；按钮尺寸判定仍 %s'
          % (old_line, n_occ, 'FAIL（符合预期）' if p1_bad else '未翻红（判据恒真！）',
             'PASS' if m1_btn_ok else 'FAIL'))
    chk('A12 ★判别力：初态改回展开后，默认折叠三判据必须 FAIL',
        len(p1_bad) == 3, 'FAIL 项=%s' % p1_bad)
    chk('A13 判别力对照：同一臂里按钮尺寸判据仍 PASS（证明两族判据互不粘连）',
        m1_btn_ok, '折叠态按钮高=%s' % m1['recollapsed']['btn'][1])
    # 臂 P2：整份 R12 旧实现 → 折叠/按钮两族判据都该红
    p2_bad = []
    if not (r12['default']['collapsed'] is True):
        p2_bad.append('A01')
    if r12['recollapsed']['btn'][1] >= 30:
        pass
    else:
        p2_bad.append('A04')
    if (r12_btn_col[0] * r12_btn_col[1]) >= r12_area_col * 1.4:
        p2_bad.append('A05(恒真!)')
    arms['armP2_R12旧实现'] = {'FAIL': [x for x in p2_bad if x != 'A05(恒真!)'],
                              'A05 在 R12 上的比值': round(r12_area_col / float(r12_area_col), 3)}
    print('    臂P2（整份 R12 %s 旧实现）：_adv_collapsed=%s、折叠态按钮=%sx%s（%d px²）'
          % (R12_COMMIT, r12['default']['collapsed'], r12_btn_col[0], r12_btn_col[1], r12_area_col))
    chk('A14 ★判别力：旧实现（R12）下 A01 与 A04 必须 FAIL',
        ('A01' in p2_bad) and ('A04' in p2_bad), 'FAIL 项=%s' % p2_bad)

    with open(os.path.join(TMP, 'A_metrics.json'), 'w', encoding='utf-8') as f:
        json.dump({'current': cur, 'r12': r12, 'arms': arms,
                   'derived': {'r12_btn_exp': r12_btn_exp, 'r12_btn_col': r12_btn_col,
                               'r12_win_col': r12_win_col, 'cur_btn_col': cur_btn_col,
                               'cur_btn_exp': cur_btn_exp, 'cur_win_col': cur_win_col,
                               'grow': grow, 'allow': allow}},
                  f, ensure_ascii=False, indent=1)
    print('\n[A 段小结] 按钮 折叠态 %sx%s（R12 %sx%s）｜展开态 %sx%s（R12 %sx%s）｜'
          '折叠态窗口高 %s（R12 %s，允许 ≤%s）｜展开态窗口高 %s（R12 %s）'
          % (cur_btn_col[0], cur_btn_col[1], r12_btn_col[0], r12_btn_col[1],
             cur_btn_exp[0], cur_btn_exp[1], r12_btn_exp[0], r12_btn_exp[1],
             cur_win_col, r12_win_col, allow,
             cur['expanded']['win']['req_h'], r12['expanded']['win']['req_h']))
    return cur, r12, arms


# ==========================================================================
# B 段：N2 —— 预览里带 alpha 的图不再盖住模拟候选框（t8 独立验证并入）
# ==========================================================================
import hashlib                                                       # noqa: E402


def _sha_rgb(im):
    return hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()[:16]


def make_b_fixtures():
    """我自造的夹具（三份，尺寸互不相同；含全透明边 / 半透明块 / 不透明核）。"""
    from PIL import Image, ImageDraw                                 # 延迟导入：别把 PIL 变成全脚本前置
    specs = [('b1_alpha_ring.png', 128, 128), ('b2_tall_cutout.png', 86, 234),
             ('b3_wide_soft_band.png', 301, 96)]
    out = []
    for name, w, h in specs:
        im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([int(w * 0.16), int(h * 0.16), int(w * 0.84), int(h * 0.84)],
                  fill=(255, 64, 32, 255))                            # 不透明核
        d.rectangle([int(w * 0.30), int(h * 0.30), int(w * 0.70), int(h * 0.70)],
                    fill=(16, 128, 255, 150))                         # 半透明块
        p = os.path.join(TMP, name)
        im.save(p)
        out.append((name, p, (w, h)))
    return out


def b_case(mod, fixture, cfg_over, flatten_arm=False):
    """建真向导 → 真 _update_preview() → 返回候选框矩形 + 各图片 item 的显示位图/掩膜。

    flatten_arm=True 时把显示端那一步 monkeypatch 成「不装掩膜」（只用于 B07 负控）。
    """
    rec = []
    disp_name = '_preview_display_img'
    has_disp = hasattr(mod.ConfigWizard, disp_name)
    orig = getattr(mod.ConfigWizard, disp_name, None)

    if flatten_arm or not has_disp:
        def _flat(self, img):
            r = self._preview_compose(img)          # ← 退回修前行为：纯 RGB、无 alpha
            rec.append((img, r))
            return r
        setattr(mod.ConfigWizard, disp_name, _flat)
    else:
        def _wrap(self, img):
            r = orig(self, img)
            rec.append((img, r))
            return r
        setattr(mod.ConfigWizard, disp_name, _wrap)

    wiz = None
    try:
        wiz = build_wizard(mod)
        wiz.cfg.update(cfg_over)
        for k, v in (('layout', 'var_layout'), ('side', 'var_side'), ('layer', 'var_layer'),
                     ('scale', 'var_scale'), ('offset_x', 'var_offx'), ('offset_y', 'var_offy')):
            if k in cfg_over:
                getattr(wiz, v).set(cfg_over[k])
        wiz.cfg['image'] = fixture
        wiz._update_preview()
        wiz.root.update_idletasks()
        wiz.root.update()
        cv = wiz.canvas
        items = list(cv.find_all())
        cand, cand_idx, imgs = None, None, []
        for it in items:
            kind = cv.type(it)
            co = [int(v) for v in cv.coords(it)]
            if kind == 'rectangle':
                fill = str(cv.itemcget(it, 'fill') or '').lower()
                outline = str(cv.itemcget(it, 'outline') or '')
                dash = str(cv.itemcget(it, 'dash') or '')
                if fill == '#f5f5f5' and outline and not dash and (co[2] - co[0]) > 100:
                    cand, cand_idx = co[:4], items.index(it)
            elif kind == 'image':
                nm = str(cv.itemcget(it, 'image'))
                iw = int(cv.tk.call('image', 'width', nm))
                ih = int(cv.tk.call('image', 'height', nm))
                x, y = co[0], co[1]
                anchor = str(cv.itemcget(it, 'anchor') or 'center')
                if anchor == 'nw':                      # ← 预览图片项用的就是 nw
                    rect = [x, y, x + iw, y + ih]
                elif anchor == 'center':
                    rect = [x - iw // 2, y - ih // 2, x - iw // 2 + iw, y - ih // 2 + ih]
                elif anchor == 'ne':
                    rect = [x - iw, y, x, y + ih]
                elif anchor == 'sw':
                    rect = [x, y - ih, x + iw, y]
                elif anchor == 'se':
                    rect = [x - iw, y - ih, x, y]
                else:
                    chk('B00 未支持的画布锚点（量测会错位，必须先补）', False, repr(anchor))
                    continue
                imgs.append({'zidx': items.index(it), 'anchor': anchor, 'rect': rect,
                             'size': (iw, ih)})
        disp = [d for d in rec if d[1] is not None]
        for im in imgs:
            m = None
            for k, (arg, out) in enumerate(disp):
                if (int(out.width), int(out.height)) == im['size']:
                    m = disp.pop(k)
                    break
            if m is None and disp:
                m = disp.pop(0)
            if m is None:
                continue
            arg, out = m
            alpha = wiz._preview_render_mode_img(arg)              # 产品自带掩膜口径
            im['out'] = out
            im['alpha'] = alpha.convert('RGBA').split()[3] if alpha.mode == 'RGBA' \
                else alpha.convert('L')
            im['disp_has_alpha'] = ('A' in out.mode) or ('transparency' in out.info)
            comp = wiz._preview_compose(arg)
            im['comp_has_alpha'] = ('A' in comp.mode) or ('transparency' in comp.info)
            im['sha_disp'] = _sha_rgb(out)
            im['sha_comp'] = _sha_rgb(comp)
        return {'cand': cand, 'cand_idx': cand_idx, 'imgs': imgs, 'has_disp_fn': has_disp}
    finally:
        if orig is not None:
            setattr(mod.ConfigWizard, disp_name, orig)
        elif hasattr(mod.ConfigWizard, disp_name):
            delattr(mod.ConfigWizard, disp_name)
        close_wizard(wiz)


def b_counts(im, cand):
    """候选框 ∩ 该图片矩形（且图片在框之上）里：遮盖像素数 + 按源 alpha 分档。"""
    out, alpha = im['out'], im['alpha']
    w, h = out.size
    oa = out.convert('RGBA').split()[3] if im['disp_has_alpha'] else None
    a_cand = [max(cand[0], im['rect'][0]), max(cand[1], im['rect'][1]),
              min(cand[2], im['rect'][2]), min(cand[3], im['rect'][3])]
    st = dict(inter=0, covered=0, n_zero=0, cov_zero=0, n_pos=0, cov_pos=0, n_mid=0)
    if not (a_cand[2] > a_cand[0] and a_cand[3] > a_cand[1]):
        return st
    ap, op = alpha.load(), (oa.load() if oa else None)
    for y in range(a_cand[1], a_cand[3]):
        for x in range(a_cand[0], a_cand[2]):
            ix, iy = x - im['rect'][0], y - im['rect'][1]
            if not (0 <= ix < w and 0 <= iy < h):
                continue
            st['inter'] += 1
            al = ap[ix, iy]
            cov = True if op is None else (op[ix, iy] > 0)
            if cov:
                st['covered'] += 1
            if al == 0:
                st['n_zero'] += 1
                if cov:
                    st['cov_zero'] += 1
            else:
                st['n_pos'] += 1
                if cov:
                    st['cov_pos'] += 1
                if al < 255:
                    st['n_mid'] += 1
    return st


def section_B():
    print('\n--- B. N2：预览里带 alpha 的图不再盖住模拟候选框（t8 独立验证）---')
    mod = load_module(SRC, 'rime_char_overlay_b4_n2')
    fx = [('t1 的 f1', os.path.join(HERE, '_evidence_r15', 'N2_repro', 'fixtures',
                                   'f1_alpha_block.png'))] + make_b_fixtures()
    base = {'layout': 'horizontal_double', 'side': 'center', 'layer': 'above',
            'scale': 1.0, 'offset_x': 0, 'offset_y': 0, 'render_mode': 'compat'}
    rows = []
    has_disp = None
    for name, path, *_ in fx:
        if not os.path.exists(path):
            chk('B00 夹具存在: %s' % name, False, path)
            continue
        case = b_case(mod, path, dict(base))
        has_disp = case['has_disp_fn'] if has_disp is None else has_disp
        if not case['cand'] or not case['imgs']:
            chk('B00 %s：预览画出候选框与图片' % name, False,
                'cand=%s imgs=%d' % (case['cand'], len(case['imgs'])))
            continue
        for im in case['imgs']:
            if 'out' not in im or im['zidx'] <= (case['cand_idx'] or 0):
                continue
            st = b_counts(im, case['cand'])
            rows.append((name, path, im, st))
    if not rows:
        chk('B00 至少量到一个「图片在候选框之上且交叠」的预览用例', False, '')
        return

    n_zero_total = sum(r[3]['n_zero'] for r in rows)
    inter_total = sum(r[3]['inter'] for r in rows)
    chk('B01 显示端口径：显示位图带 alpha、合成产物不带 alpha（D2 未被挪动）',
        bool(has_disp) and all(r[2]['disp_has_alpha'] for r in rows)
        and not any(r[2]['comp_has_alpha'] for r in rows),
        'display_has_alpha=%s comp_has_alpha=%s'
        % ([r[2]['disp_has_alpha'] for r in rows], [r[2]['comp_has_alpha'] for r in rows]))
    chk('B02 几何前提：交叠区里有图片自身 alpha==0 的像素（否则 B03 恒真）',
        inter_total > 0 and n_zero_total > 0,
        '交叠 %d px，其中 α==0 档 %d px' % (inter_total, n_zero_total))
    chk('B03 ★N2 核心：α==0 的透明档遮盖像素数 == 0（候选框完整透出）',
        all(r[3]['cov_zero'] == 0 for r in rows),
        '逐例 α==0 遮盖: %s（合计 %d）'
        % ([r[3]['cov_zero'] for r in rows], sum(r[3]['cov_zero'] for r in rows)))
    chk('B04 α>0 档遮盖率 == 100%（图体照旧可见，不误伤）',
        all(r[3]['cov_pos'] == r[3]['n_pos'] for r in rows),
        'α>0 遮盖/总数: %s' % [(r[3]['cov_pos'], r[3]['n_pos']) for r in rows])
    chk('B05 反向断言：显示位图 RGB == _preview_compose() 的 RGB（掩膜只改 alpha，颜色逐位不变）',
        all(r[2]['sha_disp'] == r[2]['sha_comp'] for r in rows),
        '逐例 sha: %s' % [(r[2]['sha_disp'], r[2]['sha_comp']) for r in rows])
    chk('B06 不再整块盖住：遮盖像素数 < 交叠面积，且差值 == α==0 档像素数',
        all(r[3]['covered'] == r[3]['inter'] - r[3]['n_zero'] for r in rows),
        '逐例 (covered, inter, α==0): %s'
        % [(r[3]['covered'], r[3]['inter'], r[3]['n_zero']) for r in rows])
    print('     [原始数字] %s' % '; '.join(
        '%s anchor=%s inter=%d covered=%d α=0:%d→盖%d α>0:%d/%d mid=%d'
        % (r[0], r[2].get('anchor'), r[3]['inter'], r[3]['covered'], r[3]['n_zero'],
           r[3]['cov_zero'], r[3]['cov_pos'], r[3]['n_pos'], r[3]['n_mid']) for r in rows))

    # ---- B07 就地负控（判别力）：把「装回掩膜」那一步 monkeypatch 掉 ----
    name0, path0 = rows[0][0], rows[0][1]
    c2 = b_case(mod, path0, dict(base), flatten_arm=True)
    neg = None
    for im in c2['imgs']:
        if 'out' in im and im['zidx'] > (c2['cand_idx'] or 0):
            neg = b_counts(im, c2['cand'])
            break
    if neg is None:
        chk('B07 ★判别力：负控（不装掩膜）臂量不到数据', False, '')
        return
    chk('B07 ★判别力：把显示端「装回掩膜」monkeypatch 掉（退回纯 RGB）后，B03 判据必须翻红',
        (neg['cov_zero'] == neg['n_zero']) and neg['n_zero'] > 0,
        '负控臂 α==0 档: 盖 %d / 共 %d（正臂为 0）; covered=%d inter=%d'
        % (neg['cov_zero'], neg['n_zero'], neg['covered'], neg['inter']))
    chk('B08 负控臂颜色也一致（负控只改「装不装掩膜」这一个变量）',
        neg['inter'] == rows[0][3]['inter'],
        '负控 inter=%d / 正臂 inter=%d' % (neg['inter'], rows[0][3]['inter']))


# ==========================================================================
# C 段 · N3（c38adff）独立验证：③ 贴边方向与水平翻转都只作用于**当前选中层**
#   规矩：自己造 ≥3 层场景、自己点控件、自己量 `layers[j]['anchor'] / ['flip']` 与顶层键；
#   不复用实现者（B_test_n3_side_per_layer.py）与 t11 改写过的 13 条断言。
# ==========================================================================
C_ANCHOR_WORD = {'left_edge': '左侧', 'right_edge': '右侧', 'center': '中间'}
C_SIDE_WORD = {'left': '左侧', 'right': '右侧', 'center': '中间'}


def c_figs(tmp, n=3):
    """自造 n 张不同尺寸/颜色的 PNG（自己造夹具，不借实现者的）"""
    from PIL import Image
    out = []
    sizes = [(120, 160), (90, 140), (200, 120)]
    for i in range(n):
        p = os.path.join(tmp, 'c_fig_%d.png' % i)
        w, h = sizes[i % len(sizes)]
        Image.new('RGBA', (w, h), (30 + i * 70, 90, 200, 255)).save(p)
        out.append(p)
    return out


def c_walk(w, out=None):
    out = [] if out is None else out
    for c in list(w.winfo_children()):
        out.append(c)
        c_walk(c, out)
    return out


def c_side_radios(wiz):
    """绑 var_side 的 Radiobutton（**变量绑定**定位，不看文案/位置）"""
    return [w for w in c_walk(wiz.root)
            if w.winfo_class() == 'Radiobutton'
            and str(w.cget('variable')) == str(wiz.var_side)]


def c_radio_selected_text(wiz):
    """实测控件态（不读 Python 侧 var 对象）：绑 var_side 的单选里，
    「该控件的 value == 其绑定变量在 Tk 变量表里的当前值」的那一颗就是被选中的。"""
    sel = []
    for w in c_side_radios(wiz):
        try:
            if str(w.getvar(str(w.cget('variable')))) == str(w.cget('value')):
                sel.append(str(w.cget('text')))
        except Exception:
            pass
    return sel[0] if len(sel) == 1 else ('<?%s>' % sel)


def c_flip_selected(wiz):
    """实测控件态（不读 Python 侧 var 对象）：绑 var_flip 的勾选框在 Tk 变量表里的实际布尔值。
    注意：经典 Tk 的 Checkbutton 没有 ttk 的 instate()，故走 getvar(name)。"""
    chk = getattr(wiz, 'chk_flip', None)
    if chk is None:
        return None
    try:
        return bool(chk.getvar(str(chk.cget('variable'))))
    except Exception:
        return None


def c_side_by_word(wiz, word):
    for w in c_side_radios(wiz):
        try:
            if word in str(w.cget('text')):
                return w
        except Exception:
            pass
    return None


def c_build(mod, cfg, skins, tmp):
    old = getattr(mod, 'SKINS_DIR', None)
    mod.SKINS_DIR = skins
    wiz = mod.ConfigWizard(lambda *a: None, None)
    if old is not None:
        mod.SKINS_DIR = old
    import copy
    wiz.cfg.update(copy.deepcopy(cfg))
    wiz._layer_sync_from_cfg()
    wiz.root.update_idletasks()
    wiz.root.update()
    return wiz


def c_select(wiz, i):
    wiz.layer_list.selection_clear(0, 'end')
    wiz.layer_list.selection_set(i)
    wiz._on_layer_select()
    wiz.root.update_idletasks()
    wiz.root.update()


def c_layers_cfg(figs, anchors, flips, **top):
    cfg = {'image': figs[0], 'layout': 'horizontal_double', 'side': 'right', 'layer': 'above',
           'scale': 1.0, 'offset_x': 0, 'offset_y': 0, 'base_height': 300, 'name': 't12',
           'schema_version': getattr(R_MOD, 'LAYERS_SCHEMA_VERSION', 2),
           'flip_h': flips[0],
           'layers': [{'image': f, 'anchor': a, 'scale': 1.0, 'offset_x': 0,
                       'offset_y': 0, 'flip': fl}
                      for f, a, fl in zip(figs, anchors, flips)]}
    cfg.update(top)
    return cfg


R_MOD = None       # section_C 里赋成被测模块（c_layers_cfg 用它的 schema 常量）


def section_C():
    print('\n=== C 段 · N3 独立验证（③ / 翻转按当前选中层；撤销 R11/R13 统一语义）===')
    print('自造 3 层夹具、自己点控件、自己量持久值与顶层键；不引用实现者测试的任何数字。\n')
    global R_MOD
    mod = load_module(SRC, 'rco_C')
    R_MOD = mod
    tmp = os.path.join(TMP, 'c')
    os.makedirs(tmp, exist_ok=True)
    skins = os.path.join(tmp, 'skins')
    os.makedirs(skins, exist_ok=True)
    figs = c_figs(tmp)

    def anchors(wiz):
        return [d.get('anchor') for d in wiz.cfg['layers']]

    def flips(wiz):
        return [bool(d.get('flip')) for d in wiz.cfg['layers']]

    # ---------------- C01/C02 逐层写回：只有当前选中层变 ----------------
    wiz = c_build(mod, c_layers_cfg(figs, ['right_edge', 'left_edge', 'center'],
                                    [False, True, False]), skins, tmp)
    try:
        print('  [C01/C02 逐层写回]')
        c_select(wiz, 1)                       # 选中第 2 层
        b_a, b_f = anchors(wiz), flips(wiz)
        b_top = (wiz.cfg.get('side'), bool(wiz.cfg.get('flip_h')))
        c_side_by_word(wiz, '中间').invoke()
        wiz.root.update_idletasks()
        a1 = anchors(wiz)
        c_flip_after_side = flips(wiz)
        chk('C01 ★选中第 2 层点 ③「中间」：只有 layers[1].anchor 变（其余层与顶层 side 纹丝不动）',
            a1 == ['right_edge', 'center', 'center'] and a1[0] == b_a[0]
            and wiz.cfg.get('side') == b_top[0] and c_flip_after_side == b_f,
            'before=%s → after=%s（顶层 side %r→%r，各层 flip %s 未动）'
            % (b_a, a1, b_top[0], wiz.cfg.get('side'), c_flip_after_side))
        b_a = anchors(wiz)
        cur_f1 = c_flip_selected(wiz)          # 第 2 层当前勾选态（由 fixture 决定）
        exp_f1 = list(b_f)
        exp_f1[1] = (not cur_f1)               # Checkbutton.invoke() 是**切换**语义
        wiz.chk_flip.invoke()
        wiz.root.update_idletasks()
        f1 = flips(wiz)
        chk('C02 ★选中第 2 层切换翻转（%s→%s）：只有 layers[1].flip 变（层 0/2 与顶层 flip_h 纹丝不动）'
            % (cur_f1, not cur_f1),
            cur_f1 is not None and f1 == exp_f1 and anchors(wiz) == b_a
            and bool(wiz.cfg.get('flip_h')) is False,
            'before=%s → after=%s（期望 %s；顶层 flip_h=%r，anchors 未动=%s）'
            % (b_f, f1, exp_f1, wiz.cfg.get('flip_h'), anchors(wiz) == b_a))
        # 换一层再各改一次（证明不是"只对第 2 层生效"的巧合）
        c_select(wiz, 2)
        c_side_by_word(wiz, '右侧').invoke()
        wiz.root.update_idletasks()
        c_flip_after_side2 = flips(wiz)
        chk('C02b ★换到第 3 层点 ③「右侧」：只有 layers[2].anchor 变，前两层保持',
            anchors(wiz) == ['right_edge', 'center', 'right_edge'],
            'anchors=%s' % anchors(wiz))
        cur_f2 = c_flip_selected(wiz)
        exp_f2 = list(c_flip_after_side2)
        exp_f2[2] = (not cur_f2)
        wiz.chk_flip.invoke()
        wiz.root.update_idletasks()
        chk('C02c ★第 3 层切换翻转（%s→%s）：只有 layers[2].flip 变，层 0/1 保持 %s'
            % (cur_f2, not cur_f2, c_flip_after_side2[:2]),
            cur_f2 is not None and flips(wiz) == exp_f2
            and flips(wiz)[:2] == c_flip_after_side2[:2],
            'before=%s → after=%s（期望 %s）' % (c_flip_after_side2, flips(wiz), exp_f2))

        # ---------------- C03 R2 断头路：多图层下选中主层也能改得动 ----------------
        print('  [C03 R2 断头路 · 主层可改]')
        c_select(wiz, 0)
        pre_a, pre_f = anchors(wiz), flips(wiz)
        c_side_by_word(wiz, '左侧').invoke()
        wiz.root.update_idletasks()
        a_after = anchors(wiz)
        chk('C03a ★R2 断头路：选中第 0 层（主层）点 ③「左侧」→ cfg[side] 与 layers[0].anchor 同步改',
            wiz.cfg.get('side') == 'left' and a_after[0] == 'left_edge'
            and a_after[1:] == pre_a[1:],
            'side=%r layers=%s（改前 %s；其余层 %s 未动）'
            % (wiz.cfg.get('side'), a_after, pre_a, a_after[1:]))
        wiz.chk_flip.invoke()
        wiz.root.update_idletasks()
        f_after = flips(wiz)
        chk('C03b ★R2 断头路：选中第 0 层勾翻转 → cfg[flip_h] 与 layers[0].flip 同步改，其余层不动',
            bool(wiz.cfg.get('flip_h')) is True and f_after[0] is True
            and f_after[1:] == pre_f[1:],
            'flip_h=%r flips=%s（改前 %s）' % (wiz.cfg.get('flip_h'), f_after, pre_f))

        # ---------------- C04 切层回显：3 层各不同、来回切 3 轮 ----------------
        print('  [C04 切层回显 · 3 轮]')
        # 把三层做成**各不相同**：anchor 与 flip 都要有区分度
        plan = [(0, '右侧', False), (1, '左侧', True), (2, '中间', False)]
        for i, word, want_flip in plan:
            c_select(wiz, i)
            c_side_by_word(wiz, word).invoke()
            wiz.root.update_idletasks()
            if c_flip_selected(wiz) != want_flip:
                wiz.chk_flip.invoke()
                wiz.root.update_idletasks()
        a_now, f_now = anchors(wiz), flips(wiz)
        print('      · 三层持久值：anchors=%s flips=%s' % (a_now, f_now))
        rounds = []
        seq = [0, 1, 2, 2, 1, 0, 1, 2, 0]        # 来回切 3 轮
        ok_all = True
        for i in seq:
            c_select(wiz, i)
            got_word = c_radio_selected_text(wiz)
            got_flip = c_flip_selected(wiz)
            want_word = C_ANCHOR_WORD.get(anchors(wiz)[i])
            want_flip = bool(flips(wiz)[i])
            ok = (got_word == want_word) and (got_flip == want_flip)
            ok_all = ok_all and ok
            rounds.append('层%d: ③=%s(期望%s) 翻转=%s(期望%s) %s'
                          % (i + 1, got_word, want_word, got_flip, want_flip,
                             'OK' if ok else '**不一致**'))
        for r in rounds:
            print('        %s' % r)
        chk('C04 ★切层回显 9 次（3 轮）× 3 层：③ 单选选中项与翻转勾选框态都 == 该层持久值',
            ok_all and len(set(a_now)) == 3 and len(set(f_now)) == 2,
            'anchors=%s（3 个不同=%s） flips=%s' % (a_now, len(set(a_now)) == 3, f_now))
        chk('C04b ★切层本身不改写任何持久值（9 次切层后 anchors/flips 逐位不变）',
            anchors(wiz) == a_now and flips(wiz) == f_now,
            'anchors=%s flips=%s' % (anchors(wiz), flips(wiz)))
    finally:
        close_wizard(wiz)


def section_C2():
    """C05~C09：撤销 5 点（保存 / 存皮肤 / 切皮肤 + 顶层键）与档案往返、旧档案保护。"""
    print('\n=== C2 段 · 撤销 5 点的独立复核 + 档案往返 + 旧档案原样保留 ===')
    mod = load_module(SRC, 'rco_C2')
    tmp = os.path.join(TMP, 'c2')
    os.makedirs(tmp, exist_ok=True)
    skins = os.path.join(tmp, 'skins')
    os.makedirs(skins, exist_ok=True)
    figs = c_figs(tmp)
    base = c_layers_cfg(figs, ['right_edge', 'left_edge', 'center'], [False, True, False])

    def anchors(w):
        return [d.get('anchor') for d in w.cfg['layers']]

    def flips(w):
        return [bool(d.get('flip')) for d in w.cfg['layers']]

    def make_layer2_center_flip_true(w):
        """把第 2 层做成 center + flip=True（主层保持 right/False）"""
        c_select(w, 1)
        c_side_by_word(w, '中间').invoke()
        w.root.update_idletasks()
        if c_flip_selected(w) is not True:
            w.chk_flip.invoke()
            w.root.update_idletasks()
        c_select(w, 1)
        return w

    # ---------------- C05 保存通路 + 顶层键 ----------------
    wiz = c_build(mod, base, skins, tmp)
    cap = {}
    try:
        make_layer2_center_flip_true(wiz)
        pre_a, pre_f = anchors(wiz), flips(wiz)
        pre_top = (wiz.cfg.get('side'), bool(wiz.cfg.get('flip_h')))
        print('  [C05 保存通路] 保存前：选中=%s anchors=%s flips=%s 顶层 side=%r flip_h=%r'
              % (getattr(wiz, '_layer_sel', '?'), pre_a, pre_f, pre_top[0], pre_top[1]))
        real_sc, real_sa = mod.save_config, mod.set_autostart
        mod.save_config = lambda c: cap.update({'cfg': c})
        mod.set_autostart = lambda *a, **k: (True, 'stub(t12)')
        try:
            wiz._save_and_start()             # 真实通路（会 destroy 窗口；cfg 引用仍可读）
        finally:
            mod.save_config, mod.set_autostart = real_sc, real_sa
        saved = cap.get('cfg') or {}
        sv_layers = saved.get('layers') or []
        chk('C05 ★撤销点「保存」+ 顶层键：选中第 2 层（%s/flip=%s）保存 → 顶层 side/flip_h 取'
            '**主层**值（%r/%r），各层持久值逐位 == 保存前快照（没被统一、也没把第 2 层顶上去）'
            % (pre_a[1], pre_f[1], pre_top[0], pre_top[1]),
            saved.get('side') == pre_top[0] and bool(saved.get('flip_h')) is bool(pre_top[1])
            and [d.get('anchor') for d in sv_layers] == pre_a
            and [bool(d.get('flip')) for d in sv_layers] == pre_f
            and pre_a[1] != pre_top[0] and pre_f[1] != pre_top[1],
            '落盘 side=%r flip_h=%r layers.anchor=%s layers.flip=%s（保存前 %s / %s；'
            '第 2 层与主层取值本就不同 ⇒ 断言有区分度）'
            % (saved.get('side'), saved.get('flip_h'),
               [d.get('anchor') for d in sv_layers], [bool(d.get('flip')) for d in sv_layers],
               pre_a, pre_f))
        # C05b 判别力：把顶层键改回「读 UI 变量」的口径（side_from_anchor 返回当前选中层的
        # var_side）→ C05 的同一条断言必须 FAIL
        wiz2 = c_build(mod, base, skins, tmp)
        try:
            make_layer2_center_flip_true(wiz2)
            cap2 = {}
            real_sfa = mod.side_from_anchor
            mod.side_from_anchor = lambda anc, _w=wiz2: str(_w.var_side.get())
            real_sc2, real_sa2 = mod.save_config, mod.set_autostart
            mod.save_config = lambda c: cap2.update({'cfg': c})
            mod.set_autostart = lambda *a, **k: (True, 'stub(t12)')
            try:
                wiz2._save_and_start()
            finally:
                mod.side_from_anchor = real_sfa
                mod.save_config, mod.set_autostart = real_sc2, real_sa2
            sv2 = cap2.get('cfg') or {}
            chk('C05b ★判别力：把顶层键改回「读 UI 变量」→ C05 同款断言必须 FAIL（非恒真）',
                not (sv2.get('side') == 'right' and bool(sv2.get('flip_h')) is False
                     and [d.get('anchor') for d in (sv2.get('layers') or [])]
                     == ['right_edge', 'left_edge', 'center']),
                '注入后落盘 side=%r flip_h=%r（= 第 2 层的值，正是要被挡住的那种串层）'
                % (sv2.get('side'), sv2.get('flip_h')))
        finally:
            close_wizard(wiz2)
    finally:
        close_wizard(wiz)

    # ---------------- C06 存皮肤通路 + 顶层键 + 档案往返 ----------------
    wiz = c_build(mod, base, skins, tmp)
    try:
        make_layer2_center_flip_true(wiz)
        pre_a6, pre_f6 = anchors(wiz), flips(wiz)
        pre_top6 = (wiz.cfg.get('side'), bool(wiz.cfg.get('flip_h')))
        old_sk = mod.SKINS_DIR
        mod.SKINS_DIR = skins
        try:
            okv, nm, msg = wiz._save_skin_named('t12-c06', ask_overwrite=False)
            back = mod.find_skin(nm or 't12-c06') or {}
        finally:
            mod.SKINS_DIR = old_sk
        bl = back.get('layers') or []
        chk('C06 ★撤销点「存皮肤」+ 顶层键：第 2 层（%s/flip=%s）时存档案 → 档案顶层 side/flip_h 取'
            '主层值（%r/%r）、各层持久值逐位 == 存档前快照（不被统一）'
            % (pre_a6[1], pre_f6[1], pre_top6[0], pre_top6[1]),
            okv and back.get('side') == pre_top6[0]
            and bool(back.get('flip_h')) is bool(pre_top6[1])
            and [d.get('anchor') for d in bl] == pre_a6
            and [bool(d.get('flip')) for d in bl] == pre_f6
            and pre_a6[1] != pre_top6[0],
            '存皮肤 ok=%s 名=%r 档案 side=%r flip_h=%r anchor=%s flip=%s（存档前 %s / %s）msg=%r'
            % (okv, nm, back.get('side'), back.get('flip_h'),
               [d.get('anchor') for d in bl], [bool(d.get('flip')) for d in bl],
               pre_a6, pre_f6, msg))
        # ---------------- C07 切皮肤通路：各层保持档案值、不被统一 ----------------
        wiz3 = c_build(mod, c_layers_cfg(figs, ['right_edge'] * 3, [False, False, False]),
                       skins, tmp)
        try:
            old_sk = mod.SKINS_DIR
            mod.SKINS_DIR = skins
            try:
                wiz3.skin_var.set(nm or 't12-c06')
                wiz3._apply_skin_to_wizard()
            finally:
                mod.SKINS_DIR = old_sk
            wiz3.root.update_idletasks()
            a3, f3 = anchors(wiz3), flips(wiz3)
            old_sk = mod.SKINS_DIR
            mod.SKINS_DIR = skins
            try:
                arch = mod.find_skin(nm or 't12-c06') or {}
            finally:
                mod.SKINS_DIR = old_sk
            bl_arch = arch.get('layers') or []
            chk('C07 ★撤销点「切皮肤」：套用该档案 → 各层保持档案里**各自**的值（不被统一到某一层）、'
                '顶层 side 随档案主层更新',
                a3 == [d.get('anchor') for d in bl_arch]
                and f3 == [bool(d.get('flip')) for d in bl_arch]
                and wiz3.cfg.get('side') == arch.get('side')
                and len(set(a3)) >= 2,
                '切后 anchors=%s flips=%s（档案 %s / %s）；顶层 side=%r（档案 %r，≥2 种取值=%s）'
                % (a3, f3, [d.get('anchor') for d in bl_arch],
                   [bool(d.get('flip')) for d in bl_arch], wiz3.cfg.get('side'),
                   arch.get('side'), len(set(a3)) >= 2))
            # ---------------- C08 档案往返：再存一次 → 逐层一致 ----------------
            old_sk = mod.SKINS_DIR
            mod.SKINS_DIR = skins
            try:
                okv2, nm2, _ = wiz3._save_skin_named('t12-c08', ask_overwrite=False)
                back2 = mod.find_skin(nm2 or 't12-c08') or {}
            finally:
                mod.SKINS_DIR = old_sk
            bl2 = back2.get('layers') or []
            chk('C08 ★档案往返（存→读→再存→再读）：各层 anchor/flip 与顶层 side/flip_h 逐位一致',
                okv2 and [d.get('anchor') for d in bl2] == a3
                and [bool(d.get('flip')) for d in bl2] == f3
                and back2.get('side') == wiz3.cfg.get('side')
                and bool(back2.get('flip_h')) is bool(wiz3.cfg.get('flip_h')),
                '往返 anchor=%s flip=%s side=%r flip_h=%r'
                % ([d.get('anchor') for d in bl2], [bool(d.get('flip')) for d in bl2],
                   back2.get('side'), back2.get('flip_h')))
        finally:
            close_wizard(wiz3)
    finally:
        close_wizard(wiz)

    # ---------------- C09 旧档案（R11 前的左右夹持）原样保留 ----------------
    wiz = c_build(mod, base, skins, tmp)
    try:
        pre_a, pre_f = anchors(wiz), flips(wiz)
        wiz._update_preview()
        wiz.root.update_idletasks()
        for _ in range(3):                        # 连刷 3 次预览（历史 bug：重绘时静默改写）
            wiz._update_preview()
            wiz.root.update_idletasks()
        a9, f9 = anchors(wiz), flips(wiz)
        top9 = (wiz.cfg.get('side'), bool(wiz.cfg.get('flip_h')))
        chk('C09 ★旧档案（各层 anchor 不同的左右夹持）打开 + 连刷 3 次预览：'
            '逐层持久值一个没被静默改写、顶层键也没被某个子层的值顶替',
            a9 == pre_a and f9 == pre_f and top9 == ('right', False),
            '打开 %s / %s → 刷 3 次后 %s / %s；顶层 side=%r flip_h=%r'
            % (pre_a, pre_f, a9, f9, top9[0], top9[1]))
        chk('C09b ★反面对照：这份档案两次读出的值本身就"各层不同"（不是恒真）',
            len(set(pre_a)) == 3 and len(set(pre_f)) == 2,
            'anchors=%s flips=%s' % (pre_a, pre_f))
    finally:
        close_wizard(wiz)


def c_y_prefix(wiz, ch):
    """窗口里所有以 ch 开头的带字控件的最小屏幕 y（判编号行上下顺序）"""
    ys = []
    for w in c_walk(wiz.root):
        try:
            if w.winfo_class() in ('Label', 'Button', 'Checkbutton', 'Radiobutton') \
                    and str(w.cget('text')).startswith(ch):
                ys.append(int(w.winfo_rooty()))
        except Exception:
            pass
    return min(ys) if ys else None


def section_C3():
    """C10~C13：三态窗口高（两臂对照）/ 控件形态 / 运行时逐层读锚点 / 判别力总验。"""
    print('\n=== C3 段 · 三态高度（两臂对照）+ 控件形态 + 运行时逐层读锚点 + 判别力总验 ===')
    mod = load_module(SRC, 'rco_C3')
    tmp = os.path.join(TMP, 'c3')
    os.makedirs(tmp, exist_ok=True)
    skins = os.path.join(tmp, 'skins')
    os.makedirs(skins, exist_ok=True)
    figs = c_figs(tmp)
    base = c_layers_cfg(figs, ['right_edge', 'left_edge', 'center'], [False, True, False])
    PREV = '74f225f'                     # c38adff 的父提交（N2 之后、N3 之前）= 同场景基线

    def tri(modx, tag):
        """三态量测：折叠（构造完默认）/ 展开 / top_block（预览块）"""
        w = c_build(modx, base, skins, tmp)
        try:
            w.root.update_idletasks()
            w.root.update()
            col = int(w.root.winfo_reqheight())
            tb = int(w.top_block.winfo_reqheight()) if getattr(w, 'top_block', None) else -1
            w._toggle_adv_collapse(False)
            w.root.update_idletasks()
            w.root.update()
            exp = int(w.root.winfo_reqheight())
            w._toggle_adv_collapse(True)
            w.root.update_idletasks()
            w.root.update()
            col2 = int(w.root.winfo_reqheight())
            print('      · %-10s 折叠=%spx 展开=%spx 再折叠=%spx top_block=%spx'
                  % (tag, col, exp, col2, tb))
            return {'col': col, 'exp': exp, 'col2': col2, 'top': tb}
        finally:
            close_wizard(w)

    cur = tri(mod, 'current')
    prev_path = extract_commit_file(PREV, 'rime_char_overlay.py', os.path.join(TMP, 'prev_n3'))
    prev = tri(load_module(prev_path, 'rco_C3_prev'), 'prev %s' % PREV)
    chk('C10 ★三态高度不退化（同场景两臂对照：当前 vs %s）：折叠态 ≤ 基线、展开态 ≤ 基线、'
        '折叠确实生效（展开 − 折叠 ≥ 200px）' % PREV,
        cur['col'] > 0 and cur['col'] <= prev['col'] and cur['exp'] <= prev['exp']
        and (cur['exp'] - cur['col']) >= 200 and cur['col2'] == cur['col'],
        '当前 折叠=%s 展开=%s / 基线%s 折叠=%s 展开=%s（差 %+d / %+d），top_block 当前=%s 基线=%s'
        % (cur['col'], cur['exp'], PREV, prev['col'], prev['exp'],
           cur['col'] - prev['col'], cur['exp'] - prev['exp'], cur['top'], prev['top']))

    # ---------------- C10b 小屏（工作区 728）：折叠态不滚动、按钮行底边在窗内 ----------------
    real_wh = mod.screen_work_area_height
    mod.screen_work_area_height = lambda root=None: 728
    w_small = None
    try:
        w_small = c_build(mod, base, skins, tmp)
        w_small.root.update_idletasks()
        w_small.root.update()
        small_req = int(w_small.root.winfo_reqheight())
        win_h = int(w_small.root.winfo_height())
        win_top = int(w_small.root.winfo_rooty())
        eff_h = win_h if win_h > 1 else small_req          # 未 map 时退回需求高
        scroll = bool(getattr(w_small, '_scroll_needed', False))
        _b, row = find_bottom_row(w_small)
        # 口径修正：winfo_rooty 是**屏幕**坐标（窗口会被居中放置，不能直接与工作区高比）；
        # 要量的是「底部按钮行相对窗口顶的底边 ≤ 窗口实际高」= 窗内可见。
        row_rel = ((int(row.winfo_rooty()) + int(row.winfo_height()) - win_top)
                   if row is not None else -1)
        print('      · 小屏(工作区 728)：折叠态 req_h=%s win_h=%s _scroll_needed=%s '
              '按钮行底边（相对窗口顶）=%s' % (small_req, win_h, scroll, row_rel))
        chk('C10b ★小屏 728：折叠态不滚动（_scroll_needed False）、窗口实际高 ≤ 728、'
            '底部按钮行在窗内可见（相对窗口的底边 ≤ 窗口高）',
            scroll is False and 0 < eff_h <= 728 and 0 < row_rel <= eff_h,
            'req_h=%s win_h=%s(取用 %s) scroll=%s 按钮行底边(窗内)=%s（工作区 728）'
            % (small_req, win_h, eff_h, scroll, row_rel))
    finally:
        mod.screen_work_area_height = real_wh
        if w_small is not None:
            close_wizard(w_small)

    # ---------------- C11 控件形态：③ 只一处 + 形态 + 文案 ----------------
    wiz = c_build(mod, base, skins, tmp)
    try:
        wiz._toggle_adv_collapse(False)
        wiz.root.update_idletasks()
        wiz.root.update()
        rbs = c_side_radios(wiz)
        flip_chks = [x for x in c_walk(wiz.root)
                     if x.winfo_class() == 'Checkbutton'
                     and str(x.cget('variable')) == str(wiz.var_flip)]
        lay_rbs = [x for x in c_walk(wiz.root)
                   if x.winfo_class() == 'Radiobutton'
                   and str(x.cget('variable')) == str(wiz.var_layer_anchor)]
        side_v, flip_v = str(wiz.var_side), str(wiz.var_flip)
        # 「形态仍是单选组 + 勾选框」：① 该行容器内只允许 Label/Radiobutton/Checkbutton/Frame；
        # ② 不允许下拉框/组合框绑这两个变量（Listbox/Menu 没有 -variable，用容器类集合兜住）
        weird = []
        for x in c_walk(wiz.root):
            if x.winfo_class() not in ('OptionMenu', 'TCombobox'):
                continue
            try:
                if str(x.cget('variable')) in (side_v, flip_v):
                    weird.append(x.winfo_class())
            except Exception:
                pass
        row_side = rbs[0].master if rbs else None
        row_kinds = sorted({x.winfo_class() for x in c_walk(row_side)}) \
            if row_side is not None else []
        y2, y3, y4 = c_y_prefix(wiz, '②'), c_y_prefix(wiz, '③'), c_y_prefix(wiz, '④')
        t_side = str(wiz.lbl_side_title.cget('text'))
        t_flip = str(wiz.chk_flip.cget('text'))
        c_select(wiz, 1)
        t_side2 = str(wiz.lbl_side_title.cget('text'))
        t_flip2 = str(wiz.chk_flip.cget('text'))
        c_select(wiz, 2)
        t_side3 = str(wiz.lbl_side_title.cget('text'))
        print('      · ③ 单选=%d 个（图层区绑 var_layer_anchor 的单选=%d）；编号行 y：②=%s ③=%s ④=%s'
              % (len(rbs), len(lay_rbs), y2, y3, y4))
        print('      · 文案：主层 ③=%r 翻转=%r / 第 2 层 ③=%r 翻转=%r / 第 3 层 ③=%r'
              % (t_side, t_flip, t_side2, t_flip2, t_side3))
        chk('C11 ★控件形态：③ 只出现一处（绑 var_side 的恰 3 个单选；图层区无第二套 = 0 个）、'
            '③ 在 ② 与 ④ 之间、形态仍是单选组 + 勾选框（③ 所在行内只有 Label/Radiobutton/'
            'Checkbutton/Frame，且无下拉框/组合框绑这两个变量）',
            len(rbs) == 3 and len(flip_chks) == 1 and len(lay_rbs) == 0 and not weird
            and set(row_kinds) <= {'Label', 'Radiobutton', 'Checkbutton', 'Frame'}
            and None not in (y2, y3, y4) and y2 < y3 < y4,
            '③单选=%d 翻转勾选=%d 图层区单选=%d 异常形态=%s ③行控件类=%s y(②<③<④)=%s<%s<%s'
            % (len(rbs), len(flip_chks), len(lay_rbs), weird or '无', row_kinds, y2, y3, y4))
        chk('C11b ★两控件文案标出「第 N 层」并随选中层更新（主层/第 2 层/第 3 层各读一次），'
            '且都不含「所有图层」字样',
            ('第 1 层' in t_side and '第 2 层' in t_side2 and '第 3 层' in t_side3
             and '第 1 层' in t_flip and '第 2 层' in t_flip2)
            and ('所有图层' not in t_side and '所有图层' not in t_side2
                 and '所有图层' not in t_side3 and '所有图层' not in t_flip
                 and '所有图层' not in t_flip2),
            '③ 文案=%r/%r/%r 翻转=%r/%r' % (t_side, t_side2, t_side3, t_flip, t_flip2))

        # ---------------- C12 运行时逐层读锚点（行为对照，不复算公式） ----------------
        cfg_a = c_layers_cfg(figs, ['right_edge', 'center', 'right_edge'], [False, False, False])
        cfg_b = c_layers_cfg(figs, ['right_edge', 'left_edge', 'right_edge'], [False, False, False])

        def plan_x(cfgx):
            rl = mod.resolve_layers(dict(cfgx))
            dims = []
            from PIL import Image
            for ld in rl:
                with Image.open(ld['image']) as im:
                    dims.append((im.size[0], im.size[1]))
            wx, wy, ww, wh, pl = mod.plan_layer_layout(rl, dims, (0, 0, 460, 84))
            return {p[0]: wx + p[1] for p in pl}, [d.get('anchor') for d in rl]

        xa, aa = plan_x(cfg_a)
        xb, ab = plan_x(cfg_b)
        only1 = all(xa[j] == xb[j] for j in (0, 2))
        chk('C12 ★运行时逐层读锚点（on-layer anchor 真的决定落点，不是全层同一个）：'
            '只把 layers[1].anchor 从 center 改成 left_edge → 只有第 2 层落点左移、层 0/2 不动',
            aa == ['right_edge', 'center', 'right_edge'] and ab[1] == 'left_edge'
            and only1 and xb[1] < xa[1],
            'anchors %s→%s；x %s→%s（第 2 层 %s→%s，左移=%s）'
            % (aa, ab, xa, xb, xa[1], xb[1], xb[1] < xa[1]))

        # ---------------- C13 判别力总验：打桩回退成「写全部层」→ C01 判据必须 FAIL ----------------
        c_select(wiz, 1)
        before = [d.get('anchor') for d in wiz.cfg['layers']]
        real_set = wiz._layer_set_params

        def _old_all(i, scale=None, offset_x=None, offset_y=None, flip=None, anchor=None):
            r = real_set(i, scale=scale, offset_x=offset_x, offset_y=offset_y,
                         flip=flip, anchor=anchor)
            if anchor is not None:
                for d in wiz.cfg['layers']:
                    d['anchor'] = wiz._layer_anchor_at(0)
            if flip is not None:
                for d in wiz.cfg['layers']:
                    d['flip'] = bool(wiz.cfg.get('flip_h', False))
            return r

        wiz._layer_set_params = _old_all
        try:
            c_side_by_word(wiz, '中间').invoke()
            wiz.root.update_idletasks()
        finally:
            wiz._layer_set_params = real_set
        aft = [d.get('anchor') for d in wiz.cfg['layers']]
        exp = list(before)
        exp[1] = 'center'
        chk('C13 ★判别力总验：把「只写当前层」打桩回退成「写全部层」→ C01 同款判据必须 FAIL（非恒真）',
            aft != exp,
            '回退前=%s 注入后=%s（期望若只改第 2 层应为 %s）' % (before, aft, exp))
    finally:
        close_wizard(wiz)


def main():
    which = [a.upper() for a in sys.argv[1:]] or ['A', 'B', 'C']
    print('B_test_indep_batch4.py ｜ 第四轮独立探针 ｜ tempdir=%s' % TMP)
    print('被测源码: %s' % SRC)
    if 'A' in which:
        section_A()
    if 'B' in which:
        section_B()
    if 'C' in which:
        section_C()
        section_C2()
        section_C3()
    print('\n=== RESULT: %s（%d 条 FAIL）===' % ('FAIL' if FAILED else 'PASS', len(FAILED)))
    if FAILED:
        for t, d in FAILED:
            print('   FAIL: %s | %s' % (t, d))
    return 1 if FAILED else 0


if __name__ == '__main__':
    sys.exit(main())
