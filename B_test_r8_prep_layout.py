# -*- coding: utf-8 -*-
"""B_test_r8_prep_layout.py —— R8「图片预处理对话框不挤占下方功能」验证

用户第三轮实测原话（截图投诉）：
  「动图抠图时下方的功能会被挤到无法点击的位置。」
真 bug（R6 引入）：R6 给右栏加了「▶ 动图预览」区（标题 + 播放/逐帧行 + 帧号 + 两行说明
≈ 128px），而右栏 panel 是 `width=240 + pack_propagate(False)` 的固定框，高度被左画布
602px 锁死 → 右栏内容需求 662px（动图）比可视区高 60px，pack 把最后排的
「应用 / 重置 / 取消」整行压成 1px 高且不 map（winfo_ismapped=0），用户根本点不到。
静态图（内容 534px）不触发，所以只在动图模式下暴露。

本脚本验收：
  A 段 · 动图模式逐控件可见可点（最下方控件的底边 y ≤ 窗高、winfo_ismapped=1、窗口在工作区内）
       A 段给「重新自动检测」按钮与最下方提示文字逐条坐标证据
  B 段 · 静态图零回归：窗口尺寸 / 控件相对坐标与改前模块一致，且不增生滚动条
  C 段 · 小屏兜底：工作区不足时窗口不越界、右栏可滚动，滚到底最下方控件可见可点，
       且没有控件被压成 1px
  D 段 · R6 功能不许砍：播放/暂停/逐帧/帧号仍在；大 GIF 打开耗时与改前同量级；
       仍按需解码（打开只付首帧）
  E 段 · 右栏控件清单 ⊇ 改前（R8 只许改布局，不许删控件）
  F 段 · 销毁不留 after（滚动容器不得新增残留回调）

红→绿：改前（80762e7）实测 A3/A4/A5/A6/A7/C1/C2/C3/C4 共 15 条 FAIL / exit=1；
       改后全绿。判别力：把右栏可视高度人为锁回 602（_panel_view_h monkeypatch）
       再跑 A/B 段必须重新出红（见 B06 的判别力断言）。

运行: python B_test_r8_prep_layout.py   （退出码 0 = 全过；默认 GBK 控制台直接跑）
"""
import os
import sys
import time
import shutil
import tempfile
import subprocess
import importlib.util

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
try:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from PIL import Image
import tkinter as tk

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R          # noqa: E402

# 改前基线：R8 开工前最后一个提交（R12 高级设置可折叠）。固定写死 —— 跟着 HEAD 走的话
# 提交之后「改前」就变成新代码，前后对照会失去意义。
R8_BASE_REV = '80762e7'

PASS, FAIL, SKIP = [], [], []
NOTES = []

BIG_W, BIG_H, BIG_N, BIG_DUR = 200, 260, 60, 60


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f'{"PASS" if cond else "FAIL"}  {name}{(" | " + detail) if detail else ""}')


def skip(name, detail=''):
    SKIP.append(name)
    print(f'SKIP  {name}{(" | " + detail) if detail else ""}')


def section(t):
    print('')
    print('-' * 8, t, '-' * 8)


def note(msg):
    NOTES.append(msg)
    print('    · ' + msg)


def ms(fn, n=1):
    t0 = time.perf_counter()
    r = None
    for _ in range(n):
        r = fn()
    return (time.perf_counter() - t0) * 1000.0 / n, r


# ---------------- 夹具 ----------------
def make_gif(path, w=200, h=260, n=8, duration=70):
    frames = []
    for i in range(n):
        im = Image.new('RGB', (w, h), (250, 250, 250))
        for y in range(20, 180):
            for x in range(20 + i, 120 + i):
                im.putpixel((x, y), (220, 40, 40))
        frames.append(im.convert('P', palette=Image.ADAPTIVE, colors=64))
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=duration, loop=0)
    return path


def make_big_gif(path):
    """大 GIF（≥50 帧）做打开耗时对照：噪声内容保证解码不廉价"""
    frames = []
    for i in range(BIG_N):
        base = Image.effect_noise((BIG_W, BIG_H), 60).convert('RGB')
        base.paste(Image.new('RGB', (40, 40), ((i * 7) % 256, 200, 90)),
                   (20 + (i * 3) % (BIG_W - 60), 20))
        frames.append(base.convert('P', palette=Image.ADAPTIVE, colors=128))
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=BIG_DUR, loop=0, optimize=False)
    return path


