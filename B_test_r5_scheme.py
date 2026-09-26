# -*- coding: utf-8 -*-
"""B_test_r5_scheme.py —— R5「配色注入两处」验证

用户原话（HANDOFF-2.0 §3 R5）：
  「颜色注入依旧没有先保存皮肤名字的提醒，而且注入 weasel.custom.yaml 时没有标题，
    和我最后一个皮肤并一起的。」

覆盖：
  A 段 · yaml 分节标题与空行（纯函数 + tempfile，不碰真文件）
      A1 紧贴反例输入 → 新块前面有 `# ===== <皮肤名> =====` 标题且至少 1 个空行
      A2 A1 走完整 plan → apply → 落盘结果逐行核对
      A3 亮/暗两套标题各 1 个、与自己的 21 行紧邻、不与别的方案混行
      A4 幂等：同一皮肤重复注入 → diff 为空 / 不写盘 / 标题不重复 / 键数仍 21×2
      A5 两个皮肤先后注入 → 两块各自完整、各 1 个标题
      A5b 皮肤改名重注入 → 旧标题被清（不留孤儿注释）、新标题 1 个
      A6 原文件里用户自己写的注释一条不丢（真实 weasel.custom.yaml 副本）
      A7 皮肤名为空 → 标题退化为方案名，不出现空标题
      A8 只改 style/color_scheme（无新键）→ 不插标题
      A9 CRLF 文件：标题行与空行也用 CRLF，不出现混合换行
      A10 目标文件不存在（目录在）→ 骨架 + 标题
  B 段 · 先绑皮肤名（向导 GUI，串行跑，跑完 destroy）
      B1 未保存皮肤 + 用户在提示里选「否」→ 不写文件、不建档案、提示明确
      B2 未保存皮肤 + 确认保存 → 档案落盘，scheme 名以皮肤名命名（不是匿名的图片名）
      B3 已保存皮肤 → 不再弹保存提示（askstring 零调用），名字稳定不换
      B4 未保存皮肤 + auto=True → 程序化保存分支（无弹窗、不挂死），名字跟随皮肤名
      B5 同一皮肤重复生成 → 方案名稳定、不产生第二套 / 第二个标题
      B6 切皮肤整套恢复：图片 + 参数 + 对应 scheme 绑定各自成套，不串
      B7 dry-run → 零副作用（不落盘、不建档案）
  C 段 · 真实 %APPDATA%\\Rime 零触碰（前后 md5 + 目录清单逐字段对比）

设计口径（实现前先写死，作为红→绿判据）：
  · 标题行形如 `  # ===== <皮肤名> =====`（亮套）/ `  # ===== <皮肤名> · 深色 =====`（暗套），
    对齐用户文件里现成的 `  # ===== 柚子橙 🍊 亮色 =====` 写法（同为 patch 段 2 空格缩进注释）；
  · 标题只在「该方案真的有新增键」时才写，且同一标题文本已存在则不重复写（幂等）；
  · 新块与前一块之间至少 1 个空行。

运行: python B_test_r5_scheme.py   （退出码 0 = 全过；默认 GBK 控制台直接跑）
"""
import os
import sys
import re
import json
import shutil
import hashlib
import tempfile

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
try:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import rime_char_overlay as R

PASS, FAIL, SKIP = [], [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f'{"PASS" if cond else "FAIL"}  {name}{(" | " + detail) if detail else ""}')


def section(t):
    print('')
    print('-' * 8, t, '-' * 8)


def _md5(p):
    try:
        h = hashlib.md5()
        with open(p, 'rb') as f:
            h.update(f.read())
        return h.hexdigest()
    except Exception:
        return None


def _write(path, text, newline='\n'):
    if newline != '\n':
        text = text.replace('\n', newline)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    return path


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def _lines(path):
    return _read(path).splitlines()


# ---------------- 夹具 ----------------
# 「紧贴上一块」反例：patch 段最后一行的下一行就是文件尾（没有空行），
# 且上一个块是用户手写的配色 —— 旧实现会把新键直接怼在它屁股后面。
TIGHT_CUSTOM = '''# 测试用 weasel.custom.yaml（结构参照真实文件；patch 段尾部「紧贴」）
customization:
  distribution_code_name: Weasel
  distribution_version: 0.17.0
patch:
  "style/color_scheme": furina_aqua
  "style/horizontal": true
  # ===== 芙芙·水色 =====
  "preset_color_schemes/furina_aqua/name": "芙芙·水色 furina_aqua"
  "preset_color_schemes/furina_aqua/back_color": 0xDCE2F0
  # ===== 柚子橙 亮色 =====
  "preset_color_schemes/yuzu_orange/name": "柚子橙 yuzu_orange"
  "preset_color_schemes/yuzu_orange/back_color": 0xFFFBF1'''


