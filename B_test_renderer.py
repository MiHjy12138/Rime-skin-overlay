# -*- coding: utf-8 -*-
"""B_test_renderer.py —— v2.0-①a 渲染层收口验证（Renderer 接口 + CompatRenderer）

对照《Rime皮肤外挂-升级操作手册》① 步 1/2 的验收：
  A. render_mode 选择逻辑：缺键 / 非法值 / 大小写 → compat 兜底（手册 ① 步 1）
  B. create_renderer 分派 + 构造失败兜底；LayeredRenderer 骨架就位（alpha 期不改对外行为）
  C. CompatRenderer 产出与 _flatten_alpha_for_tk 旧路径逐像素一致（PIL 层 + PhotoImage 层）
  D. FollowOverlay 集成：load_char 收口成 Renderer 调用；切皮肤 / 热重载 / 滚轮缩放仍走 compat；
     alpha 配置的对外表现与 compat 逐像素一致；动图桩（无 renderer 字段）懒补建不崩

红线：只读被测模块；皮肤档案写临时目录（不碰真实 skins/）；save_config 打桩（不写真实 config.json）。

用法: python B_test_renderer.py
"""
import os
import sys
import time
import tempfile
import collections

import tkinter as tk
from PIL import Image, ImageTk

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R          # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f'  [PASS] {name}' + (f'  ({detail})' if detail else ''))
    else:
        FAIL.append(name)
        print(f'  [FAIL] {name}' + (f'  ({detail})' if detail else ''))


def _photo_pixels(photo, w, h, step=1):
    """逐像素读 PhotoImage。

    Pillow 12 的 ImageTk.PhotoImage 不再是 tkinter.PhotoImage 子类（无 get/write），
    只能走 tcl 原生命令 <name> get x y —— 返回 (r,g,b) 或不透明时的 (r,g,b,a)。
    """
    name, tkc = str(photo), photo.tk
    out = []
    for y in range(0, h, step):
        for x in range(0, w, step):
            out.append(tuple(tkc.call(name, 'get', x, y)))
    return out


class _StubOverlay:
    """只带渲染层所需字段的壳（不用真窗口）"""

    def __init__(self, root, cfg=None):
        self.root = root
        self.cfg = dict(R.DEFAULT_CONFIG) if cfg is None else cfg
        self._Image = Image
        self._ImageTk = ImageTk


def _test_imgs():
    """一批有代表性的 RGBA 测试图（透明底 / 半透明 / 含品红 / 纯不透明 / 奇数尺寸 / 1x1）"""
    out = []
    im = Image.new('RGBA', (40, 60), (0, 0, 0, 0))          # 全透明底
    for y in range(10, 50):
        for x in range(8, 32):
            im.putpixel((x, y), (200, 60, 40, 255))
    for y in range(20, 30):                                  # 半透明带（紫边根源）
        for x in range(8, 32):
            im.putpixel((x, y), (250, 120, 200, 60))
    im.putpixel((0, 0), (255, 0, 255, 255))                  # 含纯品红
    out.append(('透明底+半透明+品红', im))

    out.append(('纯不透明', Image.new('RGBA', (33, 21), (12, 34, 56, 255))))
    out.append(('全透明', Image.new('RGBA', (20, 20), (0, 0, 0, 0))))
    out.append(('1x1 透明', Image.new('RGBA', (1, 1), (0, 0, 0, 0))))
    out.append(('1x1 不透明', Image.new('RGBA', (1, 1), (7, 8, 9, 255))))
    rg = Image.new('RGBA', (24, 18))
    for y in range(18):
        for x in range(24):
            rg.putpixel((x, y), (x * 10 % 256, y * 12 % 256, (x + y) * 5 % 256, (x * y) % 256))
    out.append(('alpha 渐变', rg))
    return out


