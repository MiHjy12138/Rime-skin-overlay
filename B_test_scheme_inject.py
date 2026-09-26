# -*- coding: utf-8 -*-
"""B_test_scheme_inject.py —— ③ 选图自动生成候选框配色并安全注入 验证

覆盖：
  [1] 颜色提取（单图 / 动图多帧颜色并集 / 透明像素不参与 / 空输入兜底）
  [2] 21 字段生成（字段名与 weasel.custom.yaml 现成先例逐一对应、无遗漏无多余；亮暗两套）
  [3] 对比度下限（每套 9 组「文字 vs 所在背景」+ 强调色 vs 候选栏底色）
  [4] 临时目录内的注入 / 合并（保留同名方案其它字段、不动 style/* 与其它方案）/ 备份 / 回滚
  [5] dry-run 只返回 diff 不落盘
  [6] WeaselDeployer 缺失 / 失败 / 超时都给明确提示，不静默吞错
  [7] 向导入口与结果提示；皮肤档案保存配色名；切皮肤整套恢复（含光环联动 get_rime_accent）
  [8] 全程不触碰真实 %APPDATA%\\Rime（结束时断言真实文件哈希与目录清单一字未变）

运行: python B_test_scheme_inject.py   （退出码 0 = 全过）
"""
import os
import sys
import json
import shutil
import tempfile

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f'{"PASS" if cond else "FAIL"}  {name}{(" | " + detail) if detail else ""}')


def _md5(p):
    import hashlib
    try:
        h = hashlib.md5()
        with open(p, 'rb') as f:
            h.update(f.read())
        return h.hexdigest()
    except Exception:
        return None


# ---------------- 夹具 ----------------
def make_char_fixture(path):
    """160x240 透明底 RGBA 小人像（与其它回归脚本共用的 char.png 结构）"""
    img = Image.new('RGBA', (160, 240), (0, 0, 0, 0))
    for y in range(20, 220):
        for x in range(40, 120):
            img.putpixel((x, y), (220, 40, 40, 255))       # 红衣服
    for y in range(20, 70):
        for x in range(55, 105):
            img.putpixel((x, y), (245, 225, 200, 255))     # 浅色脸
    for y in range(70, 110):
        for x in range(60, 100):
            img.putpixel((x, y), (40, 70, 200, 255))       # 蓝饰带
    img.save(path)
    return path


def make_multiframe_gif(path):
    """3 帧动图：帧0 全红 / 帧1 全蓝 / 帧2 蓝底 + 帧独有黄块（验证颜色并集）"""
    frames = []
    f0 = Image.new('RGBA', (80, 100), (220, 40, 40, 255))
    f1 = Image.new('RGBA', (80, 100), (40, 70, 200, 255))
    f2 = Image.new('RGBA', (80, 100), (40, 70, 200, 255))
    for y in range(30, 60):
        for x in range(20, 60):
            f2.putpixel((x, y), (250, 220, 30, 255))       # 只在第 3 帧出现的黄
    for f in (f0, f1, f2):
        frames.append(f.convert('P'))
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)
    return path


SAMPLE_CUSTOM = '''# 测试用 weasel.custom.yaml（结构参照真实文件）
customization:
  distribution_code_name: Weasel
patch:
  "style/color_scheme": furina_aqua
  "style/color_scheme_dark": furina_night
  "style/horizontal": true
  "style/layout/corner_radius": 12
  # ===== 芙芙·水色 =====
  "preset_color_schemes/furina_aqua/name": "芙芙·水色 furina_aqua"
  "preset_color_schemes/furina_aqua/author": 贾维斯
  "preset_color_schemes/furina_aqua/color_format": rgba
  "preset_color_schemes/furina_aqua/back_color": 0xDCE2F0
  "preset_color_schemes/furina_aqua/text_color": 0x4A6FA5
  "preset_color_schemes/furina_night/name": "芙芙·夜色 furina_night"
  "preset_color_schemes/furina_night/back_color": 0x1A2A47
'''


def _write(path, text, newline='\n'):
    if newline != '\n':
        text = text.replace('\n', newline)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    return path


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


