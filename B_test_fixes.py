# -*- coding: utf-8 -*-
"""B_test_fixes.py —— 实机反馈三项修复的离线/半实机验证（v1.6）

1) 托盘/向导连点 → 不再叠出多个配置窗（open_wizard 单实例守卫）
2) 动图预处理后仍是动图（APNG 输出，皮肤继续会动）
3) --tray 开机静默启动到托盘（不弹选择框、不显示窗口）

运行: python B_test_fixes.py
"""
import os
import sys
import time
import subprocess
import tempfile

import tkinter as tk
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f'{"PASS" if cond else "FAIL"}  {name}{(" | " + detail) if detail else ""}')


def make_gif(path, n=12, size=(160, 240), duration=80):
    frames = []
    for i in range(n):
        im = Image.new('RGBA', size, (20 + i * 8, 70, 130, 255))
        for y in range(10 + i, 44 + i):
            for x in range(10, 44):
                im.putpixel((x, y), (245, 245, 245, 255))
        frames.append(im.convert('P'))
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=duration, loop=0, disposal=2)


def test_anim_preprocess(tmp):
    print('--- [2] 动图预处理后仍是动图 ---')
    gif = os.path.join(tmp, 'anim.gif')
    make_gif(gif)

    root = tk.Tk()
    root.withdraw()
    dlg = R.ImagePreprocessDialog(root, gif)
    check('2a 对话框识别动图帧数', dlg.n_frames == 12, f'n_frames={dlg.n_frames}')

    # 动点真格：裁剪 + 水平翻转，再应用
    dlg.crop = (20, 30, 140, 210)
    dlg._toggle_flip()
    dlg._apply()
    out = dlg.result_path
    check('2b 产出文件存在', bool(out) and os.path.exists(out), str(out))
    check('2c 产出仍是 .png（APNG）', out.endswith('.png'))
    im = Image.open(out)
    n = int(getattr(im, 'n_frames', 1) or 1)
    check('2d 产出仍是动图', n == 12, f'n_frames={n}')
    check('2e 帧时长保留', int(im.info.get('duration') or 0) == 80,
          f"duration={im.info.get('duration')}")
    check('2f 帧尺寸随裁剪变化', im.size[0] < 160 or im.size[1] < 240, f'size={im.size}')
    # 逐帧内容不同（真动图，不是复制同一帧）
    im.seek(0); f0 = im.convert('RGB').tobytes()
    im.seek(6); f6 = im.convert('RGB').tobytes()
    check('2g 各帧内容不同（真动图帧序列）', f0 != f6)
    try:
        root.destroy()
    except Exception:
        pass

    # 端到端：预处理产物喂给外挂 → 仍然识别为动图并播放
    cfg = dict(R.DEFAULT_CONFIG)
    cfg['image'] = out
    ov = R.FollowOverlay(cfg)
    try:
        ov.tray.stop()
    except Exception:
        pass
    check('2h 外挂识别预处理产物为动图', ov.anim_n == 12, f'anim_n={ov.anim_n}')
    ov.pinned = True
    ov.visible = True
    ov.root.deiconify()
    seen = set()
    t_end = time.time() + 0.8
    while time.time() < t_end:
        ov.root.update()
        seen.add(ov.anim_idx)
        time.sleep(0.06)
    check('2i 预处理后的皮肤真的在播放', len(seen) >= 3, f'不同帧号={len(seen)}')
    ov.root.destroy()

    # 静态图回归
    png = os.path.join(tmp, 'static.png')
    Image.new('RGBA', (120, 180), (200, 90, 60, 255)).save(png)
    root2 = tk.Tk()
    root2.withdraw()
    d2 = R.ImagePreprocessDialog(root2, png)
    d2._apply()
    im2 = Image.open(d2.result_path)
    check('2j 静态图预处理仍为单帧', int(getattr(im2, 'n_frames', 1) or 1) == 1)
    try:
        root2.destroy()
    except Exception:
        pass


