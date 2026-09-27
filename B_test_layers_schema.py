# -*- coding: utf-8 -*-
"""B_test_layers_schema.py —— v2.0-② 套层皮肤验证（多图层档案 + 锚点布局 + 单窗多图合成）

对照《Rime皮肤外挂-升级操作手册》② 章的操作步骤 1~6 与验收标准：
  A. 档案兼容：老单图 skin.json 读入自动包成单元素图层列表，schema=2，旧字段全保留
  B. 真实档案读写：save_skin / list_skins / find_skin 的 schema 2 往返；多图层图片都进皮肤目录
  C. 锚点布局：left_edge / right_edge / center + offset 微调 + follow_width_ratio 比例分摊；
     候选框变宽左右层同步拉开、变窄收拢；纯函数、无状态、可平移
  D. 单层退化等价：只有一个图层时 _calc_layer_targets == v1.6 的 _calc_target（逐位相同）
  E. 单窗多图合成：一个画布容纳全部图层（各自 alpha 保留），z 顺序正确，单层合成逐像素等价
  F. 真实窗口集成：多图层只开一个窗口；候选框变宽窗口跟着拉开；句柄重建（自愈）后不错位；
     compat / alpha 两种渲染模式都能跑多图层（无桌面环境 → SKIP，不算 FAIL）
  G. 向导：图层列表 + 每层可选中调参；预览 _draw_img_layer 支持多层绘制，_draw_candidate 层级不破

红线：只读被测模块；皮肤档案只写临时目录（不碰真实 skins/）；写文件类断言全部在 tempfile 内。

用法: python B_test_layers_schema.py
"""
import os
import sys
import json
import ctypes
import shutil
import tempfile
import ctypes.wintypes as wintypes

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


# ==========================================================================
# 夹具
# ==========================================================================
def make_img(path, size, color, mode='RGBA', band=None):
    """造一张测试图；band=(y0,y1,color) 可加一条半透明横带"""
    from PIL import Image
    im = Image.new(mode, size, color)
    if band:
        y0, y1, c = band
        for y in range(y0, y1):
            for x in range(size[0]):
                im.putpixel((x, y), c)
    im.save(path)
    return path


# ------- 真 Win32 假候选框（与 B_test_follow_sim.py 同款，自包含）-------
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('style', wintypes.UINT),
                ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', wintypes.HINSTANCE),
                ('hIcon', wintypes.HICON), ('hCursor', wintypes.HANDLE),
                ('hbrBackground', wintypes.HBRUSH), ('lpszMenuName', wintypes.LPCWSTR),
                ('lpszClassName', wintypes.LPCWSTR), ('hIconSm', wintypes.HICON)]


def _def_proc(hwnd, msg, wp, lp):
    try:
        return R.user32.DefWindowProcW(hwnd, msg, wp, lp)
    except Exception:
        return 0


def _setup_fake_win32():
    """假候选框要用的 Win32 签名（64 位下必须显式声明，否则 hInstance 被截断）"""
    R.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    R.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    R.user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                        wintypes.WPARAM, wintypes.LPARAM]
    R.user32.DefWindowProcW.restype = ctypes.c_longlong
    R.user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    R.user32.GetClassNameW.restype = ctypes.c_int
    R.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                  ctypes.POINTER(wintypes.DWORD)]
    R.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    R.user32.IsWindowVisible.argtypes = [wintypes.HWND]
    R.user32.IsWindowVisible.restype = wintypes.BOOL


class FakeCandidate:
    """类名 ATL: 前缀 + 候选框样式/尺寸的假候选框（真实顶层窗口，可移动可销毁）"""

    _n = 0

    def __init__(self, x=60, y=120, w=420, h=72):
        FakeCandidate._n += 1
        cls = f'ATL:MockLayerCand{FakeCandidate._n}'
        _setup_fake_win32()
        self.proc = WNDPROC(_def_proc)
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.lpfnWndProc = self.proc
        wc.hInstance = R.kernel32.GetModuleHandleW(None)
        wc.lpszClassName = cls
        R.user32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
        R.user32.RegisterClassExW.restype = wintypes.ATOM
        R.user32.RegisterClassExW(ctypes.byref(wc))
        self.cls = cls
        R.user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        R.user32.CreateWindowExW.restype = wintypes.HWND
        self.hwnd = R.user32.CreateWindowExW(
            0x80 | 0x08000000, cls, 'mock', 0x80000000 | 0x10000000,
            x, y, w, h, 0, 0, wc.hInstance, None)
        if not self.hwnd:
            raise RuntimeError('CreateWindowExW failed')

    def rect(self):
        r = wintypes.RECT()
        R.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        R.user32.GetWindowRect(self.hwnd, ctypes.byref(r))
        return r

    def move(self, x, y, w=None, h=None):
        rr = self.rect()
        w = rr.right - rr.left if w is None else w
        h = rr.bottom - rr.top if h is None else h
        R.user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                          wintypes.UINT]
        R.user32.SetWindowPos(self.hwnd, 0, int(x), int(y), int(w), int(h), 0x0010)

    def destroy(self):
        try:
            R.user32.DestroyWindow(self.hwnd)
        except Exception:
            pass


class _Rect:
    """离屏布局断言用的假 rect（无需真窗口）"""

    def __init__(self, l, t, r, b):
        self.left, self.top, self.right, self.bottom = l, t, r, b


def _layers_for(n, anchor='right_edge', **kw):
    """造 n 个规范化图层（纯数据，喂 plan_layer_layout）"""
    out = []
    for i in range(n):
        ld = {'image': f'lay{i}.png', 'anchor': anchor, 'offset_x': 0, 'offset_y': 0,
              'scale': 1.0, 'flip': False, 'z': i, 'follow_width_ratio': 0.0}
        ld.update(kw)
        out.append(ld)
    return out


# ==========================================================================
# Z. 接口清单（红阶段先列清缺口：每个符号都必须存在）
# ==========================================================================
def test_api_surface():
    section('Z. 接口清单：② 套层皮肤要新增的全部符号')
    mod_syms = ['LAYER_SCHEMA', 'LAYER_ANCHORS', 'MAX_LAYERS', 'LAYER_KEYS',
                'DEFAULT_LAYER_GAP', 'anchor_from_side', 'side_from_anchor',
                'normalize_layer', 'make_layer_from_cfg', 'resolve_layers',
                'save_layers_into_cfg', 'migrate_skin_cfg', 'plan_layer_layout',
                'compose_layers']
    for s in mod_syms:
        check(f'Z01 模块级符号 {s} 存在', hasattr(R, s))
    ov_syms = ['_layer_specs', '_layer_dims', '_calc_layer_targets', '_compose_frame',
               '_layers_active']
    for s in ov_syms:
        check(f'Z02 FollowOverlay.{s} 存在', hasattr(R.FollowOverlay, s))
    wiz_syms = ['_layer_sync_from_cfg', '_on_layer_select', '_on_layer_param_change',
                '_layer_add', '_layer_delete']
    for s in wiz_syms:
        check(f'Z03 ConfigWizard.{s} 存在', hasattr(R.ConfigWizard, s))


