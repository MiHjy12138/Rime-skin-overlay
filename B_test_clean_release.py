# -*- coding: utf-8 -*-
"""B_test_clean_release.py —— 纯净包组装脚本（make_clean_release.py）契约回归

对齐全新交付口径（历史发布样式）：包内**恰好 4 项、根目录平铺**
（RimeSkinOverlay.exe / README.md / CHANGELOG.md / LICENSE），
不含 icon.png、不含 skins/ 空目录、无外层文件夹。

全程只操作临时目录：不启动 GUI、不读写用户配置、不碰桌面、不联网，秒级完成。

覆盖：
  A. 契约审计 audit()：4 项干净集通过；黑名单逐项命中；icon.png / skins/ 必须被判违规；
     缺必需文件；未知文件；exe 唯一性；每个黑名单条目独立成条
  B. 端到端 build→zip→verify：条目集合精确等于 4 项、默认包名、脏包必须被拒、
     目标已存在需 --force、非 PE / 体积异常拒绝、目标不存在退出码

运行: python B_test_clean_release.py
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import make_clean_release as M

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f'{"PASS" if cond else "FAIL"}  {name}{(" | " + detail) if detail else ""}')


def quiet(fn, *a, **kw):
    """吞掉脚本自身的 stdout/stderr 噪声，只取返回值。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        return fn(*a, **kw)


def clean_entries():
    """历史发布样式：4 个文件、无任何目录。"""
    return sorted((f, False) for f in ('RimeSkinOverlay.exe', 'README.md',
                                       'CHANGELOG.md', 'LICENSE'))


def hits(problems, needle):
    return any(needle in p for p in problems)


# --------------------------------------------------------------- A. audit

def test_audit_clean():
    print('--- [A1] 4 项干净集应通过 ---')
    probs = quiet(M.audit, clean_entries(), 'test')
    check('4 项干净集零问题', probs == [], f'problems={probs}')
    check('白名单恰好 4 项', M.ALLOWED_FILES == {'RimeSkinOverlay.exe', 'README.md',
                                                 'CHANGELOG.md', 'LICENSE'},
          f'ALLOWED_FILES={sorted(M.ALLOWED_FILES)}')


def test_audit_blacklist():
    print('--- [A2] 黑名单逐项命中 ---')
    cases = [
        ('config.json', '用户当前皮肤配置'),
        ('error.log', '错误日志'),
        ('error.log.1', '错误日志轮转'),
        ('perf.log', '性能日志'),
        ('overlay.log', '历史运行日志'),
        ('diag_misdetect.log', '诊断日志'),
        ('rime_char_overlay.py.bak-20260926', '备份残留'),
        ('preprocessed_1790391804686.png', '预处理中间图'),
        ('cfg_image_abc.png', '配置托管图片副本'),
        ('icon.png', '不含 icon.png'),
        ('icon.ico', '图标文件不随包分发'),
        ('skins/config.json', '不得包含 "skins/"'),
        ('skins/心灵信标/芙芙.png', '不得包含 "skins/"'),
        ('note.txt', '不在白名单内'),
        ('RimeSkinOverlay-v1.5.exe', '不在白名单内'),
        ('__pycache__/rime_char_overlay.cpython-312.pyc', '__pycache__'),
        ('build/x.toc', 'build'),
        ('dist_v2/RimeSkinOverlay.exe', 'dist_v2'),
    ]
    for bad, needle in cases:
        ents = clean_entries() + [(bad, False)]
        probs = quiet(M.audit, ents, 'test')
        check(f'黑名单命中：{bad}', hits(probs, needle), f'期望含「{needle}」got={probs}')

    # 目录条目本身
    for bad_dir in ('build', 'dist', 'skins'):
        ents = clean_entries() + [(bad_dir, True)]
        probs = quiet(M.audit, ents, 'test')
        check(f'目录条目不得通过：{bad_dir}/', hits(probs, bad_dir), f'problems={probs}')

    # 空 skins/ 目录（历史发布样式没有它）
    ents = clean_entries() + [('skins', True)]
    probs = quiet(M.audit, ents, 'test')
    check('空 skins/ 目录 → 报错（历史样式无此项）',
          hits(probs, '不得包含 "skins/"'), f'problems={probs}')


