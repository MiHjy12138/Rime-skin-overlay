# -*- coding: utf-8 -*-
"""B_test_r20_preview.py —— 预览自适应缩放（先生实测：当前皮肤「直接出顶」）

先生原话（2026-09-27）：「还有个问题，预览窗口自适应缩放，当前皮肤直接出顶了。」

现象：⑦ 预览画布里图片顶到上边界外（被裁掉一截）。现场参数 = 竖版大图 + 缩放 0.6 +
      垂直 -132px。根因两条（改前实测）：
        ① fit 判定只比「图高 vs 画布高」，**偏移量没算进去** → -132 把图推出画布上边；
        ② `base_y` 用了硬编码 360，而画布高早已是 260 → 候选框整体偏下。
      本脚本先跑出红（越界 → FAIL），再改实现到绿。

红线：只读被测模块；不写真实 config.json（只在内存 cfg 上改）；
      文件对话框与消息框不打桩（本脚本不触发）。
用法: python B_test_r20_preview.py
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
_TRUE_HERE = R.HERE


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


def _big_png(path, size=(900, 1350), color=(120, 60, 200, 255)):
    """竖版大图（先生的立绘就是这个比例：明显高于预览画布）"""
    im = Image.new('RGBA', size, (0, 0, 0, 0))
    w, h = size
    for y in range(int(h * 0.05), int(h * 0.95)):
        for x in range(int(w * 0.1), int(w * 0.9)):
            im.putpixel((x, y), color)
    im.save(path)
    return path


def _cfg(img, scale=0.6, offx=0, offy=0):
    return {'image': img, 'layout': 'horizontal_double', 'side': 'right',
            'scale': scale, 'offset_x': offx, 'offset_y': offy, 'layer': 'above',
            'corner_enabled': False, 'corner_radius': 24,
            'feather_enabled': False, 'feather_radius': 24, 'flip_h': False}


def _wiz(cfg):
    w = R.ConfigWizard(on_done=lambda c: None, overlay=None)
    w.cfg.update(cfg)
    w._layer_sync_from_cfg()
    w.root.update_idletasks()
    w.root.update()
    w._update_preview()
    w.root.update_idletasks()
    w.root.update()
    return w


def _kill(w):
    try:
        w.root.destroy()
    except Exception:
        pass


def _boxes(cv):
    """画布里所有可见 item 的外接框 [(x0, y0, x1, y1), ...]"""
    out = []
    for it in cv.find_all():
        try:
            bb = cv.bbox(it)
        except Exception:
            bb = None
        if bb:
            out.append(tuple(int(v) for v in bb))
    return out


def _judge_bound(w, name, detail=''):
    """判据：画布内**一切内容**都不许越界（留 1px 容差）"""
    cv = w.canvas
    cw, ch = int(R.ConfigWizard.CV_W), int(R.ConfigWizard.CV_H)
    bs = _boxes(cv)
    bad = [b for b in bs if b[0] < -1 or b[1] < -1 or b[2] > cw + 1 or b[3] > ch + 1]
    check(name,
          bool(bs) and not bad,
          f'画布={cw}x{ch} 共 {len(bs)} 个元素，越界 {len(bad)} 个：{bad[:3]}  {detail}')
    return bs, bad


# ==========================================================================
# A. 单层：大图 + 缩放 0.6（先生现场参数的基础形态）
# ==========================================================================
def test_single_basic(tmp):
    section('A. 单层大图（900×1350，缩放 0.6，无偏移）：预览不出界')
    img = _big_png(os.path.join(tmp, 'r20a.png'))
    w = _wiz(_cfg(img))
    try:
        _judge_bound(w, 'A01 ★单层大图：预览内容全部落在画布内（不出顶 / 不出底）')
        bs = _boxes(w.canvas)
        h = max(b[3] for b in bs) - min(b[1] for b in bs) if bs else 0
        check('A02 ★内容占据画布的主要高度（不是被缩成一小块）',
              h >= int(R.ConfigWizard.CV_H * 0.5), f'内容高={h} 画布高={R.ConfigWizard.CV_H}')
    finally:
        _kill(w)


# ==========================================================================
# B. 单层 + 先生现场参数（垂直 -132）—— 就是「直接出顶」那一张
# ==========================================================================
def test_single_offsets(tmp):
    section('B. 单层 + 先生现场参数（缩放 0.6 / 水平 -132 / 垂直 -132）：不出顶')
    img = _big_png(os.path.join(tmp, 'r20b.png'))
    for tag, ox, oy in (('B1 垂直 -132', 0, -132),
                        ('B2 水平 -132', -132, 0),
                        ('B3 双 -132（现场）', -132, -132)):
        w = _wiz(_cfg(img, offx=ox, offy=oy))
        try:
            _judge_bound(w, f'B0★ {tag}：预览内容全部落在画布内', f'offx={ox} offy={oy}')
        finally:
            _kill(w)


# ==========================================================================
# C. 候选框居中（base_y 曾用硬编码 360 → 画布高 260 时整体偏下）
# ==========================================================================
def test_candidate_centered(tmp):
    section('C. 候选框在画布内垂直居中（不再用硬编码 360 定位）')
    img = _big_png(os.path.join(tmp, 'r20c.png'))
    w = _wiz(_cfg(img, scale=0.2, offx=0, offy=0))   # 小图：候选框是内容的决定项
    try:
        bs = _boxes(w.canvas)
        ch = int(R.ConfigWizard.CV_H)
        if not bs:
            check('C01 画布里有内容', False, '空画布')
            return
        top = min(b[1] for b in bs)
        bottom = ch - max(b[3] for b in bs)
        # 阈值 30（不是更小的数）：预览内容除「图 + 候选框」外还有候选框下方那行类型名
        # （画在框外），上下留白天然不完全对称 —— 实测修复后 87 / 64（差 23）。
        # 判别力：修 base_y 之前是 137 / 14（差 123），照样抓得住。
        check('C01 ★内容在画布内上下留白基本均衡（不偏下；差 ≤30）',
              abs(top - bottom) <= 30, f'上留白={top} 下留白={bottom}')
    finally:
        _kill(w)


# ==========================================================================
# D. 多图层 + 偏移：同一口径
# ==========================================================================
def test_multi(tmp):
    section('D. 多图层 + 偏移：同样不许越界')
    a = _big_png(os.path.join(tmp, 'r20d1.png'), color=(200, 40, 40, 255))
    b = _big_png(os.path.join(tmp, 'r20d2.png'), size=(600, 900), color=(40, 40, 200, 255))
    cfg = _cfg(a)
    cfg['layers'] = [{'image': a, 'anchor': 'right_edge', 'scale': 0.6,
                      'flip': False, 'offset_x': 0, 'offset_y': -132},
                     {'image': b, 'anchor': 'left_edge', 'scale': 0.6,
                      'flip': False, 'offset_x': 0, 'offset_y': 120}]
    w = _wiz(cfg)
    try:
        _judge_bound(w, 'D01 ★多层 + 偏移：预览内容全部落在画布内')
    finally:
        _kill(w)


def main():
    if not PIL_OK:
        print('PIL 不可用 → 全部跳过')
        return 2
    if not _has_gui():
        print('无 GUI（tkinter 起不来）→ 全部跳过')
        return 2
    tmp = tempfile.mkdtemp(prefix='r20_')
    R.HERE = tmp
    try:
        test_single_basic(tmp)
        test_single_offsets(tmp)
        test_candidate_centered(tmp)
        test_multi(tmp)
    finally:
        R.HERE = _TRUE_HERE
        shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n=== B_test_r20_preview：{len(PASS)} PASS / {len(FAIL)} FAIL ===')
    if FAIL:
        print('FAIL 明细：')
        for f in FAIL:
            print(f'  · {f}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