def test_wizard_guard(tmp):
    print('--- [1] 连点托盘/菜单不再叠出多个配置窗 ---')
    png = os.path.join(tmp, 'static.png')
    cfg = dict(R.DEFAULT_CONFIG)
    cfg['image'] = png
    ov = R.FollowOverlay(cfg)
    try:
        ov.tray.stop()
    except Exception:
        pass

    created = []
    real_wizard = R.ConfigWizard

    class Counting(real_wizard):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            created.append(self)

    R.ConfigWizard = Counting
    state = {}

    def act1():
        ov.open_wizard()          # 第一次：正常打开（会阻塞在嵌套 mainloop）

    def act2():
        # 第二次/第三次连点：应命中守卫 —— 立即返回并把已有窗提到前面
        t0 = time.time()
        ov.open_wizard()
        state['guard_ms'] = (time.time() - t0) * 1000
        state['same'] = (ov._wizard is created[0]) if created else False
        state['n_created'] = len(created)

    def close():
        try:
            ov._wizard._on_cancel()
        except Exception as e:
            state['close_err'] = repr(e)

    try:
        ov.root.after(200, act1)
        ov.root.after(700, act2)
        ov.root.after(900, act2)   # 再点一次
        ov.root.after(1200, close)
        ov.root.after(1600, ov.root.destroy)
        ov.root.mainloop()
    finally:
        R.ConfigWizard = real_wizard

    check('1a 只创建了 1 个配置窗', state.get('n_created') == 1,
          f"n_created={state.get('n_created')}")
    check('1b 后到的点击命中同一窗口（未新建）', state.get('same') is True)
    check('1c 守卫立即返回（<50ms）', state.get('guard_ms', 9999) < 50,
          f"guard={state.get('guard_ms', -1):.1f}ms")


def test_tray_mode(tmp):
    print('--- [3] --tray 开机静默启动到托盘 ---')
    # 造一个独立工作目录：模块副本 + config.json + 图片
    work = os.path.join(tmp, 'trayrun')
    os.makedirs(work, exist_ok=True)
    import shutil
    shutil.copy2(os.path.join(BASE, 'rime_char_overlay.py'), work)
    # 用一个测试专用互斥体名：本机可能正跑着一个真实例（占着正式互斥体），
    # 不隔离的话新进程会直接「已有实例在跑」退出，测不到静默托盘路径。
    mod_path = os.path.join(work, 'rime_char_overlay.py')
    src = open(mod_path, encoding='utf-8').read()
    src = src.replace("LOCK_NAME = 'RimeSkinOverlay_SingleInstance'",
                      "LOCK_NAME = 'RimeSkinOverlay_SingleInstance_TESTONLY'")
    open(mod_path, 'w', encoding='utf-8').write(src)
    png = os.path.join(work, 'skin.png')
    Image.new('RGBA', (120, 180), (90, 160, 220, 255)).save(png)
    with open(os.path.join(work, 'config.json'), 'w', encoding='utf-8') as f:
        f.write('{"image": %s, "layout": "horizontal_double", "side": "right", '
                '"layer": "above", "scale": 1.0, "offset_x": 0, "offset_y": 0, '
                '"base_height": 300, "autostart": true}'
                % ('"' + png.replace('\\', '\\\\') + '"'))

    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    p = subprocess.Popen([sys.executable, os.path.join(work, 'rime_char_overlay.py'), '--tray'],
                         cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    time.sleep(5)
    alive = p.poll() is None
    check('3a --tray 进程在后台活着', alive)

    # 该进程不应该有可见窗口（托盘模式：窗口隐藏，只在候选框出现时显示）
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    vis = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == p.pid and u32.IsWindowVisible(hwnd):
            cls = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(hwnd, cls, 256)
            vis.append(cls.value)
        return True

    u32.EnumWindows(cb, 0)
    check('3b 没有可见的程序窗口（只有托盘）', len(vis) == 0, f'可见窗口={vis}')

    log = os.path.join(work, 'error.log')
    txt = open(log, encoding='utf-8', errors='replace').read() if os.path.exists(log) else ''
    check('3c 日志确认走的是静默托盘路径', '--tray 静默启动到托盘' in txt,
          txt.strip().splitlines()[-1] if txt.strip() else '(无日志)')

    p.terminate()
    try:
        p.wait(timeout=5)
    except Exception:
        pass


def main():
    tmp = tempfile.mkdtemp(prefix='fixes_')
    print('=' * 60)
    test_anim_preprocess(tmp)
    test_wizard_guard(tmp)
    test_tray_mode(tmp)
    print('=' * 60)
    print(f'通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项')
    if FAIL:
        print('失败项: ' + ', '.join(FAIL))
        return 1
    print('ALL CHECKS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