def test_audit_structure():
    print('--- [A3] 结构约束（必需项 / exe 唯一性 / 无外层文件夹） ---')
    for miss in ('CHANGELOG.md', 'README.md', 'LICENSE'):
        ents = [e for e in clean_entries() if e[0] != miss]
        probs = quiet(M.audit, ents, 'test')
        check(f'缺 {miss} → 报错', hits(probs, f'缺少必需文件 "{miss}"'), f'problems={probs}')

    ents = [e for e in clean_entries() if e[0] != 'RimeSkinOverlay.exe']
    probs = quiet(M.audit, ents, 'test')
    check('缺 exe → 报错', hits(probs, '缺少必需文件 "RimeSkinOverlay.exe"'), f'problems={probs}')

    ents = clean_entries() + [('RimeSkinOverlay.exe.bak-20260926', False)]
    probs = quiet(M.audit, ents, 'test')
    check('exe 备份残留 → 报错', hits(probs, '备份残留'), f'problems={probs}')

    ents = clean_entries() + [('RimeSkinOverlay-1.6.exe', False)]
    probs = quiet(M.audit, ents, 'test')
    check('旧版 exe（带版本号）→ 报错', hits(probs, '恰好是') and hits(probs, '不在白名单内'),
          f'problems={probs}')

    ents = clean_entries() + [('sub', True), ('sub/x.txt', False)]
    probs = quiet(M.audit, ents, 'test')
    check('外层文件夹（任意子目录）→ 报错', hits(probs, '不在白名单内'), f'problems={probs}')


def test_audit_independence():
    print('--- [A4] 每个黑名单条目必须独立报出（不能因同段去重被吞） ---')
    ents = clean_entries() + [('build/a.txt', False), ('build/b.txt', False),
                              ('__pycache__/c.pyc', False)]
    probs = quiet(M.audit, ents, 'test')
    for rel, _ in ents[-3:]:
        check(f'独立报出：{rel}', any(rel in p for p in probs), f'problems={probs}')


# --------------------------------------------------------------- B. 端到端

def make_fake_repo(tmp, exe_bytes=(2 << 20), version='v9.9'):
    repo = os.path.join(tmp, 'repo')
    os.makedirs(os.path.join(repo, 'dist'), exist_ok=True)
    with open(os.path.join(repo, 'rime_char_overlay.py'), 'w', encoding='utf-8') as f:
        f.write(f"# fake\nVERSION = '{version}'\n")
    for name in ('README.md', 'CHANGELOG.md', 'LICENSE'):
        with open(os.path.join(repo, name), 'w', encoding='utf-8') as f:
            f.write(f'{name} 内容\n')
    exe = os.path.join(repo, 'dist', M.EXE_NAME)
    with open(exe, 'wb') as f:
        f.write(b'MZ' + b'\0' * max(0, exe_bytes - 2))
    return repo, exe