# ---------------- [1] 颜色提取 ----------------
def test_extract(tmp):
    print('--- [1] 颜色提取（单图 / 动图多帧并集 / 透明像素）---')
    single = os.path.join(tmp, 'single.png')
    make_char_fixture(single)
    frames, meta = R.collect_scheme_frames(single, Image)
    check('1a 单图：帧收集正常', meta['n_frames'] == 1 and len(frames) == 1, str(meta))
    th = R.extract_scheme_theme(frames, Image)
    pr = th['primary']
    check('1b 单图主色 = 面积最大的红衣服', pr[0] > 150 and pr[0] > pr[1] + 60 and pr[0] > pr[2] + 60,
          f'primary={pr}')
    check('1c 单图强调色与主色距离够远（蓝饰带）',
          R._color_dist(th['accent'], pr) >= 60 and th['accent'][2] > th['accent'][0],
          f'accent={th["accent"]}')
    check('1d 亮套底色足够浅（≥ 阈值）',
          R._luma255(th['bg_light']) >= R.SCHEME_BG_LIGHT_MIN_LUMA,
          f'bg_light={th["bg_light"]} luma={R._luma255(th["bg_light"]):.1f}')
    check('1e 暗套底色足够深（≤ 阈值）',
          R._luma255(th['bg_dark']) <= R.SCHEME_BG_DARK_MAX_LUMA,
          f'bg_dark={th["bg_dark"]} luma={R._luma255(th["bg_dark"]):.1f}')

    # 透明像素不参与统计：99% 透明绿 + 1% 实心紫
    trans = Image.new('RGBA', (200, 200), (0, 255, 0, 0))
    for y in range(150, 200):
        for x in range(100, 200):
            trans.putpixel((x, y), (200, 40, 220, 255))
    th2 = R.extract_scheme_theme([trans], Image)
    check('1f 透明像素（alpha=0）不参与配色提取',
          th2['primary'][2] > th2['primary'][1] and th2['primary'][0] > 150,
          f'primary={th2["primary"]}（若把全透明绿算进来会偏绿）')

    # 动图：所有帧颜色并集（第 3 帧独有黄必须进统计）
    gif = os.path.join(tmp, 'multi.gif')
    make_multiframe_gif(gif)
    gf, gmeta = R.collect_scheme_frames(gif, Image)
    check('1g 动图：取到所有帧（而非只首帧）',
          gmeta['n_frames'] == 3 and gmeta['used'] >= 3 and not gmeta['sampled'], str(gmeta))
    th3 = R.extract_scheme_theme(gf, Image)
    names = [s['rgb'] for s in th3['swatches']]
    has_yellow = any(r > 200 and g > 170 and b < 90 for r, g, b in names)
    has_red = any(r > 180 and g < 90 for r, g, b in names)
    has_blue = any(b > 150 and r < 90 for r, g, b in names)
    check('1h 动图颜色并集：红/蓝/仅在末帧出现的黄都在统计里',
          has_yellow and has_red and has_blue,
          f'swatches={names}')
    th_single = R.extract_scheme_theme(gf[:1], Image)
    check('1i 多帧并集结果与只取首帧不同（证明并集真的生效）',
          th3['swatches'] != th_single['swatches'])

    # 空输入兜底
    empty = R.extract_scheme_theme([], Image)
    check('1j 空输入兜底不崩且有合理默认色',
          all(isinstance(empty[k], tuple) and len(empty[k]) == 3
              for k in ('primary', 'accent', 'bg_light', 'bg_dark')))
    frames_empty, meta_empty = R.collect_scheme_frames(single, Image, max_frames=0)
    check('1k 帧收集参数边界（max_frames=0 不崩）', isinstance(meta_empty, dict))


# ---------------- [2] 21 字段生成 ----------------
def test_fields(tmp, real_custom):
    print('--- [2] 21 字段生成（与现成先例逐一对应）---')
    frames, _ = R.collect_scheme_frames(make_char_fixture(os.path.join(tmp, 'f2.png')), Image)
    th = R.extract_scheme_theme(frames, Image)
    names = R.make_scheme_names('demo')
    light = R.build_scheme_fields('demo', th, dark=False, scheme=names[0])
    dark = R.build_scheme_fields('demo', th, dark=True, scheme=names[1])
    check('2a 亮套恰好 21 字段', len(light) == 21, f'{len(light)}')
    check('2b 暗套恰好 21 字段', len(dark) == 21, f'{len(dark)}')
    check('2c 常量字段表本身 21 个且无重复', len(R.SCHEME_FIELDS) == 21 == len(set(R.SCHEME_FIELDS)))
    check('2d 生成字段集合 == SCHEME_FIELDS（无遗漏无多余）',
          set(light) == set(R.SCHEME_FIELDS) and set(dark) == set(R.SCHEME_FIELDS),
          f'多={sorted(set(light) - set(R.SCHEME_FIELDS))} 缺={sorted(set(R.SCHEME_FIELDS) - set(light))}')

    # 与真实 weasel.custom.yaml 先例（furina_aqua）的字段集逐一对账（只读真实文件）
    if real_custom and os.path.exists(real_custom):
        sample = R.parse_flat_yaml(real_custom)
        got = {k.split('/')[2] for k in sample
               if k.startswith('preset_color_schemes/furina_aqua/')}
        check('2e 与真实先例 furina_aqua 的 21 字段完全一致',
              got == set(R.SCHEME_FIELDS),
              f'先例 {len(got)} 个；差集={sorted(got ^ set(R.SCHEME_FIELDS))}')
    else:
        check('2e 与真实先例 furina_aqua 的 21 字段完全一致', False, '真实 weasel.custom.yaml 不存在')

    check('2f 亮/暗方案名不同且暗套带 _dark 尾缀',
          names[0] != names[1] and names[1] == names[0] + '_dark', str(names))
    check('2g color_format / author 写法合规',
          light['color_format'] == 'rgba' and light['author'] == R.SCHEME_AUTHOR)
    import re as _re
    hex6 = _re.compile(r'^0x[0-9A-F]{6}$')
    hex8 = _re.compile(r'^0x[0-9A-F]{8}$')
    colored = ['back_color', 'text_color', 'label_color', 'comment_text_color',
               'candidate_text_color', 'candidate_back_color', 'hilited_text_color',
               'hilited_back_color', 'hilited_candidate_text_color',
               'hilited_candidate_back_color', 'hilited_candidate_border_color',
               'hilited_label_color', 'hilited_comment_text_color',
               'nextpage_color', 'prevpage_color']
    check('2h 颜色字段全部是 0xRRGGBB（15 个）',
          all(hex6.match(light[f]) for f in colored), str([f for f in colored if not hex6.match(light[f])]))
    check('2i 带透明度的字段是 0xAARRGGBB（border/shadow）',
          all(hex8.match(light[f]) for f in ('border_color', 'shadow_color',
                                             'hilited_candidate_shadow_color')),
          f'{light["border_color"]} {light["shadow_color"]}')
    check('2j 亮暗两套底色确实不同（浅底/深底）',
          light['back_color'] != dark['back_color'], f'{light["back_color"]} vs {dark["back_color"]}')
    check('2k 亮暗两套的 name 字段都含方案名',
          names[0] in light['name'] and names[1] in dark['name'], f'{light["name"]} / {dark["name"]}')

    # 方案名：中文皮肤名走稳定哈希、两次调用结果一致、字符安全
    n1 = R.make_scheme_names('阿芙·水色')
    n2 = R.make_scheme_names('阿芙·水色')
    check('2l 中文皮肤名的方案名稳定且只含安全字符',
          n1 == n2 and all(_re.match(r'^[a-z0-9_]+$', x) for x in n1), str(n1))
    check('2m 英文皮肤名 → rime_<名>',
          R.make_scheme_names('furina') == ('rime_furina', 'rime_furina_dark'),
          str(R.make_scheme_names('furina')))


