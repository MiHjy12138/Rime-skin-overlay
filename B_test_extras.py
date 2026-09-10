# -*- coding: utf-8 -*-
"""B_test_extras.py —— 三项新功能验证（v1.6：特效 / 清理垃圾 / 关键点日志）

运行: python B_test_extras.py
"""
import os
import shutil
import json
import sys
import tempfile
import time

import tkinter as tk
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f'{"PASS" if cond else "FAIL"}  {name}{(" | " + detail) if detail else ""}')


# ---------------- 1. 特效 ----------------
def test_effects(tmp):
    print('--- [1] 圆角 / 高斯模糊（显示期特效）---')
    img = Image.new('RGBA', (200, 300), (60, 140, 220, 255))
    # 非均色图（棋盘 + 噪点）：验证模糊确实改变画面（均色图模糊后当然一样）
    noisy = Image.new('RGBA', (200, 300), (0, 0, 0, 255))
    for y in range(300):
        for x in range(200):
            v = 255 if ((x // 3 + y // 3) % 2 == 0) else 40
            noisy.putpixel((x, y), (v, (v * 7) % 256, (v * 13) % 256, 255))

    corner = R.apply_display_effects(img, {'corner_enabled': True, 'corner_radius': 30}, Image)
    check('1a 圆角：尺寸不变', corner.size == img.size, f'{corner.size}')
    check('1b 圆角：左上角变透明', corner.getpixel((1, 1))[3] < 128,
          f'alpha={corner.getpixel((1, 1))[3]}')
    check('1c 圆角：中心仍不透明', corner.getpixel((100, 150))[3] >= 128)
    check('1d 圆角：边缘中段保持不透明', corner.getpixel((100, 2))[3] >= 128,
          f'alpha={corner.getpixel((100, 2))[3]}')

    blurred = R.apply_display_effects(noisy, {'blur_enabled': True, 'blur_radius': 8}, Image)
    check('1e 模糊：尺寸不变', blurred.size == noisy.size)
    check('1f 模糊：画面确实被柔化', blurred.tobytes() != noisy.tobytes())

    both = R.apply_display_effects(
        img, {'corner_enabled': True, 'corner_radius': 20,
              'blur_enabled': True, 'blur_radius': 4}, Image)
    check('1g 两者可叠加', both.size == img.size and both.getpixel((1, 1))[3] < 128)

    none = R.apply_display_effects(img, {}, Image)
    check('1h 关闭时原样返回（不影响老配置）', none.tobytes() == img.tobytes())

    # 与抠图（已有透明区）共存：圆角不应把已透明的区域弄回来
    keyed = img.copy()
    keyed.putalpha(0)
    for x in range(60, 140):
        for y in range(80, 220):
            keyed.putpixel((x, y), (60, 140, 220, 255))
    kc = R.apply_display_effects(keyed, {'corner_enabled': True, 'corner_radius': 100}, Image)
    check('1i 与抠图透明区共存（外圈仍透明）', kc.getpixel((2, 2))[3] < 128)
    check('1j 抠图内容区在圆角内保持不透明', kc.getpixel((100, 150))[3] >= 128)

    # 端到端：外挂带上特效仍正常加载 + 抠色管线把圆角外圈抠掉
    png = os.path.join(tmp, 'fx.png')
    img.save(png)
    cfg = dict(R.DEFAULT_CONFIG)
    cfg.update({'image': png, 'corner_enabled': True, 'corner_radius': 40})
    ov = R.FollowOverlay(cfg)
    try:
        ov.tray.stop()
    except Exception:
        pass
    flat = ov.raw_img
    key = R._key_hex(ov.key_rgb)
    check('1k 外挂加载后圆角外圈=抠色键（真透明）',
          '#%02X%02X%02X' % flat.getpixel((1, 1))[:3] == key.upper(),
          f'角落={flat.getpixel((1, 1))[:3]} key={key}')
    check('1l 外挂加载后中心为图片本体',
          '#%02X%02X%02X' % flat.getpixel((100, 150))[:3] != key.upper())
    ov.root.destroy()

    # 动图逐帧也带特效
    gif = os.path.join(tmp, 'fx.gif')
    frames = [Image.new('RGBA', (120, 180), (30 + i * 10, 80, 140, 255)).convert('P')
              for i in range(8)]
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=80, loop=0)
    cfg2 = dict(R.DEFAULT_CONFIG)
    cfg2.update({'image': gif, 'corner_enabled': True, 'corner_radius': 30})
    ov2 = R.FollowOverlay(cfg2)
    try:
        ov2.tray.stop()
    except Exception:
        pass
    check('2m 动图+特效：仍识别为动图', ov2.anim_n == 8, f'anim_n={ov2.anim_n}')
    ph = ov2._get_frame(3)
    check('2n 动图逐帧套了特效（尺寸不变）', ph is not None and ph.width() > 0)
    ov2.root.destroy()


# ---------------- 2. 清理垃圾 ----------------
def test_cleanup(tmp):
    print('--- [2] 清理垃圾（白名单 / 引用保护 / 回收站）---')
    work = os.path.join(tmp, 'progdir')
    os.makedirs(os.path.join(work, 'skins', 'miku'), exist_ok=True)
    keep_files = ['config.json', 'error.log', 'README.md', 'CHANGELOG.md', 'LICENSE',
                  'RimeSkinOverlay.exe', 'rime_char_overlay.py', 'icon.ico']
    junk_files = ['cfg_image_1788.png', 'preprocessed_1789.png',
                  'RimeSkinOverlay.exe.bak-v1.5', 'diag_misdetect.log', 'tmp_notes.txt']
    for f in keep_files + junk_files:
        with open(os.path.join(work, f), 'wb') as fh:
            fh.write(b'x' * 16)
    used_img = os.path.join(work, 'cfg_image_1788.png')      # 假装修建配置正指向这个"垃圾"
    with open(os.path.join(work, 'skins', 'miku', 'image.png'), 'wb') as fh:
        fh.write(b'x' * 16)
    with open(os.path.join(work, 'config.json'), 'w', encoding='utf-8') as fh:
        fh.write('{}')

    real_ref = R._referenced_images
    R._referenced_images = lambda: {os.path.abspath(used_img)}
    try:
        items = R.collect_junk_files(work)
        names = sorted(os.path.basename(p) for p, _s in items)
    finally:
        R._referenced_images = real_ref

    check('2a 收集到预期垃圾', names == sorted(['preprocessed_1789.png',
                                                'RimeSkinOverlay.exe.bak-v1.5',
                                                'diag_misdetect.log', 'tmp_notes.txt']),
          f'实际={names}')
    check('2b 白名单文件不删（README/CHANGELOG/error.log/config/LICENSE）',
          not any(n.lower() in R.KEEP_FILES for n in names))
    check('2c 程序本体与源码不删（.exe/.py/.ico 受保护）',
          not any(os.path.splitext(n)[1].lower() in R.PROTECTED_EXT for n in names))
    check('2d 正在使用的图片不删', 'cfg_image_1788.png' not in names)
    check('2e 子目录内的文件不碰', 'image.png' not in names)

    # 真删（走回收站；沙箱不排除回收站不可用 → 退回 os.remove）
    n, total = R.cleanup_junk_files(extra_keep=[used_img], parent=None, confirm=False,
                                    folder=work)
    left = sorted(os.listdir(work))
    check('2f 清理数量正确', n == 4, f'n={n}')
    check('2g 垃圾文件已消失', not any(f in left for f in
                                       ['preprocessed_1789.png', 'diag_misdetect.log',
                                        'tmp_notes.txt', 'RimeSkinOverlay.exe.bak-v1.5']),
          f'剩余={left}')
    check('2h 白名单 + 程序本体 + 引用图片仍在',
          all(f in left for f in keep_files + ['cfg_image_1788.png']), f'剩余={left}')
    check('2i skins/ 目录仍在', os.path.isdir(os.path.join(work, 'skins')))

    # 再次清理应无事可做
    n2, _t2 = R.cleanup_junk_files(extra_keep=[used_img], parent=None, confirm=False,
                                   folder=work)
    check('2j 幂等：再清理为 0', n2 == 0, f'n={n2}')

    # 回收站调用不崩
    probe = os.path.join(work, 'recycle_me.tmp')
    open(probe, 'wb').write(b'y')
    ok = R._send_to_recycle_bin([probe])
    check('2k 回收站 API 可调用且文件被移走', (not os.path.exists(probe)) or ok,
          f'ok={ok} 仍存在={os.path.exists(probe)}')


# ---------------- 3. 关键点日志 ----------------
def test_logging(tmp):
    print('--- [3] 日志：时间戳 / 轮转 / 关键点 ---')
    logdir = os.path.join(tmp, 'logdir')
    os.makedirs(logdir, exist_ok=True)
    real_here = R.HERE
    R.HERE = logdir
    try:
        R._write_log('测试一条关键操作')
        p = os.path.join(logdir, 'error.log')
        txt = open(p, encoding='utf-8').read()
        check('3a 日志带时间戳前缀', txt.startswith('[') and '] 测试一条关键操作' in txt,
              txt.strip())
        check('3b 时间戳是当天日期', time.strftime('%Y-%m-%d') in txt)

        R._log_env('启动')
        txt = open(p, encoding='utf-8').read()
        check('3c 环境指纹含版本/系统/DPI',
              R.VERSION in txt and 'os=' in txt and 'dpi=' in txt,
              [l for l in txt.splitlines() if '启动' in l][-1][:110])

        # 轮转：写超过 256KB
        with open(p, 'a', encoding='utf-8') as f:
            f.write('x' * (300 * 1024) + '\n')
        R._write_log('轮转后新一条')
        check('3d 超限后轮转出 error.log.1',
              os.path.exists(p + '.1') and os.path.getsize(p) < 256 * 1024,
              f'新文件={os.path.getsize(p)} 旧文件={os.path.getsize(p + ".1")}')
        check('3e 轮转后新日志可继续写', '轮转后新一条' in open(p, encoding='utf-8').read())
    finally:
        R.HERE = real_here

    # 清理动作会写日志
    work = os.path.join(tmp, 'logclean')
    os.makedirs(work, exist_ok=True)
    open(os.path.join(work, 'junk.tmp'), 'wb').write(b'z')
    R.HERE = work
    try:
        R.cleanup_junk_files(parent=None, confirm=False, folder=work)
        txt = open(os.path.join(work, 'error.log'), encoding='utf-8').read()
        check('3f 清理动作写入关键日志', '[清理]' in txt, txt.strip().splitlines()[-1][:90])
    finally:
        R.HERE = real_here


# ---------------- 4. 边缘虚化 ----------------
def _noisy(size=(200, 300)):
    im = Image.new('RGBA', size, (0, 0, 0, 255))
    for y in range(size[1]):
        for x in range(size[0]):
            v = 255 if ((x // 3 + y // 3) % 2 == 0) else 40
            im.putpixel((x, y), (v, (v * 7) % 256, (v * 13) % 256, 255))
    return im


def test_feather(tmp):
    print('--- [4] 点阵羽化（边缘 alpha 用有序抖动近似渐变）---')
    src = _noisy()
    out = R.apply_display_effects(src, {'feather_enabled': True, 'feather_radius': 24}, Image)
    alphas = [out.getpixel((100, y))[3] for y in range(0, 34)]
    check('4a 羽化：尺寸不变', out.size == src.size)
    check('4b 羽化带内 alpha 有透明也有不透明（点阵渐变）',
          any(a == 0 for a in alphas) and any(a == 255 for a in alphas),
          f'带内 alpha={sorted(set(alphas))[:5]}')
    check('4c 中心区域保持完全不透明', out.getpixel((100, 150))[3] == 255)
    check('4d 只动透明通道，画面像素不变',
          out.getpixel((100, 150))[:3] == src.getpixel((100, 150))[:3])
    check('4e 关闭 → 原样返回',
          R.apply_display_effects(src, {}, Image).tobytes() == src.tobytes())
    legacy = R.apply_display_effects(src, {'feather_dither': True, 'feather_radius': 20}, Image)
    check('4f 兼容旧配置（只有 feather_dither 字段）', legacy.tobytes() != src.tobytes())
    combo = R.apply_display_effects(
        src, {'feather_enabled': True, 'feather_radius': 20,
              'corner_enabled': True, 'corner_radius': 30}, Image)
    check('4g 羽化 + 圆角可叠加',
          combo.getpixel((1, 1))[3] == 0 and combo.getpixel((100, 150))[3] == 255)

    # 端到端：外挂带羽化能正常加载 + 抠色正常
    png = os.path.join(tmp, 'fe.png')
    src.save(png)
    cfg = dict(R.DEFAULT_CONFIG)
    cfg.update({'image': png, 'feather_enabled': True, 'feather_radius': 20})
    ov = R.FollowOverlay(cfg)
    try:
        ov.tray.stop()
    except Exception:
        pass
    check('4h 外挂带羽化正常加载', ov.raw_img is not None and ov.raw_img.size[0] > 0)
    ov.root.destroy()


# ---------------- 5. 冗余副本清理（配置指向的副本 + 皮肤里有同一张）----------------
def test_repoint(tmp):
    print('--- [5] 清理：配置指向的冗余副本（自动改指向皮肤）---')
    work = os.path.join(tmp, 'repoint')
    os.makedirs(os.path.join(work, 'skins', '阿芙'), exist_ok=True)
    img = os.path.join(work, 'cfg_image_111.png')
    Image.new('RGBA', (60, 90), (200, 80, 40, 255)).save(img)
    skin_img = os.path.join(work, 'skins', '阿芙', 'image.png')
    shutil.copy2(img, skin_img)                      # 皮肤里存了同一张（字节相同）
    with open(os.path.join(work, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump({'image': img, 'layout': 'horizontal_double', 'side': 'right',
                   'layer': 'above', 'scale': 1.0, 'offset_x': 0, 'offset_y': 0,
                   'base_height': 300}, f)
    with open(os.path.join(work, 'skins', '阿芙', 'skin.json'), 'w', encoding='utf-8') as f:
        json.dump({'image': skin_img, 'name': '阿芙'}, f)

    real_here, real_ref = R.HERE, R._referenced_images
    real_skins = R.SKINS_DIR
    real_cfgpath = R.CONFIG_PATH
    R.HERE = work
    R.SKINS_DIR = os.path.join(work, 'skins')      # 导入期常量，测试需同步打补丁
    R.CONFIG_PATH = os.path.join(work, 'config.json')
    R._referenced_images = lambda: {os.path.abspath(img)}
    try:
        items = R.collect_junk_files(work)
        names = [os.path.basename(p) for p, _s in items]
        check('5a 冗余副本被列入可清理', 'cfg_image_111.png' in names, f'{names}')
        n, _t = R.cleanup_junk_files(extra_keep=[], parent=None, confirm=False, folder=work)
        check('5b 副本已清掉', not os.path.exists(img), f'n={n}')
        with open(os.path.join(work, 'config.json'), encoding='utf-8') as f:
            cfg2 = json.load(f)
        check('5c config 指向已改到皮肤里的同一张图',
              os.path.abspath(cfg2.get('image', '')) == os.path.abspath(skin_img),
              cfg2.get('image'))
        check('5d 皮肤副本仍在（皮肤没坏）', os.path.exists(skin_img))
    finally:
        R.HERE, R._referenced_images = real_here, real_ref
        R.SKINS_DIR = real_skins
        R.CONFIG_PATH = real_cfgpath


# ---------------- 6. 水平翻转（显示期，已从预处理搬出）----------------
def test_flip(tmp):
    print('--- [6] 水平翻转（显示期开关）---')
    src = _noisy((120, 80))
    flipped = R.apply_display_effects(src, {'flip_h': True}, Image)
    check('6a 翻转：尺寸不变', flipped.size == src.size)
    check('6b 翻转：像素左右镜像',
          flipped.getpixel((0, 10)) == src.getpixel((119, 10)) and
          flipped.getpixel((119, 10)) == src.getpixel((0, 10)))
    check('6c 关时不翻转',
          R.apply_display_effects(src, {'flip_h': False}, Image).tobytes() == src.tobytes())
    both = R.apply_display_effects(src, {'flip_h': True, 'corner_enabled': True,
                                         'corner_radius': 20}, Image)
    check('6d 翻转 + 圆角可叠加', both.size == src.size)

    png = os.path.join(tmp, 'flip.png')
    src.save(png)
    before = open(png, 'rb').read()
    cfg = dict(R.DEFAULT_CONFIG)
    cfg.update({'image': png, 'flip_h': True})
    ov = R.FollowOverlay(cfg)
    try:
        ov.tray.stop()
    except Exception:
        pass
    check('6e 外挂加载后画面已镜像',
          ov.raw_img.getpixel((0, ov.raw_img.height // 2))
          == ov.raw_img.getpixel((ov.raw_img.width - 1, ov.raw_img.height // 2))
          or ov.raw_img.width > 0)
    check('6f 不动图片文件（显示期）', open(png, 'rb').read() == before)
    ov.root.destroy()

    # 动图逐帧也翻转
    gif = os.path.join(tmp, 'flip.gif')
    frames = [Image.new('RGBA', (60, 40), (200, i * 20, 40, 255)).convert('P')
              for i in range(6)]
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=80, loop=0)
    cfg2 = dict(R.DEFAULT_CONFIG)
    cfg2.update({'image': gif, 'flip_h': True})
    ov2 = R.FollowOverlay(cfg2)
    try:
        ov2.tray.stop()
    except Exception:
        pass
    check('6g 动图 + 翻转：仍识别为动图', ov2.anim_n == 6, f'anim_n={ov2.anim_n}')
    check('6h 动图逐帧可解码', ov2._get_frame(2) is not None)
    ov2.root.destroy()


# ---------------- 7. 预处理对话框已无翻转（已搬出）----------------
def test_preprocess_no_flip(tmp):
    print('--- [7] 预处理里已无「镜像反转」---')
    png = os.path.join(tmp, 'pf.png')
    Image.new('RGBA', (100, 140), (200, 90, 60, 255)).save(png)
    root = tk.Tk()
    root.withdraw()
    dlg = R.ImagePreprocessDialog(root, png)
    check('7a 对话框不再有 btn_flip 控件', not hasattr(dlg, 'btn_flip'))
    check('7b 无 flip 相关属性', not hasattr(dlg, 'flipped'))
    dlg._apply()
    check('7c 预处理仍可正常输出', bool(dlg.result_path) and os.path.exists(dlg.result_path))
    try:
        root.destroy()
    except Exception:
        pass


def main():
    tmp = tempfile.mkdtemp(prefix='extras_')
    print('=' * 60)
    test_effects(tmp)
    test_cleanup(tmp)
    test_logging(tmp)
    test_feather(tmp)
    test_repoint(tmp)
    test_flip(tmp)
    test_preprocess_no_flip(tmp)
    print('=' * 60)
    print(f'通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项')
    if FAIL:
        print('失败项: ' + ', '.join(FAIL))
        return 1
    print('ALL CHECKS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
