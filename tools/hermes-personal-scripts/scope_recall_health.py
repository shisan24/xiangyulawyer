# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""scope-recall 数据库健康检查 — no_agent cron 脚本
检查项：DB 大小、memories 分布、journal 积压、digest 状态
输出：全正常 → [SILENT]，有异常 → 报告"""
import sqlite3
import json
import os
import sys
from datetime import datetime, timedelta, timezone

DB_PATH = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('[本地路径]')),
                       'hermes', 'scope-recall', 'memory.sqlite3')

def check():
    if not os.path.exists(DB_PATH):
        print(f"[WARN] scope-recall DB not found: {DB_PATH}")
        return

    db = sqlite3.connect(DB_PATH)
    issues = []

    try:
        # memories by target
        mem = {r[0]: r[1] for r in db.execute('SELECT target, COUNT(*) FROM memories GROUP BY target')}
        total_mem = sum(mem.values())

        # journal
        total_journal = db.execute('SELECT COUNT(*) FROM journal_entries').fetchone()[0]

        # digest
        last_digest = db.execute("SELECT MAX(started_at) FROM journal_digest_runs WHERE status='ok'").fetchone()[0]
        last_attempt = db.execute('SELECT MAX(started_at) FROM journal_digest_runs').fetchone()[0]
        recent_failures = db.execute(
            "SELECT COUNT(*) FROM journal_digest_runs WHERE status='error' AND started_at > datetime('now','-1 day')"
        ).fetchone()[0]
        digest_cnt = db.execute('SELECT COUNT(*) FROM journal_digest_runs').fetchone()[0]

        # DB size
        size_mb = os.path.getsize(DB_PATH) / 1024 / 1024

        # integrity check
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            issues.append(f"⚠️ integrity_check: {integrity}")

        # checks
        now = datetime.now(timezone.utc)
        if last_digest:
            last_dt = datetime.fromisoformat(last_digest.replace('Z', '+00:00'))
            hours_ago = (now - last_dt).total_seconds() / 3600
            if hours_ago > 24:
                issues.append(f"⚠️ last successful digest {hours_ago:.0f}h ago (>24h)")
        else:
            issues.append("⚠️ no successful digest runs found")
        if recent_failures > 0:
            issues.append(f"⚠️ digest failures in last 24h: {recent_failures}")

        if size_mb > 50:
            issues.append(f"⚠️ DB size {size_mb:.1f}MB (>50MB)")

        if total_journal > 10000:
            issues.append(f"⚠️ journal {total_journal} entries (>10000)")

    finally:
        db.close()

    if issues:
        print(f"## scope-recall health\n")
        print(f"| 指标 | 值 |")
        print(f"|------|-----|")
        print(f"| memories | {total_mem} ({', '.join(f'{k}:{v}' for k,v in sorted(mem.items()))}) |")
        print(f"| journal | {total_journal} |")
        print(f"| digest_runs | {digest_cnt} |")
        print(f"| last_digest_ok | {last_digest or 'N/A'} |")
        print(f"| last_attempt | {last_attempt or 'N/A'} |")
        print(f"| failures_24h | {recent_failures} |")
        print(f"| db_size | {size_mb:.1f} MB |")
        print(f"")
        for issue in issues:
            print(issue)
    else:
        print("[SILENT]")

if __name__ == '__main__':
    check()
