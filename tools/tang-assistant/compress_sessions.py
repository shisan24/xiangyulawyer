# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
会话日志压缩脚本
压缩 >7 天的 run journal JSONL 文件为 .gz，节省 ~70% 空间。
由 cron 调用。
"""
import os, gzip, time

NOW = time.time()
MIN_AGE = 7 * 86400  # Only compress files older than 7 days
compressed = 0
saved_bytes = 0

targets = [
    os.path.expanduser(r"[本地路径]"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "sessions", "_run_journal"),
]

for target in targets:
    if not os.path.isdir(target):
        continue
    for root, dirs, files in os.walk(target):
        for f in files:
            if not f.endswith('.jsonl'):
                continue
            fp = os.path.join(root, f)
            try:
                st = os.stat(fp)
                if NOW - st.st_mtime < MIN_AGE:
                    continue
                orig_size = os.path.getsize(fp)
                gz_path = fp + '.gz'
                if os.path.exists(gz_path):
                    continue  # Already compressed
                with open(fp, 'rb') as fin:
                    with gzip.open(gz_path, 'wb') as fout:
                        fout.write(fin.read())
                os.remove(fp)
                new_size = os.path.getsize(gz_path)
                saved_bytes += orig_size - new_size
                compressed += 1
            except:
                pass

if compressed > 0:
    print(f"OK: compressed {compressed} files, saved {saved_bytes//1024**2}MB")
else:
    print("OK: nothing to compress")