# ---------------- [3] 对比度下限 ----------------
PAIRS = [
    ('text_color', 'back_color', R.SCHEME_MIN_DELTA_MAIN),
    ('candidate_text_color', 'candidate_back_color', R.SCHEME_MIN_DELTA_MAIN),
    ('hilited_text_color', 'hilited_back_color', R.SCHEME_MIN_DELTA_MAIN),
    ('hilited_candidate_text_color', 'hilited_candidate_back_color', R.SCHEME_MIN_DELTA_MAIN),
    ('label_color', 'back_color', R.SCHEME_MIN_DELTA_SUB),
    ('comment_text_color', 'back_color', R.SCHEME_MIN_DELTA_SUB),
    ('hilited_label_color', 'hilited_candidate_back_color', R.SCHEME_MIN_DELTA_SUB),
    ('hilited_comment_text_color', 'hilited_back_color', R.SCHEME_MIN_DELTA_SUB),
    ('nextpage_color', 'back_color', R.SCHEME_MIN_DELTA_SUB),
]


def test_contrast(tmp):
    print('--- [3] 对比度下限（阈值写在实现里）---')
    themes = []
    frames, _ = R.collect_scheme_frames(make_char_fixture(os.path.join(tmp, 'f3.png')), Image)
    themes.append(('红蓝小人像', R.extract_scheme_theme(frames, Image)))
    themes.append(('近白浅色图', R.extract_scheme_theme(
        [Image.new('RGBA', (80, 80), (248, 246, 242, 255))], Image)))
    themes.append(('近黑深色图', R.extract_scheme_theme(
        [Image.new('RGBA', (80, 80), (16, 14, 22, 255))], Image)))
    themes.append(('中灰图', R.extract_scheme_theme(
        [Image.new('RGBA', (80, 80), (128, 128, 128, 255))], Image)))
    bad = []
    for tag, th in themes:
        for dark in (False, True):
            f = R.build_scheme_fields('t', th, dark=dark, scheme='s')
            for fg_k, bg_k, need in PAIRS:
                fg = R._parse_hex_color(f[fg_k])
                bg = R._parse_hex_color(f[bg_k])
                d = abs(R._luma255(fg) - R._luma255(bg))
                if d < need:
                    bad.append(f'{tag}/{"暗" if dark else "亮"}:{fg_k}<->{bg_k}={d:.1f}<{need}')
            ab = abs(R._luma255(R._parse_hex_color(f['hilited_candidate_back_color']))
                     - R._luma255(R._parse_hex_color(f['back_color'])))
            if ab < R.SCHEME_MIN_DELTA_ACCENT_BG:
                bad.append(f'{tag}/{"暗" if dark else "亮"}:强调色<->底色={ab:.1f}')
    check('3a 4 种图 × 亮暗两套 × 9 组文字/背景 + 强调色 全部达下限',
          not bad, '超标项=' + '; '.join(bad[:4]))
    check('3b 阈值常量已写明（主/次/强调-底色）',
          (R.SCHEME_MIN_DELTA_MAIN, R.SCHEME_MIN_DELTA_SUB,
           R.SCHEME_MIN_DELTA_ACCENT_BG) == (100, 70, 40),
          f'{R.SCHEME_MIN_DELTA_MAIN}/{R.SCHEME_MIN_DELTA_SUB}/{R.SCHEME_MIN_DELTA_ACCENT_BG}')
    # _ensure_delta 单测：低对比输入必须被纠正
    fixed = R._ensure_delta((120, 120, 120), (128, 128, 128), R.SCHEME_MIN_DELTA_MAIN, 'dark')
    check('3c _ensure_delta：中灰对中灰 → 自动拉开到下限',
          abs(R._luma255(fixed) - 128) >= R.SCHEME_MIN_DELTA_MAIN, f'{fixed}')
    fixed2 = R._ensure_delta((200, 200, 100), (250, 250, 250), R.SCHEME_MIN_DELTA_MAIN, 'dark')
    check('3d _ensure_delta：浅底 → 压深（保持色相，R>B 不变）',
          fixed2[0] > fixed2[2] and abs(R._luma255(fixed2) - 250) >= R.SCHEME_MIN_DELTA_MAIN,
          f'{fixed2}')
    check('3e 达标的颜色原样返回（不无谓改动）',
          R._ensure_delta((10, 10, 10), (250, 250, 250), R.SCHEME_MIN_DELTA_MAIN) == (10, 10, 10))


