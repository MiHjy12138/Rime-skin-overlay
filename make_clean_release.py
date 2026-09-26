#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_clean_release.py —— Rime 皮肤外挂「纯净发布包」组装与核验（2.0 交付用）

只用标准库，裸 Python 3 即可运行。

契约（白名单 / 黑名单）
    白名单（包内只允许这些，与历史发布 RimeSkinOverlay-v1.6.zip 的结构逐项一致）：
        RimeSkinOverlay.exe   README.md   CHANGELOG.md   LICENSE
        —— 解压后根目录平铺、无外层文件夹。
    特别说明（历史发布样式就是如此）：
        · 不含 icon.png —— 程序图标已由 _MEIPASS 内置。
        · 不含 skins/ 空目录 —— 由程序首次存皮肤时自建。
    黑名单（出现即失败）：
        config.json（用户当前皮肤配置）、error.log*、perf.log*、overlay.log、
        diag_*.log、*.bak-*、*.bak、*.tmp、preprocessed_*.png、cfg_image_*.png、
        icon.png / icon.ico、skins/（任何内容）、__pycache__/、build/、dist/、.git/、
        旧版 exe（包内 .exe 必须恰好是 RimeSkinOverlay.exe 一个）

用法
    # 组装：默认取 <repo>/dist/RimeSkinOverlay.exe，默认输出 <repo>/dist/RimeSkinOverlay-<版本>.zip
    python make_clean_release.py
    python make_clean_release.py --exe dist_v2/RimeSkinOverlay.exe ^
        --out "E:\\桌面\\RimeSkinOverlay-v2.0.zip"

    # 只核验（交付后复检桌面上的 zip，或核验已解压目录）
    python make_clean_release.py verify "E:\\桌面\\RimeSkinOverlay-v2.0.zip"
    python make_clean_release.py verify "D:\\tmp\\解压出来的目录"

退出码
    0 = 通过
    2 = 契约违反（黑名单命中 / 白名单缺失 / 混入未知文件 / exe 数量不对）
    3 = 环境或输入问题（文件不存在、目标已存在且未加 --force）
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile

# ---------------------------------------------------------------- 契约常量

EXE_NAME = 'RimeSkinOverlay.exe'
REQUIRED_FILES = (EXE_NAME, 'README.md', 'CHANGELOG.md', 'LICENSE')
ALLOWED_FILES = set(REQUIRED_FILES)
# 历史发布样式：包内不放任何子目录（skins/ 由程序首次存皮肤时自建）
ALLOWED_DIRS = set()

# 目录段黑名单（路径里任意一层命中即失败）
BLACKLIST_DIR_SEGMENTS = {
    '__pycache__': 'Python 字节码缓存',
    '.git': '版本库残留',
    '.pytest_cache': '测试缓存',
    'build': 'PyInstaller 构建目录',
    'dist': 'PyInstaller 产物目录',
    'build_v2': '备用构建目录',
    'dist_v2': '备用产物目录',
}

# 文件名黑名单：(fnmatch 模式, 说明)，匹配小写化后的文件名
BLACKLIST_FILE_PATTERNS = (
    ('config.json', '用户当前皮肤配置（禁止随包分发）'),
    ('config.json.*', '用户配置残留'),
    ('error.log', '错误日志'),
    ('error.log.*', '错误日志轮转'),
    ('perf.log', '性能日志'),
    ('overlay.log', '历史运行日志'),
    ('diag_*.log', '诊断日志'),
    ('*.bak', '备份残留'),
    ('*.bak-*', '备份残留'),
    ('*.tmp', '临时文件'),
    ('*.log', '任何日志文件'),
    ('preprocessed_*.png', '预处理中间图（用户数据派生）'),
    ('cfg_image_*.png', '配置托管图片副本（用户数据）'),
    ('icon.png', '历史发布样式不含 icon.png（程序图标已由 _MEIPASS 内置）'),
    ('icon.ico', '图标文件不随包分发（已嵌在 exe 里）'),
    ('*.py', '源码不得随包分发'),
    ('*.spec', '构建脚本不得随包分发'),
    ('*.pyd', '编译扩展不得随包分发'),
    ('*.dll', '依赖库不得随包分发（onefile 已内置）'),
    ('*.lnk', '快捷方式不得随包分发'),
)
MIN_EXE_BYTES = 1 << 20  # 1 MiB：小于此值必不是完整 onefile 产物


