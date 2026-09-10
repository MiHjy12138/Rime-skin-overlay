# -*- coding: utf-8 -*-
"""B_test_anim_live.py —— 动图支持（v1.6）实机烟雾测试（真窗口，约 3s）

与 B_test_anim_sim.py 不同：这里真的把 FollowOverlay 跑起来（真 Tk 窗口 + 真 after 节拍），
确认「动图在运行中真的在换帧」+ 静态图不受影响 + 向导预览动画可用 + 无 _anim_tick 异常。

运行: python B_test_anim_live.py
"""
import os
import sys
import time
import tempfile

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rime_char_overlay as R

LOG = os.path.join(R.HERE, 'error.log')
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f'{"PASS" if cond else "FAIL"}  {name}{(" | " + detail) if detail else ""}')


def _log_size():
    try:
        return os.path.getsize(LOG)
    except OSError:
        return 0


def _log_tail_from(offset):
    try:
        with open(LOG, encoding='utf-8', errors='replace') as f:
            f.seek(offset)
            return f.read()
    except Exception:
        return ''


def _make_gif(path, n=12, size=(120, 180), duration=80):
    frames = []
    for i in range(n):
        im = Image.new('RGBA', size, (20 + i * 8, 70, 130, 255))
        for y in range(10 + i, 40 + i):
            for x in range(10, 40):
                im.putpixel((x, y), (245, 245, 245, 255))
        frames.append(im.convert('P'))
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=duration, loop=0, disposal=2)


def test_overlay(gif, png):
    print('--- [1] FollowOverlay 真实运行（动图）---')
    off = _log_size()
    cfg = dict(R.DEFAULT_CONFIG)
    cfg['image'] = gif
    cfg['scale'] = 1.0
    ov = R.FollowOverlay(cfg)
    try:
        ov.tray.stop()
    except Exception:
        pass
    check('1a 识别为动图', ov.anim_n == 12, f'anim_n={ov.anim_n}')
    check('1b 动图帧已建 PhotoImage', ov.img is not None)

    # 无候选框时窗口不显示 → 强制 pinned+visible 让动画真正跑起来
    ov.pinned = True
    ov.visible = True
    ov.root.deiconify()
    samples = []
    t_end = time.time() + 1.2
    while time.time() < t_end:
        ov.root.update()
        samples.append(ov.anim_idx)
        time.sleep(0.08)
    uniq = len(set(samples))
    check('1c 运行中帧号在推进（真播放）', uniq >= 4, f'不同帧号={uniq} of 12')
    check('1d 帧号始终在 0..n-1 内', all(0 <= s < 12 for s in samples),
          f'min={min(samples)} max={max(samples)}')
    check('1e 帧缓存不超上限', len(ov._frame_cache) <= R.ANIM_CACHE_MAX,
          f'{len(ov._frame_cache)} <= {R.ANIM_CACHE_MAX}')

    # 隐藏 → 暂停（帧号不再变化）
    ov.visible = False
    ov.root.withdraw()
    for _ in range(12):
        ov.root.update()
        time.sleep(0.05)
    idx_before = ov.anim_idx
    for _ in range(12):
        ov.root.update()
        time.sleep(0.05)
    check('1f 窗口隐藏时动画暂停', ov.anim_idx == idx_before,
          f'{idx_before} -> {ov.anim_idx}')
    ov.root.destroy()

    tail = _log_tail_from(off)
    check('1g 无 _anim_tick 异常', '[_anim_tick]' not in tail, '日志干净' if '[_anim_tick]' not in tail else tail[:200])

    print('--- [2] 静态图回归（不应进入动画模式）---')
    cfg2 = dict(R.DEFAULT_CONFIG)
    cfg2['image'] = png
    ov2 = R.FollowOverlay(cfg2)
    try:
        ov2.tray.stop()
    except Exception:
        pass
    check('2a 静态图 anim_n<=1', ov2.anim_n <= 1, f'anim_n={ov2.anim_n}')
    check('2b 静态图未排动画节拍', not ov2.anim_after)
    check('2c 静态图 raw_img 已生成（老管线）', ov2.raw_img is not None)
    ov2.root.destroy()


def test_wizard(gif):
    print('--- [3] 向导「预览动画」---')
    import tkinter as tk
    w = R.ConfigWizard(on_done=lambda c: None)
    try:
        w.cfg['image'] = gif
        w._anim_n = 12
        w.btn_anim.config(state='normal', text='▶ 预览动画(12帧)')
        w._update_preview()
        w._toggle_anim_preview()
        check('3a 播放中标志已置位', w._anim_on)
        check('3b 按钮变为停止态', '停止' in w.btn_anim.cget('text'))
        samples = []
        t_end = time.time() + 0.9
        while time.time() < t_end:
            w.root.update()
            samples.append(w._anim_idx)
            time.sleep(0.08)
        check('3c 预览在换帧', len(set(samples)) >= 3, f'不同帧号={len(set(samples))}')
        w._toggle_anim_preview()
        check('3d 可停止播放', not w._anim_on and w._anim_after is None)
        check('3e 停止后回到首帧', w._anim_idx == 0)
    finally:
        try:
            w._on_cancel()
        except Exception:
            pass


def main():
    tmp = tempfile.mkdtemp(prefix='anim_live_')
    gif = os.path.join(tmp, 'anim.gif')
    png = os.path.join(tmp, 'static.png')
    _make_gif(gif)
    Image.new('RGBA', (120, 180), (200, 90, 60, 255)).save(png)

    print('=' * 60)
    test_overlay(gif, png)
    test_wizard(gif)
    print('=' * 60)
    print(f'通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项')
    if FAIL:
        print('失败项: ' + ', '.join(FAIL))
        return 1
    print('ALL CHECKS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