# ---------------- [4] 注入 / 合并 / 备份 / 回滚 ----------------
def test_inject(tmp, real_custom):
    print('--- [4] 注入 / 合并 / 备份 / 回滚（临时目录）---')
    work = os.path.join(tmp, 'inject')
    os.makedirs(work, exist_ok=True)
    tgt = os.path.join(work, 'weasel.custom.yaml')
    if real_custom and os.path.exists(real_custom):
        shutil.copy2(real_custom, tgt)
    else:
        _write(tgt, SAMPLE_CUSTOM)
    orig = _read(tgt)
    orig_hash = _md5(tgt)

    frames, _ = R.collect_scheme_frames(make_char_fixture(os.path.join(tmp, 'f4.png')), Image)
    th = R.extract_scheme_theme(frames, Image)
    names = R.make_scheme_names('demo')
    light = R.build_scheme_fields('demo', th, dark=False, scheme=names[0])
    dark = R.build_scheme_fields('demo', th, dark=True, scheme=names[1])

    # --- dry-run：只返回 diff，不落盘 ---
    plan = R.plan_scheme_injection(tgt, skin='demo', light=light, dark=dark,
                                   scheme_light=names[0], scheme_dark=names[1],
                                   set_active=False, dry_run=True)
    check('4a dry-run plan 成功且有 diff', plan['ok'] and len(plan['diff']) >= 42,
          f"diff={len(plan['diff'])} stats={plan['stats']}")
    check('4b dry-run 不落盘（文件字节未变、无 .bak）',
          _md5(tgt) == orig_hash and not [f for f in os.listdir(work) if '.bak-' in f],
          f'files={os.listdir(work)}')
    dry_apply = R.apply_scheme_injection(plan)
    check('4c dry-run 计划被拒绝落盘（双保险）',
          (not dry_apply['ok']) and 'dry-run' in dry_apply['msg'], dry_apply['msg'])
    check('4d dry-run 默认不动 style/*（diff 里无 style 行）',
          not any('style/color_scheme' in d for d in plan['diff']))

    # --- 正式注入（set_active=False）---
    plan2 = R.plan_scheme_injection(tgt, skin='demo', light=light, dark=dark,
                                    scheme_light=names[0], scheme_dark=names[1],
                                    set_active=False)
    wr = R.apply_scheme_injection(plan2, ts='20260926-000000')
    text = _read(tgt)
    bans = [f for f in os.listdir(work) if f.startswith('weasel.custom.yaml.bak-')]
    check('4e 写前生成 .bak-<时间戳> 备份',
          wr['ok'] and wr['backup'] and os.path.basename(wr['backup']) ==
          'weasel.custom.yaml.bak-20260926-000000', str(bans))
    check('4f 备份内容与写前一致', _read(wr['backup']) == orig)
    check('4g 两套方案各 21 键都写进去了',
          all(f'"preset_color_schemes/{names[0]}/{f}":' in text for f in R.SCHEME_FIELDS) and
          all(f'"preset_color_schemes/{names[1]}/{f}":' in text for f in R.SCHEME_FIELDS))
    check('4h 新方案的行数 = 42', text.count(f'preset_color_schemes/{names[0]}/')
          + text.count(f'preset_color_schemes/{names[1]}/') == 42,
          str(text.count(f'preset_color_schemes/{names[0]}/')))
    flat = R.parse_flat_yaml(tgt)
    check('4i 亮套 back_color 与生成值一致',
          R._flat_value(flat, f'preset_color_schemes/{names[0]}/back_color') == light['back_color'],
          f'{R._flat_value(flat, f"preset_color_schemes/{names[0]}/back_color")} vs {light["back_color"]}')
    # 其它方案 / style/* 一字未变
    for key in ('preset_color_schemes/furina_aqua/back_color', 'preset_color_schemes/furina_aqua/name',
                'preset_color_schemes/furina_night/back_color', 'style/horizontal',
                'style/layout/corner_radius'):
        check(f'4j 未触碰 {key}',
              R._flat_value(flat, key) == R._flat_value(R.parse_flat_yaml_text(orig), key),
              f'{R._flat_value(flat, key)}')
    check('4k 其它方案键数量不变（没被清掉）',
          sum(1 for k in flat if k.startswith('preset_color_schemes/furina_aqua/')) ==
          sum(1 for k in R.parse_flat_yaml_text(orig)
              if k.startswith('preset_color_schemes/furina_aqua/')))
    check('4l 注释行数量未变',
          len([l for l in orig.splitlines() if l.strip().startswith('#')]) ==
          len([l for l in text.splitlines() if l.strip().startswith('#')]))

    # --- 幂等：再注入一次应无变化、不再备份 ---
    plan3 = R.plan_scheme_injection(tgt, skin='demo', light=light, dark=dark,
                                    scheme_light=names[0], scheme_dark=names[1])
    wr3 = R.apply_scheme_injection(plan3, ts='20260926-111111')
    bans2 = [f for f in os.listdir(work) if '.bak-' in f]
    check('4m 幂等：重复生成 → diff 为空、不写盘、不新增备份',
          wr3['ok'] and not plan3['diff'] and len(bans2) == 1 and _read(tgt) == text,
          f'diff={len(plan3["diff"])} baks={bans2}')

    # --- 合并语义：同名方案的其它字段保留、缺的字段补全、已有值被更新 ---
    manual = text.replace(f'  "preset_color_schemes/{names[0]}/hilited_label_color": ',
                          f'  "preset_color_schemes/{names[0]}/user_extra_field": keep-me\n'
                          f'  "preset_color_schemes/{names[0]}/hilited_label_color": ', 1)
    manual = manual.replace(f'  "preset_color_schemes/{names[0]}/nextpage_color"', '# 删掉一行', 1)
    _write(tgt, manual)
    light2 = dict(light)
    light2['label_color'] = '0x123456'          # 与现状不同的值 → 应被就地更新
    plan4 = R.plan_scheme_injection(tgt, skin='demo', light=light2, dark={},
                                    scheme_light=names[0], scheme_dark=None)
    R.apply_scheme_injection(plan4, ts='20260926-222222')
    text2 = _read(tgt)
    check('4n 同名方案的其它字段（用户自定义键）被保留',
          'user_extra_field' in text2 and 'keep-me' in text2)
    check('4o 缺失字段被补全（nextpage_color 回来了）',
          f'"preset_color_schemes/{names[0]}/nextpage_color":' in text2)
    check('4p 已有字段就地更新为新值', 
          R._flat_value(R.parse_flat_yaml(tgt), f'preset_color_schemes/{names[0]}/label_color')
          == '0x123456')
    check('4q 删除的注释行不再出现（没被乱改）', '# 删掉一行' in text2)

    # --- stale 清理（皮肤改名 → 旧方案清掉，不堆垃圾）---
    names_new = R.make_scheme_names('demo2')
    light_new = R.build_scheme_fields('demo2', th, dark=False, scheme=names_new[0])
    dark_new = R.build_scheme_fields('demo2', th, dark=True, scheme=names_new[1])
    plan5 = R.plan_scheme_injection(tgt, skin='demo2', light=light_new, dark=dark_new,
                                    scheme_light=names_new[0], scheme_dark=names_new[1],
                                    stale_schemes=(names[0], names[1]), set_active=True)
    R.apply_scheme_injection(plan5, ts='20260926-333333')
    text3 = _read(tgt)
    check('4r 改名后旧方案键被清掉（不堆垃圾）',
          f'preset_color_schemes/{names[0]}/name' not in text3 and
          f'preset_color_schemes/{names[1]}/name' not in text3)
    check('4s 新方案已写入且 style/color_scheme 指向它',
          f'preset_color_schemes/{names_new[0]}/name' in text3 and
          R._flat_value(R.parse_flat_yaml(tgt), 'style/color_scheme') == names_new[0],
          R._flat_value(R.parse_flat_yaml(tgt), 'style/color_scheme'))
    check('4t set_active 时 style/color_scheme_dark 也一起指过去',
          R._flat_value(R.parse_flat_yaml(tgt), 'style/color_scheme_dark') == names_new[1])
    check('4u 其它先例方案仍在（改动有界）',
          R._flat_value(R.parse_flat_yaml(tgt), 'preset_color_schemes/furina_aqua/back_color')
          == R._flat_value(R.parse_flat_yaml_text(orig),
                           'preset_color_schemes/furina_aqua/back_color'))

    # --- 行尾注释保留 / 原子写无残留 ---
    cmt = os.path.join(work, 'comment.yaml')
    _write(cmt, SAMPLE_CUSTOM.replace('  "style/color_scheme": furina_aqua',
                                      '  "style/color_scheme": furina_aqua  # 当前配色'))
    plan9 = R.plan_scheme_injection(cmt, skin='demo', light=light, dark={},
                                    scheme_light=names[0], scheme_dark=None, set_active=True)
    R.apply_scheme_injection(plan9, ts='c')
    t9 = _read(cmt)
    check('4z 改 style/color_scheme 时保留行尾注释',
          '# 当前配色' in t9 and '"style/color_scheme": %s' % names[0] in t9,
          str([l for l in t9.splitlines() if 'style/color_scheme"' in l]))
    check('4z2 原子写后无 .tmp-scheme-write 残留',
          not [f for f in os.listdir(work) if 'tmp-scheme-write' in f], str(os.listdir(work)))
    check('4z3 带行尾注释的 style 值仍能正确比较（不误判为不同）',
          R._flat_value(R.parse_flat_yaml(cmt), 'style/color_scheme') == names[0],
          str(R._flat_value(R.parse_flat_yaml(cmt), 'style/color_scheme')))

    # --- 回滚 ---
    rb = R.restore_weasel_backup(wr['backup'], tgt)
    check('4v 一键回滚：内容回到写前状态',
          rb['ok'] and _read(tgt) == orig and rb['backup_of_current'], rb['msg'])

    # --- CRLF 保留 / 目标缺失 ---
    crlf = os.path.join(work, 'crlf.yaml')
    _write(crlf, SAMPLE_CUSTOM, newline='\r\n')
    plan6 = R.plan_scheme_injection(crlf, skin='demo', light=light, dark=dark,
                                    scheme_light=names[0], scheme_dark=names[1])
    R.apply_scheme_injection(plan6, ts='x')
    raw = open(crlf, 'rb').read()
    check('4w CRLF 文件仍为 CRLF（不改用户换行风格）',
          b'\r\n' in raw and raw.count(b'\r\n') == raw.count(b'\n'), 'CRLF')
    missing_parent = os.path.join(work, 'nodir', 'weasel.custom.yaml')
    plan7 = R.plan_scheme_injection(missing_parent, skin='demo', light=light, dark=dark,
                                    scheme_light=names[0], scheme_dark=names[1])
    check('4x 目标目录不存在 → ok=False 且提示明确（不静默新建目录）',
          (not plan7['ok']) and '未找到 Rime 配置目录' in plan7['msg'], plan7['msg'])
    newfile = os.path.join(work, 'new.yaml')
    plan8 = R.plan_scheme_injection(newfile, skin='demo', light=light, dark=dark,
                                    scheme_light=names[0], scheme_dark=names[1])
    wr8 = R.apply_scheme_injection(plan8, ts='n')
    check('4y 目标文件不存在但目录在 → 建最小骨架并明确标注',
          plan8['ok'] and plan8['created'] and wr8['ok'] and
          _read(newfile).startswith('patch:') and '无旧文件可备份' in wr8['msg'],
          wr8['msg'])


