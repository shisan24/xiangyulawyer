#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
Session 维护 — 僵尸清理 + 知识蒸馏
作为 no_agent cron 脚本运行（配合现有 vacuum_state.py）
"""

import sqlite3, time, os, sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "state.db"
NOW = time.time()
DAY = 86400


def clean_zombies():
    """Mark abandoned sessions as ended"""
    conn = sqlite3.connect(str(DB))
    result = conn.execute("""
        UPDATE sessions SET ended_at = ?, end_reason = 'auto_cleanup'
        WHERE ended_at IS NULL AND id NOT LIKE 'cron_%'
        AND (started_at IS NULL OR started_at < ?)
    """, (NOW, NOW - DAY))
    cleaned = result.rowcount
    conn.commit()
    
    # Also patch sessions with really wrong timestamps
    conn.execute("""
        UPDATE sessions SET started_at = ended_at 
        WHERE started_at < 1000000 AND ended_at > 1000000
    """)
    
    conn.close()
    return cleaned


def count_active():
    conn = sqlite3.connect(str(DB))
    total = conn.execute("SELECT COUNT(*) FROM sessions WHERE ended_at IS NULL").fetchone()[0]
    user = conn.execute("SELECT COUNT(*) FROM sessions WHERE ended_at IS NULL AND id NOT LIKE 'cron_%'").fetchone()[0]
    conn.close()
    return total, user


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv
    cleaned = clean_zombies()
    total, user = count_active()
    if cleaned > 0 or verbose:
        print(f"Housekeeping: cleaned {cleaned} zombies | active: {total} ({user} user)")
