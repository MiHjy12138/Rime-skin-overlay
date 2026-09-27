# -*- coding: utf-8 -*-
"""B_test_wizard_layout.py —— v2.0-t15 向导布局与图层交互验证

对照用户实测反馈的两个问题：
  1) 【阻断】向导窗口过高 → 「保存并启动 / 取消 / 清理垃圾…」按钮行被推出屏幕，点不到保存
     验收：W 段 —— 按钮行在任何工作区高度下始终可见可点；窗口总高 ≤ 工作区；
           高级设置栏（⑧~⑭）可滚动（滚轮 + 拖动滚动条），按钮行与顶部不随内容滚动；
           1366x768 小屏模拟下按钮行在可视区、⑭ 开机自启仍可达
  2) 图层交互：删除图层区自带滑条 → 复用上方 ④缩放/⑤水平/⑥垂直；层间短时记忆；
     点选即同步；「点选图片时无法预览」
     验收：S 段（滑条复用/记忆/同步）、P 段（预览）

红线：只读被测模块；不写真实 config.json / skin.json（save_config 打桩）；
     文件对话框与模态框全部打桩（否则测试会挂在等待用户点击上）。

用法: python B_test_wizard_layout.py
"""
import os
import sys
import json
import shutil
import tempfile

# 控制台编码保护（与 B_test_layered_alpha.py 同写法）：
# GBK 控制台下打印 🧹 / ⑪ 等非 GBK 字符会 UnicodeEncodeError 并让脚本 exit≠0
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R          # noqa: E402

PASS, FAIL, SKIPPED = [], [], []


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
        import tkinter
        p = tkinter.Tk()
        p.withdraw()
        p.update()
        p.destroy()
        return True
    except Exception:
        return False


def make_img(path, size=(120, 180), color=(220, 60, 60, 255)):
    from PIL import Image
    im = Image.new('RGBA', size, (0, 0, 0, 0))
    w, h = size
    for y in range(int(h * 0.2), int(h * 0.8)):
        for x in range(int(w * 0.15), int(w * 0.85)):
            im.putpixel((x, y), color)
    im.save(path)
    return path


# ==========================================================================
# Z. 接口清单（红阶段先列缺口）
# ==========================================================================
def test_api_surface():
    section('Z. 接口清单：本次要新增的符号')
    for s in ('screen_work_area_height',):
        check(f'Z01 模块级符号 {s} 存在', hasattr(R, s))
    for s in ('_build_scroll_body', '_on_main_slider', '_layer_get_params',
              '_layer_set_params', '_on_layer_flip', '_sync_slider_to_layer',
              '_body_scroll_height', '_on_body_wheel'):
        check(f'Z02 ConfigWizard.{s} 存在', hasattr(R.ConfigWizard, s))


# ==========================================================================
# W. 布局（问题 1）
# ==========================================================================
_SAVED_STUB = []


def _wiz_probe(work_h=None, cfg=None):
    """建向导（可注入工作区高度）→ 返回 (wiz, real_fn们)。

    小屏模拟要**同时**打桩 screen_work_area_height 与 screen_work_area —— 只改高度的话，
    窗口定位仍按真实工作区（1040）算 y，会把它放到模拟工作区之外，测出来的"按钮被挤出"
    其实是模拟口径不自洽造成的假阳性。
    """
    if not _SAVED_STUB:
        _SAVED_STUB.append((R.screen_work_area_height, R.screen_work_area))
    if work_h is not None:
        R.screen_work_area_height = lambda root=None: int(work_h)
        R.screen_work_area = lambda root=None: (0, int(work_h))
    import tkinter
    done = {}
    wiz = R.ConfigWizard(on_done=lambda c: done.update(c), overlay=None)
    if cfg:
        wiz.cfg.update(cfg)
        wiz._layer_sync_from_cfg()
    wiz.root.update_idletasks()
    wiz.root.update()
    # v2.0-R15（第四轮 N1）改写**取样前提**（HANDOFF-2.1 §6-13）：向导现在默认折叠，
    # ⑧~⑭ 不 map、滚动区内容变矮 —— 而本脚本量的是「展开态放不下 ⇒ 必须可滚动」，
    # 旧前提「构造完即展开」被用户需求推翻。取样前一次性显式展开把条件恢复成旧口径；
    # **判据表达式一条未改、强度未降**。
    # 判别力证据：把这三行注释掉（= 退回旧取样顺序）后 W11/W12/W13/W15/W16 全部 FAIL。
    try:
        wiz._toggle_adv_collapse(False)
        wiz.root.update_idletasks()
        wiz.root.update()
    except Exception:
        pass
    return wiz, _SAVED_STUB[0]