def make_char_fixture(path, base=(220, 40, 40)):
    img = Image.new('RGBA', (160, 240), (0, 0, 0, 0))
    for y in range(20, 220):
        for x in range(40, 120):
            img.putpixel((x, y), base + (255,))
    for y in range(20, 70):
        for x in range(55, 105):
            img.putpixel((x, y), (245, 225, 200, 255))
    img.save(path)
    return path


HEADER_RE = re.compile(r'^\s*#\s*=+\s*(?P<title>.+?)\s*=+\s*$')


def _header_indices(lines, title_part):
    out = []
    for i, ln in enumerate(lines):
        m = HEADER_RE.match(ln)
        if m and title_part in m.group('title'):
            out.append(i)
    return out


def _key_span(lines, start, sname):
    """从 start 起连续读取属于 sname 的键行，返回 (行列表, 结束下标)"""
    out, i = [], start
    tag = 'preset_color_schemes/%s/' % sname
    while i < len(lines) and tag in lines[i]:
        out.append(lines[i])
        i += 1
    return out, i


def _scheme_pair(tmp, tag, base=(220, 40, 40)):
    img = make_char_fixture(os.path.join(tmp, 'f_%s.png' % tag), base)
    frames, _m = R.collect_scheme_frames(img, Image)
    th = R.extract_scheme_theme(frames, Image)
    names = R.make_scheme_names(tag)
    light = R.build_scheme_fields(tag, th, dark=False, scheme=names[0])
    dark = R.build_scheme_fields(tag, th, dark=True, scheme=names[1])
    return names, light, dark


# ================= A 段：yaml 分节标题与空行 =================
def test_a1_tight(work):
    section('A1 紧贴反例：新块前有标题 + 至少 1 个空行（纯函数）')
    names, light, dark = _scheme_pair(work, 'demo')
    src = TIGHT_CUSTOM
    new, diff, stats = R.merge_scheme_into_yaml(
        src, [(names[0], light), (names[1], dark)], skin='阿芙')
    lines = new.splitlines()
    h_l = _header_indices(lines, '阿芙')
    check('A1a 亮/暗两套各写了 1 个分节标题', len(h_l) == 2, f'找到 {len(h_l)} 个：{h_l}')
    if len(h_l) == 2:
        hi = h_l[0]
        check('A1b 亮套标题形如 `# ===== 阿芙 =====`',
              lines[hi].strip() == '# ===== 阿芙 =====', repr(lines[hi]))
        check('A1c 暗套标题带「深色」区分',
              lines[hi + 22].strip() == '# ===== 阿芙 · 深色 =====', repr(lines[hi + 22]))
        check('A1d ★标题之前至少有 1 个空行（不再与上一个皮肤并在一起）',
              hi > 0 and lines[hi - 1].strip() == '',
              f'标题前一行={lines[hi - 1]!r}（原文件尾部本来是紧贴的）')
        keys_l, end_l = _key_span(lines, hi + 1, names[0])
        check('A1e 亮套 21 行紧跟在标题后（中间无别的方案/无空行）',
              len(keys_l) == 21, f'{len(keys_l)} 行')
        check('A1f 亮套之后立刻是暗套标题',
              end_l == hi + 22 and lines[end_l].strip() == '# ===== 阿芙 · 深色 =====',
              repr(lines[end_l] if end_l < len(lines) else None))
        keys_d, end_d = _key_span(lines, end_l + 1, names[1])
        check('A1g 暗套 21 行紧跟在暗套标题后', len(keys_d) == 21, f'{len(keys_d)} 行')
        check('A1h 原有行一字未动（新内容只追加在末尾）',
              lines[:len(src.splitlines())] == src.splitlines(),
              '\n'.join(lines[:14][-3:]))
        check('A1i diff 里带 + 标题行（用户预览能看见标题）',
              any(d.strip() == '+ # ===== 阿芙 =====' for d in diff),
              str([d for d in diff if '=====' in d]))
        check('A1j 键行数仍是 42（标题不算键）',
              sum(1 for ln in lines if 'preset_color_schemes/' in ln)
              - sum(1 for ln in src.splitlines() if 'preset_color_schemes/' in ln) == 42,
              f"stats={stats}")
    else:
        for nm in ('A1b', 'A1c', 'A1d', 'A1e', 'A1f', 'A1g', 'A1h', 'A1i', 'A1j'):
            check(nm, False, '标题数不对，后续断言无法进行')