def main():
    print('=== v2.0-①a 渲染层收口验证：Renderer 接口 + CompatRenderer ===')
    print('Python', sys.version.split()[0])
    import tkinter
    print('tk', tkinter.TkVersion)
    try:
        probe = tkinter.Tk()
        probe.withdraw()
        probe.update()
        probe.destroy()
    except Exception as e:
        print('SKIP：GUI 不可用 ->', repr(e))
        return 0

    tmp = tempfile.mkdtemp(prefix='renderer_test_')
    img_path = os.path.join(BASE, 'char.png')
    if not os.path.exists(img_path):     # 夹具兜底（160x240 透明底 RGBA）
        Image.new('RGBA', (160, 240), (0, 0, 0, 0)).save(img_path)
        print('[夹具] 现场生成 char.png（160x240 透明底 RGBA）')
    img2_path = os.path.join(tmp, 'skin2.png')
    Image.new('RGBA', (80, 120), (30, 150, 90, 255)).save(img2_path)
    gif_path = os.path.join(tmp, 'anim.gif')
    frames = []
    for i in range(4):
        f = Image.new('RGBA', (60, 90), (0, 0, 0, 0))
        for y in range(10, 80):
            for x in range(10, 50):
                f.putpixel((x, y), (30 * i + 20, 90, 220, 255))
        frames.append(f.convert('P', palette=Image.ADAPTIVE))
    frames[0].save(gif_path, save_all=True, append_images=frames[1:],
                   duration=80, loop=0, disposal=2)

    root = None
    overlays = []
    try:
        root = tk.Tk()
        root.withdraw()
        root.update()
        stub = _StubOverlay(root)

        # ---------------- A. render_mode 选择逻辑 ----------------
        print('\n[A] render_mode 选择逻辑（缺键/非法 → compat）')
        check('A1 缺 render_mode 键 → compat',
              R.resolve_render_mode({}) == 'compat', R.resolve_render_mode({}))
        check('A2 cfg=None → compat', R.resolve_render_mode(None) == 'compat')
        check('A3 显式 compat → compat',
              R.resolve_render_mode({'render_mode': 'compat'}) == 'compat')
        check('A4 显式 alpha → alpha',
              R.resolve_render_mode({'render_mode': 'alpha'}) == 'alpha')
        check('A5 空白/大小写宽松（" Alpha " / "ALPHA" / " compat "）',
              R.resolve_render_mode({'render_mode': ' Alpha '}) == 'alpha'
              and R.resolve_render_mode({'render_mode': 'ALPHA'}) == 'alpha'
              and R.resolve_render_mode({'render_mode': ' compat '}) == 'compat')
        bad = ['xyz', '', ' ', 'alphas', 'layered', 'compat ', 'α', 'alpha2']
        vals = [(v, R.resolve_render_mode({'render_mode': v})) for v in bad]
        check('A6 拼写不对的值一律 compat',
              all(r == 'compat' for _v, r in vals), repr(vals))
        weird = [None, True, False, 1, 0, 1.5, ['alpha'], {'a': 'alpha'}, (('a', 'b'),)]
        wv = [(v, R.resolve_render_mode({'render_mode': v})) for v in weird]
        check('A7 非字符串脏值一律 compat',
              all(r == 'compat' for _v, r in wv), repr(wv))
        check('A8 DEFAULT_CONFIG 含 render_mode 且默认 compat',
              R.DEFAULT_CONFIG.get('render_mode') == 'compat',
              repr(R.DEFAULT_CONFIG.get('render_mode')))
        check('A9 RENDER_MODES 常量恰为 compat/alpha',
              tuple(R.RENDER_MODES) == ('compat', 'alpha'), repr(R.RENDER_MODES))
        check('A10 非映射 cfg（list/str）不抛异常且 → compat',
              R.resolve_render_mode([]) == 'compat'
              and R.resolve_render_mode('alpha') == 'compat')

        # ---------------- B. create_renderer 分派与骨架 ----------------
        print('\n[B] create_renderer 分派 + LayeredRenderer 骨架')
        r_default = R.create_renderer(stub)
        check('B1 缺键 cfg → CompatRenderer(compat)',
              type(r_default) is R.CompatRenderer and r_default.mode == 'compat',
              r_default.describe())
        r_bad = R.create_renderer(stub, {'render_mode': 'bogus'})
        check('B2 非法值 → CompatRenderer',
              type(r_bad) is R.CompatRenderer, r_bad.describe())
        r_alpha = R.create_renderer(stub, {'render_mode': 'alpha'})
        check('B3 alpha → LayeredRenderer(alpha)',
              type(r_alpha) is R.LayeredRenderer and r_alpha.mode == 'alpha',
              r_alpha.describe())
        check('B4 LayeredRenderer 是 CompatRenderer/Renderer 子类（骨架可继承老路径）',
              issubclass(R.LayeredRenderer, R.CompatRenderer)
              and issubclass(R.CompatRenderer, R.Renderer)
              and issubclass(R.LayeredRenderer, R.Renderer))
        check('B5 LayeredRenderer 已完成实装（①b：alpha_ready=True，不再骨架期空转）',
              R.LayeredRenderer.alpha_ready is True
              and R.LayeredRenderer.uses_tk_label is False)
        skeleton = ('ensure_layered', 'premultiply_bgra', 'push_bitmap', 'push_frame',
                    'make_label', 'apply_window', 'apply_label', 'apply_photo_only',
                    'flatten', 'to_photo', 'prepare', 'release')
        missing = [n for n in skeleton if not callable(getattr(R.LayeredRenderer, n, None))]
        check('B6 t3 实装所需接口全部就位', not missing, f'missing={missing}')
        # 基类接口 = FollowOverlay 实际会调的那套（ensure_layered/premultiply_bgra/
        # push_bitmap 是 LayeredRenderer 的内部实现细节，不属于对外契约）
        base_api = ('pick_key', 'flatten', 'to_photo', 'prepare', 'make_label',
                    'apply_window', 'apply_label', 'apply_photo_only', 'push_frame',
                    'on_moved', 'on_shown', 'release', 'describe')
        base_missing = [n for n in base_api if not callable(getattr(R.Renderer, n, None))]
        check('B7 Renderer 基类对外接口完整（FollowOverlay 只认这套）',
              not base_missing, f'missing={base_missing}')
        check('B8 alpha 实装能力齐备（向量化预乘 + 分层窗推送 + 状态复位）',
              callable(R.LayeredRenderer.premultiply_bgra)
              and callable(R.LayeredRenderer.push_bitmap)
              and callable(R.LayeredRenderer.ensure_layered)
              and callable(R.LayeredRenderer.make_bmi)
              and R.LayeredRenderer.alpha_ready is True)
        check('B9 Renderer 接口默认 mode / uses_tk_label 自洽',
              R.Renderer.mode == 'compat' and R.CompatRenderer.uses_tk_label is True)

        # 构造失败兜底
        class _Boom(R.Renderer):
            def __init__(self, overlay, mode=None):
                raise RuntimeError('boom')

        saved = R.RENDERER_CLASSES['alpha']
        R.RENDERER_CLASSES['alpha'] = _Boom
        try:
            r_fb = R.create_renderer(stub, {'render_mode': 'alpha'})
            check('B10 渲染器构造失败 → 回落 compat（渲染层不是崩溃源）',
                  type(r_fb) is R.CompatRenderer, r_fb.describe())
        finally:
            R.RENDERER_CLASSES['alpha'] = saved

        # ---------------- C. 逐像素等价（老路径原样承载）----------------
        print('\n[C] CompatRenderer 与 _flatten_alpha_for_tk 旧路径逐像素一致')
        for name, im in _test_imgs():
            key = R.pick_key_color([im], Image)
            old = R._flatten_alpha_for_tk(im, Image, key)
            new = R.CompatRenderer(stub).flatten(im, key, Image)
            same = (old.size == new.size and old.mode == new.mode
                    and old.tobytes() == new.tobytes())
            check(f'C·flatten 逐像素一致 [{name}]', same,
                  f'size={new.size} key={key}')
        key0 = R.MAGENTA
        im0 = _test_imgs()[0][1]
        check('C7 key=None 兜底等价于 MAGENTA',
              R.CompatRenderer(stub).flatten(im0, None, Image).tobytes()
              == R._flatten_alpha_for_tk(im0, Image, key0).tobytes())

        im_small = Image.new('RGBA', (40, 60), (0, 0, 0, 0))
        for y in range(6, 54):
            for x in range(4, 36):
                im_small.putpixel((x, y), (180, 90, 40, 255 if y % 3 else 90))
        im_small.putpixel((0, 0), (255, 0, 255, 255))
        k_small = R.pick_key_color([im_small], Image)
        ref_photo = ImageTk.PhotoImage(R._flatten_alpha_for_tk(im_small, Image, k_small),
                                       master=root)
        got_photo = R.CompatRenderer(stub).prepare(im_small, k_small, Image)
        ok_px = (got_photo.width() == ref_photo.width()
                 and got_photo.height() == ref_photo.height()
                 and _photo_pixels(ref_photo, 40, 60) == _photo_pixels(got_photo, 40, 60))
        check('C8 prepare → PhotoImage 与旧路径逐像素一致（40x60 全量 2400 点）', ok_px,
              f'{got_photo.width()}x{got_photo.height()}')
        check('C9 raw_img 语义不变：flatten 输出 alpha 恒 255',
              R.CompatRenderer(stub).flatten(im_small, k_small, Image).getpixel((0, 0))[3] == 255)

        # ---------------- D. FollowOverlay 集成 ----------------
        print('\n[D] FollowOverlay 集成：收口 / 切皮肤 / 热重载 / 缩放 / alpha 等价')
        cfg = dict(R.DEFAULT_CONFIG)
        cfg['image'] = img_path
        cfg['base_height'] = 60          # 160x240 → 40x60，便于逐像素比对
        cfg['scale'] = 1.0
        cfg.pop('render_mode', None)     # 模拟 v1.6 老配置（无该键）
        ov = R.FollowOverlay(cfg)
        overlays.append(ov)
        try:
            ov.tray.stop()
        except Exception:
            pass
        check('D1 老配置（无 render_mode）→ compat + CompatRenderer',
              ov.render_mode == 'compat' and type(ov.renderer) is R.CompatRenderer,
              f'{ov.render_mode}/{type(ov.renderer).__name__}')
        check('D2 老配置渲染产物尺寸不变（base_height=60 → 40x60）',
              (ov.img.width(), ov.img.height()) == (40, 60),
              f'{ov.img.width()}x{ov.img.height()}')
        key_hex = R._key_hex(ov.key_rgb)
        tc = str(ov.root.attributes('-transparentcolor')).lower().lstrip('#')
        check('D3 -transparentcolor 与动态键色一致', tc == key_hex.lower().lstrip('#'),
              f'{tc} vs {key_hex}')
        check('D4 Label 底色与键色一致', str(ov.label.cget('bg')).lower() == key_hex.lower(),
              str(ov.label.cget('bg')))
        compat_px = _photo_pixels(ov.img, 40, 60)

        # 收口证据 1：load_char 只走 renderer 接口
        calls = collections.Counter()

        class Recording(R.CompatRenderer):
            def flatten(self, img_rgba, key=R.MAGENTA, Image=None):
                calls['flatten'] += 1
                return super().flatten(img_rgba, key, Image)

            def to_photo(self, img):
                calls['to_photo'] += 1
                return super().to_photo(img)

            def apply_window(self, key_rgb):
                calls['apply_window'] += 1
                return super().apply_window(key_rgb)

            def apply_label(self, label, photo, key_rgb):
                calls['apply_label'] += 1
                return super().apply_label(label, photo, key_rgb)

            def pick_key(self, imgs, Image=None):
                calls['pick_key'] += 1
                return super().pick_key(imgs, Image)

        real_renderer = ov.renderer
        ov.renderer = Recording(ov, 'compat')
        ov.load_char()
        ov.renderer = real_renderer
        need = ('pick_key', 'flatten', 'to_photo', 'apply_window', 'apply_label')
        check('D5 load_char 的渲染四步全部经 Renderer 接口',
              all(calls[n] >= 1 for n in need), f'calls={dict(calls)}')

        # 收口证据 2：CompatRenderer 原样调用 _flatten_alpha_for_tk
        hit = {'n': 0}
        real_flat = R._flatten_alpha_for_tk

        def counting_flat(img, Image=None, key=R.MAGENTA):
            hit['n'] += 1
            return real_flat(img, Image, key)

        R._flatten_alpha_for_tk = counting_flat
        try:
            ov.load_char()
        finally:
            R._flatten_alpha_for_tk = real_flat
        check('D6 CompatRenderer 原样承载 _flatten_alpha_for_tk（键色抠色路径）',
              hit['n'] == 1, f'调用 {hit["n"]} 次/次 load_char')

        # 收口证据 3：替换 renderer 后 Label / 窗口属性由 renderer 驱动
        class MarkRenderer(R.CompatRenderer):
            flag = {'win': 0, 'label': 0}

            def apply_window(self, key_rgb):
                self.flag['win'] += 1
                return super().apply_window(key_rgb)

            def apply_label(self, label, photo, key_rgb):
                self.flag['label'] += 1
                return super().apply_label(label, photo, key_rgb)

        mr = MarkRenderer(ov, 'compat')
        ov.renderer = mr
        ov.load_char()
        check('D7 窗口透明色/Label 应用由 renderer 承担（不再散落 load_char）',
              mr.flag['win'] == 1 and mr.flag['label'] == 1, repr(mr.flag))
        ov.renderer = real_renderer

        # 交互链路：菜单 / 事件绑定 / 快捷键照旧
        binds = [ov.label.bind('<ButtonPress-1>'), ov.label.bind('<B1-Motion>'),
                 ov.label.bind('<MouseWheel>'), ov.label.bind('<Button-3>'),
                 ov.root.bind('<Control-Alt-Key-c>'), ov.root.bind('<Control-Alt-Key-q>')]
        check('D8 拖动/滚轮/右键/快捷键绑定全部在（Label 仍是事件载体）',
              all(binds), 'bindings=' + str([bool(b) for b in binds]))
        check('D9 右键菜单项照旧（隐藏显示 / 退出）',
              ov.menu.index('end') == 1, f'items={ov.menu.index("end") + 1}')

        # 切皮肤（在 compat 实例上）：皮肤档案缺 render_mode 键 → 仍走 compat
        R.save_config = lambda c: None          # 打桩：不写真实 config.json
        old_skins = R.SKINS_DIR
        R.SKINS_DIR = os.path.join(tmp, 'skins')
        os.makedirs(R.SKINS_DIR, exist_ok=True)
        try:
            R.save_skin('渲染测试皮', dict(cfg))    # cfg 无 render_mode 键（老档案形态）
            ok = ov.apply_skin('渲染测试皮')
            check('D10 切皮肤成功且仍走 compat（皮肤档案无 render_mode 键）',
                  ok and type(ov.renderer) is R.CompatRenderer
                  and ov.render_mode == 'compat',
                  f'ok={ok} {ov.renderer.describe()}')
            check('D11 切皮肤后产物正常（图像已重载 40x60）',
                  (ov.img.width(), ov.img.height()) == (40, 60),
                  f'{ov.img.width()}x{ov.img.height()}')
            check('D12 切皮肤后窗口属性仍随键色（compat 链路完整）',
                  str(ov.root.attributes('-transparentcolor')).lower()
                  == R._key_hex(ov.key_rgb).lower(),
                  str(ov.root.attributes('-transparentcolor')))
            # 皮肤档案显式声明 render_mode=alpha → 应采纳（声明优先）
            import json as _json
            skin_json = os.path.join(R.SKINS_DIR, '渲染测试皮', 'skin.json')
            scfg = R.find_skin('渲染测试皮')
            scfg['render_mode'] = 'alpha'
            with open(skin_json, 'w', encoding='utf-8') as f:
                _json.dump(scfg, f, ensure_ascii=False, indent=2)
            ok2 = ov.apply_skin('渲染测试皮')
            check('D13 皮肤档案显式 render_mode=alpha → 采纳（声明优先）',
                  ok2 and ov.render_mode == 'alpha'
                  and type(ov.renderer) is R.LayeredRenderer,
                  f'{ov.render_mode}/{type(ov.renderer).__name__}')
            check('D14 alpha 皮肤下帧保留 RGBA（①b 真 alpha 不再抠色）',
                  ov.renderer._frame is not None
                  and ov.renderer._frame.mode == 'RGBA'
                  and ov.renderer._frame.size == (40, 60)
                  and hasattr(ov.img, 'image'),      # LayerFrame：width()/height() 语义
                  ov.renderer.describe())
            scfg['render_mode'] = 'compat'
            with open(skin_json, 'w', encoding='utf-8') as f:
                _json.dump(scfg, f, ensure_ascii=False, indent=2)
            ov.apply_skin('渲染测试皮')
            check('D15 切回 compat 完全恢复老行为',
                  ov.render_mode == 'compat' and type(ov.renderer) is R.CompatRenderer
                  and str(ov.root.attributes('-transparentcolor')).lower()
                  == R._key_hex(ov.key_rgb).lower())
        finally:
            R.SKINS_DIR = old_skins

        # 热重载（check_skin）：图片变化 → load_char 走 renderer，模式不变
        ov.cfg['image'] = img2_path
        ov.img_mtime = 0
        ov.skin_ms = 10 ** 7            # 不让下一拍真的排进来
        ov.check_skin()
        ok_reload = (os.path.getmtime(img2_path) == ov.img_mtime
                     and type(ov.renderer) is R.CompatRenderer
                     and ov.render_mode == 'compat')
        check('D16 热重载（check_skin）走 renderer 且模式不变',
              ok_reload, f'mtime={ov.img_mtime} {ov.renderer.describe()}')
        check('D17 热重载后窗口属性随新图键色更新',
              str(ov.root.attributes('-transparentcolor')).lower()
              == R._key_hex(ov.key_rgb).lower(),
              str(ov.root.attributes('-transparentcolor')))

        # 滚轮缩放：仍走 compat 管线
        class _Ev:
            delta = 120

        before = ov.img.width()
        ov.on_wheel(_Ev())
        check('D18 滚轮缩放走 load_char → renderer 不变、尺寸变大',
              ov.cfg['scale'] > 1.0 and ov.img.width() > before
              and type(ov.renderer) is R.CompatRenderer,
              f'scale={ov.cfg["scale"]} {before}→{ov.img.width()}')

        # alpha 配置实例：对外表现与 compat 逐像素一致（骨架期不许改行为）
        cfg_a = dict(cfg)
        cfg_a['render_mode'] = 'alpha'
        ov_a = R.FollowOverlay(cfg_a)           # 会关掉上一个实例（_close_active_overlay）
        overlays.append(ov_a)
        try:
            ov_a.tray.stop()
        except Exception:
            pass
        check('D19 alpha 配置 → LayeredRenderer 被选中（①b 实装完成）',
              type(ov_a.renderer) is R.LayeredRenderer and ov_a.render_mode == 'alpha'
              and R.LayeredRenderer.alpha_ready is True,
              ov_a.renderer.describe())
        check('D20 alpha 配置下 Label 仍在（交互不受影响）且不贴图',
              ov_a.label is not None and ov_a.label.bind('<B1-Motion>')
              and not ov_a.label.cget('image'))
        check('D21 alpha 模式已摘掉 -transparentcolor（键色抠色不再参与显示）',
              str(ov_a.root.attributes('-transparentcolor')) in ('', '0'),
              repr(str(ov_a.root.attributes('-transparentcolor'))))
        semi = Image.new('RGBA', (6, 6), (200, 60, 40, 60))
        k_semi = R.pick_key_color([semi], Image)
        compat_semi = R._flatten_alpha_for_tk(semi, Image, k_semi).getpixel((2, 2))
        alpha_semi = ov_a.renderer.flatten(semi, k_semi, Image).getpixel((2, 2))
        check('D22 alpha 保留逐像素 alpha，compat 把它抠成键色（升级一的实质差别）',
              alpha_semi == (200, 60, 40, 60) and compat_semi[:3] == tuple(k_semi),
              f'alpha={alpha_semi} compat={compat_semi[:3]} key={k_semi}')

        # alpha 实例切「无 render_mode 键」的老皮肤 → 全局开关保持 alpha（不被老档案打回）
        old_skins = R.SKINS_DIR
        R.SKINS_DIR = os.path.join(tmp, 'skins')
        os.makedirs(R.SKINS_DIR, exist_ok=True)
        try:
            R.save_skin('渲染测试皮2', dict(cfg))
            ok3 = ov_a.apply_skin('渲染测试皮2')
            check('D23 alpha 实例切老皮肤（缺 render_mode 键）→ 保持 alpha，不打回 compat',
                  ok3 and ov_a.render_mode == 'alpha'
                  and type(ov_a.renderer) is R.LayeredRenderer,
                  f'ok={ok3} {ov_a.render_mode}/{type(ov_a.renderer).__name__}')
        finally:
            R.SKINS_DIR = old_skins

        # 动图桩：无 renderer 字段（B_test_anim_sim 同款）→ 懒补建 compat，不崩
        class _FakeOverlay:
            pass

        src = Image.open(gif_path)
        n = int(getattr(src, 'n_frames', 1) or 1)
        fake = _FakeOverlay()
        fake.anim_src = src
        fake.anim_n = n
        fake.cfg = dict(R.DEFAULT_CONFIG)
        fake.key_rgb = R.MAGENTA
        fake._Image = Image
        fake._ImageTk = ImageTk
        fake.anim_idx = 0
        fake._base_h = 60.0
        fake._frame_cache = collections.OrderedDict()
        fake.root = root
        try:
            ph = R.FollowOverlay._decode_frame(fake, 0)
            ok_fake = (ph is not None and ph.width() == int(60 * (60.0 / 90))
                       and type(fake.renderer) is R.CompatRenderer)
            check('D24 动图桩（无 renderer 字段）懒补建 compat 渲染器并出帧',
                  ok_fake, f'n={n} w={getattr(ph, "width", lambda: None)()}')
            key_gif = R.FollowOverlay._pick_anim_key(fake, Image, n)
            check('D25 动图抠色键走 renderer.pick_key（多帧并集）',
                  isinstance(key_gif, tuple) and len(key_gif) == 3, repr(key_gif))
        except Exception as e:
            import traceback
            traceback.print_exc()
            check('D24 动图桩懒补建不崩', False, repr(e))

        print('\n' + '=' * 60)
        print(f'通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项')
        if FAIL:
            print('失败项: ' + ', '.join(FAIL))
            return 1
        print('ALL CHECKS PASS')
        return 0
    except AssertionError as e:
        print('RESULT FAIL:', e)
        return 1
    except Exception:
        import traceback
        traceback.print_exc()
        print('RESULT ERROR')
        return 2
    finally:
        for ovx in list(overlays):
            try:
                ovx.root.withdraw()
                ovx.root.destroy()
            except Exception:
                pass
        overlays.clear()
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        try:
            R.set_candidate_hwnd(0)
        except Exception:
            pass
        time.sleep(0.1)


if __name__ == '__main__':
    sys.exit(main())
