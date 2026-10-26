# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
state.db 备份脚本 — 跨机兼容
复制 state.db 到 backups/，保留最近 4 份。
由 cron 以 no_agent=true 模式调用。
"""
import os, shutil, glob
from datetime import datetime

# 第三方同步盘同步目录解决 expanduser 陷阱：
# 本机 本机目录 但同步目录在 承办人 下
KEEP = 4

def find_sync_dir():
    candidates = [
        r"[本地路径]",
        os.path.join(os.path.expanduser("~"), "本机目录"),
    ]
    for d in candidates:
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "state.db")):
            return d
    return None

SYNC_DIR = find_sync_dir()
if not SYNC_DIR:
    print("ERROR: Cannot find 本机目录 directory with state.db")
    exit(1)

SRC = os.path.join(SYNC_DIR, "state.db")
DST_DIR = os.path.join(SYNC_DIR, "backups")
os.makedirs(DST_DIR, exist_ok=True)

ts = datetime.now().strftime("%Y%m%d-%H%M%S")
dst = os.path.join(DST_DIR, f"state-{ts}.db")
shutil.copy2(SRC, dst)

files = sorted(glob.glob(os.path.join(DST_DIR, "state-*.db")), reverse=True)
deleted = []
for f in files[KEEP:]:
    os.remove(f)
    deleted.append(os.path.basename(f))

size_kb = os.path.getsize(dst) // 1024
print(f"OK: {os.path.basename(dst)} ({size_kb}KB)")
if deleted:
    print(f"  deleted: {', '.join(deleted)}")