# ==========================================================================
# A. 档案兼容（纯函数）
# ==========================================================================
def test_schema_compat():
    section('A. 档案兼容：老单图 skin.json → 单元素图层列表（schema 2）')
    old = {
        'image': 'C:/tmp/char.png', 'layout': 'horizontal_double', 'side': 'right',
        'layer': 'above', 'scale': 1.3, 'offset_x': 12, 'offset_y': -5,
        'base_height': 300, 'flip_h': True, 'corner_enabled': True, 'corner_radius': 30,
        'feather_enabled': True, 'feather_radius': 18, 'rime_scheme': 'S1',
        'render_mode': 'compat', 'name': 'old1',
    }
    src = dict(old)
    cfg = R.migrate_skin_cfg(dict(old), skin_dir=None)

    check('A01 migrate_skin_cfg 不修改入参', old == src)
    check('A02 升级后 schema == 2', cfg.get('schema') == R.LAYER_SCHEMA, f'schema={cfg.get("schema")}')
    check('A03 layers 是单元素列表', isinstance(cfg.get('layers'), list) and len(cfg['layers']) == 1,
          f'len={len(cfg.get("layers") or [])}')
    l0 = (cfg.get('layers') or [{}])[0]
    check('A04 layer0.image == 旧 image', l0.get('image') == old['image'], repr(l0.get('image')))
    check('A05 side=right → anchor=right_edge', l0.get('anchor') == 'right_edge',
          repr(l0.get('anchor')))
    check('A06 顶层 offset_x 保留（权威）', cfg.get('offset_x') == 12, repr(cfg.get('offset_x')))
    check('A07 layer0.offset_x 归零（防与顶层翻倍）', l0.get('offset_x') == 0,
          repr(l0.get('offset_x')))
    check('A08 layer0.offset_y 归零', l0.get('offset_y') == 0, repr(l0.get('offset_y')))
    check('A09 layer0.z == 0', l0.get('z') == 0, repr(l0.get('z')))
    check('A10 layer0.scale 跟随顶层 scale', abs(float(l0.get('scale', 0)) - 1.3) < 1e-9,
          repr(l0.get('scale')))
    check('A11 layer0.flip 跟随顶层 flip_h', l0.get('flip') is True, repr(l0.get('flip')))
    eff = l0.get('effects') or {}
    check('A12 layer0.effects 带上圆角/羽化参数',
          eff.get('corner_enabled') is True and int(eff.get('corner_radius', 0)) == 30
          and eff.get('feather_enabled') is True and int(eff.get('feather_radius', 0)) == 18,
          repr(eff))
    keep = all(cfg.get(k) == v for k, v in old.items())
    check('A13 旧字段一个不丢（含 image/layout/side/layer/特效/配色/渲染模式）', keep,
          ','.join(k for k, v in old.items() if cfg.get(k) != v) or 'all kept')
    cfg2 = R.migrate_skin_cfg(dict(cfg), skin_dir=None)
    check('A14 幂等：再迁移一次结果不变', cfg2 == cfg)

    for side, anc in (('left', 'left_edge'), ('right', 'right_edge'),
                      ('center', 'center'), ('weird', 'right_edge'), ('', 'right_edge')):
        c = R.migrate_skin_cfg({'image': 'a.png', 'side': side}, skin_dir=None)
        got = c['layers'][0]['anchor']
        check(f'A15 side={side!r} → anchor={anc}', got == anc, f'got={got!r}')

    c = R.migrate_skin_cfg({'image': 'a.png', 'layers': [
        {'image': 'x.png', 'anchor': 'badname'}]}, skin_dir=None)
    check('A16 非法 anchor 回退 right_edge', c['layers'][0]['anchor'] == 'right_edge',
          repr(c['layers'][0]['anchor']))
    c = R.migrate_skin_cfg({'image': 'a.png', 'layers': [
        {'image': 'x.png', 'anchor': 'left_edge', 'scale': 99}]}, skin_dir=None)
    check('A17 scale 超界被夹到 2.0', abs(float(c['layers'][0]['scale']) - 2.0) < 1e-9,
          repr(c['layers'][0]['scale']))
    c = R.migrate_skin_cfg({'image': 'a.png', 'layers': [
        {'image': 'x.png', 'scale': 0.01}]}, skin_dir=None)
    check('A18 scale 过小被夹到 0.2', abs(float(c['layers'][0]['scale']) - 0.2) < 1e-9,
          repr(c['layers'][0]['scale']))

    many = [{'image': f'{i}.png', 'z': i} for i in range(20)]
    c = R.migrate_skin_cfg({'image': 'a.png', 'layers': many}, skin_dir=None)
    check(f'A19 图层数上限 {R.MAX_LAYERS} 生效', len(c['layers']) == R.MAX_LAYERS,
          f'len={len(c["layers"])}')

    c = R.migrate_skin_cfg({'image': 'a.png', 'layers': []}, skin_dir=None)
    check('A20 空 layers → 从顶层字段补出单层', len(c['layers']) == 1
          and c['layers'][0]['image'] == 'a.png', repr(c['layers']))
    c = R.migrate_skin_cfg({'image': 'a.png', 'layers': 'oops'}, skin_dir=None)
    check('A21 非列表 layers → 补出单层不崩', len(c['layers']) == 1,
          repr(c.get('layers')))

    c = R.migrate_skin_cfg({'image': 'a.png', 'layers': [
        {'image': 'b.png', 'z': 5}, {'image': 'c.png', 'z': 1},
        {'image': 'd.png', 'z': 3}]}, skin_dir=None)
    zs = [x['z'] for x in c['layers']]
    check('A22 多层按 z 升序排列', zs == sorted(zs), repr(zs))

    c = R.migrate_skin_cfg({'image': 'a.png', 'layers': [
        {'image': 'b.png', 'anchor': 'left_edge', 'follow_width_ratio': 0.5}]}, skin_dir=None)
    check('A23 follow_width_ratio 被保留', abs(c['layers'][0]['follow_width_ratio'] - 0.5) < 1e-9,
          repr(c['layers'][0]['follow_width_ratio']))
    c = R.migrate_skin_cfg({'image': 'a.png', 'layers': [
        {'image': 'b.png', 'follow_width_ratio': 9}]}, skin_dir=None)
    check('A24 follow_width_ratio 越界夹到 [-1,1]',
          -1.0 <= float(c['layers'][0]['follow_width_ratio']) <= 1.0,
          repr(c['layers'][0]['follow_width_ratio']))

    c = R.migrate_skin_cfg({'image': '', 'side': 'right'}, skin_dir=None)
    check('A25 无图老档案不崩（layers 仍可构造）', isinstance(c.get('layers'), list)
          and len(c['layers']) == 1, repr(c.get('layers')))

    # ---- F-V1 / F-V3：主层 offset 的单一权威（纯函数面，比端到端更快定位）----
    c = R.resolve_layers({'image': 'a.png', 'offset_x': -132, 'offset_y': -132})
    check('A26 F-V1（纯函数面）老配置无 layers 键：顶层 offset 必须传进主层',
          int(c[0]['offset_x']) == -132 and int(c[0]['offset_y']) == -132,
          f'{c[0]["offset_x"]},{c[0]["offset_y"]}')
    c = R.resolve_layers({'image': 'a.png', 'offset_x': 10, 'offset_y': 20,
                          'layers': [{'image': 'a.png', 'anchor': 'left_edge',
                                      'offset_x': 50, 'offset_y': 60}]})
    check('A27 F-V3：主层 offset 只认顶层，层内值不叠加（无双计）',
          int(c[0]['offset_x']) == 10 and int(c[0]['offset_y']) == 20,
          f'{c[0]["offset_x"]},{c[0]["offset_y"]}')
    check('A27b 主层 anchor 也以顶层 side 为权威（层内的 left_edge 被忽略）',
          c[0]['anchor'] == 'right_edge' and abs(float(c[0]['scale']) - 1.0) < 1e-9,
          f'{c[0]["anchor"]}/{c[0]["scale"]}')
    c = R.resolve_layers({'image': 'a.png', 'offset_x': 7,
                          'layers': [{'image': 'a.png', 'anchor': 'left_edge'},
                                     {'image': 'b.png', 'anchor': 'right_edge',
                                      'offset_x': 30, 'z': 1}]})
    check('A28 F-V3：非主层（i>0）的层内 offset 不受影响（仍是自己的值）',
          int(c[1]['offset_x']) == 30, repr(c[1]['offset_x']))

    c = R.migrate_skin_cfg({'schema': 2, 'image': 'a.png', 'layers': [
        {'image': 'sub/b.png', 'anchor': 'left_edge'}]}, skin_dir='D:/skins/测试')
    p = str(c['layers'][0]['image']).replace('\\', '/')
    check('A26 相对路径按皮肤目录解析成绝对',
          p.startswith('D:/skins/') and p.endswith('sub/b.png'), p)