# ---------------- [5] WeaselDeployer ----------------
def test_deployer(tmp):
    print('--- [5] WeaselDeployer：缺失 / 失败 / 超时都给明确提示 ---')

    class _Timeout(Exception):
        pass

    _Timeout.__name__ = 'TimeoutExpired'
    fake_exe = os.path.join(tmp, 'WeaselDeployer.exe')
    _write(fake_exe, 'MZ fake')

    r1 = R.run_weasel_deployer(exe=os.path.join(tmp, 'nope.exe'), runner=lambda c, t: 0)
    check('5a exe 不存在 → ok=False + 提示含「未找到 WeaselDeployer」+ 手动部署指引',
          (not r1['ok']) and '未找到 WeaselDeployer' in r1['msg'] and '重新部署' in r1['msg'],
          r1['msg'])
    r2 = R.run_weasel_deployer(exe=fake_exe, runner=lambda c, t: (_ for _ in ()).throw(_Timeout()))
    check('5b 超时 → timed_out=True + 提示含「秒未返回」',
          (not r2['ok']) and r2['timed_out'] and '秒未返回' in r2['msg'], r2['msg'])
    r3 = R.run_weasel_deployer(exe=fake_exe, runner=lambda c, t: 7)
    check('5c 非 0 返回码 → ok=False + 回显返回码',
          (not r3['ok']) and r3['rc'] == 7 and '返回码 7' in r3['msg'], r3['msg'])
    r4 = R.run_weasel_deployer(exe=fake_exe, runner=lambda c, t: 0)
    check('5d 成功 → ok=True + 回显已部署', r4['ok'] and '已调用' in r4['msg'], r4['msg'])
    r5 = R.run_weasel_deployer(exe=fake_exe,
                               runner=lambda c, t: (_ for _ in ()).throw(OSError('拒绝访问')))
    check('5e 启动异常 → ok=False + 明确原因（不吞错）',
          (not r5['ok']) and '拒绝访问' in r5['msg'], r5['msg'])
    called = {}

    def _runner(cmd, t):
        called['cmd'] = cmd
        called['timeout'] = t
        return 0

    R.run_weasel_deployer(exe=fake_exe, runner=_runner, timeout=11.0)
    check('5f runner 收到 exe 与超时参数', called.get('cmd') == fake_exe and called.get('timeout') == 11.0,
          str(called))
    found = R.find_weasel_deployer(extra=os.path.join(tmp, 'nope2.exe'))
    check('5g find_weasel_deployer 未命中显式路径时返回 None 或真实文件',
          found is None or os.path.isfile(found), str(found))


