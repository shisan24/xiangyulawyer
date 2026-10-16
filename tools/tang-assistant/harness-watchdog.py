#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
Harness Watchdog — 上下文+停滞监控
检查活跃 session 的消息数/Token 数，超过阈值发出告警。
适配 Hermes state.db，只读模式避免锁冲突。
"""
import sqlite3
import os
import sys
from datetime import datetime, timezone

# ============ 配置 ============
CRIT_MSGS = 300
CRIT_TOKENS = 500_000       # Token 总数 ≥ 此值 → CRIT
WARN_MSGS = 150
WARN_TOKENS = 300_000       # Token 总数 ≥ 此值 → WARN
STALL_MSGS = 200            # 消息数 ≥ 此值 且 tools ≥ 此值 → 建议 /reset
STALL_TOOLS = 100

# state.db 路径
STATE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "state.db")


def get_active_sessions(db_path):
    """查询所有活跃 session（ended_at IS NULL）"""
    if not os.path.exists(db_path):
        return []
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        cur = db.execute(
            "SELECT id, title, model, message_count, input_tokens, output_tokens, "
            "tool_call_count, started_at "
            "FROM sessions WHERE ended_at IS NULL "
            "ORDER BY started_at DESC"
        )
        rows = [dict(r) for r in cur.fetchall()]
        db.close()
        return rows
    except sqlite3.OperationalError as e:
        print(f"[WARN] state.db 读取失败: {e}", file=sys.stderr)
        return []


def run():
    sessions = get_active_sessions(STATE_DB)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%d %H:%M UTC")

    ctx_alerts = []
    reset_alerts = []

    for s in sessions:
        sid = s["id"][:12] if s["id"] else "?"
        title = s["title"] or "(no title)"
        model = s["model"] or "?"
        msgs = s["message_count"] or 0
        in_tok = s["input_tokens"] or 0
        out_tok = s["output_tokens"] or 0
        total_tok = in_tok + out_tok
        tools = s["tool_call_count"] or 0

        level = None
        if msgs >= CRIT_MSGS or total_tok >= CRIT_TOKENS:
            level = "CRIT"
        elif msgs >= WARN_MSGS or total_tok >= WARN_TOKENS:
            level = "WARN"

        if level:
            ctx_alerts.append(
                f"  [{level}] {title} ({model}) msgs:{msgs} tokens:{total_tok//1000}K"
                f" — msgs:{msgs}, tokens:{total_tok//1000}K"
            )

        # 停滞检测：高消息数 + 高工具调用 → 建议 /reset 释放上下文
        if msgs >= STALL_MSGS and tools >= STALL_TOOLS:
            reset_alerts.append(
                f"  [RESET] {title} — msgs:{msgs}, tokens:{total_tok//1000}K, "
                f"tools:{tools} -> suggest /reset + handoff"
            )

    total_alerts = len(ctx_alerts) + len(reset_alerts)
    if total_alerts == 0:
        print(f"HARNESS WATCHDOG {ts} | alerts:0 — all clear")
        return

    print(
        f"HARNESS WATCHDOG {ts} | alerts:{total_alerts}"
        f" (ctx:{len(ctx_alerts)} stall:0 reset:{len(reset_alerts)})"
    )
    for line in ctx_alerts:
        print(line)
    for line in reset_alerts:
        print(line)


if __name__ == "__main__":
    run()
