#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""每小时补戳僵尸 cron 运行会话（no-agent 定时任务包装）。

为什么要每小时跑：gate 跳过型任务（如 scope-recall-瘦身 `19 * * * *`）每轮由 gateway
先建会话行、又在预检返回 wakeAgent=false 时早退、不写 ended_at，于是每小时留下一条
0 消息的空会话；桌面把 `ended_at IS NULL 且调度器不持有` 判为僵尸，打开即只读。
每日清理一次跟不上造行速度，所以本任务按小时补戳。

退出码（cron no-agent 约定）：
  0 = 无事可报（静默，不投递）
  3 = 有值得看的结果或异常（投递摘要）
  2 = 脚本缺失 / 无法执行

真源：scripts/reap_cron_zombies.py（与 hermes-health-diagnostics 技能内副本逐字节一致）。
本文件只做调用、解析与告警阈值，不改动补戳逻辑。
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(r"[本地路径]")
REAP = HOME / "scripts" / "reap_cron_zombies.py"
DB = HOME / "state.db"

# 单轮补戳超过这个数才算异常（正常节奏是每小时 1 条），避免每小时刷屏。
BULK_THRESHOLD = 3


def open_unclosed() -> tuple[int, int]:
    """(未结算 cron 行数, 其中 0 消息的空行数)；读不到返回 (-1, -1)。"""
    try:
        con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=20)
        try:
            open_rows = con.execute(
                "SELECT count(*) FROM sessions WHERE source='cron' AND ended_at IS NULL").fetchone()[0]
            empty_rows = con.execute(
                "SELECT count(*) FROM sessions s WHERE s.source='cron' AND s.ended_at IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id)").fetchone()[0]
            return int(open_rows), int(empty_rows)
        finally:
            con.close()
    except sqlite3.Error:
        return -1, -1


def main() -> int:
    if not REAP.exists():
        print(f"[FAIL] 补戳脚本不存在：{REAP}")
        return 2

    try:
        proc = subprocess.run(
            [sys.executable, str(REAP), "--apply"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        )
    except Exception as exc:  # noqa: BLE001 - 任何执行异常都要看得见
        print(f"[FAIL] 无法运行补戳脚本：{type(exc).__name__}: {exc}")
        return 2

    out = (proc.stdout or "") + (proc.stderr or "")
    m_done = re.search(r"已补结束标记\s*(\d+)\s*条，失败\s*(\d+)\s*条", out)
    m_left = re.search(r"处理后剩余僵尸:\s*(\d+)\s*条", out)
    closed = int(m_done.group(1)) if m_done else -1
    failed = int(m_done.group(2)) if m_done else 0
    left = int(m_left.group(1)) if m_left else -1
    open_rows, empty_rows = open_unclosed()

    stamp = time.strftime("%Y-%m-%d %H:%M")

    # 脚本自身执行失败（非零退出且解析不到结果行）
    if proc.returncode != 0 and closed < 0:
        print(f"[FAIL] 补戳脚本退出码 {proc.returncode}（{stamp}）\n{out.strip()[-1500:]}")
        return 2

    # 正常的每小时一条：静默
    if closed <= 0 and failed == 0 and left <= 0:
        return 0

    # 异常或积压：投递摘要
    if failed > 0 or left > 0 or closed > BULK_THRESHOLD or open_rows > BULK_THRESHOLD:
        print(
            f"僵尸 cron 会话清理（{stamp}）：补戳 {closed} 条，失败 {failed} 条，"
            f"处理后剩余 {left} 条；库内未结算 cron 行 {open_rows} 条（其中 0 消息空行 {empty_rows} 条）。"
        )
        if out.strip():
            print("--- reap 输出 ---")
            print(out.strip()[-1500:])
        return 3

    # 少量补戳（1~3 条）= 每小时预期节奏，不必打扰
    return 0


if __name__ == "__main__":
    sys.exit(main())