# ---------------- [6] 向导入口 / 皮肤绑定 / 光环联动 ----------------
def _patch_messagebox(store):
    """把向导里的 messagebox 弹窗打桩（记录调用，不阻塞）"""
    import tkinter.messagebox as mb
    orig = {}
    for fn in ('showinfo', 'showwarning', 'showerror', 'askyesno'):
        orig[fn] = getattr(mb, fn)

        def _mk(name):
            def _f(*a, **k):
                store.append((name, a[0] if a else '', a[1] if len(a) > 1 else ''))
                return True
            return _f
        setattr(mb, fn, _mk(fn))
    return orig


def _restore_messagebox(orig):
    import tkinter.messagebox as mb
    for k, v in orig.items():
        setattr(mb, k, v)


def test_wizard_binding(tmp, real_custom):
    print('--- [6] 向导入口 / 皮肤档案绑定 / 切皮肤整套恢复 ---')
    work = os.path.join(tmp, 'wiz')
    os.makedirs(work, exist_ok=True)
    tgt = os.path.join(work, 'weasel.custom.yaml')
    if real_custom and os.path.exists(real_custom):
        shutil.copy2(real_custom, tgt)
    else:
        _write(tgt, SAMPLE_CUSTOM)
    base_hash = _md5(tgt)
    img = make_char_fixture(os.path.join(work, 'char.png'))

    # 全局安全重定向：所有注入目标都在临时目录
    real = (R.WEASEL_CUSTOM, R.RIME_DIR, R.SCHEME_MANIFEST, R.SKINS_DIR)
    R.WEASEL_CUSTOM = tgt
    R.RIME_DIR = work
    R.SCHEME_MANIFEST = os.path.join(work, 'rime_schemes.json')
    R.SKINS_DIR = os.path.join(work, 'skins')
    deploy_calls = []

    def _fake_deploy(exe=None, timeout=None, runner=None, extra_dir=None):
        deploy_calls.append(1)
        return {'ok': True, 'msg': '已调用 WeaselDeployer 重新部署（fake）',
                'exe': 'fake', 'rc': 0, 'timed_out': False}

    real_deploy = R.run_weasel_deployer
    R.run_weasel_deployer = _fake_deploy
    msgs = []
    mb_orig = _patch_messagebox(msgs)
    wiz = None
    try:
        wiz = R.ConfigWizard(on_done=lambda c: None, overlay=None)
        wiz.root.withdraw()
        check('6a 向导有「生成候选框配色」入口按钮', hasattr(wiz, 'btn_scheme'),
              str(getattr(wiz, 'btn_scheme', None)))
        check('6b 向导有结果提示标签', hasattr(wiz, 'lbl_scheme_hint'))
        # 缺图片 → 明确提示，不崩
        res0 = wiz._generate_scheme(auto=True)
        check('6c 未选图片 → ok=False + 明确提示', (not res0['ok']) and '图片' in res0['msg'],
              res0['msg'])
        # dry-run：只算不写
        wiz.cfg['image'] = img
        res_dry = wiz._generate_scheme(auto=True, dry_run=True)
        check('6d 向导 dry-run：plan 有 diff 且文件未变、无备份',
              res_dry['ok'] and res_dry['plan']['dry_run'] and len(res_dry['plan']['diff']) > 40
              and _md5(tgt) == base_hash and not [f for f in os.listdir(work) if '.bak-' in f],
              res_dry['msg'])
        # 正式生成
        res = wiz._generate_scheme(auto=True)
        text = _read(tgt)
        style_now = R._flat_value(R.parse_flat_yaml(tgt), 'style/color_scheme')
        check('6e 向导生成成功并写入 21×2 键',
              res['ok'] and text.count('preset_color_schemes/') >= 42, res['msg'])
        check('6f 向导把配色名写进 cfg（供档案/配置保存）',
              bool(wiz.cfg.get('rime_scheme')) and bool(wiz.cfg.get('rime_scheme_dark')),
              f"{wiz.cfg.get('rime_scheme')} / {wiz.cfg.get('rime_scheme_dark')}")
        check('6g 生成后自动把候选框切到新方案（color_scheme 已指向它）',
              style_now == wiz.cfg.get('rime_scheme'), str(style_now))
        check('6h 部署器被调用且结果进入提示',
              deploy_calls and '重新部署' in res['msg'], res['msg'])
        hint = wiz.lbl_scheme_hint.cget('text') if hasattr(wiz, 'lbl_scheme_hint') else ''
        check('6i 向导结果提示标签回显方案名', wiz.cfg['rime_scheme'] in hint, repr(hint))
        check('6j 生成了 .bak 备份', bool([f for f in os.listdir(work) if '.bak-' in f]),
              str(os.listdir(work)))
        check('6k 生成记录写入 manifest（清理残留用）',
              json.load(open(R.SCHEME_MANIFEST, encoding='utf-8')).get('阿芙') is not None or
              bool(json.load(open(R.SCHEME_MANIFEST, encoding='utf-8'))),
              R.SCHEME_MANIFEST)

        # 皮肤档案：保存 → 读回 → 含配色名
        scfg = dict(wiz.cfg)
        scfg['name'] = '阿芙'
        saved = R.save_skin('阿芙', scfg)
        check('6l 皮肤档案保存了配色名',
              bool(saved.get('rime_scheme')) and
              bool(json.load(open(os.path.join(R.SKINS_DIR, '阿芙', 'skin.json'),
                                  encoding='utf-8')).get('rime_scheme')),
              str(saved.get('rime_scheme')))
        back = R.find_skin('阿芙')
        check('6m 读回皮肤档案仍带配色名', bool(back and back.get('rime_scheme')))

        # 切皮肤：整套恢复（图 + 参数 + 配色）+ 光环联动
        _write(tgt, _read(tgt).replace('style/color_scheme": %s' % saved['rime_scheme'],
                                       'style/color_scheme": furina_aqua', 1))
        before = _md5(tgt)
        ov = R.FollowOverlay(dict(back))
        try:
            try:
                ov.tray.stop()
            except Exception:
                pass
            R.WEASEL_CUSTOM = tgt
            r = ov._bind_rime_scheme(back)
            check('6n 切皮肤触发配色整套恢复（写回 + 重部署）',
                  r[0] and R._flat_value(R.parse_flat_yaml(tgt),
                                         'style/color_scheme') == saved['rime_scheme'],
                  str(r))
            check('6o 切皮肤前有备份（可一键还原）',
                  _md5(tgt) != before and
                  bool([f for f in os.listdir(work) if '.bak-' in f]))
            accent = R.get_rime_accent()
            want = R._parse_hex_color(back['rime_scheme'] and R.parse_flat_yaml(tgt).get(
                'preset_color_schemes/%s/hilited_candidate_back_color' % saved['rime_scheme']))
            check('6p 光环联动：get_rime_accent 读到新方案的高亮底色',
                  accent == want, f'{accent} vs {want}')
            # 未绑定配色的皮肤 → 不写文件（老用户零感知）
            h0 = _md5(tgt)
            r2 = ov._bind_rime_scheme({'name': '老皮肤', 'image': img})
            check('6q 未绑定配色的皮肤：静默跳过、不写文件',
                  r2[0] and r2[1] and '未绑定' in r2[1] and _md5(tgt) == h0, str(r2))
            # 幂等
            n_bak = len([f for f in os.listdir(work) if '.bak-' in f])
            r3 = ov._bind_rime_scheme(back)
            check('6r 已是指定配色时不再重写（不堆备份）',
                  r3[0] and len([f for f in os.listdir(work) if '.bak-' in f]) == n_bak, str(r3))
            # ↩ 一键还原（向导入口）
            check('6s 向导有「还原配色备份」入口', hasattr(wiz, 'btn_scheme_restore'))
            latest = R.find_latest_weasel_backup(tgt)
            check('6t 能定位最近的备份（排除 .bak-restore-*）',
                  bool(latest) and '.bak-restore-' not in latest, str(latest))
            r4 = wiz._restore_scheme_backup(auto=True)
            check('6u 一键还原：内容回到备份 + 重部署 + 解绑配色名',
                  r4['ok'] and R._flat_value(R.parse_flat_yaml(tgt), 'style/color_scheme')
                  == 'furina_aqua' and not wiz.cfg.get('rime_scheme'), str(r4['msg']))
            check('6v 还原前把当前文件另存 .bak-restore-*（可再次撤回）',
                  bool([f for f in os.listdir(work) if '.bak-restore-' in f]),
                  str(os.listdir(work)))
            r5 = wiz._restore_scheme_backup(auto=True)
            check('6w 无备份可用时（仅剩 .bak-restore-*）明确提示不静默',
                  r5['ok'] or '没有找到配色备份' in r5['msg'], r5['msg'])
        finally:
            try:
                ov.root.destroy()
            except Exception:
                pass
    finally:
        R.run_weasel_deployer = real_deploy
        _restore_messagebox(mb_orig)
        if wiz is not None:
            try:
                wiz.root.destroy()
            except Exception:
                pass
        R.WEASEL_CUSTOM, R.RIME_DIR, R.SCHEME_MANIFEST, R.SKINS_DIR = real


