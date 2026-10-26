# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""案件时限提醒 — no_agent cron 包装脚本
调用 deadline_scanner.py，过滤 ≤15 天，输出 [SILENT] 或报告"""
import subprocess
import sys
import os

# 2026-08-03: 本机目录 已删，scanner 在本目录
SCANNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deadline_scanner.py")

def run():
    if not os.path.exists(SCANNER):
        print("[SILENT]")
        return

    result = subprocess.run(
        [sys.executable, SCANNER],
        capture_output=True, text=True, timeout=30
    )
    output = result.stdout.strip()

    if not output or result.returncode != 0:
        print("[SILENT]")
        return

    # 过滤：只保留 ≤15 天的行（🔴 + 🟡），去掉 🟢(≤30) 和无事项
    lines = output.split('\n')
    filtered = [l for l in lines if '🔴' in l or '🟡' in l]

    if not filtered:
        print("[SILENT]")
        return

    print('\n'.join(['📅 案件时限提醒 (≤15天):'] + filtered))

if __name__ == '__main__':
    run()