def test_end_to_end(tmp):
    print('--- [B1] build → zip 条目集合 → verify ---')
    repo, exe = make_fake_repo(os.path.join(tmp, 'e2e'))
    out = os.path.join(tmp, 'e2e', 'out', 'pkg.zip')

    rc = quiet(M.main, ['build', '--repo', repo, '--out', out])
    check('build 退出码 0', rc == 0, f'rc={rc}')
    check('zip 已生成', os.path.isfile(out))

    ents = M.zip_entries(out)
    got = sorted(rel + ('/' if is_dir else '') for rel, is_dir in ents)
    want = sorted(['RimeSkinOverlay.exe', 'README.md', 'CHANGELOG.md', 'LICENSE'])
    check('zip 内恰好 4 项、根目录平铺', got == want, f'got={got}')
    check('zip 内无任何目录条目', all(not is_dir for _rel, is_dir in ents), f'ents={ents}')

    rc = quiet(M.main, ['verify', out])
    check('verify 纯净 zip → 0', rc == 0, f'rc={rc}')

    rc = quiet(M.main, ['verify', repo])
    check('verify 源码目录（脏）→ 2', rc == 2, f'rc={rc}')

    print('--- [B2] 默认包名（对齐历史发布 RimeSkinOverlay-v<版本>.zip） ---')
    check('detect_version 抓到 v9.9', M.detect_version(repo) == 'v9.9')
    rc = quiet(M.main, ['build', '--repo', repo])
    default_zip = os.path.join(repo, 'dist', f'RimeSkinOverlay-{M.detect_version(repo)}.zip')
    check('默认输出名 = RimeSkinOverlay-v9.9.zip', rc == 0 and os.path.isfile(default_zip),
          f'rc={rc} path={default_zip}')

    print('--- [B3] 覆盖保护 / 缺产物 / 非 PE ---')
    rc = quiet(M.main, ['build', '--repo', repo, '--out', out])
    check('目标已存在且无 --force → 3', rc == 3, f'rc={rc}')
    rc = quiet(M.main, ['build', '--repo', repo, '--out', out, '--force'])
    check('加 --force → 0', rc == 0, f'rc={rc}')

    repo_nb = os.path.join(tmp, 'nobuild')
    os.makedirs(repo_nb, exist_ok=True)
    rc = quiet(M.main, ['build', '--repo', repo_nb, '--out', os.path.join(tmp, 'nb.zip')])
    check('缺构建产物 → 3', rc == 3, f'rc={rc}')

    repo_small, _ = make_fake_repo(os.path.join(tmp, 'small'), exe_bytes=2048)
    rc = quiet(M.main, ['build', '--repo', repo_small, '--out', os.path.join(tmp, 'small.zip')])
    check('体积异常 exe → 2（契约违反）', rc == 2, f'rc={rc}')

    repo_html, exe_html = make_fake_repo(os.path.join(tmp, 'html'), exe_bytes=(2 << 20))
    with open(exe_html, 'wb') as f:
        f.write(b'<!DOCTYPE html>' + b'\0' * (2 << 20))
    rc = quiet(M.main, ['build', '--repo', repo_html, '--out', os.path.join(tmp, 'html.zip')])
    check('非 PE exe → 2', rc == 2, f'rc={rc}')

    print('--- [B4] 脏包必须被 verify 拒绝 ---')
    dirty = os.path.join(tmp, 'e2e', 'out', 'dirty.zip')
    shutil.copy2(out, dirty)
    with zipfile.ZipFile(dirty, 'a') as zf:
        zf.writestr('config.json', '{"image": "C:/Users/x/char.png"}')
        zf.writestr('error.log', 'boom')
        zf.writestr('RimeSkinOverlay-v1.5.exe', b'MZ' + b'\0' * (2 << 20))
        zf.writestr('preprocessed_1.png', b'x')
        zf.writestr('icon.png', b'\x89PNG\r\n\x1a\n')
        zf.writestr('skins/芙芙/图.png', b'x')
        zf.writestr('extra_folder/README.md', b'x')
    rc = quiet(M.main, ['verify', dirty])
    check('脏包 verify → 2', rc == 2, f'rc={rc}')
    probs = quiet(M.audit, M.zip_entries(dirty), 'test')
    for needle in ('config.json', 'error.log', 'preprocessed_1.png', 'icon.png',
                   '不得包含 "skins/"', '不在白名单内'):
        check(f'脏包被点名：{needle}', hits(probs, needle), f'problems={probs[:6]}')

    rc = quiet(M.main, ['verify', os.path.join(tmp, '不存在.zip')])
    check('目标不存在 → 3', rc == 3, f'rc={rc}')

    rc = quiet(M.main, ['verify', os.path.join(tmp, 'e2e', 'repo', 'README.md')])
    check('既非 zip 也非目录 → 3', rc == 3, f'rc={rc}')


def main():
    tmp = tempfile.mkdtemp(prefix='B_test_clean_release_')
    print(f'临时工作目录: {tmp}')
    try:
        test_audit_clean()
        test_audit_blacklist()
        test_audit_structure()
        test_audit_independence()
        test_end_to_end(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f'\n=== 通过 {len(PASS)} / 失败 {len(FAIL)} ===')
    if FAIL:
        for name in FAIL:
            print(f'  FAIL: {name}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
