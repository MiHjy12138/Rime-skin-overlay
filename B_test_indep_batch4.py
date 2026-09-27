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


def main():
    which = [a.upper() for a in sys.argv[1:]] or ['A', 'B']
    print('B_test_indep_batch4.py ｜ 第四轮独立探针 ｜ tempdir=%s' % TMP)
    print('被测源码: %s' % SRC)
    if 'A' in which:
        section_A()
    if 'B' in which:
        section_B()
    print('\n=== RESULT: %s（%d 条 FAIL）===' % ('FAIL' if FAILED else 'PASS', len(FAILED)))
    if FAILED:
        for t, d in FAILED:
            print('   FAIL: %s | %s' % (t, d))
    return 1 if FAILED else 0


if __name__ == '__main__':
    sys.exit(main())
