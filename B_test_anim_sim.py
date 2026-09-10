# -*- coding: utf-8 -*-
"""B_test_anim_sim.py —— 动图支持（v1.6）离线验证

不启动外挂主循环（不碰 WinEventHook/托盘/真实窗口跟随），只验证动图管线的
关键性质：帧采样、时长钳位、多帧抠色键并集、按需解码 + LRU 上限、静态图回归。

运行: python B_test_anim_sim.py
"""
import os
import sys
import tempfile
import collections

import tkinter as tk
from PIL import Image, ImageTk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rime_char_overlay as R

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f'{"PASS" if cond else "FAIL"}  {name}{(" | " + detail) if detail else ""}')


def _make_gif(path, n_frames=12, size=(160, 240), magenta_at=5):
    """造一张动图 GIF：底色渐变 + 第 magenta_at 帧带一块纯品红（验动态键）"""
    frames = []
    for i in range(n_frames):
        im = Image.new('RGBA', size, (30 + i * 6, 60, 120, 255))
        # 左上角一块随帧变化的白块，便于肉眼区分帧
        for y in range(20 + i, 60 + i):
            for x in range(20, 60):
                im.putpixel((x, y), (250, 250, 250, 255))
        if i == magenta_at:
            for y in range(100, 140):
                for x in range(100, 140):
                    im.putpixel((x, y), (255, 0, 255, 255))
        frames.append(im.convert('P', palette=Image.ADAPTIVE))
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=80, loop=0, disposal=2)


class _FakeOverlay:
    """只带动图解码所需字段的壳（复用 FollowOverlay 的真实方法）"""


def main():
    tmp = tempfile.mkdtemp(prefix='anim_test_')
    gif = os.path.join(tmp, 'anim.gif')
    _make_gif(gif)

    print('=' * 60)
    # T1 帧采样
    check('T1a n<=limit 全取（不丢帧）',
          R._sample_frame_indices(12, 48) == list(range(12)))
    big = R._sample_frame_indices(1000, 48)
    check('T1b n>limit 均匀采样且含首末帧',
          len(big) <= 50 and big[0] == 0 and big[-1] == 999 and big == sorted(set(big)),
          f'len={len(big)}')

    # T2 帧时长钳位
    class _I:
        def __init__(self, d):
            self.info = {} if d is None else {'duration': d}
    check('T2a 缺省 duration → 100', R._frame_duration(_I(None)) == 100)
    check('T2b 过小 duration → 钳到下限', R._frame_duration(_I(1)) == R.ANIM_MIN_MS)
    check('T2c 过大 duration → 钳到上限', R._frame_duration(_I(99999)) == R.ANIM_MAX_MS)
    check('T2d 正常 duration 原样', R._frame_duration(_I(80)) == 80)

    # T3 动图识别 + 多帧抠色键并集
    src = Image.open(gif)
    n = int(getattr(src, 'n_frames', 1) or 1)
    check('T3a n_frames 识别为动图', n == 12, f'n={n}')
    src.seek(0)
    static_key = R.pick_key_color([src.convert('RGBA')], Image)
    check('T3b 仅首帧统计 → 品红可用（键=品红）', static_key == R.MAGENTA,
          f'key={static_key}')

    obj = _FakeOverlay()
    obj.anim_src = src
    obj.anim_n = n
    obj.cfg = dict(R.DEFAULT_CONFIG)      # 特效管线会读 cfg（真实实例里必有）
    obj.key_rgb = R.MAGENTA
    obj._Image = Image
    obj._ImageTk = ImageTk
    obj.anim_idx = 0
    obj._base_h = 300.0
    obj._frame_cache = collections.OrderedDict()
    root = tk.Tk()
    root.withdraw()
    obj.root = root
    # 桩对象：把 FollowOverlay 的真实方法绑上去（复用生产代码，不复制逻辑）
    obj._decode_frame = lambda i: R.FollowOverlay._decode_frame(obj, i)
    obj._get_frame = lambda i: R.FollowOverlay._get_frame(obj, i)

    key = R.FollowOverlay._pick_anim_key(obj, Image, n)
    check('T3c 全帧并集 → 品红被占用，自动换键', key != R.MAGENTA, f'key={key}')

    obj.key_rgb = key

    # T4 按需解码 + LRU 上限 + 当前帧不被淘汰
    first = R.FollowOverlay._get_frame(obj, 0)
    check('T4a 首帧可解码成 PhotoImage',
          first is not None and first.width() == int(160 * (300.0 / 240)),
          f'{first.width()}x{first.height()}')
    ok_size, ok_alive, max_seen = True, True, 0
    for i in range(0, 60):
        idx = i % n
        ph = R.FollowOverlay._get_frame(obj, idx)
        if ph is None:
            ok_alive = False
            break
        max_seen = max(max_seen, len(obj._frame_cache))
        if len(obj._frame_cache) > R.ANIM_CACHE_MAX:
            ok_size = False
        if idx not in obj._frame_cache:
            ok_alive = False   # 当前帧绝不能被淘汰
    check('T4b 帧缓存不超过上限', ok_size, f'max={max_seen} limit={R.ANIM_CACHE_MAX}')
    check('T4c 全程可解码且当前帧常驻缓存', ok_alive)
    # 大帧数（>100）也只解有限的帧（内存保护）
    check('T4d 缓存里始终只留少量帧（按需解码）',
          len(obj._frame_cache) <= R.ANIM_CACHE_MAX,
          f'{len(obj._frame_cache)} <= {R.ANIM_CACHE_MAX}')

    # T5 静态图回归：抠色管线行为不变（alpha 二值化 + 透明区填键色）
    st = Image.new('RGBA', (8, 8), (10, 20, 30, 255))
    st.putpixel((0, 0), (10, 20, 30, 0))     # 透明像素 → 应填键色
    st.putpixel((1, 1), (10, 20, 30, 200))   # 半透明 → 二值化为不透明
    out = R._flatten_alpha_for_tk(st, Image, (255, 0, 255))
    check('T5a 透明像素填键色', out.getpixel((0, 0))[:3] == (255, 0, 255))
    check('T5b 半透明像素二值化为不透明', out.getpixel((1, 1))[:3] == (10, 20, 30))
    check('T5c 输出 alpha 恒为 255', out.getpixel((0, 0))[3] == 255)

    try:
        root.destroy()
    except Exception:
        pass

    print('=' * 60)
    print(f'通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项')
    if FAIL:
        print('失败项: ' + ', '.join(FAIL))
        return 1
    print('ALL CHECKS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
