# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
Agent 更新检查脚本
检查 hermes-agent 是否有新版本。
"""
import os, subprocess, sys

AGENT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "hermes-agent")
if not os.path.isdir(AGENT_DIR):
    print("Agent directory not found")
    exit(1)

try:
    r = subprocess.run(
        ["git", "fetch", "origin"],
        cwd=AGENT_DIR, capture_output=True, text=True, timeout=30
    )
    r2 = subprocess.run(
        ["git", "rev-list", "--count", "HEAD..origin/main"],
        cwd=AGENT_DIR, capture_output=True, text=True, timeout=10
    )
    behind = int(r2.stdout.strip()) if r2.stdout.strip().isdigit() else -1
    if behind > 0:
        print(f"UPDATE: {behind} commits behind — run 'hermes update' or setup_other_machine.bat")
    elif behind == 0:
        print("OK: up to date")
    else:
        print("OK: unknown (fetch error?)")
except Exception as e:
    print(f"ERROR: {e}")
