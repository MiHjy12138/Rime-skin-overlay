# -*- coding: utf-8 -*-
"""B_test_r4_layout.py —— v2.0-R4 向导窗口重排验证

用户原话（HANDOFF-2.0 §3 R4）：「窗口大小只变了一点点。你不如把高级设置完整放预览框下面
横排放置。」t15 只解决了「按钮点不到」，窗口本身还是 1038px 高（1080p 工作区 1040 = 占满）。

本脚本守住四件事：
  A 结构：⚙ 高级设置整体在**预览框下方**（不再是右侧竖排），且是**横向多列**，列数随
    工作区宽度自适应（1920→3 / 1024→2 / 800→1）
  B 尺寸：窗口需求高 ≤ 工作区、按钮行完整落在窗内、宽度不超工作区（复用 t15 的度量手法）
  C 清单：① ~ ⑭ 全部控件仍在且可操作（逐项断言，防止「为了变小偷偷删功能」）
  D 分项：adv / top_block / body_inner 三段需求高度分项数字（缩窗收益要看得见：
    右栏竖排时 adv=901 独占高度，横排后最高列 ≈300）
  E 守卫：R3 的窗口尺寸记账（_applied_size）仍在 _move_to / _sync_tk_geometry 里 ——
    本项只改向导构建期布局，不得碰运行期图片窗的记账路径

红线：只读被测模块；不写真实 config.json / skin.json（save_config 打桩）；
      文件对话框与模态框全部打桩。

================== v2.0-R11 需求回退（本文件已按新需求改写两处） ==================
  · C 段清单条目「③ 贴边方向（图层区）」→ ③ 已按用户要求搬回**通用区**（② 与 ④ 之间，
    统一管所有图层），条目改为 ('var_side', 'lbl_side_target')；var_layer_anchor 自 R11 起
    降级为「当前选中层 anchor 的回显镜像」（不再绑单选按钮），故移出该条目。
  · B02 的高度阈值 900 → 960：旧的 900 是「③ 在图层区、通用区只有 ② 一行」时代的实测值
    （R4 后 867px）。R11 把 ③ 一行搬回通用区后实测 914px（+ 图层区说明行换文案），
    阈值按新事实放宽到 960，同时新增 **B02b 判别力**断言（把高级设置 monkeypatch 回
    竖排一列 → 需求高必须超过 960），证明阈值不是恒真、横排收益仍在。
    R12 折叠（⚙ 高级设置可折叠）另有约 -330px 的折叠态收益，见 B_test_r12_collapse.py。

用法: python B_test_r4_layout.py
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


_SAVED_STUB = []


def _wiz_probe(work_h=None, work_w=None, cfg=None):
    """建向导（可注入工作区高度/宽度）→ 返回 (wiz, real_fns)。

    小屏模拟要同时打桩三个函数：只改高度的话窗口定位仍按真实工作区算 y，
    测出来的「按钮被挤出」是模拟口径不自洽造成的假阳性（t15 的教训）。
    screen_work_area_width 是 R4 新增符号：改动前不存在 —— 用 getattr 保护，
    让「缺符号」表现为断言 FAIL 而不是脚本崩溃（红阶段也要能读完）。
    """
    real_w = getattr(R, 'screen_work_area_width', None)
    if not _SAVED_STUB:
        _SAVED_STUB.append((R.screen_work_area_height, R.screen_work_area, real_w))
    real = _SAVED_STUB[0]
    if work_h is not None:
        R.screen_work_area_height = lambda root=None: int(work_h)
        R.screen_work_area = lambda root=None: (0, int(work_h))
    if work_w is not None and real_w is not None:
        R.screen_work_area_width = lambda root=None: int(work_w)
    wiz = R.ConfigWizard(on_done=lambda c: None, overlay=None)
    if cfg:
        wiz.cfg.update(cfg)
        wiz._layer_sync_from_cfg()
    wiz.root.update_idletasks()
    wiz.root.update()
    return wiz, real


def _restore(all_real):
    if not all_real:
        return
    R.screen_work_area_height = all_real[0]
    R.screen_work_area = all_real[1]
    if len(all_real) > 2 and all_real[2] is not None:
        R.screen_work_area_width = all_real[2]


def _kill(wiz):
    try:
        wiz.root.destroy()
    except Exception:
        pass


def _btn_row_info(wiz):
    """按钮行的屏幕位置与三个按钮的可见性（与 B_test_wizard_layout 同手法）"""
    import tkinter
    target = getattr(wiz, 'btn_row', None)
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


def _scroll_span(cv):
    try:
        bbox = cv.bbox('all')
        return bbox[3] - bbox[1] if bbox else 0
    except Exception:
        return 0


def _in_body(wiz, widget):
    """widget 的祖先链里有没有 body_inner（= 真的在可滚动内容里）"""
    try:
        inner = wiz.body_inner
        w = widget
        while w is not None:
            if w is inner:
                return True
            w = w.master
        return False
    except Exception:
        return False


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


def _card_xs(wiz):
    """各编号卡片代表控件的屏幕 x（用来判定「横排多列」）"""
    picks = [('⑧', getattr(wiz, 'var_layer', None)),
             ('⑨', getattr(wiz, 'var_corner', None)),
             ('⑩', getattr(wiz, 'chk_feather', None)),
             ('⑫', getattr(wiz, 'layer_list', None)),
             ('⑬', getattr(wiz, 'skin_cb', None)),
             ('⑭', getattr(wiz, 'var_autostart', None))]
    out = {}
    for tag, w in picks:
        if w is None:
            continue
        try:
            anchor = w
            out[tag] = anchor.winfo_rootx()
        except Exception:
            pass
    return out


# ==========================================================================
# A. 结构：高级设置在预览下方 + 横排多列 + 列数自适应
# ==========================================================================
def test_structure(tmp, cfg):
    section('A. 结构：⚙ 高级设置移到预览框下方并横排多列')
    wiz, real = _wiz_probe(None, None, cfg)
    try:
        for attr in ('top_block', 'adv_area', 'adv_cols'):
            check(f'A00 布局容器 {attr} 已就位', hasattr(wiz, attr))
        if not (hasattr(wiz, 'adv_area') and hasattr(wiz, 'adv_cols')):
            check('A01 ★高级设置在预览框下方', False, 'adv_area 不存在')
            check('A02 ★高级设置是横向多列', False, 'adv_cols 不存在')
            check('A04 高级设置不再位于预览右侧', False, 'adv_area 不存在')
            return
        cv = getattr(wiz, 'canvas', None)
        adv = wiz.adv_area
        check('A01 ★高级设置整体在预览画布下方（top ≥ canvas 底边）',
              cv is not None and adv.winfo_rooty() >= cv.winfo_rooty() + cv.winfo_height(),
              f'canvas_bottom={cv.winfo_rooty() + cv.winfo_height() if cv else "?"} '
              f'adv_top={adv.winfo_rooty()}')
        xs = _card_xs(wiz)
        uniq = sorted(set(xs.values()))
        check('A02 ★高级设置是横向多列（同层卡片至少 3 个不同 x）',
              len(uniq) >= 3, f'卡位 x={xs} 去重={uniq}')
        check('A04 ★高级设置不再位于预览右侧（左边界不晚于画布）',
              cv is not None and adv.winfo_rootx() <= cv.winfo_rootx() + 4,
              f'adv_x={adv.winfo_rootx()} canvas_x={cv.winfo_rootx()}')
        check('A05 卡片确实落在各列容器里',
              all(_in_body(wiz, c) for c in wiz.adv_cols), '')
        check('A06 高级设置仍在可滚动内容里',
              _in_body(wiz, adv) and _in_body(wiz, wiz.top_block), '')
    finally:
        _restore(real)
        _kill(wiz)

    # 列数自适应
    for w_px, want in ((1920, 3), (1024, 2), (800, 1)):
        wiz2, real2 = _wiz_probe(None, w_px, cfg)
        try:
            n = len(getattr(wiz2, 'adv_cols', []) or [])
            check(f'A07 ★工作区宽 {w_px} → 高级设置 {want} 列（自适应）', n == want,
                  f'实际 {n} 列')
        finally:
            _restore(real2)
            _kill(wiz2)


# ==========================================================================
# B. 尺寸：窗口高度 / 宽度 / 按钮行（1080p 与小屏）
# ==========================================================================
def test_size(tmp, cfg, real_work_h):
    section('B. 尺寸：窗口需求高 ≤ 工作区、按钮行可见、宽度不超屏')
    wiz, real = _wiz_probe(None, None, cfg)
    try:
        need_h = wiz.root.winfo_reqheight()
        need_w = wiz.root.winfo_reqwidth()
        check('B01 ★1080p 下窗口需求高度 ≤ 工作区 1040', need_h <= real_work_h,
              f'reqheight={need_h}（R3 基线 1038）')
        check('B02 ★窗口需求高度显著变小（≤960，R3 基线 1038；R11 回退 ③ 后 867→914）',
              need_h <= 960, f'reqheight={need_h}（省 {1038 - need_h}px）')
        check('B06 ★窗口需求宽度不超工作区，且显著变窄（≤1100，R3 基线 1225）',
              need_w <= 1920 and need_w <= 1100, f'reqwidth={need_w}（R3 基线 1225）')
        info = _btn_row_info(wiz)
        check('B03a 按钮行 frame 已就位', info is not None, str(info))
        if info:
            check('B03b ★按钮行底边 ≤ 工作区底边',
                  info['row_bottom'] <= real_work_h,
                  f"row_bottom={info['row_bottom']} 工作区={real_work_h}")
            for t, (y, h, m) in info['btns'].items():
                check(f'B03c 按钮「{t}」可见可点',
                      m == 1 and (y + h) <= real_work_h, f'top={y} h={h} mapped={m}')
        check('B04 窗口底边 ≤ 工作区',
              wiz.root.winfo_y() + wiz.root.winfo_height() <= real_work_h,
              f"底边={wiz.root.winfo_y() + wiz.root.winfo_height()}")
        check('B05 1080p 下内容放得下 → 不显示滚动条',
              getattr(wiz, '_scroll_needed', None) is False,
              f'_scroll_needed={getattr(wiz, "_scroll_needed", None)}')
    finally:
        _restore(real)
        _kill(wiz)

    # v2.0-R11 新增判别力：把高级设置 monkeypatch 回「竖排一列」→ 窗口必须变高，
    # 证明 B02 的 960 阈值确实能区分「横排生效」与「没生效」（不是恒真阈值）
    real_cnt = R.ConfigWizard._adv_column_count
    R.ConfigWizard._adv_column_count = lambda self: 1
    wiz3, real3 = _wiz_probe(None, None, cfg)
    try:
        n3 = wiz3.root.winfo_reqheight()
        check('B02b ★判别力：高级设置改回竖排一列 → 需求高超过 B02 阈值（阈值非恒真）',
              n3 > 960, f'竖排={n3} 阈值=960')
    finally:
        _restore(real3)
        _kill(wiz3)
        R.ConfigWizard._adv_column_count = real_cnt

    # 小屏 1366x768（工作区 728）：按钮行可见 + 滚动可达 ⑭
    wiz2, real2 = _wiz_probe(728, 1366, cfg)
    try:
        info = _btn_row_info(wiz2)
        check('B07a ★小屏模拟：按钮行底边 ≤ 728',
              info and info['row_bottom'] <= 728,
              f"row_bottom={info['row_bottom'] if info else '?'}")
        if info:
            for t, (y, h, m) in info['btns'].items():
                check(f'B07b 小屏下按钮「{t}」可见可点',
                      m == 1 and (y + h) <= 728, f'top={y} h={h} mapped={m}')
        check('B07c 小屏下内容放不下 → 出滚动条',
              getattr(wiz2, '_scroll_needed', None) is True,
              f'_scroll_needed={getattr(wiz2, "_scroll_needed", None)}')
        cv = getattr(wiz2, 'body_canvas', None)
        check('B07d 滚动区可滚动（scrollregion > 可视高）',
              cv is not None and _scroll_span(cv) > cv.winfo_height(),
              f'span={_scroll_span(cv) if cv else "?"} '
              f'vis={cv.winfo_height() if cv else "?"}')
        if cv is not None:
            cv.yview_moveto(1.0)
            wiz2.root.update_idletasks()
            auto = _find_widget(wiz2, '⑭ 开机自启（静默到托盘）')
            check('B07e ★滚到底后 ⑭ 开机自启仍在可视区内',
                  auto is not None
                  and auto.winfo_rooty() >= cv.winfo_rooty()
                  and auto.winfo_rooty() + auto.winfo_height()
                  <= cv.winfo_rooty() + cv.winfo_height() + 2,
                  f'auto_bottom={auto.winfo_rooty() + auto.winfo_height() if auto else "?"} '
                  f'cv_bottom={cv.winfo_rooty() + cv.winfo_height() if cv else "?"}')
    finally:
        _restore(real2)
        _kill(wiz2)


# ==========================================================================
# C. ②~⑭ 逐项清单：一个控件都不许少
# ==========================================================================
def test_widget_inventory(tmp, cfg):
    section('C. ②~⑭ 控件清单：重排后一个不少、可操作、都在滚动内容里')
    wiz, real = _wiz_probe(None, None, cfg)
    try:
        items = [
            ('① 图片', ('btn_img', 'btn_prep', 'btn_anim', 'lbl_img')),
            ('② 候选框类型', ('var_layout',)),
            # R11 需求回退：③ 搬回通用区（② 与 ④ 之间）并统一管所有图层 → 条目改绑 var_side；
            # var_layer_anchor 降级为「当前选中层 anchor 的回显镜像」，不再算 UI 控件
            ('③ 贴边方向（通用区，统一管所有图层）', ('var_side', 'lbl_side_target')),
            ('④⑤⑥ 缩放/水平/垂直', ('var_scale', 'var_offx', 'var_offy',
                                     'lbl_scale', 'lbl_offx', 'lbl_offy', 'lbl_slider_target')),
            ('⑦ 预览', ('canvas',)),
            ('⑧ 图层前后', ('var_layer', 'lbl_layer_hint')),
            ('⑨ 特效', ('var_corner', 'var_corner_r')),
            ('⑩ 点阵羽化 + 增强开关', ('var_feather', 'var_feather_r', 'chk_feather',
                                        'scl_feather', 'var_alpha_feather', 'chk_alpha_feather')),
            ('⑪ 渲染模式', ('var_render', 'lbl_render_hint')),
            ('⑫ 图层列表', ('layer_list', 'btn_layer_add', 'btn_layer_del',
                             'var_lay_follow', 'var_lay_follow_r', 'lbl_layer_hint2')),
            ('⑬ 皮肤管理', ('skin_cb', 'btn_scheme', 'btn_scheme_restore',
                             'lbl_skin_hint', 'lbl_scheme_hint')),
            ('⑭ 开机自启', ('var_autostart', 'lbl_autostart')),
        ]
        for label, names in items:
            miss = [n for n in names if not hasattr(wiz, n)]
            check(f'C01 {label}：控件齐全（{len(names)} 个）', not miss, f'缺={miss}')
        # 可操作：按钮类不被禁用（⑩ 的增强开关在兼容模式下可点、点阵勾选可编辑）
        for name, want_state in (('btn_img', 'normal'), ('layer_list', 'normal'),
                                 ('chk_feather', 'normal'), ('chk_alpha_feather', 'normal'),
                                 ('var_autostart', None)):
            w = getattr(wiz, name, None)
            if w is None:
                check(f'C02 {name} 存在', False, '')
                continue
            try:
                st = str(w.cget('state'))
            except Exception:
                st = ''
            if want_state is None:
                check(f'C02 {name} 已就位', w is not None, st)
            else:
                check(f'C02 {name} 可操作（state={want_state}）', st == want_state, st)
        check('C03 关键控件都在滚动内容里（不是游离在窗口外）',
              all(_in_body(wiz, getattr(wiz, n)) for n in
                  ('canvas', 'layer_list', 'skin_cb', 'chk_feather', 'lbl_autostart')),
              '')
        check('C04 顶部区仍在滚动容器之外（不随内容滚）',
              not _in_body(wiz, wiz.top_area) and not _in_body(wiz, wiz.btn_row), '')
    finally:
        _restore(real)
        _kill(wiz)


# ==========================================================================
# D. 分项度量表（缩窗收益看得见）
# ==========================================================================
def test_metrics(tmp, cfg):
    section('D. 分项度量：adv / top_block / body_inner 三段需求高度')
    wiz, real = _wiz_probe(None, None, cfg)
    try:
        adv_h = wiz.adv_area.winfo_reqheight() if hasattr(wiz, 'adv_area') else 0
        top_h = wiz.top_block.winfo_reqheight() if hasattr(wiz, 'top_block') else 0
        body_h = wiz.body_inner.winfo_reqheight()
        cols_h = [c.winfo_reqheight() for c in getattr(wiz, 'adv_cols', []) or []]
        print(f'    分项：adv_area={adv_h}px（最高列 {max(cols_h) if cols_h else "?"}）'
              f'  top_block={top_h}px  body_inner={body_h}px  窗口需求高={wiz.root.winfo_reqheight()}px')
        print(f'    对照 R3：adv=901px（竖排一列）  body_inner=917px  窗口需求高=1038px')
        check('D01 ★高级设置块高度 ≤400（R3 竖排 901 → 横排收益）',
              hasattr(wiz, 'adv_area') and 0 < adv_h <= 400, f'adv_area={adv_h}')
        check('D02 ★内容需求高 ≤800（R3 基线 917）', body_h <= 800,
              f'body_inner={body_h}')
        check('D03 预览块高度保持（340~460，未被压缩）', 340 <= top_h <= 460,
              f'top_block={top_h}')
        check('D04 多列列高平衡（最高列 - 最矮列 ≤ 80px）',
              len(cols_h) >= 2 and (max(cols_h) - min(cols_h)) <= 80,
              f'列高={cols_h}')
    finally:
        _restore(real)
        _kill(wiz)


# ==========================================================================
# E. 守卫：运行期窗口尺寸记账（R3）不能被本项破坏
# ==========================================================================
def test_applied_size_guard():
    section('E. 守卫：R3 的 _applied_size 记账仍在运行期路径里')
    import inspect
    try:
        src_move = inspect.getsource(R.FollowOverlay._move_to)
    except Exception as e:
        src_move = ''
        check('E01 取到 _move_to 源码', False, repr(e))
    try:
        src_sync = inspect.getsource(R.FollowOverlay._sync_tk_geometry)
    except Exception as e:
        src_sync = ''
        check('E02 取到 _sync_tk_geometry 源码', False, repr(e))
    for name, src in (('E01 _move_to', src_move), ('E02 _sync_tk_geometry', src_sync)):
        check(f'{name} 仍写 _applied_size（窗口尺寸记账）',
              '_applied_size' in src, '')
    try:
        src_plan = inspect.getsource(R.FollowOverlay._plan_targets)
    except Exception:
        src_plan = ''
    check('E03 size_changed 判据仍以 _applied_size 为准（不是画布尺寸变更）',
          '_applied_size' in src_plan, '')
    check('E04 ConfigWizard 不再自带左右分栏（cols 已撤）',
          not hasattr(R.ConfigWizard, '_legacy_cols'), '')


# ==========================================================================
def main():
    print('=== B_test_r4_layout：R4 向导窗口重排（高级设置移到预览下方 + 横排多列）===')
    print('Python', sys.version.split()[0])
    tmp = tempfile.mkdtemp(prefix='r4_layout_')
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
    cfg = {'image': _make_png(os.path.join(tmp, 'r4a.png'), (120, 180)),
           'side': 'right', 'scale': 1.0,
           'layers': [{'image': os.path.join(tmp, 'r4a.png'),
                       'anchor': 'right_edge', 'z': 0},
                      {'image': _make_png(os.path.join(tmp, 'r4b.png'), (80, 200),
                                          (60, 90, 220, 255)),
                       'anchor': 'left_edge', 'z': 1}]}
    try:
        test_applied_size_guard()
        if not gui_ok:
            for t, cnt in (('A', 7), ('B', 12), ('C', 4), ('D', 4)):
                for i in range(1, cnt + 1):
                    SKIPPED.append(f'{t}{i:02d}')
                    print(f'  [SKIP] {t}{i:02d}  (无桌面环境（GUI 不可用）)')
        else:
            real_work_h = R.screen_work_area_height()
            test_structure(tmp, cfg)
            test_size(tmp, cfg, real_work_h)
            test_widget_inventory(tmp, cfg)
            test_metrics(tmp, cfg)
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