# ---------------------------------------------------------------- 工具函数

def sha256_of_file(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def human(n: int) -> str:
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if n < 1024 or unit == 'GiB':
            return f'{n:.2f} {unit}' if unit != 'B' else f'{n} B'
        n /= 1024.0
    return f'{n} B'


def detect_version(repo) -> str:
    """从 rime_char_overlay.py 抓 VERSION = 'vX.Y'，抓不到返回 unknown。"""
    src = os.path.join(repo, 'rime_char_overlay.py')
    try:
        with open(src, encoding='utf-8', errors='replace') as f:
            head = f.read(400_000)
    except OSError:
        return 'unknown'
    m = re.search(r"^\s*VERSION\s*=\s*['\"]([^'\"]+)['\"]", head, re.M)
    return m.group(1) if m else 'unknown'


def collect_entries(root: str):
    """遍历目录，返回 (rel_posix, is_dir) 列表；rel 不以 '/' 结尾。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace('\\', '/')
        if rel_dir == '.':
            rel_dir = ''
        for d in dirnames:
            out.append(((rel_dir + '/' + d).lstrip('/'), True))
        for f in filenames:
            out.append(((rel_dir + '/' + f).lstrip('/'), False))
    return sorted(out)


def zip_entries(zip_path: str):
    """读 zip 内的条目，返回 (rel_posix, is_dir)。"""
    out = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            is_dir = name.endswith('/')
            out.append((name.rstrip('/') if is_dir else name, is_dir))
    return sorted(out)


# ---------------------------------------------------------------- 契约审计

def audit(entries, stage: str):
    """按契约审计条目集，返回问题字符串列表（空 = 通过）。

    entries : [(rel_posix, is_dir)]
    stage   : 出现在报告里的阶段名
    """
    problems = []
    files = [rel for rel, is_dir in entries if not is_dir]
    dirs = {rel for rel, is_dir in entries if is_dir}
    lower = {rel: rel.lower() for rel, _ in entries}

    # 1) 黑名单（先查，报错信息更精确）
    for rel, is_dir in entries:
        segs = rel.split('/')
        if is_dir:
            hit = BLACKLIST_DIR_SEGMENTS.get(segs[-1].lower())
            if hit:
                problems.append(f'[黑名单] 目录 "{rel}/" 命中：{hit}')
        for seg in (segs if is_dir else segs[:-1]):
            hit = BLACKLIST_DIR_SEGMENTS.get(seg.lower())
            if hit and f'目录 "{seg}/"' not in ' '.join(problems):
                problems.append(f'[黑名单] 路径 "{rel}" 含目录段 "{seg}"：{hit}')
        if not is_dir:
            fname = segs[-1].lower()
            for pat, why in BLACKLIST_FILE_PATTERNS:
                if fnmatch.fnmatchcase(fname, pat):
                    problems.append(f'[黑名单] 文件 "{rel}" 命中 {pat}：{why}')
                    break

    # 2) 历史发布样式：包内不得出现 skins/（由程序首次存皮肤时自建）
    for rel, _is_dir in entries:
        if rel == 'skins' or rel.startswith('skins/'):
            problems.append(f'[黑名单] 不得包含 "skins/"（历史发布样式无此项，'
                            f'程序首次存皮肤时自建），发现 "{rel}"')

    # 3) 必需文件
    for f in REQUIRED_FILES:
        if f not in files:
            problems.append(f'[白名单] 缺少必需文件 "{f}"')

    # 4) 严格白名单：任何未列出的条目
    for rel, is_dir in entries:
        if is_dir:
            if rel not in ALLOWED_DIRS:
                problems.append(f'[白名单] 目录 "{rel}/" 不在白名单内')
        else:
            if rel not in ALLOWED_FILES:
                problems.append(f'[白名单] 文件 "{rel}" 不在白名单内（未知项）')

    # 5) exe 唯一性：包内 exe 必须恰好是 RimeSkinOverlay.exe 一个
    exes = [f for f in files if lower[f].endswith('.exe')]
    if len(exes) != 1 or exes[0] != EXE_NAME:
        problems.append(f'[白名单] 包内 .exe 必须恰好是 "{EXE_NAME}" 一个，实际：{exes or "无"}')

    if problems:
        print(f'-- 契约自检（{stage}）：未通过，{len(problems)} 项问题', file=sys.stderr)
        for p in problems:
            print(f'   ! {p}', file=sys.stderr)
    else:
        print(f'-- 契约自检（{stage}）：通过（{len(files)} 个文件 / {len(dirs)} 个目录）')
    return problems


def check_exe_bytes(source) -> list:
    """校验 exe 是真实 PE 文件且体积合理。source 为路径或 (zip路径, 条目名)。"""
    if isinstance(source, tuple):
        with zipfile.ZipFile(source[0]) as zf:
            with zf.open(source[1]) as fh:
                head = fh.read(2)
            size = zf.getinfo(source[1]).file_size
    else:
        size = os.path.getsize(source)
        with open(source, 'rb') as fh:
            head = fh.read(2)
    problems = []
    if head != b'MZ':
        problems.append(f'[产物] {EXE_NAME} 不是 PE 可执行文件（头部 {head!r}）')
    if size < MIN_EXE_BYTES:
        problems.append(f'[产物] {EXE_NAME} 体积异常偏小：{human(size)}')
    return problems


# ---------------------------------------------------------------- build

def cmd_build(args) -> int:
    repo = os.path.abspath(args.repo or os.path.dirname(os.path.abspath(__file__)))
    exe = os.path.abspath(args.exe or os.path.join(repo, 'dist', EXE_NAME))
    version = args.version or detect_version(repo)
    pkg_name = f'RimeSkinOverlay-{version}.zip'
    out = os.path.abspath(args.out or os.path.join(repo, 'dist', pkg_name))

    print('== Rime 皮肤外挂 · 纯净发布包组装 ==')
    print(f'   源码根    : {repo}')
    print(f'   构建产物  : {exe}')
    print(f'   输出 zip  : {out}')
    print(f'   版本      : {version}（包内 {len(REQUIRED_FILES)} 项，根目录平铺）')

    if not os.path.isfile(exe):
        print(f'!! 找不到构建产物 {exe}\n   先跑 PyInstaller（python -m PyInstaller --noconfirm RimeSkinOverlay.spec）'
              f'，或用 --exe 指定路径。', file=sys.stderr)
        return 3
    for f in REQUIRED_FILES:
        if f == EXE_NAME:
            continue
        if not os.path.isfile(os.path.join(repo, f)):
            print(f'!! 源码根缺少必需文件 {f}（在 {repo} 下找不到）', file=sys.stderr)
            return 3
    if os.path.exists(out) and not args.force:
        print(f'!! 输出已存在：{out}\n   加 --force 才允许覆盖。', file=sys.stderr)
        return 3

    # 陈旧构建提示（不阻断）
    src_py = os.path.join(repo, 'rime_char_overlay.py')
    if os.path.isfile(src_py) and os.path.getmtime(src_py) > os.path.getmtime(exe) + 1:
        print(f'   [警告] {EXE_NAME} 比 rime_char_overlay.py 更旧，可能是陈旧构建'
              f'（exe {time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(exe)))}'
              f' < py {time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(src_py)))}）')

    staging = tempfile.mkdtemp(prefix='rime_clean_release_')
    try:
        # 只按白名单复制（不做通配拷贝，从根上杜绝混入）；exe 用 --exe 指定的构建产物
        for name in REQUIRED_FILES:
            src = exe if name == EXE_NAME else os.path.join(repo, name)
            shutil.copy2(src, os.path.join(staging, name))

        entries = collect_entries(staging)
        print(f'\n[1/4] 暂存目录组装完成：{staging}')
        problems = audit(entries, '打包前')
        problems += check_exe_bytes(os.path.join(staging, EXE_NAME))
        if problems:
            for p in problems:
                print(f'   ! {p}', file=sys.stderr)
            print('!! 契约自检未通过，已中止，未生成 zip。', file=sys.stderr)
            return 2

        # 打 zip
        print(f'[2/4] 压缩中（DEFLATED）…')
        t0 = time.time()
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
            for rel, is_dir in entries:
                src = os.path.join(staging, rel.replace('/', os.sep))
                zf.write(src, rel + '/' if is_dir else rel)
        dt = time.time() - t0
        print(f'      写入 {human(os.path.getsize(out))}，耗时 {dt:.2f}s')

        # 打包后复检 zip 内部
        zentries = zip_entries(out)
        zproblems = audit(zentries, '打包后')
        zproblems += check_exe_bytes((out, EXE_NAME))
        if zproblems:
            print('!! zip 内部复检未通过，产物不可用，请检查上面的问题项。', file=sys.stderr)
            return 2

        print(f'[3/4] zip 内清单（{len(zentries)} 项）：')
        with zipfile.ZipFile(out) as zf:
            for rel, is_dir in zentries:
                if is_dir:
                    print(f'       {rel}/')
                else:
                    info = zf.getinfo(rel)
                    print(f'       {rel:<22} {human(info.file_size):>10}  '
                          f'-> {human(info.compress_size):>10}')
            exe_sha = hashlib.sha256(zf.read(EXE_NAME)).hexdigest()
        print(f'\n[4/4] {EXE_NAME} sha256 = {exe_sha}')
        print(f'      产物：{out}')
        print('== 完成：契约自检通过 ==')
        return 0
    finally:
        # 暂存目录是本次新建的临时目录，仅清理由本次运行创建的内容
        shutil.rmtree(staging, ignore_errors=True)


# ---------------------------------------------------------------- verify

def cmd_verify(args) -> int:
    target = os.path.abspath(args.target)
    print('== 纯净包核验 ==')
    print(f'   目标：{target}')
    if not os.path.exists(target):
        print('!! 目标不存在。', file=sys.stderr)
        return 3

    is_zip = os.path.isfile(target) and target.lower().endswith('.zip')
    if is_zip:
        try:
            entries = zip_entries(target)
        except zipfile.BadZipFile:
            print('!! 不是有效 zip 文件。', file=sys.stderr)
            return 3
        kind = 'zip'
    elif os.path.isdir(target):
        entries = collect_entries(target)
        kind = '目录'
    else:
        print('!! 目标既不是 zip 也不是目录。', file=sys.stderr)
        return 3

    problems = audit(entries, f'{kind}核验')
    files = [rel for rel, is_dir in entries if not is_dir]
    if EXE_NAME in files:
        problems += check_exe_bytes((target, EXE_NAME) if is_zip
                                    else os.path.join(target, EXE_NAME))
    if problems:
        for p in problems:
            print(f'   ! {p}', file=sys.stderr)
        print('== 核验未通过：此包不算纯净包 ==', file=sys.stderr)
        return 2

    print(f'   条目（{len(entries)} 项）：')
    for rel, is_dir in entries:
        print(f'       {rel}/' if is_dir else f'       {rel}')
    if is_zip:
        with zipfile.ZipFile(target) as zf:
            print(f'   {EXE_NAME} sha256 = {hashlib.sha256(zf.read(EXE_NAME)).hexdigest()}')
    print('== 核验通过：白名单齐备、无黑名单命中 ==')
    return 0


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog='make_clean_release.py',
        description='Rime 皮肤外挂纯净发布包组装 / 核验（白名单+黑名单双检）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('用法', 1)[-1] if __doc__ else None)
    sub = p.add_subparsers(dest='cmd')

    b = sub.add_parser('build', help='组装纯净包 zip（默认子命令）')
    b.add_argument('--exe', help=f'构建产物 exe 路径（默认 <repo>/dist/{EXE_NAME}）')
    b.add_argument('--repo', help='源码根目录（默认脚本所在目录）')
    b.add_argument('--out', help='输出 zip 路径（默认 <repo>/dist/RimeSkinOverlay-<版本>.zip）')
    b.add_argument('--version', help="包名里的版本号（默认从 rime_char_overlay.py 的 VERSION 推断）")
    b.add_argument('--force', action='store_true', help='允许覆盖已存在的输出 zip')

    v = sub.add_parser('verify', help='核验已有的 zip 或解压目录是否纯净')
    v.add_argument('target', help='zip 路径或解压后的目录')

    # 兼容「无子命令 + 直接 --exe/--out」的调用方式
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in ('build', 'verify', '-h', '--help'):
        argv = ['build'] + argv
    args = p.parse_args(argv)

    if args.cmd == 'verify':
        return cmd_verify(args)
    return cmd_build(args)


if __name__ == '__main__':
    sys.exit(main())
