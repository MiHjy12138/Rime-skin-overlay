# -*- coding: utf-8 -*-
"""
uninstall.py — 卸载开机自启（用户主动运行）
用法:
    python uninstall.py
"""
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

APP_NAME = 'RimeCharOverlay'
STARTUP_DIR = os.path.join(
    os.environ.get('APPDATA', ''),
    r'Microsoft\Windows\Start Menu\Programs\Startup',
)

def main():
    lnk = os.path.join(STARTUP_DIR, f'{APP_NAME}.lnk')
    if os.path.exists(lnk):
        os.remove(lnk)
        print(f'✅ 已移除自启: {lnk}')
    else:
        print('未找到自启项（可能未安装）')
    return 0

if __name__ == '__main__':
    sys.exit(main())