def _restore_stub(real_fn):
    if real_fn:
        R.screen_work_area_height, R.screen_work_area = real_fn


def _btn_row_info(wiz):
    """找到按钮行 frame 与其相对屏幕的位置"""
    import tkinter
    target = None
    for c in wiz.root.winfo_children():
        for cc in c.winfo_children():
            if isinstance(cc, tkinter.Frame) and cc is getattr(wiz, 'btn_row', None):
                target = cc
    target = target or getattr(wiz, 'btn_row', None)
    if target is None:
        return None
    btns = {}
    for b in target.winfo_children():
        try:
            t = str(b.cget('text'))
        except Exception:
            continue
        if t in ('保存并启动', '取消', '🧹 清理垃圾…'):
            btns[t] = (b.winfo_rooty(), b.winfo_height(), b.winfo_ismapped())
    return {'row_top': target.winfo_rooty(), 'row_h': target.winfo_height(),
            'row_bottom': target.winfo_rooty() + target.winfo_height(), 'btns': btns}


def test_layout(real_work_h, tmp):
    section('W. 布局：按钮行始终可见 + 高级栏可滚动')
    import tkinter

    # ---- W1. 当前真实屏幕（1080p/1040 工作区）：按钮行必须在工作区内 ----
    wiz, real_fn = _wiz_probe(None)
    try:
        info = _btn_row_info(wiz)
        check('W01 按钮行 frame 已就位（self.btn_row 存在）', info is not None,
              str(info))
        if info:
            check('W02 ★按钮行底边 ≤ 屏幕工作区底边（不被挤出屏幕）',
                  info['row_bottom'] <= real_work_h,
                  f"row_bottom={info['row_bottom']} 工作区={real_work_h}")
            for t, (y, h, m) in info['btns'].items():
                check(f'W03 按钮「{t}」可见可点', m == 1 and (y + h) <= real_work_h,
                      f'top={y} h={h} mapped={m} bottom={y + h} 工作区={real_work_h}')
        check('W04 窗口总高 ≤ 屏幕工作区',
              wiz.root.winfo_y() + wiz.root.winfo_height() <= real_work_h,
              f"窗口底边={wiz.root.winfo_y() + wiz.root.winfo_height()} 工作区={real_work_h}")

        # ---- W5. 大屏（≥1080p）不需要滚动条，保持现有观感 ----
        check('W05 1080p 下内容放得下 → 不显示滚动条（观感不变）',
              getattr(wiz, '_scroll_needed', None) is False,
              f'_scroll_needed={getattr(wiz, "_scroll_needed", None)}')
        check('W06 高级设置栏已装进可滚动容器',
              hasattr(wiz, 'body_canvas') and hasattr(wiz, 'body_inner'), '')
        check('W07 顶部区（① 图片行）不被滚动容器包住（不随内容滚动）',
              hasattr(wiz, 'top_area') and hasattr(wiz, 'btn_row'), '')
    finally:
        _restore_stub(real_fn)
        try:
            wiz.root.destroy()
        except Exception:
            pass

    # ---- W8. 小屏模拟 1366x768（工作区 728）：按钮行仍可见、⑭ 可达 ----
    wiz2, real_fn2 = _wiz_probe(728)
    try:
        info = _btn_row_info(wiz2)
        check('W08 ★1366x768 模拟：按钮行底边 ≤ 工作区 728',
              info and info['row_bottom'] <= 728,
              f"row_bottom={info['row_bottom'] if info else '?'}")
        if info:
            for t, (y, h, m) in info['btns'].items():
                check(f'W09 小屏下按钮「{t}」可见可点', m == 1 and (y + h) <= 728,
                      f'top={y} h={h} mapped={m}')
        check('W10 小屏下窗口总高 ≤ 728',
              wiz2.root.winfo_y() + wiz2.root.winfo_height() <= 728,
              f"底边={wiz2.root.winfo_y() + wiz2.root.winfo_height()}")
        check('W11 小屏下内容放不下 → 出现滚动条',
              getattr(wiz2, '_scroll_needed', None) is True,
              f'_scroll_needed={getattr(wiz2, "_scroll_needed", None)}')
        scrollable = getattr(wiz2, 'body_canvas', None)
        check('W12 滚动区可滚动（scrollregion 高于可视高度）',
              scrollable is not None
              and _scroll_span(scrollable) > scrollable.winfo_height(),
              f'span={_scroll_span(scrollable) if scrollable else "?"} '
              f'vis={scrollable.winfo_height() if scrollable else "?"}')
        # ⑭ 开机自启：滚到底后应可达
        if scrollable is not None:
            scrollable.yview_moveto(1.0)
            wiz2.root.update_idletasks()
            auto = _find_widget(wiz2, '⑭ 开机自启（静默到托盘）')
            if auto is None:
                check('W13 找不到 ⑭ 开机自启控件', False, '')
            else:
                check('W13 ★滚到底后 ⑭ 开机自启仍在可视区内',
                      auto.winfo_rooty() >= scrollable.winfo_rooty()
                      and auto.winfo_rooty() + auto.winfo_height()
                      <= scrollable.winfo_rooty() + scrollable.winfo_height() + 2,
                      f"auto_bottom={auto.winfo_rooty() + auto.winfo_height()} "
                      f"cv_bottom={scrollable.winfo_rooty() + scrollable.winfo_height()}")
        # 滚轮
        check('W14 滚轮事件已绑定到滚动区', _wheel_bound(wiz2), '')
        if scrollable is not None:
            scrollable.yview_moveto(0)      # 归零再测滚轮（W13 刚滚到底，否则下滚无效）
            wiz2.root.update_idletasks()
        before = scrollable.yview()[0] if scrollable else 0
        _fire_wheel(wiz2, -120)
        wiz2.root.update_idletasks()
        after = scrollable.yview()[0] if scrollable else 0
        check('W15 滚轮下滚 → 视图位置变化', after > before, f'{before:.3f} → {after:.3f}')
        _fire_wheel(wiz2, 120)
        wiz2.root.update_idletasks()
        check('W16 滚轮上滚 → 视图回位', scrollable.yview()[0] < after,
              f'{after:.3f} → {scrollable.yview()[0]:.3f}')
    finally:
        _restore_stub(real_fn2)
        try:
            wiz2.root.destroy()
        except Exception:
            pass