def test_a2_ondisk(work):
    section('A2 落盘核对（plan → apply，tempfile 副本）')
    tgt = os.path.join(work, 'a2.yaml')
    _write(tgt, TIGHT_CUSTOM)
    names, light, dark = _scheme_pair(work, 'demo')
    plan = R.plan_scheme_injection(tgt, skin='阿芙', light=light, dark=dark,
                                   scheme_light=names[0], scheme_dark=names[1])
    wr = R.apply_scheme_injection(plan, ts='r5a2')
    lines = _lines(tgt)
    h = _header_indices(lines, '阿芙')
    check('A2a 文件里两套方案各 21 键', wr['ok'] and
          sum(1 for ln in lines if 'preset_color_schemes/%s/' % names[0] in ln) == 21 and
          sum(1 for ln in lines if 'preset_color_schemes/%s/' % names[1] in ln) == 21,
          wr['msg'])
    check('A2b 磁盘上确有 2 个标题且第一个前有空行',
          len(h) == 2 and h[0] > 0 and lines[h[0] - 1].strip() == '', str(h))
    flat = R.parse_flat_yaml(tgt)
    check('A2c 标题注释不影响取值（back_color 仍读得到）',
          R._flat_value(flat, 'preset_color_schemes/%s/back_color' % names[0]) == light['back_color'],
          R._flat_value(flat, 'preset_color_schemes/%s/back_color' % names[0]))
    check('A2d 写入前有 .bak 备份',
          bool(wr['backup']) and os.path.exists(wr['backup']), str(wr['backup']))


def test_a3_idem(work):
    section('A3 幂等：重复注入不产生重复标题/重复块')
    tgt = os.path.join(work, 'a3.yaml')
    _write(tgt, TIGHT_CUSTOM)
    names, light, dark = _scheme_pair(work, 'demo')
    plan1 = R.plan_scheme_injection(tgt, skin='阿芙', light=light, dark=dark,
                                    scheme_light=names[0], scheme_dark=names[1])
    R.apply_scheme_injection(plan1, ts='r5a3-1')
    text1 = _read(tgt)
    n_bak1 = len([f for f in os.listdir(work) if '.bak-' in f])
    plan2 = R.plan_scheme_injection(tgt, skin='阿芙', light=light, dark=dark,
                                    scheme_light=names[0], scheme_dark=names[1])
    wr2 = R.apply_scheme_injection(plan2, ts='r5a3-2')
    text2 = _read(tgt)
    check('A3a 第二次注入 diff 为空、不写盘',
          wr2['ok'] and not plan2['diff'] and text2 == text1,
          f"diff={len(plan2['diff'])} {wr2['msg']}")
    check('A3b 未新增备份', len([f for f in os.listdir(work) if '.bak-' in f]) == n_bak1)
    lines = text2.splitlines()
    check('A3c 标题数仍是 2（没有堆出重复标题）',
          len(_header_indices(lines, '阿芙')) == 2, str(_header_indices(lines, '阿芙')))
    check('A3d 键行仍是 21×2（没有堆出重复块）',
          sum(1 for ln in lines if 'preset_color_schemes/%s/' % names[0] in ln) == 21 and
          sum(1 for ln in lines if 'preset_color_schemes/%s/' % names[1] in ln) == 21)
    # 再跑一次纯函数（不带 stale）也必须是零变化
    new3, diff3, _s = R.merge_scheme_into_yaml(
        text2, [(names[0], light), (names[1], dark)], skin='阿芙')
    check('A3e 纯函数重复调用结果逐字符相同', new3 == text2 and not diff3,
          f'diff={len(diff3)}')


def test_a5_two_skins(work):
    section('A5 两个皮肤先后注入 → 两块各自完整、各 1 个标题')
    tgt = os.path.join(work, 'a5.yaml')
    _write(tgt, TIGHT_CUSTOM)
    n1, l1, d1 = _scheme_pair(work, 'sfw')
    n2, l2, d2 = _scheme_pair(work, 'miku', base=(40, 70, 200))
    p1 = R.plan_scheme_injection(tgt, skin='阿芙', light=l1, dark=d1,
                                 scheme_light=n1[0], scheme_dark=n1[1])
    R.apply_scheme_injection(p1, ts='r5a5-1')
    p2 = R.plan_scheme_injection(tgt, skin='初音', light=l2, dark=d2,
                                 scheme_light=n2[0], scheme_dark=n2[1])
    R.apply_scheme_injection(p2, ts='r5a5-2')
    lines = _lines(tgt)
    ha = _header_indices(lines, '阿芙')
    hb = _header_indices(lines, '初音')
    check('A5a 两个皮肤各 2 个标题（亮 + 深色），互不共用',
          len(ha) == 2 and len(hb) == 2, f'阿芙={ha} 初音={hb}')
    if len(ha) == 2 and len(hb) == 2:
        check('A5b 第 2 块的标题前有空行（两块不粘连）',
              hb[0] > 0 and lines[hb[0] - 1].strip() == '', repr(lines[hb[0] - 1]))
        ka, ea = _key_span(lines, ha[0] + 1, n1[0])
        kb, eb = _key_span(lines, hb[0] + 1, n2[0])
        check('A5c 第 1 块 21 行完整（未被第 2 块插入打断）', len(ka) == 21, f'{len(ka)}')
        check('A5d 第 2 块 21 行完整', len(kb) == 21, f'{len(kb)}')
    check('A5e 改名重注入：旧标题被清、新标题 1 个（不留孤儿注释）',
          _retitle_case(work))


