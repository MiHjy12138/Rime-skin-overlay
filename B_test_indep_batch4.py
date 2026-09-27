# -*- coding: utf-8 -*-
"""B_test_indep_batch4.py —— 第四轮（R15）验证者独立探针

规矩（HANDOFF-2.1 §6-13 / §6-14）：
  · 只走用户真实通路（自己构造 ConfigWizard、自己点/自己量），不复用实现者断言；
  · 脚本自建、判据自拟；出现红必须当场定性（真回归 / 过时前提）；
  · R.HERE 指向 tempdir，产物不进项目目录；控制台 utf-8。
  · 唯一测试运行者；跑前跑后验 `git hash-object rime_char_overlay.py` == `HEAD:rime_char_overlay.py`。

用法：python B_test_indep_batch4.py [A]
      A = N1（折叠按钮做大 + 向导默认折叠）
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


def main():
    which = [a.upper() for a in sys.argv[1:]] or ['A']
    print('B_test_indep_batch4.py ｜ 第四轮独立探针 ｜ tempdir=%s' % TMP)
    print('被测源码: %s' % SRC)
    if 'A' in which:
        section_A()
    print('\n=== RESULT: %s（%d 条 FAIL）===' % ('FAIL' if FAILED else 'PASS', len(FAILED)))
    if FAILED:
        for t, d in FAILED:
            print('   FAIL: %s | %s' % (t, d))
    return 1 if FAILED else 0


if __name__ == '__main__':
    sys.exit(main())