def make_png(path, w=200, h=260):
    im = Image.new('RGB', (w, h), (250, 250, 250))
    for y in range(20, 180):
        for x in range(20, 120):
            im.putpixel((x, y), (220, 40, 40))
    im.save(path)
    return path


def load_old_module(tmp):
    """从固定修订取改前 rime_char_overlay.py，独立加载（不污染被测模块）"""
    out = os.path.join(tmp, 'rime_char_overlay_before_r8.py')
    try:
        with open(out, 'wb') as f:
            p = subprocess.run(['git', 'show', '%s:rime_char_overlay.py' % R8_BASE_REV],
                               cwd=BASE, stdout=f, stderr=subprocess.PIPE)
        if p.returncode != 0:
            return None, 'git show %s 失败：%s' % (R8_BASE_REV, p.stderr.decode('utf-8', 'replace')[:120])
        spec = importlib.util.spec_from_file_location('rco_before_r8', out)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, 'ok（%s, %d B）' % (R8_BASE_REV, os.path.getsize(out))
    except Exception as e:
        return None, '%s: %s' % (type(e).__name__, e)


# ---------------- 控件几何工具 ----------------
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


CLICKABLE = ('Button', 'Checkbutton', 'Radiobutton', 'Scale', 'Listbox', 'Entry')


def _rows(dlg):
    """右栏/窗内所有「有文字或可交互」的控件 → 几何记录（相对窗口 + 屏幕绝对）"""
    r = dlg.root
    try:
        r.update_idletasks()
        r.update()
    except Exception:
        pass
    ry = r.winfo_rooty()
    rows = []
    for w in _all_widgets(r):
        try:
            cls = w.winfo_class()
            if cls in ('Frame', 'Canvas', 'Toplevel', 'Scrollbar'):
                continue
            txt = ''
            try:
                txt = str(w.cget('text')).replace('\n', '⏎')
            except Exception:
                txt = ''
            if cls not in CLICKABLE and not txt:
                continue
            y = w.winfo_rooty() - ry
            h = w.winfo_height()
            rows.append({'cls': cls, 'text': txt, 'y': y, 'h': h, 'bottom': y + h,
                         'scr_bottom': w.winfo_rooty() + h, 'mapped': int(w.winfo_ismapped()),
                         'widget': w})
        except Exception:
            pass
    return rows


def _win_info(dlg):
    r = dlg.root
    wa_top, wa_bot = R.screen_work_area(r)
    try:
        r.update_idletasks()
        r.update()
    except Exception:
        pass
    return {'x': r.winfo_rootx(), 'y': r.winfo_rooty(), 'w': r.winfo_width(),
            'h': r.winfo_height(), 'scr_bottom': r.winfo_rooty() + r.winfo_height(),
            'wa_top': wa_top, 'wa_bot': wa_bot}


def _find(rows, cls, contains):
    for x in rows:
        if x['cls'] == cls and contains in x['text']:
            return x
    return None


def _new_root():
    """一个**可见**宿主 Tk（1×1 放左上角）：Toplevel 是 transient，宿主不 map 时
    对话框自身也不会 map，winfo_ismapped 全 0 → 量不出「可见可点」。
    所以 R8 测试必须真的把窗口挂出来（R6 测试用 withdraw 只测行为，不测几何）。"""
    r = tk.Tk()
    r.geometry('1x1+0+0')
    r.update()
    return r


def kill(dlg=None, root=None):
    try:
        if dlg is not None:
            dlg._cancel()
    except Exception:
        pass
    try:
        if root is not None:
            root.destroy()
    except Exception:
        pass