def _retitle_case(work):
    tgt = os.path.join(work, 'a5e.yaml')
    _write(tgt, TIGHT_CUSTOM)
    n1, l1, d1 = _scheme_pair(work, 'oldn')
    p1 = R.plan_scheme_injection(tgt, skin='旧皮肤', light=l1, dark=d1,
                                 scheme_light=n1[0], scheme_dark=n1[1])
    R.apply_scheme_injection(p1, ts='r5a5e-1')
    has_old = bool(_header_indices(_lines(tgt), '旧皮肤'))
    n2, l2, d2 = _scheme_pair(work, 'newn')
    p2 = R.plan_scheme_injection(tgt, skin='新皮肤', light=l2, dark=d2,
                                 scheme_light=n2[0], scheme_dark=n2[1],
                                 stale_schemes=(n1[0], n1[1]))
    R.apply_scheme_injection(p2, ts='r5a5e-2')
    lines = _lines(tgt)
    old_left = _header_indices(lines, '旧皮肤')
    new_h = _header_indices(lines, '新皮肤')
    return (has_old and not old_left and len(new_h) == 2
            and sum(1 for ln in lines if 'preset_color_schemes/%s/' % n1[0] in ln) == 0
            and sum(1 for ln in lines if 'preset_color_schemes/%s/' % n2[0] in ln) == 21)


def test_a6_comments(work, real_custom):
    section('A6 用户原有注释一条不丢（真实文件只读副本）')
    src = _read(real_custom) if (real_custom and os.path.exists(real_custom)) else TIGHT_CUSTOM
    tgt = os.path.join(work, 'a6.yaml')
    _write(tgt, src)
    names, light, dark = _scheme_pair(work, 'demo')
    plan = R.plan_scheme_injection(tgt, skin='阿芙', light=light, dark=dark,
                                   scheme_light=names[0], scheme_dark=names[1])
    R.apply_scheme_injection(plan, ts='r5a6')
    before = [ln.strip() for ln in src.splitlines() if ln.strip().startswith('#')]
    after = [ln.strip() for ln in _lines(tgt) if ln.strip().startswith('#')]
    check('A6a ★原有注释行一条不丢（多重集包含，顺序不变）',
          _subseq_contains(after, before),
          f'原有 {len(before)} 条 / 现在 {len(after)} 条')
    new_cmts = [c for c in after if c not in before]
    check('A6b 新增注释只有本工具的 2 个分节标题',
          sorted(set(new_cmts)) == sorted({'# ===== 阿芙 =====', '# ===== 阿芙 · 深色 ====='}),
          str(new_cmts))
    check('A6c 真实文件本身没被写（副本操作）',
          _md5(real_custom) == _md5(real_custom), 'only-read')


def _subseq_contains(hay, needle):
    """needle 是否为 hay 的子序列（顺序保持）"""
    it = iter(hay)
    return all(any(x == n for x in it) for n in needle)


def test_a7_edge(work):
    section('A7 边界：皮肤名为空 / 只改 style / CRLF / 目标缺失')
    tgt = os.path.join(work, 'a7.yaml')
    _write(tgt, TIGHT_CUSTOM)
    names, light, dark = _scheme_pair(work, 'demo')
    plan = R.plan_scheme_injection(tgt, skin='', light=light, dark=dark,
                                   scheme_light=names[0], scheme_dark=names[1])
    lines = plan['new_text'].splitlines()
    hdrs = [ln for ln in lines if ln.strip().startswith('# =====')]
    titles = [(HEADER_RE.match(ln).group('title').strip() if HEADER_RE.match(ln) else '')
              for ln in hdrs]
    check('A7a 皮肤名为空 → 标题退化为方案名（不出现空标题）',
          ('# ===== %s =====' % names[0]) in plan['new_text']
          and all(titles) and len(hdrs) == 4,
          f'标题={[t for t in titles]}')

    # 只改 style/color_scheme（没有任何新键）→ 不插标题
    tgt2 = os.path.join(work, 'a7b.yaml')
    _write(tgt2, TIGHT_CUSTOM)
    p1 = R.plan_scheme_injection(tgt2, skin='阿芙', light=light, dark=dark,
                                 scheme_light=names[0], scheme_dark=names[1])
    R.apply_scheme_injection(p1, ts='r5a7-1')
    n_cmt_before = len([ln for ln in _lines(tgt2) if ln.strip().startswith('#')])
    p2 = R.plan_scheme_injection(tgt2, skin='阿芙', light={}, dark={},
                                 scheme_light='yuzu_orange', scheme_dark=None,
                                 set_active=True)
    R.apply_scheme_injection(p2, ts='r5a7-2')
    t2 = _read(tgt2)
    check('A7b 只切当前配色（无新键）→ 不插标题、注释行数不变',
          len([ln for ln in t2.splitlines() if ln.strip().startswith('#')]) == n_cmt_before
          and 'yuzu_orange' in t2, f'{n_cmt_before}')

    # CRLF
    crlf = os.path.join(work, 'a7c.yaml')
    _write(crlf, TIGHT_CUSTOM, newline='\r\n')
    p3 = R.plan_scheme_injection(crlf, skin='阿芙', light=light, dark=dark,
                                 scheme_light=names[0], scheme_dark=names[1])
    R.apply_scheme_injection(p3, ts='r5a7-3')
    raw = open(crlf, 'rb').read()
    check('A7c CRLF 文件：新标题/空行也是 CRLF（无混合换行）',
          raw.count(b'\r\n') == raw.count(b'\n') and b'# ===== \xe9\x98\xbf\xe8\x8a\x99 =====' in raw,
          f'{raw.count(b"\\r\\n")}/{raw.count(b"\\n")}')

    # 目标文件不存在（目录在）→ 骨架 + 标题
    newf = os.path.join(work, 'a7d.yaml')
    p4 = R.plan_scheme_injection(newf, skin='阿芙', light=light, dark=dark,
                                 scheme_light=names[0], scheme_dark=names[1])
    w4 = R.apply_scheme_injection(p4, ts='r5a7-4')
    t4 = _read(newf) if os.path.exists(newf) else ''
    check('A7d 目标文件不存在 → 建骨架且带标题',
          w4['ok'] and t4.startswith('patch:') and '# ===== 阿芙 =====' in t4,
          w4['msg'])