def _scroll_span(cv):
    try:
        bbox = cv.bbox('all')
        return bbox[3] - bbox[1] if bbox else 0
    except Exception:
        return 0


def _find_widget(wiz, text):
    def walk(w):
        for c in w.winfo_children():
            try:
                if str(c.cget('text')) == text:
                    return c
            except Exception:
                pass
            r = walk(c)
            if r is not None:
                return r
        return None
    return walk(wiz.root)


def _wheel_bound(wiz):
    """滚动区或其后代上绑定过 <MouseWheel>"""
    cv = getattr(wiz, 'body_canvas', None)
    if cv is None:
        return False
    try:
        if cv.bind('<MouseWheel>'):
            return True
    except Exception:
        pass
    try:
        return bool(wiz.root.bind_all('<MouseWheel>') or wiz.root.bind('<MouseWheel>'))
    except Exception:
        return False


def _fire_wheel(wiz, delta):
    """在滚动区中心派发一次滚轮事件（真 event_generate 优先，失败则直接调处理函数）"""
    cv = getattr(wiz, 'body_canvas', None)
    if cv is None:
        return
    try:
        cv.event_generate('<MouseWheel>', x=cv.winfo_width() // 2,
                          y=cv.winfo_height() // 2, delta=delta)
        return
    except Exception:
        pass
    try:
        wiz._on_body_wheel(_FakeWheel(cv, delta))
    except Exception:
        pass


class _FakeWheel:
    def __init__(self, widget, delta):
        self.widget = widget
        self.delta = delta
        self.x_root = widget.winfo_rootx() + widget.winfo_width() // 2
        self.y_root = widget.winfo_rooty() + widget.winfo_height() // 2
        self.x = widget.winfo_width() // 2
        self.y = widget.winfo_height() // 2


# ==========================================================================
# S. 图层交互：滑条复用 / 层间记忆 / 点选同步（问题 4a/4b/4d）
# ==========================================================================
def test_slider_reuse(tmp):
    section('S. 图层交互：④⑤⑥ 复用为当前层参数 + 层间记忆 + 点选同步')
    a = make_img(os.path.join(tmp, 'sa.png'), (120, 180), (220, 60, 60, 255))
    b = make_img(os.path.join(tmp, 'sb.png'), (80, 200), (60, 90, 220, 255))
    c = make_img(os.path.join(tmp, 'sc.png'), (60, 60), (60, 200, 90, 255))
    cfg = {'image': a, 'scale': 1.0, 'offset_x': 0, 'offset_y': 0,
           'layers': [{'image': a, 'anchor': 'left_edge', 'z': 0},
                      {'image': b, 'anchor': 'right_edge', 'z': 1,
                       'scale': 0.7, 'offset_x': 20, 'offset_y': -10},
                      {'image': c, 'anchor': 'center', 'z': 2, 'scale': 1.3}]}
    wiz, real_fn = _wiz_probe(None, cfg)
    try:
        # ---- 4a：图层区不再自带独立滑条 ----
        check('S01 图层区已无独立缩放滑条（var_lay_scale 已移除）',
              not hasattr(wiz, 'var_lay_scale'))
        check('S02 图层区已无独立水平滑条（var_lay_offx 已移除）',
              not hasattr(wiz, 'var_lay_offx'))
        check('S03 图层区已无独立垂直滑条（var_lay_offy 已移除）',
              not hasattr(wiz, 'var_lay_offy'))
        check('S04 上方 ④⑤⑥ 滑条仍在（var_scale / var_offx / var_offy）',
              hasattr(wiz, 'var_scale') and hasattr(wiz, 'var_offx')
              and hasattr(wiz, 'var_offy'))
        check('S05 图层区保留锚点控件', hasattr(wiz, 'var_layer_anchor'))
        check('S06 图层区保留随宽度比例控件',
              hasattr(wiz, 'var_lay_follow') and hasattr(wiz, 'var_lay_follow_r'))

        # ---- 4d：点选即同步 ----
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(1)
        wiz._on_layer_select()
        check('S07 ★点选第 2 层 → 上方 ④缩放 同步为该层值 0.7',
              abs(float(wiz.var_scale.get()) - 0.7) < 1e-6, repr(wiz.var_scale.get()))
        check('S08 ★点选第 2 层 → 上方 ⑤水平 同步为该层值 20',
              int(wiz.var_offx.get()) == 20, repr(wiz.var_offx.get()))
        check('S09 ★点选第 2 层 → 上方 ⑥垂直 同步为该层值 -10',
              int(wiz.var_offy.get()) == -10, repr(wiz.var_offy.get()))
        check('S10 点选第 2 层 → 锚点控件同步为 right_edge',
              wiz.var_layer_anchor.get() == 'right_edge', repr(wiz.var_layer_anchor.get()))
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(2)
        wiz._on_layer_select()
        check('S11 点选第 3 层 → 上方缩放同步为 1.3',
              abs(float(wiz.var_scale.get()) - 1.3) < 1e-6, repr(wiz.var_scale.get()))
        check('S12 点选第 3 层 → 锚点同步为 center',
              wiz.var_layer_anchor.get() == 'center', repr(wiz.var_layer_anchor.get()))

        # ---- 4a 写入：拖滑条 → 写进当前层 ----
        wiz.var_scale.set(1.1)
        wiz.var_offx.set(33)
        wiz.var_offy.set(-7)
        wiz._on_main_slider()
        lc = wiz.cfg['layers'][2]
        check('S13 ★拖 ④⑤⑥ 写入当前（第 3）层：scale=1.1',
              abs(float(lc.get('scale', 0)) - 1.1) < 1e-6, repr(lc.get('scale')))
        check('S14 拖 ⑤ 写入当前层 offset_x=33', int(lc.get('offset_x', 0)) == 33,
              repr(lc.get('offset_x')))
        check('S15 拖 ⑥ 写入当前层 offset_y=-7', int(lc.get('offset_y', 0)) == -7,
              repr(lc.get('offset_y')))
        check('S16 未选中的第 2 层参数不受影响',
              abs(float(wiz.cfg['layers'][1].get('scale', 0)) - 0.7) < 1e-6
              and int(wiz.cfg['layers'][1].get('offset_x', 0)) == 20,
              f"l1.scale={wiz.cfg['layers'][1].get('scale')} l1.ox={wiz.cfg['layers'][1].get('offset_x')}")
        check('S17 顶层兼容字段不被第 3 层的调整污染（仍是主层的值）',
              abs(float(wiz.cfg.get('scale', 0)) - 1.0) < 1e-6
              and int(wiz.cfg.get('offset_x', 0)) == 0,
              f"scale={wiz.cfg.get('scale')} offx={wiz.cfg.get('offset_x')}")

        # ---- 4b：层间短时记忆（切走再切回）----
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(1)
        wiz._on_layer_select()
        check('S18 ★切回第 2 层 → 仍是原值 0.7 / 20 / -10（互不覆盖）',
              abs(float(wiz.var_scale.get()) - 0.7) < 1e-6
              and int(wiz.var_offx.get()) == 20 and int(wiz.var_offy.get()) == -10,
              f'{wiz.var_scale.get()}/{wiz.var_offx.get()}/{wiz.var_offy.get()}')
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(2)
        wiz._on_layer_select()
        check('S19 ★再切回第 3 层 → 保留刚才改的 1.1 / 33 / -7',
              abs(float(wiz.var_scale.get()) - 1.1) < 1e-6
              and int(wiz.var_offx.get()) == 33 and int(wiz.var_offy.get()) == -7,
              f'{wiz.var_scale.get()}/{wiz.var_offx.get()}/{wiz.var_offy.get()}')

        # ---- 主层（第 1 层）走顶层兼容字段 ----
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(0)
        wiz._on_layer_select()
        check('S20 点选第 1 层（主图）→ 上方滑条回到顶层值 1.0 / 0 / 0',
              abs(float(wiz.var_scale.get()) - 1.0) < 1e-6
              and int(wiz.var_offx.get()) == 0 and int(wiz.var_offy.get()) == 0,
              f'{wiz.var_scale.get()}/{wiz.var_offx.get()}/{wiz.var_offy.get()}')
        wiz.var_offy.set(-64)
        wiz._on_main_slider()
        check('S21 拖主层 ⑥ → 写进顶层 cfg.offset_y（不是 layers[0]）',
              int(wiz.cfg.get('offset_y', 0)) == -64
              and int(wiz.cfg['layers'][0].get('offset_y', 0) or 0) == 0,
              f"top={wiz.cfg.get('offset_y')} l0={wiz.cfg['layers'][0].get('offset_y')}")

        # ---- 翻转：R13 起在通用区；N3 起**按当前选中层**调 ----
        # N3 语义再回退（第四轮，用户「翻转也按当前选中层（一起改）」）：推翻 R13 的「统一管
        # 所有图层」。旧断言「切到第 2 层显示统一值（True）」「在第 2 层取消 → 全部层一起回」
        # 的前提被推翻 → 按需求回退改为每层独立断言（不删整段、不改恒真）。
        check('S22 翻转控件仍复用 var_flip（挂通用区 chk_flip，不再是图层区勾选框）',
              hasattr(wiz, 'var_flip') and hasattr(wiz, 'chk_flip'))
        wiz.var_flip.set(True)
        wiz._on_flip_change()
        check('S23 勾翻转（当前选中主层）→ 顶层 flip_h=True（主层权威口径不变）',
              wiz.cfg.get('flip_h') is True, repr(wiz.cfg.get('flip_h')))
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(1)
        wiz._on_layer_select()
        check('S24 ★N3：切到第 2 层 → 翻转控件显示该层自己的值（False，不是主层的 True）',
              wiz.var_flip.get() is False, repr(wiz.var_flip.get()))
        wiz.var_flip.set(True)
        wiz._on_flip_change()
        check('S25 ★N3：在第 2 层勾上翻转 → 只改第 2 层（主层与顶层 flip_h 仍是 True，不受牵连）',
              wiz.cfg['layers'][1].get('flip') is True
              and wiz.cfg['layers'][0].get('flip') is True
              and wiz.cfg.get('flip_h') is True,
              f"l0={wiz.cfg['layers'][0].get('flip')} l1={wiz.cfg['layers'][1].get('flip')} "
              f"top={wiz.cfg.get('flip_h')}")

        # ---- 随宽度比例（图层独有）----
        wiz.var_lay_follow.set(True)
        wiz.var_lay_follow_r.set(40)
        wiz._on_layer_param_change()
        check('S26 随宽度比例写入当前层 40%',
              abs(float(wiz.cfg['layers'][1].get('follow_width_ratio', 0)) - 0.4) < 1e-9,
              repr(wiz.cfg['layers'][1].get('follow_width_ratio')))
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('S00 图层交互段未抛异常', False, repr(e))
    finally:
        _restore_stub(real_fn)
        try:
            wiz.root.destroy()
        except Exception:
            pass


# ==========================================================================
# P. 预览（问题 4c）
# ==========================================================================
def _canvas_images(wiz):
    cv = wiz.canvas
    return [i for i in cv.find_all() if cv.type(i) == 'image']


def _canvas_texts(wiz):
    cv = wiz.canvas
    out = []
    for i in cv.find_all():
        if cv.type(i) == 'text':
            out.append(str(cv.itemcget(i, 'text')))
    return out


def test_preview(tmp):
    section('P. 预览：点选图片 / 多层 / 点选层切换都要能预览')
    a = make_img(os.path.join(tmp, 'pa.png'), (120, 180), (220, 60, 60, 255))
    b = make_img(os.path.join(tmp, 'pb.png'), (80, 200), (60, 90, 220, 255))
    c = make_img(os.path.join(tmp, 'pc.png'), (60, 60), (60, 200, 90, 255))
    d = make_img(os.path.join(tmp, 'pd.png'), (100, 100), (200, 200, 60, 255))
    wiz, real_fn = _wiz_probe(None, {'image': a})
    real_ask = R.filedialog.askopenfilename
    try:
        # ---- P1. 连续「选择图片」（走真实 _pick_image，只打桩对话框）----
        for idx, (path, tag) in enumerate(((b, 'B'), (c, 'C'), (d, 'D'), (a, 'A'))):
            R.filedialog.askopenfilename = lambda *a, **k: path
            wiz._pick_image()
            wiz.root.update_idletasks()
            n = len(_canvas_images(wiz))
            check(f'P1{idx + 1} 点选图片{tag} → 预览有图（第 {idx + 1} 次连选）', n >= 1,
                  f'image项={n} texts={_canvas_texts(wiz)[:2]}')

        # ---- P2. 主图路径必须同步进 layers[0]（消除"顶层 image / 图层图"分裂）----
        wiz.cfg['layers'] = [R.normalize_layer({'image': a, 'anchor': 'left_edge', 'z': 0}),
                             R.normalize_layer({'image': b, 'anchor': 'right_edge', 'z': 1})]
        wiz._layer_sync_from_cfg()
        R.filedialog.askopenfilename = lambda *a, **k: c
        wiz._pick_image()
        check('P21 ★点选图片后 layers[0].image 与顶层 image 同步（不再陈旧）',
              os.path.normpath(wiz.cfg['layers'][0].get('image') or '')
              == os.path.normpath(wiz.cfg.get('image') or ''),
              f"top={os.path.basename(wiz.cfg.get('image') or '')} "
              f"l0={os.path.basename(wiz.cfg['layers'][0].get('image') or '')}")
        wiz.root.update_idletasks()
        check('P22 两层状态下换主图 → 预览仍有两张图',
              len(_canvas_images(wiz)) == 2,
              f'image项={len(_canvas_images(wiz))} texts={_canvas_texts(wiz)[:2]}')

        # ---- P3. 点选图层 → 预览立即刷新（刷新时机）----
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(1)
        wiz._on_layer_select()
        wiz.root.update_idletasks()
        check('P31 ★点选第 2 层 → 预览立即重绘（image 项数仍为 2）',
              len(_canvas_images(wiz)) == 2, f'image项={len(_canvas_images(wiz))}')
        # 改该层缩放 → 预览里该层应变大。注意预览整体有 fit 缩放（内容超画布会等比缩），
        # 所以要比的是「该层 / 主层」的宽度比，而不是绝对像素。
        def _ratio():
            w0, w1 = _layer_box_w(wiz, 0), _layer_box_w(wiz, 1)
            return (w1 / w0) if (w0 and w1) else None
        before = _ratio()
        wiz.var_scale.set(1.6)
        wiz._on_main_slider()
        wiz.root.update_idletasks()
        after = _ratio()
        check('P32 ★拖 ④ 改第 2 层缩放 → 预览里该层相对主层明显变大',
              before is not None and after is not None and after > before * 1.5,
              f'比例 {before} → {after}（绝对宽 '
              f'{_layer_box_w(wiz, 0)}/{_layer_box_w(wiz, 1)}）')
        check('P32b 该层参数确实写进了 layers[1]',
              abs(float(wiz.cfg['layers'][1].get('scale', 0)) - 1.6) < 1e-6,
              repr(wiz.cfg['layers'][1].get('scale')))

        # ---- P4. 缓存失效：同名路径覆盖（mtime 变）也要刷新 ----
        sz_before = wiz._get_preview_img().size if wiz._get_preview_img() else None
        wiz.cfg['image'] = a
        wiz._cache = ('stale', 0, None)      # 伪造陈旧缓存（模拟同名覆盖后未失效）
        wiz._update_preview()
        check('P41 陈旧缓存不会导致预览空白', len(_canvas_images(wiz)) >= 1,
              f'image项={len(_canvas_images(wiz))}')

        # ---- P5. 图片全失效时给出明确提示，而不是静默空白 ----
        wiz.cfg['layers'] = [R.normalize_layer({'image': os.path.join(tmp, 'gone1.png')}),
                             R.normalize_layer({'image': os.path.join(tmp, 'gone2.png')})]
        wiz.cfg['image'] = os.path.join(tmp, 'gone1.png')
        wiz._update_preview()
        texts = _canvas_texts(wiz)
        check('P51 ★图全失效 → 预览给出可见提示文字（不再静默空白）',
              any(('缺' in t) or ('失败' in t) or ('无法' in t) for t in texts), str(texts))

        # ---- P6. 部分失效 → 有效的那层仍要画出来 ----
        wiz.cfg['layers'] = [R.normalize_layer({'image': os.path.join(tmp, 'gone1.png')}),
                             R.normalize_layer({'image': b, 'anchor': 'right_edge', 'z': 1})]
        wiz.cfg['image'] = os.path.join(tmp, 'gone1.png')
        wiz._update_preview()
        check('P61 部分失效 → 仍画出有效的那一层', len(_canvas_images(wiz)) >= 1,
              f'image项={len(_canvas_images(wiz))} texts={_canvas_texts(wiz)[:2]}')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('P00 预览段未抛异常', False, repr(e))
    finally:
        R.filedialog.askopenfilename = real_ask
        _restore_stub(real_fn)
        try:
            wiz.root.destroy()
        except Exception:
            pass


def _layer_box_w(wiz, idx):
    """预览里第 idx 层的虚线框宽度。

    _draw_img_layer 按 _preview_layers 的顺序 create_rectangle，所以**按 canvas 项顺序**
    取第 idx 个虚线框就是第 idx 层（不能按宽度排序 —— 改缩放后顺序会变，断言就失效了）。
    """
    cv = wiz.canvas
    dashed = []
    for i in cv.find_all():
        if cv.type(i) != 'rectangle':
            continue
        try:
            coords = cv.coords(i)
            dash = str(cv.itemcget(i, 'dash'))
        except Exception:
            continue
        w = coords[2] - coords[0]
        h = coords[3] - coords[1]
        if w > 10 and h > 10 and dash not in ('', '0'):
            dashed.append(w)
    return dashed[idx] if len(dashed) > idx else None


# ==========================================================================
# R. 保存往返（4b 的后半：写回 skin.json / config.json 正确）
# ==========================================================================
def test_save_roundtrip(tmp):
    section('R. 保存往返：各层参数写回正确，关掉向导再打开不丢')
    a = make_img(os.path.join(tmp, 'ra.png'), (120, 180), (220, 60, 60, 255))
    b = make_img(os.path.join(tmp, 'rb.png'), (80, 200), (60, 90, 220, 255))
    real_skins = R.SKINS_DIR
    tmp_skins = os.path.join(tmp, 'skins_rt')
    os.makedirs(tmp_skins, exist_ok=True)
    real_save = R.save_config
    real_mb = (R.messagebox.showinfo, R.messagebox.showwarning,
               R.messagebox.showerror, R.messagebox.askyesno)
    saved = {}
    try:
        R.SKINS_DIR = tmp_skins
        R.save_config = lambda cfg: saved.update(cfg)
        R.messagebox.showinfo = lambda *a, **k: None
        R.messagebox.showwarning = lambda *a, **k: None
        R.messagebox.showerror = lambda *a, **k: None
        R.messagebox.askyesno = lambda *a, **k: True
        R.set_autostart = lambda want, force=False: (True, '（测试打桩）')

        cfg = {'image': a, 'layout': 'horizontal_double', 'side': 'left',
               'scale': 0.9, 'offset_x': 5, 'offset_y': -5,
               'layers': [{'image': a, 'anchor': 'left_edge', 'z': 0},
                          {'image': b, 'anchor': 'right_edge', 'z': 1,
                           'scale': 0.6, 'offset_x': 12, 'offset_y': 8}]}
        wiz, real_fn = _wiz_probe(None, cfg)
        try:
            wiz.layer_list.selection_clear(0, 'end')
            wiz.layer_list.selection_set(1)
            wiz._on_layer_select()
            wiz.var_scale.set(1.4)
            wiz.var_offx.set(21)
            wiz._on_main_slider()
            wiz._save_and_start()
            out = dict(saved)
            check('R01 保存后顶层 scale 仍是主层值 0.9（未被第 2 层污染）',
                  abs(float(out.get('scale', 0)) - 0.9) < 1e-6, repr(out.get('scale')))
            lay = out.get('layers') or []
            check('R02 保存后 layers 长度 2', len(lay) == 2, str(len(lay)))
            check('R03 第 2 层改动落盘（scale=1.4 / offset_x=21）',
                  len(lay) > 1 and abs(float(lay[1].get('scale', 0)) - 1.4) < 1e-6
                  and int(lay[1].get('offset_x', 0)) == 21,
                  f"l1={lay[1].get('scale') if len(lay) > 1 else '?'}/"
                  f"{lay[1].get('offset_x') if len(lay) > 1 else '?'}")
            check('R04 保存后 schema=2（档案形态）', int(out.get('schema', 0)) == 2,
                  repr(out.get('schema')))
            check('R05 第 0 层 offset 归零（单一权威在顶层）',
                  int(lay[0].get('offset_y', -999)) == 0, repr(lay[0].get('offset_y')))
        finally:
            _restore_stub(real_fn)
            try:
                wiz.root.destroy()
            except Exception:
                pass

        # 保存成皮肤 → 再读回（模拟关掉向导再打开）
        sk = R.save_skin('滑条往返皮肤', {'image': a, 'side': 'left', 'scale': 0.9,
                                       'offset_x': 5, 'offset_y': -5,
                                       'layers': [{'image': a, 'anchor': 'left_edge', 'z': 0},
                                                  {'image': b, 'anchor': 'right_edge', 'z': 1,
                                                   'scale': 1.4, 'offset_x': 21}]})
        back = R.find_skin('滑条往返皮肤')
        check('R06 皮肤档案读回 2 层', back and len(back.get('layers') or []) == 2,
              str(len((back or {}).get('layers') or [])))
        check('R07 读回后第 2 层参数不丢（scale=1.4 / offset_x=21）',
              back and abs(float(back['layers'][1].get('scale', 0)) - 1.4) < 1e-6
              and int(back['layers'][1].get('offset_x', 0)) == 21,
              f"{back['layers'][1].get('scale') if back else '?'}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('R00 保存往返段未抛异常', False, repr(e))
    finally:
        R.SKINS_DIR = real_skins
        R.save_config = real_save
        (R.messagebox.showinfo, R.messagebox.showwarning,
         R.messagebox.showerror, R.messagebox.askyesno) = real_mb


# ==========================================================================
def main():
    print('=== B_test_wizard_layout：t15 向导布局（按钮行可见 / 高级栏可滚动）+ 图层交互 ===')
    print('Python', sys.version.split()[0])
    tmp = tempfile.mkdtemp(prefix='wizard_layout_')
    R.HERE = tmp          # 只读约束（HANDOFF-2.1 §8.5）：日志/临时产物只落临时目录，不碰项目 error.log
    gui_ok = _has_gui()
    print('GUI 可用:', gui_ok, ' | 临时目录:', tmp)
    real_save = R.save_config
    real_mb = (R.messagebox.showinfo, R.messagebox.showwarning,
               R.messagebox.showerror, R.messagebox.askyesno)
    R.save_config = lambda cfg: None
    R.messagebox.showinfo = lambda *a, **k: None
    R.messagebox.showwarning = lambda *a, **k: None
    R.messagebox.showerror = lambda *a, **k: None
    R.messagebox.askyesno = lambda *a, **k: True
    try:
        test_api_surface()
        if not gui_ok:
            for t in ('W', 'S', 'P', 'R'):
                for i in range(1, 30):
                    skip(f'{t}{i:02d}', '无桌面环境（GUI 不可用）')
                break
            return _summary()
        real_work = R.screen_work_area_height() if hasattr(R, 'screen_work_area_height') \
            else R.ConfigWizard and 1040
        test_layout(real_work, tmp)
        test_slider_reuse(tmp)
        test_preview(tmp)
        test_save_roundtrip(tmp)
    finally:
        R.save_config = real_save
        (R.messagebox.showinfo, R.messagebox.showwarning,
         R.messagebox.showerror, R.messagebox.askyesno) = real_mb
        shutil.rmtree(tmp, ignore_errors=True)
    return _summary()


def _summary():
    print('\n' + '=' * 66)
    print(f'通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项 / 跳过 {len(SKIPPED)} 项')
    if SKIPPED:
        print('跳过项: ' + ', '.join(SKIPPED))
    if FAIL:
        print('失败项:')
        for n in FAIL:
            print('  -', n)
        print('RESULT: FAIL')
        return 1
    print('ALL CHECKS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
