# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
会话日志清理脚本
清理 >30 天的 run journal 日志和旧 session 文件。
由 cron 调用。
"""
import os, time, shutil

NOW = time.time()
MAX_AGE = 30 * 86400  # 30 days

targets = [
    os.path.expanduser(r"[本地路径]"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "sessions", "_run_journal"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "sessions"),
]

total_deleted = 0
total_size = 0

for target in targets:
    if not os.path.isdir(target):
        continue
    for root, dirs, files in os.walk(target):
        # Check dirs
        for d in dirs[:]:
            dp = os.path.join(root, d)
            try:
                st = os.stat(dp)
                if NOW - st.st_mtime > MAX_AGE:
                    size = sum(
                        os.path.getsize(os.path.join(r, f))
                        for r, _, fs in os.walk(dp)
                        for f in fs
                        if os.path.isfile(os.path.join(r, f))
                    )
                    shutil.rmtree(dp, ignore_errors=True)
                    total_deleted += 1
                    total_size += size
                    dirs.remove(d)
            except:
                pass
        # Check files
        for f in files:
            fp = os.path.join(root, f)
            try:
                st = os.stat(fp)
                if NOW - st.st_mtime > MAX_AGE:
                    sz = os.path.getsize(fp)
                    os.remove(fp)
                    total_deleted += 1
                    total_size += sz
            except:
                pass

if total_deleted > 0:
    print(f"OK: deleted {total_deleted} items ({total_size//1024**2}MB)")
else:
    print("OK: nothing to clean")
