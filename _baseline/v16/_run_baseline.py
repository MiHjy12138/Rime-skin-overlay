# -*- coding: utf-8 -*-
"""_baseline/v16/_run_baseline.py —— v1.6 基线回归采集器（只读被测树，不写入被测树）

用途：在「git HEAD 的纯净 v1.6 检出」里依次跑 6 个 B_test_*.py，
      把 stdout+stderr 合并存档到 _baseline/v16/<name>.txt，并记录退出码/耗时。

注意：本脚本由 verifier 编写，不属于产品代码；t5 可用它重跑同一套基线。
用法：python _run_baseline.py <pristine_dir> <out_dir>
"""
import os
import subprocess
import sys
import time

TESTS = [
    'B_test_follow_sim.py',
    'B_test_layer_sim.py',
    'B_test_misdetect_regress.py',
    'B_test_anim_sim.py',
    'B_test_fixes.py',
    'B_test_extras.py',
]
TIMEOUT = 420


def main():
    tree = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    os.makedirs(out, exist_ok=True)
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    rows = []
    for t in TESTS:
        path = os.path.join(tree, t)
        t0 = time.time()
        if not os.path.exists(path):
            rows.append((t, 'MISSING', -1, 0.0, 0))
            with open(os.path.join(out, t + '.txt'), 'w', encoding='utf-8') as f:
                f.write('[MISSING] %s not found under %s\n' % (t, tree))
            continue
        try:
            p = subprocess.run([sys.executable, t], cwd=tree, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=TIMEOUT)
            out_bytes = p.stdout
            code = p.returncode
            note = 'ok'
        except subprocess.TimeoutExpired as e:
            out_bytes = (e.stdout or b'')
            code = -9
            note = 'TIMEOUT>%ss' % TIMEOUT
        dt = time.time() - t0
        text = out_bytes.decode('utf-8', errors='replace')
        header = ('# ==== v1.6 baseline run ====\n# script : %s\n# cwd    : %s\n'
                  '# return : %s (%s)\n# seconds: %.1f\n'
                  '# note   : 输出为 stdout+stderr 合并，utf-8\n'
                  '# ===========================\n\n') % (t, tree, code, note, dt)
        with open(os.path.join(out, t + '.txt'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(header)
            f.write(text)
        rows.append((t, note, code, dt, len(text)))
        print('[baseline] %-30s rc=%-4s %6.1fs  %6d chars  %s' % (t, code, dt, len(text), note),
              flush=True)
    print('\n==== SUMMARY ====')
    for t, note, code, dt, n in rows:
        print('%-30s rc=%-4s %6.1fs %s' % (t, code, dt, note))


if __name__ == '__main__':
    main()
