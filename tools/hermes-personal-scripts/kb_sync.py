# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""知识库同步 — no_agent cron 脚本
扫描案件目录新增文件 → 同步到 Obsidian 本机目录/"""
import os
import sys
import shutil
from pathlib import Path
from datetime import datetime, timedelta

# 源目录
SOURCES = [
    r"[本地路径]",
    r"[本地路径]",
]
# Obsidian 目标
OBSIDIAN = os.path.expanduser(r"[本地路径]")
# 状态文件：记录上次同步时间
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.kb_sync_state')

def get_last_sync():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return datetime.fromisoformat(f.read().strip())
    return datetime.min

def save_sync():
    with open(STATE_FILE, 'w') as f:
        f.write(datetime.now().isoformat())

def scan_new_files(since):
    """扫描 since 之后的新增/修改文件"""
    new_files = []
    for src in SOURCES:
        if not os.path.exists(src):
            continue
        for root, dirs, files in os.walk(src):
            # 跳过隐藏目录
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if f.startswith('.') or f.startswith('~'):
                    continue
                fp = os.path.join(root, f)
                mtime = datetime.fromtimestamp(os.path.getmtime(fp))
                if mtime > since:
                    new_files.append((fp, mtime))
    return new_files

def main():
    since = get_last_sync()
    new_files = scan_new_files(since)

    if not new_files:
        print("[SILENT]")
        return

    # 同步到 Obsidian（创建符号链接或复制索引）
    synced = 0
    for fp, mtime in sorted(new_files, key=lambda x: x[1], reverse=True)[:20]:
        rel = os.path.relpath(fp, SOURCES[0] if SOURCES[0] in fp else SOURCES[1])
        print(f"  {mtime.strftime('%m-%d %H:%M')}  {rel}")
        synced += 1

    print(f"\n共 {synced} 个新文件（本次仅报告，未实际复制到 Obsidian）")
    save_sync()

if __name__ == '__main__':
    main()