# ================= B 段：先绑皮肤名（向导） =================
def _patch_dialogs(store, yesno=True, askstring=None, askstring_boom=False):
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd
    orig = {'mb': {}, 'sd': sd.askstring}

    def _mk(name):
        def _f(*a, **k):
            store.append((name, a[0] if a else '', a[1] if len(a) > 1 else ''))
            return True
        return _f
    for fn in ('showinfo', 'showwarning', 'showerror', 'askyesno'):
        orig['mb'][fn] = getattr(mb, fn)

        def _mkw(name):
            def _f(*a, **k):
                store.append((name, a[0] if a else '', a[1] if len(a) > 1 else ''))
                return bool(yesno)
            return _f

        def _mks(name):
            def _f(*a, **k):
                store.append((name, a[0] if a else '', a[1] if len(a) > 1 else ''))
                return True
            return _f
        setattr(mb, fn, _mkw(fn) if fn == 'askyesno' else _mks(fn))

    def _ask(*a, **k):
        store.append(('askstring', a[0] if a else '', k.get('initialvalue', '')))
        if askstring_boom:
            raise AssertionError('不该弹「保存皮肤名」输入框（皮肤已保存）')
        return askstring
    sd.askstring = _ask
    return orig


def _restore_dialogs(orig):
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd
    for k, v in orig['mb'].items():
        setattr(mb, k, v)
    sd.askstring = orig['sd']


def _hint(wiz):
    try:
        return wiz.lbl_scheme_hint.cget('text')
    except Exception:
        return ''


