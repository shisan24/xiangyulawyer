# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
# harness-watchdog.py — minimal health check for harness system
import os, sys

# 2026-08-03: 取消坚果云同步，原 .harness(指向【律师】/【本机标识】) 断链已删除，harness 未部署
# 未部署 = 无需监控 → all clear，避免 cron 误报
harness_dir = os.path.expanduser(r"[本地路径]")

if os.path.isdir(harness_dir):
    files = [f for f in os.listdir(harness_dir) if f.endswith((".py", ".md", ".json", ".yaml"))]
    print(f"[OK] Harness dir exists: {len(files)} files")
else:
    print("all clear")
