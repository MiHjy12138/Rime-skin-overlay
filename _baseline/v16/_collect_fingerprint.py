# -*- coding: utf-8 -*-
"""_baseline/v16/_collect_fingerprint.py —— 用户数据 / 发布物指纹采集（只读）

由 verifier 编写，不属于产品代码。输出：_baseline/v16/userdata_fingerprint.json
用法：python _collect_fingerprint.py <repo_root> <out_dir>
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

EXPECTED_SCHEMES = [
    'furina_aqua', 'furina_night', 'mint_fresh', 'mint_glass',
    'yuzu_orange', 'yuzu_orange_dark', 'spring_bloom', 'spring_bloom_dark',
    'miku_aqua', 'miku_night',
]
EXPECTED_SKINS = ['心灵信标', '芙芙']


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def file_fp(p):
    if not os.path.exists(p):
        return {'path': p, 'exists': False}
    st = os.stat(p)
    return {
        'path': p,
        'exists': True,
        'size': st.st_size,
        'mtime': datetime.datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
        'sha256': sha256_file(p),
    }


def git(repo, *args):
    r = subprocess.run(['git'] + list(args), cwd=repo, capture_output=True)
    return r.stdout.decode('utf-8', errors='replace').strip(), r.returncode


def collect_yaml_facts(path):
    facts = {'exists': os.path.exists(path)}
    if not facts['exists']:
        return facts
    raw = open(path, encoding='utf-8', errors='replace').read()
    facts.update(file_fp(path))
    facts['scheme_names'] = sorted(set(re.findall(r'preset_color_schemes/([^/"\'\s]+)/', raw)))
    facts['style_keys'] = {}
    for m in re.finditer(r'^(\s*)"?(style/[^"\s:]+)"?\s*:\s*(.*?)\s*$', raw, re.M):
        facts['style_keys'][m.group(2)] = m.group(3)
    facts['color_scheme_keys'] = {}
    for m in re.finditer(r'^(\s*)"?([a-zA-Z_]*color_scheme[a-zA-Z_]*)"?\s*:\s*(.*?)\s*$', raw, re.M):
        facts['color_scheme_keys'][m.group(2)] = m.group(3)
    facts['patch_top_level_keys'] = sorted(set(
        m.group(2) for m in re.finditer(r'^(\s*)"?([a-zA-Z_][\w/.]*)"?\s*:', raw, re.M)))
    facts['scheme_field_count'] = len(re.findall(r'^\s*"?preset_color_schemes/[^"\s:]+/[^"\s:]+"?\s*:', raw, re.M))
    facts['unknown_schemes'] = [n for n in facts['scheme_names'] if n not in EXPECTED_SCHEMES]
    facts['missing_expected_schemes'] = [n for n in EXPECTED_SCHEMES if n not in facts['scheme_names']]
    return facts


def tree_listing(root):
    out = []
    if not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            fp = file_fp(p)
            fp['rel'] = os.path.relpath(p, root).replace('\\', '/')
            out.append(fp)
    return out


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    os.makedirs(out, exist_ok=True)
    rime = os.path.join(os.environ.get('APPDATA', ''), 'Rime')
    now = datetime.datetime.now()

    head, _ = git(repo, 'rev-parse', 'HEAD')
    branch, _ = git(repo, 'rev-parse', '--abbrev-ref', 'HEAD')
    status, _ = git(repo, 'status', '--porcelain')
    head_subject, _ = git(repo, 'log', '-1', '--format=%h %ad %s', '--date=iso')

    # HEAD blob（LF 原样）指纹，用于证明「基线源码 = v1.6 提交」
    blob = subprocess.run(['git', 'cat-file', 'blob', 'HEAD:rime_char_overlay.py'],
                          cwd=repo, capture_output=True).stdout

    d = {
        'collected_at': now.strftime('%Y-%m-%d %H:%M:%S'),
        'repo_root': repo,
        'git': {
            'head': head,
            'branch': branch,
            'head_subject': head_subject,
            'status_porcelain': status.splitlines(),
            'head_blob_rime_char_overlay_sha256': hashlib.sha256(blob).hexdigest().upper(),
            'head_blob_rime_char_overlay_size_lf': len(blob),
        },
        'fixture_char_png': file_fp(os.path.join(repo, 'char.png')),
        'live_source_worktree': file_fp(os.path.join(repo, 'rime_char_overlay.py')),
        'rime_user_dir': rime,
        'rime_files': {
            n: file_fp(os.path.join(rime, n)) for n in [
                'weasel.custom.yaml', 'weasel.yaml', 'default.custom.yaml',
                'rime_ice.custom.yaml', 'user.yaml', 'default.yaml',
                'weasel.custom.yaml.bak',
            ]
        },
        'rime_backups': sorted(
            f for f in os.listdir(rime) if f.startswith('weasel.custom.yaml.bak')) if os.path.isdir(rime) else [],
        'weasel_custom': collect_yaml_facts(os.path.join(rime, 'weasel.custom.yaml')),
        'expected_schemes': EXPECTED_SCHEMES,
        'project_skins_dir': {'path': os.path.join(repo, 'skins'),
                              'exists': os.path.isdir(os.path.join(repo, 'skins'))},
        'project_skins_tree': tree_listing(os.path.join(repo, 'skins')),
        'release_config_json': file_fp(os.path.join(repo, 'release', 'config.json')),
        'release_exe': file_fp(os.path.join(repo, 'release', 'RimeSkinOverlay.exe')),
        'release_skins_dir': os.path.join(repo, 'release', 'skins'),
        'release_skins_tree': tree_listing(os.path.join(repo, 'release', 'skins')),
        'expected_release_skins': EXPECTED_SKINS,
    }
    try:
        d['release_config_json_text'] = open(os.path.join(repo, 'release', 'config.json'),
                                             encoding='utf-8', errors='replace').read()
    except OSError:
        d['release_config_json_text'] = None

    # ---------- 污染判定 ----------
    findings = []
    wc = d['weasel_custom']
    if wc.get('exists'):
        if wc['unknown_schemes']:
            findings.append({'severity': 'blocker',
                             'problem': 'weasel.custom.yaml 出现未知配色方案名: %s' % wc['unknown_schemes'],
                             'requiredFix': '判定是否为测试误写真实用户数据；如有则回滚 .bak 并禁止测试直写真机 Rime 目录'})
        if wc['missing_expected_schemes']:
            findings.append({'severity': 'high',
                             'problem': '预期配色方案缺失: %s' % wc['missing_expected_schemes'],
                             'requiredFix': '确认是否被注入逻辑覆盖删除；必要时从 .bak 恢复'})
        mt = datetime.datetime.strptime(wc['mtime'], '%Y-%m-%d %H:%M:%S')
        if mt.date() == now.date():
            findings.append({'severity': 'high',
                             'problem': 'weasel.custom.yaml mtime 就是今天（%s），疑似本轮工作误写真机配置' % wc['mtime'],
                             'requiredFix': '立刻核对是否有进程写入了真实 Rime 目录，必要时回滚备份'})
    skins_now = sorted({e['rel'].split('/')[0] for e in d['release_skins_tree']})
    d['release_skins_top_names'] = skins_now
    extra = [s for s in skins_now if s not in EXPECTED_SKINS]
    if extra:
        findings.append({'severity': 'high',
                         'problem': 'release/skins 出现非预期条目: %s' % extra,
                         'requiredFix': '确认是否测试残留皮肤目录，清理或说明'})
    d['pollution_findings'] = findings

    jp = os.path.join(out, 'userdata_fingerprint.json')
    with open(jp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(d, f, ensure_ascii=False, indent=2, sort_keys=False)
    print('written:', jp)
    print('scheme_names:', wc.get('scheme_names'))
    print('unknown:', wc.get('unknown_schemes'), 'missing:', wc.get('missing_expected_schemes'))
    print('style_keys:', json.dumps(wc.get('style_keys', {}), ensure_ascii=False))
    print('color_scheme_keys:', wc.get('color_scheme_keys'))
    print('release_skins_top_names:', skins_now)
    print('pollution_findings:', json.dumps(findings, ensure_ascii=False))
    print('live source size:', d['live_source_worktree'].get('size'),
          'sha256:', d['live_source_worktree'].get('sha256'),
          'mtime:', d['live_source_worktree'].get('mtime'))
    print('HEAD blob size(LF):', d['git']['head_blob_rime_char_overlay_size_lf'],
          'sha256:', d['git']['head_blob_rime_char_overlay_sha256'])


if __name__ == '__main__':
    main()