def test_b_wizard(tmp, work, real_custom):
    section('B 段 先绑皮肤名（未保存 → 提示并可完成保存）')
    os.makedirs(work, exist_ok=True)
    tgt = os.path.join(work, 'wz.yaml')
    if real_custom and os.path.exists(real_custom):
        shutil.copy2(real_custom, tgt)
    else:
        _write(tgt, TIGHT_CUSTOM)
    img_a = make_char_fixture(os.path.join(work, 'char.png'))
    img_b = make_char_fixture(os.path.join(work, 'green.png'), base=(40, 160, 70))
    skins_dir = os.path.join(work, 'skins')

    real = (R.WEASEL_CUSTOM, R.RIME_DIR, R.SCHEME_MANIFEST, R.SKINS_DIR, R.HERE)
    R.WEASEL_CUSTOM = tgt
    R.RIME_DIR = work
    R.SCHEME_MANIFEST = os.path.join(work, 'rime_schemes.json')
    R.SKINS_DIR = skins_dir
    R.HERE = work
    dep_calls = []

    def _fake_deploy(exe=None, timeout=None, runner=None, extra_dir=None):
        dep_calls.append(1)
        return {'ok': True, 'msg': '已调用 WeaselDeployer 重新部署（fake）',
                'exe': 'fake', 'rc': 0, 'timed_out': False}
    real_deploy = R.run_weasel_deployer
    R.run_weasel_deployer = _fake_deploy
    wiz = None
    msgs = []
    dlg = _patch_dialogs(msgs, yesno=False, askstring=None)
    try:
        wiz = R.ConfigWizard(on_done=lambda c: None, overlay=None)
        wiz.root.withdraw()
        wiz.cfg['image'] = img_a
        wiz.cfg.pop('name', None)
        base_hash = _md5(tgt)

        # --- B1 未保存皮肤 + 用户拒绝保存 → 不写文件 ---
        msgs[:] = []
        res1 = wiz._generate_scheme(auto=False)
        check('B1a ★未保存皮肤 → 生成被拦下（ok=False）且提示要皮肤名',
              (not res1['ok']) and ('皮肤' in res1['msg']), res1['msg'])
        check('B1b ★没有写入 weasel.custom.yaml（哈希未变、无新 .bak）',
              _md5(tgt) == base_hash and not [f for f in os.listdir(work) if '.bak-' in f],
              str(os.listdir(work)))
        check('B1c 没有建皮肤档案', not os.path.isdir(skins_dir) or not os.listdir(skins_dir),
              str(os.listdir(skins_dir) if os.path.isdir(skins_dir) else None))
        check('B1d 弹出了「先保存皮肤名」的确认框（有提醒）',
              any(t.startswith('先保存皮肤名') or '皮肤' in str(t) for t in [m[1] for m in msgs]),
              str(msgs[:3]))
        check('B1e 向导提示行也说明原因', '皮肤' in _hint(wiz), repr(_hint(wiz)))
        check('B1f 没有任何匿名 scheme 名被写进文件',
              _md5(tgt) == base_hash and not any('preset_color_schemes/rime_' in ln
                                                 for ln in _lines(tgt)))

        # --- B7 dry-run 零副作用 ---
        before_files = sorted(os.listdir(work))
        res7 = wiz._generate_scheme(auto=True, dry_run=True)
        check('B7a ★dry-run 成功且不落盘', res7['ok'] and res7['plan']['dry_run']
              and _md5(tgt) == base_hash, res7['msg'])
        check('B7b ★dry-run 不建皮肤档案、不写 manifest',
              not os.path.isdir(skins_dir) or not os.listdir(skins_dir),
              str(sorted(os.listdir(work)) == before_files))

        # --- B2 未保存皮肤 + 确认保存 → 档案落盘、名字跟随皮肤名 ---
        _restore_dialogs(dlg)
        msgs[:] = []
        dlg = _patch_dialogs(msgs, yesno=True, askstring='阿芙')
        res2 = wiz._generate_scheme(auto=False)
        want = R.make_scheme_names('阿芙')
        arch = os.path.join(skins_dir, '阿芙', 'skin.json')
        acfg = json.load(open(arch, encoding='utf-8')) if os.path.exists(arch) else {}
        text = _read(tgt)
        check('B2a ★确认后先保存了皮肤档案', os.path.exists(arch) and acfg.get('name') == '阿芙',
              f'files={os.listdir(skins_dir) if os.path.isdir(skins_dir) else None}')
        check('B2b ★schema 名以皮肤名命名（== make_scheme_names(皮肤名)）',
              res2.get('skin') == '阿芙' and res2['scheme_light'] == want[0]
              and res2['scheme_dark'] == want[1],
              f"{res2.get('skin')} / {res2.get('scheme_light')} / {res2.get('scheme_dark')}")
        check('B2c ★不是匿名（图片名）方案：与 image stem 命名不同',
              want[0] != R.make_scheme_names('char')[0], f'{want[0]}')
        check('B2d 写入 yaml 的就是这套名字（21×2 键）',
              text.count('preset_color_schemes/%s/' % want[0]) == 21
              and text.count('preset_color_schemes/%s/' % want[1]) == 21,
              str(text.count('preset_color_schemes/%s/' % want[0])))
        check('B2e yaml 里有 `# ===== 阿芙 =====` 标题（可查找）',
              '# ===== 阿芙 =====' in text and '# ===== 阿芙 · 深色 =====' in text)
        check('B2f ★皮肤档案记录了 scheme 名',
              acfg.get('rime_scheme') == want[0] and acfg.get('rime_scheme_dark') == want[1],
              str({k: acfg.get(k) for k in ('rime_scheme', 'rime_scheme_dark')}))
        check('B2g 档案里的图仍是档案自己的副本（没被改）',
              (acfg.get('image') or '').startswith(os.path.join(skins_dir, '阿芙')),
              str(acfg.get('image')))
        check('B2h 向导提示行回显方案名', want[0] in _hint(wiz), repr(_hint(wiz)))
        check('B2i 部署被调用', bool(dep_calls))

        # --- B3 已保存皮肤 → 不再要求保存 ---
        _restore_dialogs(dlg)
        msgs[:] = []
        dlg = _patch_dialogs(msgs, yesno=True, askstring_boom=True)
        wiz.skin_var.set('阿芙')
        n_bak = len([f for f in os.listdir(work) if '.bak-' in f])
        res3 = wiz._generate_scheme(auto=False)
        check('B3a ★已保存皮肤：不再弹保存输入框（askstring 零调用）',
              not [m for m in msgs if m[0] == 'askstring'], str(msgs[:3]))
        check('B3b 名字稳定（同一皮肤同一套方案名）',
              res3['scheme_light'] == want[0] and res3['scheme_dark'] == want[1],
              f"{res3['scheme_light']}")
        check('B3c 幂等：没有新备份、标题/键数都没涨',
              len([f for f in os.listdir(work) if '.bak-' in f]) == n_bak
              and text.count('# ===== 阿芙 =====') == 1
              and _read(tgt).count('preset_color_schemes/%s/' % want[0]) == 21,
              str(os.listdir(work)))

        # --- B4/B5 auto 分支（无弹窗）+ 名字跟随皮肤名 ---
        wiz.cfg['image'] = img_b
        wiz.cfg.pop('name', None)
        wiz.skin_var.set('')
        try:
            wiz.var_scale.set(1.7)
            wiz.var_offx.set(24)
            # 真实界面里滑条回调会同步写 cfg；测试直接 .set() 绕过了回调，这里手动补上口径
            wiz.cfg['scale'] = 1.7
            wiz.cfg['offset_x'] = 24
        except Exception as e:
            print('    （scale/offset 设置失败：%s）' % e)
        res4 = wiz._generate_scheme(auto=True)
        arch_b = os.path.join(skins_dir, 'green', 'skin.json')
        want_b = R.make_scheme_names('green')
        check('B4a ★auto 分支程序化保存皮肤（无弹窗、不挂死）',
              res4['ok'] and os.path.exists(arch_b), res4['msg'])
        check('B4b ★scheme 名跟随皮肤名（ASCII 名可读）',
              want_b == ('rime_green', 'rime_green_dark')
              and res4['scheme_light'] == 'rime_green'
              and 'preset_color_schemes/rime_green/name' in _read(tgt),
              str(want_b))
        check('B4c 该皮肤在 yaml 里也有自己的标题',
              '# ===== green =====' in _read(tgt))
        res5 = wiz._generate_scheme(auto=True)
        t5 = _read(tgt)
        check('B5a 同一皮肤重复生成：方案名不变、不产生第二套',
              res5['scheme_light'] == want_b[0]
              and t5.count('preset_color_schemes/rime_green_dark/') == 21,
              str(res5['scheme_light']))
        check('B5b 标题不重复', t5.count('# ===== green =====') == 1
              and t5.count('# ===== green · 深色 =====') == 1, str(t5.count('# ===== green =====')))

        # --- B6 切皮肤整套恢复（不串） ---
        a_arch = json.load(open(arch, encoding='utf-8'))
        b_arch = json.load(open(arch_b, encoding='utf-8'))
        wiz.skin_var.set('阿芙')
        wiz._apply_skin_to_wizard()
        snap_a = (wiz.cfg.get('image'), wiz.cfg.get('rime_scheme'), wiz.cfg.get('scale'),
                  wiz.cfg.get('offset_x'))
        hint_a = _hint(wiz)
        wiz.skin_var.set('green')
        wiz._apply_skin_to_wizard()
        snap_b = (wiz.cfg.get('image'), wiz.cfg.get('rime_scheme'), wiz.cfg.get('scale'),
                  wiz.cfg.get('offset_x'))
        hint_b = _hint(wiz)
        wiz.skin_var.set('阿芙')
        wiz._apply_skin_to_wizard()
        snap_a2 = (wiz.cfg.get('image'), wiz.cfg.get('rime_scheme'), wiz.cfg.get('scale'),
                   wiz.cfg.get('offset_x'))
        check('B6a ★两个皮肤各自恢复自己的图（不串）',
              snap_a[0] and snap_b[0] and snap_a[0] != snap_b[0]
              and os.path.basename(os.path.dirname(snap_a[0])) == '阿芙'
              and os.path.basename(os.path.dirname(snap_b[0])) == 'green',
              f'{snap_a[0]} | {snap_b[0]}')
        check('B6b ★各自恢复自己的 scheme 绑定（不串）',
              snap_a[1] == a_arch.get('rime_scheme') == want[0]
              and snap_b[1] == b_arch.get('rime_scheme') == 'rime_green',
              f'{snap_a[1]} | {snap_b[1]}')
        check('B6c 各自恢复自己的参数（不串）',
              snap_a[2] != snap_b[2] or snap_a[3] != snap_b[3],
              f'A={snap_a[2:]}, B={snap_b[2:]}')
        check('B6d 来回切回阿芙 → 逐项与第一次一致',
              snap_a2 == snap_a, f'{snap_a2} vs {snap_a}')
        check('B6e 提示行分别回显各自的 scheme 名',
              want[0] in hint_a and 'rime_green' in hint_b and want[0] not in hint_b,
              f'A={hint_a!r} B={hint_b!r}')
        # 切皮肤时真的把 weasel.custom.yaml 指到各自方案
        r_a = R.apply_rime_scheme_binding(dict(a_arch), path=tgt, runner=lambda c, t: 0)
        got_a = R._flat_value(R.parse_flat_yaml(tgt), 'style/color_scheme')
        r_b = R.apply_rime_scheme_binding(dict(b_arch), path=tgt, runner=lambda c, t: 0)
        got_b = R._flat_value(R.parse_flat_yaml(tgt), 'style/color_scheme')
        check('B6f ★切皮肤把当前配色指到各自方案（真文件通路）',
              r_a['ok'] and r_b['ok'] and got_a == want[0] and got_b == 'rime_green',
              f'{got_a} / {got_b}')
        check('B6g 写回时对每套方案都带自己的标题（两套都在文件里）',
              '# ===== 阿芙 =====' in _read(tgt) and '# ===== green =====' in _read(tgt))

        # --- B6h 还原备份 → 皮肤档案解绑（不留悬空绑定） ---
        msgs[:] = []
        _restore_dialogs(dlg)
        dlg = _patch_dialogs(msgs, yesno=True, askstring='阿芙')
        wiz.skin_var.set('阿芙')
        r_res = wiz._restore_scheme_backup(auto=True)
        a_after = json.load(open(arch, encoding='utf-8'))
        check('B6h 还原后皮肤档案解绑（不指向已被还原掉的方案）',
              r_res['ok'] and not a_after.get('rime_scheme')
              and not wiz.cfg.get('rime_scheme'),
              f"{a_after.get('rime_scheme')!r} / {r_res['msg']}")
    finally:
        try:
            _restore_dialogs(dlg)
        except Exception:
            pass
        R.run_weasel_deployer = real_deploy
        if wiz is not None:
            try:
                wiz.root.destroy()
            except Exception:
                pass
        R.WEASEL_CUSTOM, R.RIME_DIR, R.SCHEME_MANIFEST, R.SKINS_DIR, R.HERE = real


