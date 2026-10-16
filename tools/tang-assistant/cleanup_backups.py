# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
技能备份清理 — 跨机兼容
保留最近3天各1份，删除多余的旧备份。
由 cron 以 no_agent=true 模式调用。
"""
import os, glob
from datetime import datetime

def find_sync_dir():
    candidates = [
        r"[本地路径]",
        os.path.join(os.path.expanduser("~"), "【本机标识】"),
    ]
    for d in candidates:
        if os.path.isdir(d):
            return d
    return None

SYNC_DIR = find_sync_dir()
if not SYNC_DIR:
    print("ERROR: Cannot find 【本机标识】")
    exit(1)

backups = sorted(glob.glob(os.path.join(SYNC_DIR, "skills-backup-*.tar.gz")), reverse=True)

if len(backups) <= 3:
    print(f"OK: {len(backups)} backups, no cleanup needed")
    exit(0)

keep = []
seen_dates = set()
for bp in backups:
    mtime = datetime.fromtimestamp(os.path.getmtime(bp))
    date_key = mtime.strftime("%Y-%m-%d")
    if date_key not in seen_dates:
        keep.append(bp)
        seen_dates.add(date_key)
    if len(keep) >= 3:
        break

removed = [b for b in backups if b not in keep]
for bp in removed:
    os.remove(bp)
    print(f"  deleted: {os.path.basename(bp)}")

print(f"OK: kept {len(keep)} from {len(backups)}")