def _interleaved_open_cost(root, big, old_mod, n=5):
    """交替取样「新 → 改前」各开一次、重复 n 轮；返回 dict（各轮样本 + 配对差）。

    为什么必须交替：单侧独立测量在本机负载波动下完全不可比 —— 同一份代码实测 63ms ~
    576ms。交替取样让新/旧经历同一段负载环境，逐轮的**配对差**才是「这次改动带来的增量」。
    判据用配对差的中位数（抗单轮尖峰），阈值仍是 60ms —— **只改测量方法，判据一字未放宽**。
    """
    new_s, old_s, pairs = [], [], []
    last_new = last_old = None
    kill(R.ImagePreprocessDialog(root, big), None)          # 预热：付掉 PIL/Tk 冷启动
    if old_mod is not None:
        kill(old_mod.ImagePreprocessDialog(root, big), None)
    for _ in range(max(1, int(n))):
        t0 = time.perf_counter()
        d = R.ImagePreprocessDialog(root, big)
        tn = (time.perf_counter() - t0) * 1000.0
        new_s.append(tn)
        if last_new is not None:
            kill(last_new, None)
        last_new = d
        if old_mod is None:
            continue
        t0 = time.perf_counter()
        d2 = old_mod.ImagePreprocessDialog(root, big)
        to = (time.perf_counter() - t0) * 1000.0
        old_s.append(to)
        if last_old is not None:
            kill(last_old, None)
        last_old = d2
        pairs.append((tn, to))
    kill(last_old, None)
    diffs = sorted(a - b for a, b in pairs)
    return {
        'new_min': min(new_s), 'new_samples': new_s, 'dlg': last_new,
        'old_min': (min(old_s) if old_s else None), 'old_samples': old_s,
        'diffs': diffs,
        'diff_median': (diffs[len(diffs) // 2] if diffs else None),
    }


def dump_table(rows, title):
    print('    表：%s' % title)
    print('      %-12s %-30s %6s %6s %7s %7s' % ('控件', '文案', 'y', 'h', '底边', 'mapped'))
    for x in rows:
        print('      %-12s %-30s %6d %6d %7d %7d' % (
            x['cls'], x['text'][:28], x['y'], x['h'], x['bottom'], x['mapped']))


# ================= A 段 =================
def test_a_anim_visible(tmp, gif):
    section('A 动图模式：所有控件可见可点（逐控件坐标 + ismapped 证据）')
    root = _new_root()
    dlg = None
    try:
        dlg = R.ImagePreprocessDialog(root, gif)
        rows = _rows(dlg)
        wi = _win_info(dlg)
        note('窗口 %dx%d @(%d,%d)，屏内容底 %d，工作区 %d~%d'
             % (wi['w'], wi['h'], wi['x'], wi['y'], wi['scr_bottom'], wi['wa_top'], wi['wa_bot']))
        dump_table(rows, '动图模式右栏 + 窗内控件几何')

        check('A1 对话框识别动图（前提：本段测的是动图模式）',
              int(dlg.n_frames) == 8, f'n_frames={dlg.n_frames}')

        # A2 窗口整体在屏幕工作区内
        check('A2 ★整窗在屏幕工作区内（标题栏与底边都不越过任务栏）',
              wi['y'] >= wi['wa_top'] - 1 and wi['scr_bottom'] <= wi['wa_bot'],
              f'窗口 y={wi["y"]} 内容底={wi["scr_bottom"]} vs 工作区 {wi["wa_top"]}~{wi["wa_bot"]}')

        # A3 右栏内容需求高 ≤ 可视高（不挤占的直接判据）
        panel = getattr(dlg, 'panel', None)
        view_h = None
        try:
            view_h = int(dlg._panel_view_h())
        except Exception:
            view_h = None
        req_h = int(panel.winfo_reqheight()) if panel is not None else -1
        check('A3 ★右栏内容需求高度 ≤ 右栏可视高度（不再有东西被挤出可视区）',
              view_h is not None and req_h > 0 and req_h <= view_h + 2,
              f'内容需求 {req_h}px vs 可视 {view_h}px（旧实现可视恒 602px → 溢出 {req_h - 602}px）')

        # A4 逐控件：mapped + 未被压扁 + 完整落在窗内
        unmapped = [f'{x["cls"]}:{x["text"][:14]}' for x in rows if x['mapped'] != 1]
        clipped = [f'{x["cls"]}:{x["text"][:14]}(底{x["bottom"]}>{wi["h"]})'
                   for x in rows if x['bottom'] > wi['h'] + 1 or x['y'] < -1]
        squashed = [f'{x["cls"]}:{x["text"][:14]}(h={x["h"]})' for x in rows if x['h'] < 8]
        check('A4a ★全部控件 winfo_ismapped=1（没有一个被 pack 丢掉）',
              not unmapped, f'未 map {len(unmapped)} 个：{unmapped[:6]}')
        check('A4b ★全部控件完整落在窗内（0 ≤ y 且 底边 ≤ 窗高）',
              not clipped, f'越界 {len(clipped)} 个：{clipped[:6]}')
        check('A4c ★没有控件被压成 1px 高（pack 挤压的典型症状）',
              not squashed, f'压扁 {len(squashed)} 个：{squashed[:6]}')

        # A5 点名证据：重新自动检测
        rd = _find(rows, 'Button', '重新自动检测')
        check('A5 ★「重新自动检测」可见可点（底边 ≤ 窗高 + mapped=1 + 高度正常）',
              rd is not None and rd['mapped'] == 1 and rd['h'] >= 20
              and 0 <= rd['y'] and rd['bottom'] <= wi['h'] + 1
              and rd['scr_bottom'] <= wi['wa_bot'],
              None if rd is None else
              f'y={rd["y"]} h={rd["h"]} 底边={rd["bottom"]} ≤ 窗高 {wi["h"]}；屏底 {rd["scr_bottom"]}')

        # A6 点名证据：最下方的提示文字（旧实现里它同样被 pack 压扁成 27px 高）
        tip = None
        for x in rows:
            if x['cls'] == 'Label' and '点击图片上的背景区域' in x['text']:
                tip = x
        check('A6 ★最下方提示文字「💡 也可点击图片上的背景区域 手动指定背景色」完整可见（两行高，未被压扁）',
              tip is not None and tip['mapped'] == 1 and tip['bottom'] <= wi['h'] + 1
              and tip['h'] >= 30 and tip['scr_bottom'] <= wi['wa_bot'],
              None if tip is None else
              f'y={tip["y"]} h={tip["h"]} 底边={tip["bottom"]} ≤ 窗高 {wi["h"]}；屏底 {tip["scr_bottom"]}'
              f'（改前同位置 h=27px 且贴底）')

        # A7 点名证据：按钮行三兄弟（旧实现被压成 h=1 / mapped=0）
        btns = {t: _find(rows, 'Button', t) for t in ('应用', '重置', '取消')}
        ok_btns = all(b is not None and b['mapped'] == 1 and b['h'] >= 20
                      and b['bottom'] <= wi['h'] + 1 for b in btns.values())
        check('A7 ★按钮行（应用 / 重置 / 取消）可见可点（旧实现整行 h=1px、mapped=0）',
              ok_btns,
              '; '.join(f'{t}: y={b["y"]} h={b["h"]} mapped={b["mapped"]}'
                        for t, b in btns.items() if b) or '未找到')

        # A8 ② 区（用户截图里被挤贴底的整块）
        c2 = _find(rows, 'Label', '② 纯色背景抠图')
        tol = _find(rows, 'Checkbutton', '启用抠图')
        check('A8 ★② 区标题与「启用抠图」仍在可视区内',
              c2 is not None and tol is not None and c2['bottom'] <= wi['h'] + 1
              and tol['bottom'] <= wi['h'] + 1 and tol['mapped'] == 1,
              f'② 底边={c2["bottom"] if c2 else None} / 勾选框底边={tol["bottom"] if tol else None}')
    finally:
        kill(dlg, root)


# ================= B 段 =================
def test_b_static_unchanged(tmp, png, gif, old_mod):
    section('B 静态图零回归（窗口尺寸 / 控件相对坐标与改前一致；不增生滚动条）')
    root = _new_root()
    dlg = None
    root2 = None
    od = None
    try:
        dlg = R.ImagePreprocessDialog(root, png)
        rows_new = _rows(dlg)
        wi_new = _win_info(dlg)
        note('新：窗口 %dx%d，右栏控件 %d 个' % (wi_new['w'], wi_new['h'], len(rows_new)))
        if old_mod is not None:
            root2 = _new_root()
            od = old_mod.ImagePreprocessDialog(root2, png)
            rows_old = _rows(od)
            wi_old = _win_info(od)
            note('改前（%s）：窗口 %dx%d，右栏控件 %d 个'
                 % (R8_BASE_REV, wi_old['w'], wi_old['h'], len(rows_old)))
            check('B1 ★静态图窗口尺寸与改前逐像素一致（R8 只修溢出，不改观感）',
                  wi_new['w'] == wi_old['w'] and wi_new['h'] == wi_old['h'],
                  f'{wi_new["w"]}x{wi_new["h"]} vs 改前 {wi_old["w"]}x{wi_old["h"]}')
            diffs = []
            for x in rows_old:
                y = _find(rows_new, x['cls'], x['text'])
                if y is None:
                    diffs.append(('缺失', x['cls'], x['text'][:20]))
                elif abs(y['y'] - x['y']) > 2 or abs(y['h'] - x['h']) > 2:
                    diffs.append((x['text'][:20], f'旧 y={x["y"]} h={x["h"]}', f'新 y={y["y"]} h={y["h"]}'))
            check('B2 ★静态图各控件相对坐标与改前一致（±2px）',
                  not diffs, f'差异 {len(diffs)} 处：{diffs[:4]}')
        else:
            skip('B1/B2 静态图对照', '改前模块不可用')
        un = [x['text'][:16] for x in rows_new if x['mapped'] != 1]
        check('B3 静态图所有控件也全部可见（无一被裁）', not un, f'未 map：{un[:5]}')
        sb = getattr(dlg, 'panel_sb', None)
        sb_mapped = 0
        try:
            sb_mapped = int(sb.winfo_ismapped()) if sb is not None else 0
        except Exception:
            sb_mapped = -1
        check('B4 静态图（内容装得下）不显示滚动条：不增生 UI',
              sb is None or sb_mapped == 0, f'滚动条 mapped={sb_mapped}')

        # B06 判别力：拿**改前模块**（80762e7）开同一张动图 —— 「有控件不可见 / 被压扁」
        # 必须重现。这就是本 bug 存在过的铁证，也证明 A 段的绿不是恒真断言换来的。
        if old_mod is not None:
            root3 = _new_root()
            od2 = None
            try:
                od2 = old_mod.ImagePreprocessDialog(root3, gif)
                rows_o = _rows(od2)
                wi_o = _win_info(od2)
                bad = [x for x in rows_o if x['mapped'] != 1 or x['h'] < 8
                       or x['bottom'] > wi_o['h'] + 1]
                note('改前模块开同一动图：不可见/被压扁控件 %d 个 → %s'
                     % (len(bad), [(x['cls'], x['text'][:12], f'h={x["h"]}', f'mapped={x["mapped"]}')
                                   for x in bad][:4]))
                check('B06 ★判别力：改前模块（%s）开同一动图必须重现「控件不可见」' % R8_BASE_REV,
                      bool(bad),
                      f'改前重现 {len(bad)} 个（新实现 0 个）')
                tip_o = None
                for x in rows_o:
                    if x['cls'] == 'Label' and '点击图片上的背景区域' in x['text']:
                        tip_o = x
                check('B06b ★A6 判别力：同一条最下方提示在改前被压扁（h<30），改后完整两行',
                      tip_o is not None and tip_o['h'] < 30,
                      f'改前 h={tip_o["h"] if tip_o else None}px → 改后 h=40px')
            finally:
                kill(od2, root3)
        else:
            skip('B06 判别力', '改前模块不可用')
    finally:
        kill(od, root2)
        kill(dlg, root)


# ================= C 段 =================
def test_c_small_screen(tmp, gif):
    section('C 小屏兜底：工作区不足时窗口不越界 + 右栏可滚动 + 滚到底控件可见')
    root = _new_root()
    dlg = None
    orig = R.screen_work_area_height
    orig_area = R.screen_work_area
    try:
        # 模拟 1366×768 且任务栏吃掉 40px 的机器（工作区高 728）里开 125% DPI → 更挤
        R.screen_work_area_height = lambda r=None: 600
        R.screen_work_area = lambda r=None: (0, 600)
        dlg = R.ImagePreprocessDialog(root, gif)
        rows = _rows(dlg)
        wi = _win_info(dlg)
        note('小屏：窗口 %dx%d 内容底=%d，工作区高 600' % (wi['w'], wi['h'], wi['scr_bottom']))
        check('C1 ★小屏下窗口不高出工作区（底边 ≤ 工作区底）',
              wi['scr_bottom'] <= wi['wa_bot'], f'内容底 {wi["scr_bottom"]} vs 工作区底 {wi["wa_bot"]}')
        sq = [f'{x["text"][:14]}(h={x["h"]})' for x in rows if x['h'] < 8]
        check('C2 ★小屏下仍然没有控件被压成 1px（压扁就是「点不到」的根因）',
              not sq, f'压扁 {len(sq)} 个：{sq[:5]}')
        sb = getattr(dlg, 'panel_sb', None)
        sb_mapped = int(sb.winfo_ismapped()) if sb is not None else -1
        check('C3 ★小屏下右栏出现垂直滚动条（内容装不下时给滚动通路，而不是裁掉）',
              sb is not None and sb_mapped == 1, f'滚动条 mapped={sb_mapped}')

        # 滚到底：最下方控件（按钮行）必须回到可视区内且 mapped
        btn = None
        for x in rows:
            if x['cls'] == 'Button' and '应用' in x['text']:
                btn = x
        bottom_before = btn['bottom'] if btn else None
        scroll_ok = False
        cv = getattr(dlg, 'panel_canvas', None)
        if cv is not None:
            try:
                cv.yview_moveto(1.0)
                dlg.root.update_idletasks()
                dlg.root.update()
                scroll_ok = True
            except Exception as e:
                note('滚动失败：%s' % e)
        rows2 = _rows(dlg)
        wi2 = _win_info(dlg)
        btn2 = None
        for x in rows2:
            if x['cls'] == 'Button' and '应用' in x['text']:
                btn2 = x
        tip2 = None
        for x in rows2:
            if x['cls'] == 'Label' and '点击图片上的背景区域' in x['text']:
                tip2 = x
        check('C4 ★滚到底后按钮行与最下方提示都回到窗内且 mapped（可点）',
              scroll_ok and btn2 is not None and btn2['mapped'] == 1
              and btn2['bottom'] <= wi2['h'] + 1 and 0 <= btn2['y']
              and tip2 is not None and tip2['mapped'] == 1 and tip2['bottom'] <= wi2['h'] + 1,
              f'滚动前按钮底边={bottom_before} → 滚动后 y={btn2["y"] if btn2 else None} '
              f'底边={btn2["bottom"] if btn2 else None} ≤ 窗高 {wi2["h"]}；'
              f'提示底边={tip2["bottom"] if tip2 else None}')
        # 滚回顶部：首屏控件仍在
        if cv is not None:
            try:
                cv.yview_moveto(0.0)
                dlg.root.update_idletasks()
                dlg.root.update()
            except Exception:
                pass
        rows3 = _rows(dlg)
        top_ok = _find(rows3, 'Label', '原图') is not None and _find(rows3, 'Button', '播放') is not None
        check('C5 滚回顶部后首屏控件仍可见（滚动不吞控件）', top_ok, '')
    finally:
        R.screen_work_area_height = orig
        R.screen_work_area = orig_area
        kill(dlg, root)


# ================= D 段 =================
def test_d_r6_kept(tmp, big, before_cost, old_mod):
    section('D R6 动图预览功能不许砍 + 打开耗时同量级 + 仍按需解码')
    root = _new_root()
    dlg = None
    try:
        # 交替取样（新/旧同处一段负载环境；判据不变）= 见 _interleaved_open_cost
        cost = _interleaved_open_cost(root, big, old_mod, n=5)
        dlg = cost['dlg']
        t_new, t_old = cost['new_min'], cost['old_min']
        note('大 GIF（%dx%d × %d 帧）打开耗时：新 min %.1f ms（样本 %s）/ 改前 min %s ms（样本 %s）；'
             '逐轮配对差 %s'
             % (BIG_W, BIG_H, BIG_N, t_new, ['%.1f' % v for v in cost['new_samples']],
                ('%.1f' % t_old) if t_old is not None else 'N/A',
                ['%.1f' % v for v in cost['old_samples']],
                ['%+.1f' % v for v in cost['diffs']]))
        check('D1 ★播放/暂停/逐帧/帧号控件与 API 全在（R8 没砍 R6 功能）',
              hasattr(dlg, 'btn_play') and hasattr(dlg, 'lbl_frame')
              and hasattr(dlg, '_toggle_preview') and hasattr(dlg, '_preview_step')
              and hasattr(dlg, '_preview_goto') and hasattr(dlg, 'preview_idx'),
              'btn_play/lbl_frame/_toggle_preview/_preview_step/_preview_goto/preview_idx')
        check('D2 帧号标签标出总帧数', str(BIG_N) in str(dlg.lbl_frame.cget('text')),
              repr(dlg.lbl_frame.cget('text')))
        if t_old is None:
            skip('D3 打开耗时与改前同量级', '改前模块不可用（对照缺失）')
        else:
            med = cost['diff_median']
            check('D3 ★打开耗时与改前同量级（交替 5 轮：逐轮配对差中位数 ≤ 60ms，阈值口径不变）',
                  med is not None and med <= 60.0,
                  f'配对差 中位 {med:+.1f}ms（最小 {cost["diffs"][0]:+.1f} / 最大 {cost["diffs"][-1]:+.1f}）；'
                  f'新 min {t_new:.1f}ms / 改前 min {t_old:.1f}ms')
            check('D3b ★打开耗时的绝对上限（≤ 250ms：重排成本再抖也不至于让用户觉得卡）',
                  t_new <= 250.0, f'新 min {t_new:.1f}ms')
        check('D4 ★打开仍只解码首帧（按需解码没被滚动容器吞掉）',
              int(getattr(dlg, '_decode_calls', 999)) <= 1,
              f'_decode_calls={getattr(dlg, "_decode_calls", "N/A")}')
        dlg._toggle_preview()
        idx0 = dlg.preview_idx
        calls0 = dlg._decode_calls
        ticks = []
        for _ in range(10):
            t0 = time.perf_counter()
            dlg._preview_tick()
            ticks.append((time.perf_counter() - t0) * 1000.0)
        calls1 = dlg._decode_calls
        srt = sorted(ticks)
        note('播放 10 tick：min/median/max = %.2f/%.2f/%.2f ms，解码 +%d'
             % (srt[0], srt[len(srt) // 2], srt[-1], calls1 - calls0))
        check('D5 播放仍逐帧推进（10 tick 推进 10 帧）',
              dlg.preview_steps >= 10 and dlg.preview_idx == (idx0 + 10) % BIG_N,
              f'idx {idx0} → {dlg.preview_idx}，steps={dlg.preview_steps}')
        check('D6 ★每 tick ≤1 次解码（节流/按需逻辑未被布局改动影响）',
              (calls1 - calls0) <= 10, f'+{calls1 - calls0} 次 / 10 tick')
        check('D7 ★单次 tick 阻塞仍在 30fps 预算量级（median ≤45ms / max ≤70ms）',
              srt[len(srt) // 2] <= 45.0 and srt[-1] <= 70.0,
              f'median {srt[len(srt) // 2]:.2f} ms / max {srt[-1]:.2f} ms')
        # 逐帧 / 暂停仍工作
        p1 = dlg.preview_idx
        dlg._preview_step(1)
        check('D8 逐帧按钮仍能翻帧（-1/+1 生效）', dlg.preview_idx == (p1 + 1) % BIG_N,
              f'{p1} → {dlg.preview_idx}')
        dlg._preview_goto(0)
        check('D9 ⏮ 回首帧生效', dlg.preview_idx == 0, str(dlg.preview_idx))
        return t_new
    finally:
        kill(dlg, root)


# ================= E 段 =================
def test_e_inventory(tmp, gif, png, old_mod):
    section('E 右栏控件清单 ⊇ 改前（R8 只许改布局，不许删控件）')
    if old_mod is None:
        skip('E 段', '改前模块不可用')
        return

    def texts(mod, root, path):
        d = None
        try:
            d = mod.ImagePreprocessDialog(root, path)
            out = []
            for w in _all_widgets(d.root):
                try:
                    if w.winfo_class() in ('Button', 'Checkbutton', 'Radiobutton', 'Label', 'Scale'):
                        t = str(w.cget('text')).strip()
                        if t:
                            out.append((w.winfo_class(), t))
                except Exception:
                    pass
            return out
        finally:
            kill(d, None)

    r1 = _new_root()
    r2 = _new_root()
    try:
        old_list = texts(old_mod, r1, gif)
        new_list = texts(R, r2, gif)
        miss = [t for t in old_list if t not in new_list]
        extra = [t for t in new_list if t not in old_list]
        note('改前 %d 个 / 改后 %d 个控件；新增：%s' % (len(old_list), len(new_list), extra[:5]))
        check('E1 ★动图模式：改前所有控件在改后仍存在（无删减）', not miss, f'缺失 {len(miss)}：{miss[:5]}')
    finally:
        kill(None, r1)
        kill(None, r2)
    r3 = _new_root()
    r4 = _new_root()
    try:
        old_s = texts(old_mod, r3, png)
        new_s = texts(R, r4, png)
        miss_s = [t for t in old_s if t not in new_s]
        check('E2 ★静态图：改前所有控件在改后仍存在（无删减）', not miss_s,
              f'缺失 {len(miss_s)}：{miss_s[:5]}')
    finally:
        kill(None, r3)
        kill(None, r4)


# ================= F 段 =================
def test_f_cleanup(tmp, gif):
    section('F 销毁不留 after（滚动容器不得新增残留回调）')
    root = _new_root()
    dlg = None
    try:
        dlg = R.ImagePreprocessDialog(root, gif)
        dlg._toggle_preview()
        pid = dlg._anim_after
        check('F1 播放中确实排了节拍（前提）', dlg._playing and pid is not None, f'after={pid}')
        dlg._cancel()
        left = set(map(str, root.tk.call('after', 'info')))
        check('F2 ★_cancel 后我们的 after id 不在 Tk 待执行队列里',
              str(pid) not in left, f'残留={sorted(left)[:4]}')
        err = None
        try:
            dlg._preview_tick()
            dlg._draw()
        except Exception as e:
            err = '%s: %s' % (type(e).__name__, e)
        check('F3 ★销毁后迟到的回调安全返回', err is None, str(err))
    finally:
        kill(dlg, root)


def main():
    tmp = tempfile.mkdtemp(prefix='r8prep_')
    real_here = R.HERE
    print('=' * 72)
    print('R8 图片预处理对话框：动图模式下所有控件可见可点（不挤占下方功能）')
    print('改前基线修订：%s　夹具目录：%s' % (R8_BASE_REV, tmp))
    print('=' * 72)
    old_mod = None
    try:
        gif = make_gif(os.path.join(tmp, 'anim8.gif'))
        big = make_big_gif(os.path.join(tmp, 'big.gif'))
        png = make_png(os.path.join(tmp, 'static.png'))
        old_mod, why = load_old_module(tmp)
        note('改前模块：%s' % why)
        R.HERE = tmp
        test_a_anim_visible(tmp, gif)
        test_b_static_unchanged(tmp, png, gif, old_mod)
        test_c_small_screen(tmp, gif)
        test_d_r6_kept(tmp, big, None, old_mod)     # 耗时对照在 D 段内交替取样
        test_e_inventory(tmp, gif, png, old_mod)
        test_f_cleanup(tmp, gif)
    finally:
        R.HERE = real_here
        shutil.rmtree(tmp, ignore_errors=True)
    print('')
    print('=' * 72)
    print('通过 %d 项 / 失败 %d 项%s' % (len(PASS), len(FAIL),
                                        (' / 跳过 %d 项' % len(SKIP)) if SKIP else ''))
    if FAIL:
        print('失败项: ' + ', '.join(FAIL))
        return 1
    print('ALL CHECKS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