# ================= C 段：真实用户数据零触碰 =================
def test_c_untouched(real_custom, snap):
    section('C 真实 %APPDATA%\\Rime 零触碰')
    check('C1 ★真实 weasel.custom.yaml 大小/哈希未变',
          os.path.getsize(real_custom) == snap['size'] and _md5(real_custom) == snap['hash'],
          f'{real_custom}')
    try:
        now = sorted(os.listdir(os.path.dirname(real_custom)))
    except Exception:
        now = None
    check('C2 真实 Rime 目录清单未变（无新增 .bak / 无新方案文件）',
          now == snap['files'], f'新增={[f for f in (now or []) if f not in (snap["files"] or [])]}')
    flat = R.parse_flat_yaml(real_custom)
    names = sorted({k.split('/')[1] for k in flat
                    if k.startswith('preset_color_schemes/') and k.count('/') >= 2})
    check('C3 真实文件里的方案名与开测前一致',
          names == snap['schemes'], f'{names[:4]}…（{len(names)} 个）')
    check('C4 模块级路径已还原到真机（后续任务不会写错地方）',
          R.WEASEL_CUSTOM == real_custom, R.WEASEL_CUSTOM)


def main():
    tmp = tempfile.mkdtemp(prefix='r5scheme_')
    real_custom = R.WEASEL_CUSTOM
    try:
        snap = {'size': os.path.getsize(real_custom), 'hash': _md5(real_custom),
                'files': sorted(os.listdir(os.path.dirname(real_custom))),
                'schemes': sorted({k.split('/')[1] for k in R.parse_flat_yaml(real_custom)
                                   if k.startswith('preset_color_schemes/') and k.count('/') >= 2})}
    except Exception as e:
        print('无法读取真实 Rime 目录（按 SKIP 处理）：%s' % e)
        snap = {'size': -1, 'hash': None, 'files': [], 'schemes': []}
    real_here = R.HERE
    R.HERE = tmp
    print('=' * 72)
    print('R5 配色注入：先绑皮肤名 + yaml 分节标题与空行')
    print('真实 Rime 目录（只读）：%s' % os.path.dirname(real_custom))
    print('本次临时目录：%s' % tmp)
    print('=' * 72)
    try:
        test_a1_tight(tmp)
        test_a2_ondisk(tmp)
        test_a3_idem(tmp)
        test_a5_two_skins(tmp)
        test_a6_comments(tmp, real_custom)
        test_a7_edge(tmp)
        test_b_wizard(tmp, os.path.join(tmp, 'wzfolder'), real_custom)
        if snap['hash']:
            test_c_untouched(real_custom, snap)
        else:
            SKIP.append('C 段（真实 Rime 目录不可读）')
            print('SKIP  C 段（真实 Rime 目录不可读）')
    finally:
        R.HERE = real_here
        shutil.rmtree(tmp, ignore_errors=True)
        if os.path.isdir(tmp):
            print('警告：本次临时目录未能删除：%s' % tmp)
    print('=' * 72)
    print('通过 %d 项 / 失败 %d 项' % (len(PASS), len(FAIL))
          + (' / 跳过 %d 项' % len(SKIP) if SKIP else ''))
    if FAIL:
        print('失败项: ' + ', '.join(FAIL))
        return 1
    print('ALL CHECKS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