# ==========================================================================
# B. 真实档案读写
# ==========================================================================
def test_skin_io(tmp):
    section('B. 真实档案读写：save_skin / list_skins 的 schema 2 往返')
    real_skins = R.SKINS_DIR
    tmp_skins = os.path.join(tmp, 'skins')
    os.makedirs(tmp_skins, exist_ok=True)
    a = make_img(os.path.join(tmp, 'a.png'), (80, 120), (0, 0, 0, 0),
                 band=(30, 60, (200, 30, 40, 255)))
    b = make_img(os.path.join(tmp, 'b.png'), (40, 200), (0, 0, 0, 0),
                 band=(10, 40, (20, 90, 220, 255)))
    c3 = make_img(os.path.join(tmp, 'c.png'), (60, 60), (0, 0, 0, 0),
                  band=(5, 25, (40, 200, 90, 255)))
    try:
        R.SKINS_DIR = tmp_skins
        cfg = dict(R.DEFAULT_CONFIG)
        cfg.update({'image': a, 'side': 'left', 'scale': 1.2, 'offset_x': 7,
                    'offset_y': -3, 'flip_h': True, 'corner_enabled': True,
                    'corner_radius': 12, 'layout': 'vertical'})
        scfg = R.save_skin('单图层皮肤', cfg)
        j = json.load(open(os.path.join(tmp_skins, '单图层皮肤', 'skin.json'), encoding='utf-8'))
        check('B01 skin.json 带 schema:2', j.get('schema') == 2, f'schema={j.get("schema")}')
        check('B02 skin.json 带 layers 列表', isinstance(j.get('layers'), list)
              and len(j['layers']) == 1, f'len={len(j.get("layers") or [])}')
        check('B03 layers[0].image 指向皮肤目录内文件',
              os.path.dirname(os.path.abspath(j['layers'][0]['image']))
              == os.path.abspath(os.path.join(tmp_skins, '单图层皮肤')),
              j['layers'][0]['image'])
        check('B04 顶层 image == layers[0].image（旧字段仍可用）',
              os.path.normpath(j['image']) == os.path.normpath(j['layers'][0]['image']))
        check('B05 顶层旧字段全保留（side/scale/offset/flip/特效/layout）',
              j.get('side') == 'left' and abs(float(j.get('scale')) - 1.2) < 1e-9
              and int(j.get('offset_x')) == 7 and int(j.get('offset_y')) == -3
              and j.get('flip_h') is True and j.get('corner_enabled') is True
              and j.get('layout') == 'vertical', json.dumps(
                  {k: j.get(k) for k in ('side', 'scale', 'offset_x', 'flip_h', 'layout')},
                  ensure_ascii=False))
        check('B06 layer0.anchor 与 side 一致（left→left_edge）',
              j['layers'][0].get('anchor') == 'left_edge', repr(j['layers'][0].get('anchor')))

        got = R.find_skin('单图层皮肤')
        check('B07 find_skin 读回带 layers 且 schema=2',
              got and got.get('schema') == 2 and len(got.get('layers') or []) == 1,
              repr((got or {}).get('schema')))
        check('B08 读回的 anchor 正确', (got or {}).get('layers', [{}])[0].get('anchor') == 'left_edge')
        check('B09 读回的旧字段与写入一致',
              got and got.get('layout') == 'vertical' and got.get('side') == 'left'
              and int(got.get('offset_x')) == 7)

        # ---- 多图层保存 ----
        mcfg = dict(R.DEFAULT_CONFIG)
        mcfg.update({'image': a, 'side': 'left', 'layout': 'horizontal_double',
                     'layers': [
                         {'image': a, 'anchor': 'left_edge', 'z': 0},
                         {'image': b, 'anchor': 'right_edge', 'z': 1, 'scale': 0.8,
                          'follow_width_ratio': 0.4},
                         {'image': c3, 'anchor': 'center', 'z': 2, 'offset_y': 24}]})
        R.save_skin('三层皮肤', mcfg)
        d3 = os.path.join(tmp_skins, '三层皮肤')
        j3 = json.load(open(os.path.join(d3, 'skin.json'), encoding='utf-8'))
        check('B10 三层档案 layers 长度 3', len(j3.get('layers') or []) == 3,
              f'len={len(j3.get("layers") or [])}')
        imgs = [os.path.normpath(x['image']) for x in j3['layers']]
        check('B11 三张图都复制进皮肤目录',
              all(os.path.dirname(p) == os.path.abspath(d3) for p in imgs) and len(set(imgs)) == 3,
              str([os.path.basename(p) for p in imgs]))
        check('B12 三张图文件都真实存在', all(os.path.exists(p) for p in imgs))
        check('B13 顶层 image == layers[0].image', os.path.normpath(j3['image']) == imgs[0])
        check('B14 各层 anchor 保存正确',
              [x['anchor'] for x in j3['layers']] == ['left_edge', 'right_edge', 'center'],
              str([x['anchor'] for x in j3['layers']]))
        check('B15 follow_width_ratio 落盘', abs(float(j3['layers'][1]['follow_width_ratio'])
                                                - 0.4) < 1e-9,
              repr(j3['layers'][1].get('follow_width_ratio')))
        check('B16 各层 offset_y 落盘', int(j3['layers'][2].get('offset_y', 0)) == 24,
              repr(j3['layers'][2].get('offset_y')))
        back = R.find_skin('三层皮肤')
        check('B17 读回三层且路径仍存在', back and all(os.path.exists(x['image'])
                                                     for x in back['layers']),
              f'{len((back or {}).get("layers") or [])} 层')

        # ---- 手写老格式档案（无 schema / layers）----
        d_old = os.path.join(tmp_skins, '老格式皮肤')
        os.makedirs(d_old, exist_ok=True)
        old_img = os.path.join(d_old, 'image.png')
        shutil.copy2(a, old_img)
        old_json = {k: v for k, v in cfg.items() if k != 'layers'}
        old_json['image'] = old_img
        old_json['name'] = '老格式皮肤'
        old_json.pop('schema', None)
        json.dump(old_json, open(os.path.join(d_old, 'skin.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        got_old = R.find_skin('老格式皮肤')
        check('B18 老格式档案读入自动包成单元素图层列表',
              got_old and len(got_old.get('layers') or []) == 1 and got_old.get('schema') == 2,
              repr((got_old or {}).get('schema')))
        gl = (got_old or {}).get('layers', [{}])[0]
        check('B19 老档案单层参数与 v1.6 一致（anchor/offset/scale/flip）',
              gl.get('anchor') == 'left_edge' and int(got_old.get('offset_x')) == 7
              and abs(float(got_old.get('scale')) - 1.2) < 1e-9
              and got_old.get('flip_h') is True,
              f'anchor={gl.get("anchor")} offx={got_old.get("offset_x")} scale={got_old.get("scale")}')
        gfx = gl.get('effects') or {}
        check('B20 老档案特效进 effects', gfx.get('corner_enabled') is True
              and int(gfx.get('corner_radius', 0)) == 12, repr(gfx))

        # ---- 读 → 写回 → 再读：旧字段不丢 ----
        R.save_skin('老格式皮肤', got_old)
        j_rt = json.load(open(os.path.join(d_old, 'skin.json'), encoding='utf-8'))
        check('B21 读回再写回后旧字段不丢',
              all(j_rt.get(k) == old_json.get(k) for k in
                  ('layout', 'side', 'layer', 'base_height', 'corner_enabled',
                   'corner_radius', 'flip_h')),
              ','.join(k for k in ('layout', 'side', 'layer', 'base_height',
                                   'corner_enabled', 'flip_h')
                       if j_rt.get(k) != old_json.get(k)) or 'all kept')
        check('B22 再写回后 schema 仍为 2', j_rt.get('schema') == 2)
        check('B23 再写回后 layers 仍单元素', len(j_rt.get('layers') or []) == 1)

        # ---- 图片被删的坏档案：不应崩、不应把 layers 弄丢 ----
        d_bad = os.path.join(tmp_skins, '坏图皮肤')
        os.makedirs(d_bad, exist_ok=True)
        json.dump({'schema': 2, 'image': os.path.join(d_bad, 'missing.png'),
                   'layers': [{'image': os.path.join(d_bad, 'missing.png'),
                               'anchor': 'center'}]},
                  open(os.path.join(d_bad, 'skin.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False)
        names = [n for n, _ in R.list_skins()]
        check('B24 图片缺失的档案被 list_skins 跳过（不崩）', '坏图皮肤' not in names,
              str(names))
    finally:
        R.SKINS_DIR = real_skins


# ==========================================================================
# C. 锚点布局（纯函数）
# ==========================================================================
def test_anchor_layout():
    section('C. 锚点布局：left_edge / right_edge / center + offset + follow_width_ratio')
    rect = _Rect(500, 300, 900, 372)          # 400x72 候选框
    sizes = [(80, 120)]

    for anchor, legend in (('right_edge', '右侧'), ('left_edge', '左侧'), ('center', '中间')):
        lay = _layers_for(1, anchor)
        wx, wy, ww, wh, pl = R.plan_layer_layout(lay, sizes, rect)
        if anchor == 'right_edge':
            ex = 900 + R.DEFAULT_LAYER_GAP
        elif anchor == 'left_edge':
            ex = 500 - 80 - R.DEFAULT_LAYER_GAP
        else:
            ex = 500 + (400 - 80) // 2
        ey = 300 + (72 - 120) // 2
        check(f'C01 单层 {legend}：窗口 x 与 v1.6 公式一致', wx == ex, f'got={wx} exp={ex}')
        check(f'C02 单层 {legend}：窗口 y 垂直居中一致', wy == ey, f'got={wy} exp={ey}')
        check(f'C03 单层 {legend}：窗口尺寸 == 图层尺寸',
              (ww, wh) == (80, 120), f'{ww}x{wh}')
        check(f'C04 单层 {legend}：placement 是 (0,0,0)', pl == [(0, 0, 0)], str(pl))

    # 两层：左 + 右
    lay2 = [_layers_for(1, 'left_edge')[0], _layers_for(1, 'right_edge')[0]]
    sizes2 = [(80, 120), (40, 200)]
    wx, wy, ww, wh, pl = R.plan_layer_layout(lay2, sizes2, rect)
    lx0 = 500 - 80 - R.DEFAULT_LAYER_GAP
    lx1 = 900 + R.DEFAULT_LAYER_GAP
    check('C05 双层：包围盒左上 = min(各层 x)', wx == lx0, f'got={wx} exp={lx0}')
    check('C06 双层：包围盒宽度覆盖到最右层右缘',
          wx + ww == lx1 + 40, f'wx+ww={wx + ww} exp={lx1 + 40}')
    check('C07 双层：包围盒高度取最大层高', wh == 200, f'wh={wh}')
    ly0 = 300 + (72 - 120) // 2
    ly1 = 300 + (72 - 200) // 2
    wy_exp = min(ly0, ly1)
    check('C08 双层：各层窗口内偏移正确',
          pl == [(0, 0, ly0 - wy_exp), (1, lx1 - lx0, ly1 - wy_exp)], str(pl))

    # 变宽 → 拉开；变窄 → 收拢
    wide = _Rect(500, 300, 1100, 372)
    narrow = _Rect(500, 300, 620, 372)
    def span(r):
        _wx, _wy, _ww, _wh, _pl = R.plan_layer_layout(lay2, sizes2, r)
        return (lx1 - lx0) if False else (_pl[1][1] - _pl[0][1])
    s_base = span(rect)
    s_wide = span(wide)
    s_narrow = span(narrow)
    check('C09 候选框变宽 → 左右两层的相对间距拉开', s_wide > s_base, f'{s_base}→{s_wide}')
    check('C10 候选框变窄 → 左右两层收拢', s_narrow < s_base, f'{s_base}→{s_narrow}')
    check('C11 间距变化量 == 候选框宽度变化量（严格线性跟随）',
          (s_wide - s_base) == (1100 - 900) and (s_base - s_narrow) == (900 - 620),
          f'delta={s_wide - s_base}/{s_base - s_narrow}')

    # 平移不变
    shifted = _Rect(500 + 137, 300 - 55, 900 + 137, 372 - 55)
    wx1, wy1, ww1, wh1, pl1 = R.plan_layer_layout(lay2, sizes2, rect)
    wx2, wy2, ww2, wh2, pl2 = R.plan_layer_layout(lay2, sizes2, shifted)
    check('C12 候选框整体平移 → 窗口同步平移、尺寸与布局不变',
          (wx2 - wx1, wy2 - wy1) == (137, -55) and (ww2, wh2) == (ww1, wh1) and pl2 == pl1,
          f'dxy=({wx2 - wx1},{wy2 - wy1})')

    # follow_width_ratio
    layr = _layers_for(1, 'right_edge', follow_width_ratio=0.5)
    layl = _layers_for(1, 'left_edge', follow_width_ratio=0.5)
    _w0, _y0, _W0, _H0, _p0 = R.plan_layer_layout(layr, sizes, rect)
    _w1, _y1, _W1, _H1, _p1 = R.plan_layer_layout(layr, sizes, wide)
    d_w = (_w1) - (_w0)
    check('C13 follow_width_ratio=0.5：右层随宽度额外外推一半', d_w == (1100 - 900) // 2 + (1100 - 900),
          f'delta={d_w}')
    _w2, _y2, _W2, _H2, _p2 = R.plan_layer_layout(layl, sizes, wide)
    _w3, _y3, _W3, _H3, _p3 = R.plan_layer_layout(layl, sizes, rect)
    dcw = (wide.right - wide.left) - (rect.right - rect.left)
    check('C14 follow_width_ratio 对左层反向（向左外推）', _w2 - _w3 == -(dcw // 2),
          f'delta={_w2 - _w3} exp={-(dcw // 2)}')
    lay0 = _layers_for(1, 'right_edge', follow_width_ratio=0.0)
    _w4, _y4, _W4, _H4, _p4 = R.plan_layer_layout(lay0, sizes, wide)
    _w5, _y5, _W5, _H5, _p5 = R.plan_layer_layout(lay0, sizes, rect)
    check('C15 follow_width_ratio=0（默认）不额外分摊，只跟边缘', _w4 - _w5 == (1100 - 900),
          f'delta={_w4 - _w5}')

    # offset 微调
    layo = _layers_for(1, 'right_edge', offset_x=17, offset_y=-9)
    wx, wy, _ww, _wh, _pl = R.plan_layer_layout(layo, sizes, rect)
    check('C16 layer.offset_x 微调生效', wx == 900 + R.DEFAULT_LAYER_GAP + 17, f'wx={wx}')
    check('C17 layer.offset_y 微调生效', wy == 300 + (72 - 120) // 2 - 9, f'wy={wy}')

    # main_off 只作用于 layer0：看"屏幕坐标"（placement + 窗口原点）才是无歧义口径
    lay2b = [_layers_for(1, 'left_edge')[0], _layers_for(1, 'right_edge')[0]]
    wx_a, wy_a, _ww_a, _wh_a, pl_a = R.plan_layer_layout(lay2b, sizes2, rect, main_off=(11, 13))
    wx_b, wy_b, _ww_b, _wh_b, pl_b = R.plan_layer_layout(lay2b, sizes2, rect)
    s0_a = (pl_a[0][1] + wx_a, pl_a[0][2] + wy_a)
    s0_b = (pl_b[0][1] + wx_b, pl_b[0][2] + wy_b)
    s1_a = (pl_a[1][1] + wx_a, pl_a[1][2] + wy_a)
    s1_b = (pl_b[1][1] + wx_b, pl_b[1][2] + wy_b)
    check('C18 main_off（拖动偏移）只作用于第 0 层：第 0 层屏幕坐标正好平移',
          (s0_a[0] - s0_b[0], s0_a[1] - s0_b[1]) == (11, 13), f'd0={s0_a} vs {s0_b}')
    check('C19 main_off 不影响第 1 层的屏幕坐标',
          s1_a == s1_b, f'd1={s1_a} vs {s1_b}')

    # 确定性 / 无状态
    r1 = R.plan_layer_layout(lay2, sizes2, rect)
    r2 = R.plan_layer_layout(lay2, sizes2, rect)
    r3 = R.plan_layer_layout(lay2, sizes2, wide)
    r4 = R.plan_layer_layout(lay2, sizes2, rect)
    check('C20 同输入重复调用结果完全一致（无状态、不累积漂移）', r1 == r2 == r4, str(r1 == r4))

    # 三层混合
    lay3 = [_layers_for(1, 'left_edge')[0], _layers_for(1, 'center')[0],
            _layers_for(1, 'right_edge')[0]]
    sizes3 = [(80, 120), (60, 60), (40, 200)]
    wx, wy, ww, wh, pl = R.plan_layer_layout(lay3, sizes3, rect)
    cx = 500 + (400 - 60) // 2
    check('C21 三层：包围盒覆盖最左层', wx == 500 - 80 - R.DEFAULT_LAYER_GAP, f'wx={wx}')
    check('C22 三层：包围盒覆盖最右层', wx + ww == 900 + R.DEFAULT_LAYER_GAP + 40,
          f'right={wx + ww}')
    check('C23 三层：中间层窗口内偏移 = center 位置 - 窗口原点', pl[1][1] == cx - wx,
          f'got={pl[1][1]} exp={cx - wx}')
    check('C24 placements 按图层顺序返回全部层', len(pl) == 3
          and [p[0] for p in pl] == [0, 1, 2], str(pl))

    # 尺寸数组异常兜底
    _wx, _wy, _ww, _wh, _pl = R.plan_layer_layout(lay3, [(80, 120)], rect)
    check('C25 尺寸数组缺项不崩（缺的层跳过）', len(_pl) <= 1, str(_pl))
    _wx, _wy, _ww, _wh, _pl = R.plan_layer_layout([], [], rect)
    check('C26 空图层不崩，返回零尺寸', (_wx, _wy, _ww, _wh) == (0, 0, 0, 0),
          f'{_wx},{_wy},{_ww},{_wh}')


# ==========================================================================
# E. 单窗多图合成（纯 PIL，无窗口）
# ==========================================================================
def test_compose():
    section('E. 单窗多图合成：一张画布容纳全部图层（各自 alpha 保留）')
    from PIL import Image
    red = Image.new('RGBA', (20, 30), (0, 0, 0, 0))
    for y in range(30):
        for x in range(20):
            red.putpixel((x, y), (255, 0, 0, 255))
    blue_half = Image.new('RGBA', (20, 30), (0, 0, 255, 128))
    frames = [red, blue_half]

    out = R.compose_layers(frames, (60, 40), [(0, 0, 0), (1, 25, 5)])
    check('E01 画布尺寸 == 请求尺寸', out.size == (60, 40), str(out.size))
    check('E02 画布是 RGBA', out.mode == 'RGBA', out.mode)
    check('E03 第 0 层像素落到 placement 指定位置', out.getpixel((5, 5))[:3] == (255, 0, 0),
          str(out.getpixel((5, 5))))
    check('E04 第 1 层像素独立落位', out.getpixel((30, 10))[:3] == (0, 0, 255),
          str(out.getpixel((30, 10))))
    check('E05 第 1 层自身 alpha 保留（128 半透明）', out.getpixel((30, 10))[3] == 128,
          str(out.getpixel((30, 10))[3]))
    check('E06 未被覆盖区域保持全透明', out.getpixel((58, 38))[3] == 0,
          str(out.getpixel((58, 38))))
    check('E07 两层之间空隙透明', out.getpixel((22, 2))[3] == 0,
          str(out.getpixel((22, 2))))

    # z 顺序：列表顺序 = 从下往上叠，后面的盖前面的
    overlap = R.compose_layers(frames, (30, 30), [(0, 0, 0), (1, 0, 0)])
    px = overlap.getpixel((5, 5))
    check('E08 重叠区上层（后画的）胜出且 alpha 合成正确',
          px[2] > px[0] and px[3] == 255, f'px={px}')

    # 单层退化：合成 == 原图逐像素
    single = R.compose_layers([red], (20, 30), [(0, 0, 0)])
    same = True
    for y in range(30):
        for x in range(20):
            if single.getpixel((x, y)) != red.getpixel((x, y)):
                same = False
                break
        if not same:
            break
    check('E09 单层合成与原图逐像素一致（退化等价）', same)

    # None / 越界
    out2 = R.compose_layers([red, None], (30, 30), [(0, 0, 0), (1, 40, 40)])
    check('E10 帧为 None 的层被跳过不崩', out2.size == (30, 30)
          and out2.getpixel((5, 5))[:3] == (255, 0, 0), str(out2.size))
    out3 = R.compose_layers([red], (10, 10), [(0, -5, -5)])
    check('E11 图层部分越界被裁剪不崩', out3.size == (10, 10), str(out3.size))
    out4 = R.compose_layers([red], (10, 10), [(0, 100, 100)])
    check('E12 图层完全越界 → 全透明画布', out4.getbbox() is None, str(out4.getbbox()))
    out5 = R.compose_layers([red], (0, 0), [(0, 0, 0)])
    check('E13 零尺寸画布不崩', out5.size == (0, 0), str(out5.size))

    # 缺失 placements 的层
    out6 = R.compose_layers([red, blue_half], (30, 30), [(0, 1, 1)])
    check('E14 placements 缺项时该层按 (0,0) 兜底或跳过（不崩）', out6.size == (30, 30))


# ==========================================================================
# D / F. 运行时集成（真窗口；无桌面 → SKIP）
# ==========================================================================
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


def test_runtime(tmp, gui_ok):
    section('D/F. 运行时集成：单层退化等价 + 多图层单窗 + 自愈')
    if not gui_ok:
        for i in range(1, 14):
            skip(f'D/F{i:02d}', '无桌面环境（GUI 不可用）')
        return
    import tkinter

    real_skins = R.SKINS_DIR
    tmp_skins = os.path.join(tmp, 'skins_rt')
    os.makedirs(tmp_skins, exist_ok=True)
    a = make_img(os.path.join(tmp, 'ra.png'), (80, 120), (0, 0, 0, 0),
                 band=(20, 70, (210, 40, 40, 255)))
    b = make_img(os.path.join(tmp, 'rb.png'), (50, 180), (0, 0, 0, 0),
                 band=(20, 90, (30, 60, 220, 255)))
    c = make_img(os.path.join(tmp, 'rc.png'), (44, 44), (0, 0, 0, 0),
                 band=(4, 20, (40, 190, 90, 255)))
    real_save = R.save_config
    real_mb = (R.messagebox.showinfo, R.messagebox.showwarning,
               R.messagebox.showerror, R.messagebox.askyesno)
    R.save_config = lambda cfg: None            # 不写真实 config.json
    R.messagebox.showinfo = lambda *a, **k: None      # 模态框会挂住测试，一律打桩
    R.messagebox.showwarning = lambda *a, **k: None
    R.messagebox.showerror = lambda *a, **k: None
    R.messagebox.askyesno = lambda *a, **k: True
    ov = None
    fake = None
    try:
        R.SKINS_DIR = tmp_skins
        fake = FakeCandidate(x=140, y=180, w=420, h=72)
        rect = fake.rect()

        # ---- D. 单层退化等价 ----
        cfg = dict(R.DEFAULT_CONFIG)
        cfg.update({'image': a, 'layout': 'horizontal_double', 'side': 'right',
                    'scale': 0.7, 'offset_x': 5, 'offset_y': -4})
        ov = R.FollowOverlay(cfg)
        try:
            ov.tray.stop()
        except Exception:
            pass
        check('D01 单层：layers 解析为 1 层', len(ov._layer_specs()) == 1,
              str(len(ov._layer_specs())))
        check('D02 单层：_layers_active() 为 False（走 v1.6 老路径）',
              ov._layers_active() is False, repr(ov._layers_active()))
        ex, ey = ov._calc_target(rect)
        wx, wy, ww, wh, pl = ov._calc_layer_targets(rect)
        check('D03 单层：_calc_layer_targets 的窗口坐标 == _calc_target（逐位）',
              (wx, wy) == (ex, ey), f'got=({wx},{wy}) exp=({ex},{ey})')
        check('D04 单层：窗口尺寸 == self.w/self.h', (ww, wh) == (ov.w, ov.h),
              f'got=({ww},{wh}) exp=({ov.w},{ov.h})')
        check('D05 单层：placements == [(0,0,0)]', pl == [(0, 0, 0)], str(pl))

        for side in ('left', 'center', 'right'):
            ov.cfg['side'] = side
            ov.off_x, ov.off_y = 3, -2
            ex, ey = ov._calc_target(rect)
            wx, wy, _ww, _wh, _pl = ov._calc_layer_targets(rect)
            check(f'D06 side={side}：仍然与 _calc_target 完全一致', (wx, wy) == (ex, ey),
                  f'got=({wx},{wy}) exp=({ex},{ey})')
        ov.off_x, ov.off_y = 0, 0

        # ---- F. 多图层 ----
        mcfg = dict(R.DEFAULT_CONFIG)
        mcfg.update({'image': a, 'layout': 'horizontal_double', 'side': 'left',
                     'scale': 0.8, 'layers': [
                         {'image': a, 'anchor': 'left_edge', 'z': 0},
                         {'image': b, 'anchor': 'right_edge', 'z': 1, 'scale': 0.9},
                         {'image': c, 'anchor': 'center', 'z': 2, 'offset_y': 40}]})
        ov2 = R.FollowOverlay(mcfg)
        try:
            ov2.tray.stop()
        except Exception:
            pass
        check('F01 三层档案解析出 3 层', len(ov2._layer_specs()) == 3,
              str(len(ov2._layer_specs())))
        check('F02 _layers_active() 为 True', ov2._layers_active() is True)
        dims = ov2._layer_dims(ov2._Image)
        check('F03 三层显示尺寸都算出来了', len(dims) == 3 and all(w > 0 and h > 0
                                                              for w, h in dims), str(dims))
        wx, wy, ww, wh, pl = ov2._calc_layer_targets(rect)
        check('F04 多图层窗口宽度 > 单个图层宽度（画布容纳所有层）',
              ww > max(w for w, _h in dims), f'ww={ww} max_layer={max(w for w, _h in dims)}')
        check('F05 placements 覆盖 3 层且不越出窗口',
              len(pl) == 3 and all(0 <= dx and 0 <= dy for _i, dx, dy in pl), str(pl))

        # ---- 单窗纪律（F-V2：纯 Tk 记账断言，不依赖「Tk 窗首次 update 才进 EnumWindows」的时序）----
        ov2._cached_hwnd = fake.hwnd
        R.set_candidate_hwnd(fake.hwnd)
        kids_before = str(ov2.root.tk.eval('winfo children .')).split()
        ov2._position_once()
        kids_after = str(ov2.root.tk.eval('winfo children .')).split()
        check('F06 多图层不为每层开窗：root 下没有额外 Toplevel',
              not [k for k in kids_after if 'toplevel' in k], f'children={kids_after}')
        check('F06b 定位前后 Tk 子窗口集合不变（定位不创建窗口/控件；.!label + .!menu 是既有控件）',
              kids_after == kids_before, f'before={kids_before} after={kids_after}')
        n_lbl = len([x for x in ov2.root.winfo_children() if isinstance(x, tkinter.Label)])
        check('F07 多图层仍只有 1 个承载控件（不是每层一个控件/窗口）', n_lbl <= 1,
              f'labels={n_lbl}')
        check('F08 多图层定位后窗口可见', ov2.visible is True, repr(ov2.visible))

        top = ov2._top_hwnd()
        wr = wintypes.RECT()
        R.user32.GetWindowRect(top, ctypes.byref(wr))
        check('F10 真实窗口位置与布局计算一致',
              abs(wr.left - wx) < 4 and abs(wr.top - wy) < 4,
              f'win=({wr.left},{wr.top}) exp=({wx},{wy})')
        check('F11 真实窗口宽度与画布宽度一致（±2px 边框）',
              abs((wr.right - wr.left) - ww) <= 2, f'win_w={wr.right - wr.left} exp={ww}')

        # 候选框变宽 → 窗口变宽、左右层拉开
        span0 = _layer_gap_of(ov2, fake.rect())
        fake.move(140, 180, w=700)
        ov2._pos_dirty = True
        ov2._position_once()
        rect_w = fake.rect()
        wx2, wy2, ww2, wh2, pl2 = ov2._calc_layer_targets(rect_w)
        span1 = _layer_gap_of(ov2, rect_w)
        check('F12 候选框变宽 → 左右两图层间距同步拉开', span1 > span0, f'{span0}→{span1}')
        check('F13 候选框变宽 → 窗口随之变宽', ww2 > ww, f'{ww}→{ww2}')
        top = ov2._top_hwnd()
        R.user32.GetWindowRect(top, ctypes.byref(wr))
        check('F14 变宽后真实窗口位置尺寸都跟上',
              abs(wr.left - wx2) < 6 and abs((wr.right - wr.left) - ww2) <= 4,
              f'win=({wr.left},{wr.top},{wr.right - wr.left}) exp=({wx2},{wy2},{ww2})')

        fake.move(140, 180, w=420)
        ov2._pos_dirty = True
        ov2._position_once()
        span2 = _layer_gap_of(ov2, fake.rect())
        check('F15 候选框变窄 → 两层收拢回原间距', abs(span2 - span0) <= 2,
              f'{span1}→{span2} (orig {span0})')

        # ---- 句柄重建自愈 ----
        old_hwnd = fake.hwnd
        fake.destroy()
        R.set_candidate_hwnd(0)
        ov2._cached_hwnd = 0
        R._EVT_GONE_CNT += 1
        ov2._event_tick()
        fake2 = FakeCandidate(x=300, y=240, w=460, h=80)
        R._EVT_SHOW_CNT += 1
        R._EVT_CACHE_HWND = fake2.hwnd
        attached = ov2._try_attach_show_hwnd(fake2.hwnd)
        rect2 = fake2.rect()
        wx3, wy3, ww3, wh3, pl3 = ov2._calc_layer_targets(rect2)
        top = ov2._top_hwnd()
        R.user32.GetWindowRect(top, ctypes.byref(wr))
        check('F16 候选框重建后 SHOW 直挂命中新句柄',
              attached is True and ov2._cached_hwnd == fake2.hwnd,
              f'attached={attached} cached=0x{ov2._cached_hwnd:X}')
        check('F17 重建后图层不错位（窗口位置 == 新 rect 的布局结果）',
              abs(wr.left - wx3) < 6 and abs(wr.top - wy3) < 6,
              f'win=({wr.left},{wr.top}) exp=({wx3},{wy3})')
        check('F18 重建后 3 层 placement 仍完整', len(pl3) == 3, str(pl3))
        check('F19 重建后旧句柄不会再被使用', ov2._cached_hwnd != old_hwnd)

        # ---- compat / alpha 两种模式都能跑多图层 ----
        for mode in ('compat', 'alpha'):
            mc = dict(mcfg)
            mc['render_mode'] = mode
            ov2.cfg = mc
            ov2._sync_render_mode()
            ov2.load_char()
            ov2._cached_hwnd = fake2.hwnd
            R.set_candidate_hwnd(fake2.hwnd)
            ov2._position_once()
            frame = ov2._compose_frame()
            check(f'F20 render_mode={mode} 能合成多图层帧',
                  frame is not None and frame.size[0] > 0 and frame.size[1] > 0,
                  str(getattr(frame, 'size', None)))
            check(f'F21 render_mode={mode} 渲染器类型匹配',
                  type(ov2.renderer).__name__ == ('LayeredRenderer' if mode == 'alpha'
                                                  else 'CompatRenderer'),
                  type(ov2.renderer).__name__)
            check(f'F22 render_mode={mode} 合成帧 == 当前布局窗口尺寸',
                  frame is not None and frame.size == (ww3, wh3),
                  f'{getattr(frame, "size", None)} vs {(ww3, wh3)}')

        # ---- 合成画布尺寸 / 预乘性能记录 ----
        fr = ov2._compose_frame()
        import time as _t
        rnd = getattr(ov2.renderer, 'premultiply_bgra', None)
        if rnd and fr is not None:
            t0 = _t.perf_counter()
            for _ in range(3):
                rnd(fr)
            ms = (_t.perf_counter() - t0) / 3 * 1000
            print(f'    [PERF] 三层合成画布 {fr.size[0]}x{fr.size[1]} '
                  f'预乘耗时 {ms:.2f} ms/帧（{fr.size[0] * fr.size[1] / 1000:.0f}K 像素）')
            check('F23 三层画布预乘耗时 < 60ms/帧（移动重推不卡）', ms < 60, f'{ms:.2f}ms')
        else:
            skip('F23 预乘耗时（当前渲染模式无 premultiply）')

        # ---- 合成帧内容正确性 ----
        if fr is not None:
            bb = fr.getbbox()
            check('F24 合成帧非全透明（有内容）', bb is not None, str(bb))
            check('F25 合成帧保留 alpha 跨度（未被二值化）',
                  _has_alpha_variety(fr), '有 alpha 跨度')
            check('F26 三层内容都落在画布内（bbox 覆盖多段）',
                  bb is not None and (bb[2] - bb[0]) > 0, str(bb))

        # ---- ② 兜底：候选框只改宽度（weasel 可能不发事件）与零尺寸保护 ----
        ov2._position_once()
        check('F27 定位后候选框矩形无变化 → _rect_changed() 为 False',
              ov2._rect_changed() is False, str(getattr(ov2, '_applied_rect', None)))
        fake2.move(300, 240, w=620, h=80)
        check('F28 候选框只改宽度（不动位置）→ _rect_changed() 为 True',
              ov2._rect_changed() is True, str(getattr(ov2, '_applied_rect', None)))
        ov2._position_once()          # 心跳兜底走的就是这条路径
        wx4, wy4, ww4, wh4, _pl4 = ov2._calc_layer_targets(fake2.rect())
        top = ov2._top_hwnd()
        R.user32.GetWindowRect(top, ctypes.byref(wr))
        check('F29 变宽后窗口宽度补上（心跳兜底路径可用）',
              abs((wr.right - wr.left) - ww4) <= 4,
              f'win_w={wr.right - wr.left} exp={ww4}')

        saved_layers = ov2.cfg.get('layers')
        ov2.cfg['layers'] = [{'image': os.path.join(tmp, 'missing1.png'),
                              'anchor': 'left_edge'},
                             {'image': os.path.join(tmp, 'missing2.png'),
                              'anchor': 'right_edge'}]
        _x5, _y5, w5, h5, _ch5 = ov2._plan_targets(fake2.rect())
        top = ov2._top_hwnd()
        R.user32.GetWindowRect(top, ctypes.byref(wr))
        check('F30 图层图全缺失 → 不传尺寸（窗口绝不被缩成 0）',
              w5 is None and h5 is None and (wr.right - wr.left) > 0,
              f'w={w5} h={h5} win_w={wr.right - wr.left}')
        ov2.cfg['layers'] = saved_layers
    finally:
        R.SKINS_DIR = real_skins
        R.save_config = real_save
        (R.messagebox.showinfo, R.messagebox.showwarning,
         R.messagebox.showerror, R.messagebox.askyesno) = real_mb
        for o in (ov, locals().get('ov2')):
            try:
                if o is not None:
                    o.root.destroy()
            except Exception:
                pass
        for f in (fake, locals().get('fake2')):
            try:
                if f is not None:
                    f.destroy()
            except Exception:
                pass


def _count_top_windows(exclude=()):
    """当前屏幕上的可见顶层窗口数（不含 exclude）"""
    n = [0]

    cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _impl(hwnd, _lp):
        try:
            if hwnd in exclude:
                return True
            if R.user32.IsWindowVisible(hwnd):
                n[0] += 1
        except Exception:
            pass
        return True

    try:
        R.user32.EnumWindows(cb(_impl), 0)
    except Exception:
        pass
    return n[0]


def _own_tk_windows():
    """本进程的 Tk 顶层窗口句柄集合（验证「不新增 N 个窗口」）。

    Windows 上 overrideredirect 的 Tk 窗在 EnumWindows 里类名是 TkChild，
    普通顶层窗是 TkTopLevel —— 两种都算（实测于本机 Tk 8.6）。
    """
    import os as _os
    out = set()
    cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    pid_me = _os.getpid()

    def _impl(hwnd, _lp):
        try:
            p = wintypes.DWORD()
            R.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if int(p.value) != pid_me:
                return True
            buf = ctypes.create_unicode_buffer(256)
            R.user32.GetClassNameW(hwnd, buf, 256)
            if buf.value.startswith('TkTopLevel') or buf.value.startswith('TkChild'):
                out.add(int(hwnd))
        except Exception:
            pass
        return True

    try:
        R.user32.EnumWindows(cb(_impl), 0)
    except Exception:
        pass
    return out


def _layer_gap_of(ov, rect):
    """当前布局下「最左层 x」与「最右层右缘」之间的跨度（用于验证拉开/收拢）"""
    _wx, _wy, _ww, _wh, pl = ov._calc_layer_targets(rect)
    return _ww


def _has_alpha_variety(img):
    """合成帧里同时存在 0<alpha<255 与 alpha==255 的像素（真 alpha 未被二值化）"""
    try:
        a = img.getchannel('A')
        lo, hi = a.getextrema()
        return lo < hi
    except Exception:
        return False


# ==========================================================================
# G. 向导
# ==========================================================================
def test_wizard(tmp, gui_ok):
    section('G. 向导：图层列表 + 每层调参 + 预览多层绘制')
    if not gui_ok:
        for i in range(1, 9):
            skip(f'G{i:02d}', '无桌面环境（GUI 不可用）')
        return
    real_skins = R.SKINS_DIR
    tmp_skins = os.path.join(tmp, 'skins_ui')
    os.makedirs(tmp_skins, exist_ok=True)
    a = make_img(os.path.join(tmp, 'ua.png'), (90, 140), (0, 0, 0, 0),
                 band=(20, 70, (220, 60, 60, 255)))
    b = make_img(os.path.join(tmp, 'ub.png'), (50, 160), (0, 0, 0, 0),
                 band=(20, 80, (60, 60, 220, 255)))
    c = make_img(os.path.join(tmp, 'uc.png'), (40, 40), (0, 0, 0, 0),
                 band=(4, 20, (60, 200, 90, 255)))
    wiz = None
    real_save_cfg = R.save_config
    real_autostart = R.set_autostart
    real_mb = (R.messagebox.showinfo, R.messagebox.showwarning,
               R.messagebox.showerror, R.messagebox.askyesno)
    try:
        R.save_config = lambda cfg: None           # 不写真实 config.json
        R.set_autostart = lambda want, force=False: (True, '（测试打桩）')
        R.messagebox.showinfo = lambda *a, **k: None
        R.messagebox.showwarning = lambda *a, **k: None
        R.messagebox.showerror = lambda *a, **k: None
        R.messagebox.askyesno = lambda *a, **k: True    # 模态框会阻塞，测试里一律打桩
        R.SKINS_DIR = tmp_skins
        cfg = dict(R.DEFAULT_CONFIG)
        cfg.update({'image': a, 'layers': [
            {'image': a, 'anchor': 'left_edge', 'z': 0},
            {'image': b, 'anchor': 'right_edge', 'z': 1, 'scale': 0.9},
            {'image': c, 'anchor': 'center', 'z': 2, 'offset_y': 30}]})
        wiz = R.ConfigWizard(on_done=lambda _c: None, overlay=None)
        wiz.cfg.update(cfg)
        wiz._layer_sync_from_cfg()
        check('G01 向导有图层列表控件', hasattr(wiz, 'layer_list') and wiz.layer_list is not None)
        check('G02 图层列表填充 3 项', wiz.layer_list.size() == 3,
              f'size={wiz.layer_list.size() if hasattr(wiz, "layer_list") else "?"}')
        items = [wiz.layer_list.get(i) for i in range(wiz.layer_list.size())] \
            if hasattr(wiz, 'layer_list') else []
        check('G03 列表项是人话（带层序号/位置/文件名）',
              items and all(('层' in it) or ('#' in it) for it in items), str(items))
        check('G04 有添加/删除图层按钮',
              hasattr(wiz, 'btn_layer_add') and hasattr(wiz, 'btn_layer_del'))
        check('G05 有锚点选择控件', hasattr(wiz, 'var_layer_anchor'))
        check('G06 该层 offset 已并入上方 ⑤⑥ 滑条（图层区不再自带独立控件）',
              (not hasattr(wiz, 'var_lay_offx')) and (not hasattr(wiz, 'var_lay_offy'))
              and hasattr(wiz, 'var_offx') and hasattr(wiz, 'var_offy'))
        check('G07 缩放复用上方 ④；翻转复用通用区 var_flip（R13 起在通用区、统一管所有图层）',
              (not hasattr(wiz, 'var_lay_scale')) and hasattr(wiz, 'var_scale')
              and hasattr(wiz, 'var_flip') and hasattr(wiz, 'chk_flip'))
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(1)
        wiz._on_layer_select()
        check('G08 选中第 2 层后回显其 anchor=right_edge',
              wiz.var_layer_anchor.get() == 'right_edge', repr(wiz.var_layer_anchor.get()))
        check('G09 选中第 2 层后回显其 scale=0.9（上方 ④ 切到该层值）',
              abs(float(wiz.var_scale.get()) - 0.9) < 1e-6, repr(wiz.var_scale.get()))
        wiz.var_offy.set(37)
        wiz._on_main_slider()
        lay1 = wiz.cfg['layers'][1]
        check('G10 拖上方 ⑥ 写回 cfg.layers[1].offset_y', int(lay1.get('offset_y', 0)) == 37,
              repr(lay1.get('offset_y')))
        check('G11 选中第 2 层时第 0 层不受影响',
              int(wiz.cfg['layers'][0].get('offset_y', 0)) == 0,
              repr(wiz.cfg['layers'][0].get('offset_y')))
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(0)
        wiz._on_layer_select()
        check('G12 选中第 1 层时回显顶层兼容字段（offset_y）',
              int(wiz.var_offy.get()) == int(wiz.cfg.get('offset_y', 0)),
              f'var={wiz.var_offy.get()} cfg={wiz.cfg.get("offset_y")}')
        wiz.var_offx.set(21)
        wiz._on_main_slider()
        check('G13 拖上方 ⑤ 改第 0 层 offset_x 同步顶层兼容字段 cfg.offset_x',
              int(wiz.cfg.get('offset_x', 0)) == 21, repr(wiz.cfg.get('offset_x')))
        check('G13b 第 0 层自己的 offset_x 归零（防与顶层翻倍）',
              int(wiz.cfg['layers'][0].get('offset_x', -1)) == 0,
              repr(wiz.cfg['layers'][0].get('offset_x')))
        check('G13c 上方滑条显示同一值',
              int(wiz.var_offx.get()) == 21, repr(wiz.var_offx.get()))

        # 预览多层绘制
        n_before = len(wiz.canvas.find_all())
        wiz._update_preview()
        kinds = [wiz.canvas.type(i) for i in wiz.canvas.find_all()]
        n_img = kinds.count('image')
        check('G14 预览绘制了 3 个图层图像', n_img == 3, f'image_items={n_img} kinds={kinds}')
        check('G15 预览也画了候选框', 'rectangle' in kinds)

        # below + center：候选框层级关系不破
        wiz.var_layer.set('below')
        wiz.var_side.set('center')
        wiz._update_preview()
        order_below = [wiz.canvas.type(i) for i in wiz.canvas.find_all()]
        first_img = order_below.index('image')
        check('G16 below+center：候选框画在图片之后（压住图片，层级不破）',
              any(t == 'rectangle' for t in order_below[first_img:]), str(order_below[:8]))
        wiz.var_layer.set('above')
        wiz.var_side.set('right')
        wiz._update_preview()
        order_above = [wiz.canvas.type(i) for i in wiz.canvas.find_all()]
        check('G17 above：候选框在图片之前画（图片在上）',
              order_above.index('rectangle') < order_above.index('image'),
              str(order_above[:8]))

        # 添加 / 删除
        n0 = len(wiz.cfg['layers'])
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(1)
        wiz._layer_delete()
        check('G18 删除选中层后 layers 少一层', len(wiz.cfg['layers']) == n0 - 1,
              f'{n0}→{len(wiz.cfg["layers"])}')
        check('G19 删除后列表同步', wiz.layer_list.size() == n0 - 1,
              f'size={wiz.layer_list.size()}')
        check('G20 第 0 层不可删（主层保底）',
              _layer_delete_main_guard(wiz), '主层仍在')

        # ---- 上移 / 下移（改叠放顺序 z；换主层时顶层兼容字段跟着同步）----
        wiz.cfg['layers'] = [R.normalize_layer({'image': a, 'anchor': 'left_edge', 'z': 0}),
                             R.normalize_layer({'image': b, 'anchor': 'right_edge', 'z': 1}),
                             R.normalize_layer({'image': c, 'anchor': 'center', 'z': 2})]
        wiz._layer_sel = 0
        wiz._layer_sync_from_cfg()
        names0 = [os.path.basename(x['image']) for x in wiz.cfg['layers']]
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(2)
        wiz._layer_move(-1)
        names1 = [os.path.basename(x['image']) for x in wiz.cfg['layers']]
        check('G23 上移：第 3 层与第 2 层换序',
              names1[0] == names0[0] and names1[1] == names0[2] and names1[2] == names0[1],
              f'{names0} → {names1}')
        check('G24 换序后 z 重排为 0/1/2',
              [int(x.get('z', -1)) for x in wiz.cfg['layers']] == [0, 1, 2],
              str([x.get('z') for x in wiz.cfg['layers']]))
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(1)
        wiz._layer_move(-1)
        _l0 = wiz.cfg['layers'][0]
        check('G25 换主层后顶层 side 同步新主层的锚点',
              wiz.cfg.get('side') == R.side_from_anchor(_l0.get('anchor')),
              f'side={wiz.cfg.get("side")} anchor={_l0.get("anchor")} '
              f'img={os.path.basename(_l0.get("image", ""))}')
        check('G26 换主层后顶层 image 指向新主层',
              os.path.normpath(wiz.cfg.get('image', '')) == os.path.normpath(_l0['image']),
              f'{wiz.cfg.get("image")} vs {_l0["image"]}')

        # 保存回 cfg：schema/layers 都要带出去
        wiz._save_and_start()
        check('G21 保存后 cfg 带 schema:2', int(wiz.cfg.get('schema', 0)) == 2,
              repr(wiz.cfg.get('schema')))
        check('G22 保存后 cfg 带 layers 数组', isinstance(wiz.cfg.get('layers'), list),
              type(wiz.cfg.get('layers')).__name__)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('G00 向导测试未抛异常', False, repr(e))
    finally:
        R.SKINS_DIR = real_skins
        R.save_config = real_save_cfg
        R.set_autostart = real_autostart
        (R.messagebox.showinfo, R.messagebox.showwarning,
         R.messagebox.showerror, R.messagebox.askyesno) = real_mb
        try:
            if wiz is not None:
                wiz.root.destroy()
        except Exception:
            pass


def _layer_delete_main_guard(wiz):
    """attempt 删除第 0 层：主层必须保底不被删掉"""
    try:
        n = len(wiz.cfg['layers'])
        wiz.layer_list.selection_clear(0, 'end')
        wiz.layer_list.selection_set(0)
        wiz._layer_delete()
        return len(wiz.cfg['layers']) == n
    except Exception:
        return False


# ==========================================================================
# H. 端到端向后兼容（F-V1 回归）：release/ 老配置与老皮肤的落点必须与 v1.6 逐位相同
# ==========================================================================
def _v16_xy(w, h, rect, side, off_x=0, off_y=0, cfg_off_x=0, cfg_off_y=0):
    """v1.6 `_calc_target` 的手写复刻（**独立于产品代码**，防"拿被测实现证明自己"）。

    口径与 v1.6 源码一致：gap=8；right→rect.right+gap；left→rect.left-w-gap；
    center→rect.left+(cw-w)//2；y 一律垂直居中；末尾再叠加用户微调偏移。
    """
    cw, ch = rect.right - rect.left, rect.bottom - rect.top
    gap = 8
    if side == 'left':
        x = rect.left - w - gap + off_x + cfg_off_x
    elif side == 'center':
        x = rect.left + (cw - w) // 2 + off_x + cfg_off_x
    else:
        x = rect.right + gap + off_x + cfg_off_x
    y = rect.top + (ch - h) // 2 + off_y + cfg_off_y
    return int(x), int(y)


def _probe_overlay(cfg, fake):
    """建真 overlay → 贴到假候选框 → 返回 (落点, 显示尺寸)；用完立刻销毁。

    进程内只允许一个外挂实例（_close_active_overlay 会销毁前一个），所以必须串行。
    """
    ov = None
    try:
        ov = R.FollowOverlay(dict(cfg))
        try:
            ov.tray.stop()
        except Exception:
            pass
        try:
            ov._anim_stop()          # 动图皮肤（心灵信标 24 帧）不参与本段
        except Exception:
            pass
        ov._cached_hwnd = fake.hwnd
        R.set_candidate_hwnd(fake.hwnd)
        ov._position_once()
        return (int(ov._x), int(ov._y)), (int(ov.w), int(ov.h))
    finally:
        try:
            if ov is not None:
                ov.root.destroy()
        except Exception:
            pass
        R._ACTIVE_OVERLAY = None


def _make_xinling_fixture(tmp):
    """t7-B：在临时目录里自造一份「心灵信标」最小皮肤夹具（老档案形态），返回 (皮肤根目录, 档案路径)。

    为什么自造：本机 release/skins 里已没有这份皮肤（只剩「芙芙」），而原始字节**不可恢复** ——
    _baseline/v16/userdata_fingerprint.json 只记录了它的 sha256/size（image.gif 86978B、
    skin.json 435B，采集时 exists=true）。release/ 又是 gitignore 的本地运行目录，
    不能为了测试往里塞皮肤，所以按项目既有先例（char.png 缺失时脚本用 PIL 现生成）自己造。

    夹具几何**全部取自仓库内已入库的记录性事实**，不是为断言凑数：
      · 参数：由本段 H10~H15 自身记录 —— side=center / layer=below / scale=0.9 /
        offset=(-162,-42)；base_height=300 是老档案 schema 与产品默认值（release/config.json
        与「芙芙」skin.json 都是 300）。
      · 自然尺寸：由 H12 记录的显示尺寸基线 356x270 反解 —— 产品口径
        （rime_char_overlay.py:7880/7901）h = base_height × scale = 270，
        w = int(自然宽 × h / 自然高) ⇒ 自然宽 × 270/300 ∈ [356,357) ⇒ 自然宽 = 396（整数唯一解）。
      · 形态：老档案 = 顶层字段、**无 layers 键**（H14 要断的正是这一点）。
    """
    root = os.path.join(tmp, 'skins_fixture')
    d = os.path.join(root, '心灵信标')
    os.makedirs(d, exist_ok=True)
    img = os.path.join(d, 'image.png')
    make_img(img, (396, 300), (30, 90, 160, 200))
    cfg = {'image': img, 'layout': 'horizontal_double', 'side': 'center',
           'layer': 'below', 'scale': 0.9, 'offset_x': -162, 'offset_y': -42,
           'base_height': 300, 'name': '心灵信标'}
    j = os.path.join(d, 'skin.json')
    with open(j, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return root, j


def test_release_compat(gui_ok, tmp):
    section('H. 端到端向后兼容：release 老配置 / 老皮肤落点 == v1.6（F-V1 回归）')
    rel = os.path.join(BASE, 'release')
    cfg_path = os.path.join(rel, 'config.json')
    if not gui_ok:
        for i in range(1, 16):
            skip(f'H{i:02d}', '无桌面环境（GUI 不可用）')
        return
    if not os.path.exists(cfg_path):
        for i in range(1, 16):
            skip(f'H{i:02d}', 'release/config.json 不存在')
        return

    real_skins = R.SKINS_DIR
    real_save = R.save_config
    real_mb = (R.messagebox.showinfo, R.messagebox.showwarning,
               R.messagebox.showerror, R.messagebox.askyesno)
    fake = None
    try:
        R.save_config = lambda cfg: None
        R.messagebox.showinfo = lambda *a, **k: None
        R.messagebox.showwarning = lambda *a, **k: None
        R.messagebox.showerror = lambda *a, **k: None
        R.messagebox.askyesno = lambda *a, **k: True

        with open(cfg_path, encoding='utf-8') as f:
            raw = json.load(f)
        check('H01 release/config.json 是"老配置"形态（无 layers 键）', 'layers' not in raw,
              str(sorted(raw.keys())))
        check('H02 release/config.json 微调偏移 == -132 / -132',
              int(raw.get('offset_x', 0)) == -132 and int(raw.get('offset_y', 0)) == -132,
              f'{raw.get("offset_x")},{raw.get("offset_y")}')

        # verifier 实测基线用的假候选框：420x72 @ (266,205)
        fake = FakeCandidate(x=266, y=205, w=420, h=72)
        rect = fake.rect()

        # ---- 启动路径：load_config 的语义 = 直接把 config.json 喂给 FollowOverlay ----
        pos, size = _probe_overlay(raw, fake)
        exp = _v16_xy(size[0], size[1], rect, raw.get('side', 'right'),
                      cfg_off_x=int(raw.get('offset_x', 0)),
                      cfg_off_y=int(raw.get('offset_y', 0)))
        check('H03 启动路径：落点 == v1.6 手写公式（逐位）', pos == exp,
              f'got={pos} exp={exp} size={size}')
        check('H04 启动路径：落点 == verifier 实测 v1.6 基线 (562,19)', pos == (562, 19),
              f'got={pos}')
        check('H05 芙芙图显示尺寸 == 128x180（scale 0.6）', size == (128, 180), str(size))
        lost = _v16_xy(size[0], size[1], rect, raw.get('side', 'right'))
        check('H06 若丢掉 offset 会偏成 (694,151) —— 与 verifier 的错落点一致',
              lost == (694, 151), f'got={lost}')

        # ---- 皮肤路径：find_skin → list_skins（会 migrate）----
        R.SKINS_DIR = os.path.join(rel, 'skins')
        sk_fu = R.find_skin('芙芙')
        check('H07 皮肤路径能读到 芙芙 档案', bool(sk_fu))
        if sk_fu:
            pos_skin, size_skin = _probe_overlay(sk_fu, fake)
            exp_skin = _v16_xy(size_skin[0], size_skin[1], rect, sk_fu.get('side', 'right'),
                               cfg_off_x=int(sk_fu.get('offset_x', 0)),
                               cfg_off_y=int(sk_fu.get('offset_y', 0)))
            check('H08 皮肤路径（芙芙）：落点 == v1.6 手写公式', pos_skin == exp_skin,
                  f'got={pos_skin} exp={exp_skin}')
            check('H09 ★两条通路一致：启动路径 == 皮肤路径（同一份数据同一落点）',
                  pos_skin == pos, f'startup={pos} skin={pos_skin}')

        # ---- 心灵信标：本机 release/skins 已无此皮肤，改用测试自造「复刻夹具」----
        #   数据源从 release/skins 换成 tempdir 夹具；H10~H15 的判据表达式一条未改
        #   （H10 断言仍是 bool(find_skin('心灵信标'))，H11~H15 原样）。
        #   判别力实测：夹具就位 → 全绿；夹具目录为空 / 图片缺失 → H10 立刻 FAIL。
        xl_root, xl_json = _make_xinling_fixture(tmp)
        R.SKINS_DIR = xl_root
        sk_xl = R.find_skin('心灵信标')
        check('H10 皮肤路径能读到 心灵信标 档案（center/below/scale0.9/-162,-42；自造复刻夹具）',
              bool(sk_xl))
        if sk_xl:
            check('H10b ★夹具参数读完没走形（side/offset/scale 逐项 == 档案里写的值）',
                  sk_xl.get('side') == 'center'
                  and (int(sk_xl.get('offset_x', 0)), int(sk_xl.get('offset_y', 0))) == (-162, -42)
                  and float(sk_xl.get('scale', 1.0)) == 0.9,
                  f'side={sk_xl.get("side")} '
                  f'offset=({sk_xl.get("offset_x")},{sk_xl.get("offset_y")}) '
                  f'scale={sk_xl.get("scale")}')
            pos_xl, size_xl = _probe_overlay(sk_xl, fake)
            exp_xl = _v16_xy(size_xl[0], size_xl[1], rect, sk_xl.get('side', 'center'),
                             cfg_off_x=int(sk_xl.get('offset_x', 0)),
                             cfg_off_y=int(sk_xl.get('offset_y', 0)))
            check('H11 皮肤路径（心灵信标）：落点 == v1.6 手写公式',
                  pos_xl == exp_xl, f'got={pos_xl} exp={exp_xl}')
            check('H12 心灵信标 落点 == (136,64)（尺寸 356x270 手算基线）',
                  pos_xl == (136, 64), f'got={pos_xl} size={size_xl}')
            check('H12b 显示尺寸 == 356x270（base_height 300 × scale 0.9；自然 396x300）',
                  size_xl == (356, 270), f'size={size_xl}')
            check('H13 心灵信标 x 偏移没丢：与"丢 offset"版本的差值 == 162',
                  (_v16_xy(size_xl[0], size_xl[1], rect, sk_xl.get('side', 'center'))[0]
                   - pos_xl[0]) == 162,
                  f'delta={_v16_xy(size_xl[0], size_xl[1], rect, sk_xl.get("side", "center"))[0] - pos_xl[0]}')
            # 真正的"启动路径"：直接把 skin.json 原文喂给 FollowOverlay（不经 list_skins 的 migrate）
            # —— 模拟老版本程序把档案当配置用 / 用户手工把 skin.json 拷成 config.json 的场景
            with open(xl_json, encoding='utf-8') as f:
                raw_xl = json.load(f)
            check('H14 心灵信标 skin.json 原文是"老档案"形态（无 layers 键）',
                  'layers' not in raw_xl, str(sorted(raw_xl.keys())))
            pos_xl2, _sz2 = _probe_overlay(raw_xl, fake)
            check('H15 ★心灵信标：原始档案启动路径 == 皮肤路径（两条通路逐位一致）',
                  pos_xl2 == pos_xl, f'startup={pos_xl2} skin={pos_xl}')
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('H00 端到端段未抛异常', False, repr(e))
    finally:
        R.SKINS_DIR = real_skins
        R.save_config = real_save
        (R.messagebox.showinfo, R.messagebox.showwarning,
         R.messagebox.showerror, R.messagebox.askyesno) = real_mb
        try:
            if fake is not None:
                fake.destroy()
        except Exception:
            pass
        R._ACTIVE_OVERLAY = None


# ==========================================================================
def main():
    print('=== B_test_layers_schema：v2.0-② 套层皮肤（多图层 + 锚点布局 + 单窗多图合成）===')
    print('Python', sys.version.split()[0])
    tmp = tempfile.mkdtemp(prefix='layers_schema_')
    R.HERE = tmp          # 只读约束（HANDOFF-2.1 §8.5）：日志/临时产物只落临时目录，不碰项目 error.log
    gui_ok = _has_gui()
    print('GUI 可用:', gui_ok, ' | 临时目录:', tmp)
    try:
        test_api_surface()
        test_schema_compat()
        test_skin_io(tmp)
        test_anchor_layout()
        test_compose()
        test_runtime(tmp, gui_ok)
        test_wizard(tmp, gui_ok)
        test_release_compat(gui_ok, tmp)
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass

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
