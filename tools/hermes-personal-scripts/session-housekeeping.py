#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""State.db 会话清理 — 按**当前实例配置的保留天数**（sessions.retention_days）删除过期会话的消息。

用法: python session-housekeeping.py [--dry-run] [--vacuum]
用于 cron 每日 18:00（no_agent=true）。

保留天数不再写死：2026-09-30 之前此处硬编码 30 天，与主配置的 90 天政策冲突，
导致 31–90 天的消息被提前删除（第三方核查提出，已实测确认删除发生过：现存最老消息
约 34 天前，而配置为 90 天）。现在以当前实例的 config.yaml 为唯一来源。
"""

import os
import re
import sqlite3
import sys
import time
from pathlib import Path

# 当前实例根目录：优先 HERMES_HOME（与其他脚本一致），否则用主实例默认位置。
# 本脚本只处理当前实例的 state.db，不要把它当所有 profile 的通用清理入口。
HERMES_HOME = Path(
    os.environ.get("HERMES_HOME")
    or (Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("[本地路径]"))) / "hermes")
)
STATE_DB = HERMES_HOME / "state.db"
DEFAULT_RETENTION_DAYS = 90
RETENTION_DAYS = DEFAULT_RETENTION_DAYS  # 运行开始时由 read_retention_days() 覆盖
RETENTION_SECONDS = RETENTION_DAYS * 86400


def read_retention_days(config_path=None) -> int:
    """读取当前实例 config.yaml 的 sessions.retention_days；读不到才用默认值。"""
    cfg = Path(config_path) if config_path else HERMES_HOME / "config.yaml"
    if not cfg.exists():
        print(f"[WARN] 未找到 {cfg}，使用默认保留 {DEFAULT_RETENTION_DAYS} 天")
        return DEFAULT_RETENTION_DAYS
    value = None
    try:
        import yaml  # Hermes 运行环境自带

        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        value = (data.get("sessions") or {}).get("retention_days")
    except Exception:  # yaml 不可用或格式异常 → 退回文本解析
        text = cfg.read_text(encoding="utf-8", errors="replace")
        block = re.search(r"^sessions:\s*$([\s\S]*?)(?=^\S)", text, re.M)
        if block:
            hit = re.search(r"^\s+retention_days:\s*(\d+)", block.group(1), re.M)
            value = int(hit.group(1)) if hit else None
    try:
        days = int(value)
        if days <= 0:
            raise ValueError(days)
    except (TypeError, ValueError):
        print(f"[WARN] config 未给出有效的 sessions.retention_days，使用默认保留 {DEFAULT_RETENTION_DAYS} 天")
        return DEFAULT_RETENTION_DAYS
    return days


def main():
    global RETENTION_DAYS, RETENTION_SECONDS
    RETENTION_DAYS = read_retention_days()
    RETENTION_SECONDS = RETENTION_DAYS * 86400
    print(f"[INFO] 保留政策：{RETENTION_DAYS} 天（来源 {HERMES_HOME / 'config.yaml'} 的 sessions.retention_days）")
    dry_run = "--dry-run" in sys.argv
    # VACUUM 独占锁会阻塞 gateway DB 连接导致崩溃（见 state-db-vacuum-gateway-crash skill）。
    # 默认不执行；确需收缩文件时：先 hermes gateway stop，再手动加 --vacuum 运行。
    do_vacuum = "--vacuum" in sys.argv

    if not STATE_DB.exists():
        print("[SKIP] state.db not found")
        return

    before_size = STATE_DB.stat().st_size / (1024 * 1024)
    now = time.time()
    cutoff = now - RETENTION_SECONDS

    conn = sqlite3.connect(str(STATE_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    # 找出每个 session 的最新消息时间
    cur.execute("""
        SELECT session_id, MAX(timestamp) as last_msg
        FROM messages GROUP BY session_id
    """)
    all_sessions = {row[0]: row[1] for row in cur.fetchall()}

    def _epoch(value):
        """把消息时间戳归一到秒；解析不出的返回 None（宁可跳过，不可误删）。"""
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
        return num / 1000 if num > 1e12 else num

    stale = [
        sid for sid, ts in all_sessions.items()
        if (_epoch(ts) if _epoch(ts) is not None else now) < cutoff
    ]
    active = [sid for sid in all_sessions if sid not in stale]

    print(f"Sessions: {len(all_sessions)} total, {len(active)} active, {len(stale)} stale")

    if not stale:
        print(f"[OK] All sessions active within {RETENTION_DAYS} days")
        conn.close()
        return

    if dry_run:
        print(f"[DRY-RUN] Would delete {len(stale)} stale sessions")
        for sid in stale[:5]:
            print(f"  {sid}")
        if len(stale) > 5:
            print(f"  ... and {len(stale) - 5} more")
        conn.close()
        return

    # 删除过期消息
    placeholders = ",".join(["?"] * len(stale))
    cur.execute(f"DELETE FROM messages WHERE session_id IN ({placeholders})", stale)
    deleted_count = cur.rowcount
    print(f"Deleted {deleted_count} messages from {len(stale)} sessions")

    conn.commit()

    if do_vacuum:
        print("Running VACUUM... (须已执行 hermes gateway stop)")
        conn.execute("VACUUM")
        conn.close()

        after_size = STATE_DB.stat().st_size / (1024 * 1024)
        freed = before_size - after_size

        print(f"state.db: {before_size:.1f}MB -> {after_size:.1f}MB (freed {freed:.1f}MB)")

        if freed > 10:
            print(f"[REPORT] reclaimed {freed:.1f}MB")
    else:
        conn.close()
        print("[SKIP] VACUUM skipped（独占锁会崩 gateway）。如需收缩文件：hermes gateway stop 后手动加 --vacuum 运行。")


if __name__ == "__main__":
    main()
