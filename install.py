# -*- coding: utf-8 -*-
"""
install.py — 安装开机自启（用户主动运行）
创建快捷方式到启动文件夹。不会偷偷安装，运行本脚本即表示你同意。
用法:
    python install.py [--remove]
"""
import sys
import os
import shutil
import argparse
import subprocess

sys.stdout.reconfigure(encoding='utf-8')

APP_NAME = 'RimeCharOverlay'
STARTUP_DIR = os.path.join(
    os.environ.get('APPDATA', ''),
    r'Microsoft\Windows\Start Menu\Programs\Startup',
)
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'rime_char_overlay.py')
CHAR = os.path.join(HERE, 'char.png')

def find_pythonw():
    """找一个能用的 pythonw.exe（无窗口运行）"""
    # 1. 当前解释器目录
    py = sys.executable
    base = os.path.dirname(py)
    for name in ('pythonw.exe',):
        cand = os.path.join(base, name)
        if os.path.exists(cand):
            return cand
    # 2. 退回 python.exe（会有控制台窗口）
    return py

def install():
    if not os.path.exists(SCRIPT):
        print(f'❌ 找不到主程序: {SCRIPT}')
        return 1
    if not os.path.exists(CHAR):
        print('⚠️ 未找到 char.png')
        print('   请先准备一张透明底 PNG 角色图，命名为 char.png 放入本项目目录')
        print('   （不安装自启也可直接运行: python rime_char_overlay.py 图片路径 right）')
        return 1

    lnk = os.path.join(STARTUP_DIR, f'{APP_NAME}.lnk')
    if os.path.exists(lnk):
        print(f'已存在自启项: {lnk}')
        print('如需重新安装请先运行: python uninstall.py')
        return 0

    pythonw = find_pythonw()
    # 生成一个启动器 .cmd（纯 ASCII），VBS 只负责创建快捷方式指向它
    launcher = os.path.join(HERE, '_run_overlay.cmd')
    with open(launcher, 'w', encoding='ascii') as f:
        f.write(f'@echo off\r\n')
        f.write(f'start "" "{pythonw}" -X utf8 "{SCRIPT}" "{CHAR}" right\r\n')

    vbs = os.path.join(HERE, '_mklnk.vbs')
    vbs_content = (
        'Set ws = CreateObject("WScript.Shell")\n'
        f'Set sc = ws.CreateShortcut("{lnk}")\n'
        f'sc.TargetPath = "{launcher}"\n'
        'sc.WindowStyle = 7\n'
        'sc.Description = "Rime Char Overlay"\n'
        'sc.Save()\n'
    )
    with open(vbs, 'w', encoding='ascii') as f:
        f.write(vbs_content)
    try:
        result = subprocess.run(['cscript', '//nologo', vbs], check=True,
                                capture_output=True, timeout=15)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b'').decode('gbk', errors='replace')
        print(f'❌ cscript 失败: {err}')
        return 1
    finally:
        os.remove(vbs)

    print(f'✅ 已安装自启: {lnk}')
    print('   下次登录自动启动，打字时跟随候选框显示角色')
    return 0

def uninstall():
    lnk = os.path.join(STARTUP_DIR, f'{APP_NAME}.lnk')
    if os.path.exists(lnk):
        os.remove(lnk)
        print(f'✅ 已移除自启: {lnk}')
    else:
        print('未找到自启项（可能未安装）')
    return 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Rime 角色窗 - 自启管理')
    parser.add_argument('--remove', action='store_true', help='卸载自启')
    args = parser.parse_args()
    sys.exit(uninstall() if args.remove else install())