# ---------------- [7] 真实 Rime 目录零触碰 ----------------
def test_real_untouched(real_custom, snap_before):
    print('--- [7] 真实 %APPDATA%\\Rime 零触碰 ---')
    check('7a 真实 weasel.custom.yaml 哈希未变',
          _md5(real_custom) == snap_before['hash'], f"{real_custom}")
    try:
        now = sorted(os.listdir(os.path.dirname(real_custom)))
    except Exception:
        now = None
    added = [f for f in (now or []) if f not in (snap_before['files'] or [])]
    check('7b 真实 Rime 目录没有新增文件（无新 .bak）', not added, str(added))


def main():
    tmp = tempfile.mkdtemp(prefix='scheme_')
    real_custom = R.WEASEL_CUSTOM          # 真实路径（只读）
    try:
        snap = {'hash': _md5(real_custom), 'files': sorted(os.listdir(os.path.dirname(real_custom)))}
    except Exception:
        snap = {'hash': None, 'files': []}
    real_here = R.HERE
    R.HERE = tmp                            # 日志写临时目录，别污染项目
    print('=' * 64)
    print(f'真实 Rime 目录（只读、不写）：{os.path.dirname(real_custom)}')
    print('=' * 64)
    try:
        test_extract(tmp)
        test_fields(tmp, real_custom)
        test_contrast(tmp)
        test_inject(tmp, real_custom)
        test_deployer(tmp)
        test_wizard_binding(tmp, real_custom)
        test_real_untouched(real_custom, snap)
    finally:
        R.HERE = real_here
    print('=' * 64)
    print(f'通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项')
    if FAIL:
        print('失败项: ' + ', '.join(FAIL))
        return 1
    print('ALL CHECKS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
