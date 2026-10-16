#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
memory-watchdog.py — Monitor memory system health.

Reports:
  - fact_store: total facts, facts with zero retrievals, avg trust score
  - AGENTS.md: section count, last modified, size
  - session_search: total sessions, last session age

Runs as cron watchdog (no_agent=True script-only mode).
Only outputs when there's a problem (silent when healthy).

Thresholds:
  - fact_store: >50% facts with zero retrievals → WARNING
  - AGENTS.md: >48h since last update → NOTICE
"""

import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DB = HERMES_HOME / "state.db"

def check_fact_store():
    """Check fact_store health from memory_store.db."""
    mem_db = HERMES_HOME / "memory_store.db"
    if not mem_db.exists():
        return {"error": "memory_store.db not found"}

    try:
        conn = sqlite3.connect(str(mem_db))
        cur = conn.cursor()

        # Count total facts
        cur.execute("SELECT COUNT(*) FROM facts")
        total = cur.fetchone()[0]

        # Count facts with zero retrievals
        cur.execute("SELECT COUNT(*) FROM facts WHERE retrieval_count = 0")
        zero_retrieval = cur.fetchone()[0]

        # Average trust score
        cur.execute("SELECT AVG(trust_score) FROM facts")
        avg_trust = cur.fetchone()[0] or 0

        conn.close()

        pct_unused = (zero_retrieval / total * 100) if total > 0 else 0

        return {
            "total": total,
            "zero_retrieval": zero_retrieval,
            "pct_unused": round(pct_unused, 1),
            "avg_trust": round(avg_trust, 2),
            "status": "HEALTHY" if pct_unused < 50 else "WARNING",
        }
    except Exception as e:
        return {"error": str(e)}


def check_agents_md():
    """Check AGENTS.md health."""
    paths = [
        HERMES_HOME.parent / "workspace" / "AGENTS.md",
        Path("[本地路径]"),
    ]
    for p in paths:
        if p.exists():
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            age_hours = (datetime.now() - mtime).total_seconds() / 3600
            size_kb = p.stat().st_size / 1024
            sections = 0
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("## ") and not line.startswith("### "):
                        sections += 1
            return {
                "path": str(p),
                "sections": sections,
                "size_kb": round(size_kb, 1),
                "age_hours": round(age_hours, 1),
                "status": "HEALTHY" if age_hours < 48 else "NOTICE",
            }
    return {"error": "AGENTS.md not found"}


def check_session_search():
    """Check session_search health."""
    if not STATE_DB.exists():
        return {"error": "state.db not found"}

    try:
        conn = sqlite3.connect(str(STATE_DB))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sessions")
        total = cur.fetchone()[0]
        cur.execute("SELECT MAX(updated_at) FROM sessions")
        last_ts = cur.fetchone()[0]
        conn.close()

        last_active_hours = None
        if last_ts:
            try:
                last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                last_active_hours = (datetime.now().astimezone() - last_dt).total_seconds() / 3600
            except:
                pass

        return {
            "total_sessions": total,
            "last_active_hours": round(last_active_hours, 1) if last_active_hours else None,
            "status": "HEALTHY",
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    results = {
        "timestamp": datetime.now().isoformat(),
        "fact_store": check_fact_store(),
        "agents_md": check_agents_md(),
        "session_search": check_session_search(),
    }

    # Determine if we should alert
    alerts = []
    fs = results["fact_store"]
    if fs.get("status") == "WARNING":
        alerts.append(f'fact_store: {fs["pct_unused"]}% facts unused ({fs["zero_retrieval"]}/{fs["total"]})')
    if fs.get("avg_trust", 1) < 0.4:
        alerts.append(f'fact_store: low trust avg={fs["avg_trust"]}')

    am = results["agents_md"]
    if am.get("status") == "NOTICE":
        alerts.append(f'AGENTS.md: {am["age_hours"]}h since last update')

    if alerts:
        print("⚠ Hermes Memory Health Alert")
        for a in alerts:
            print(f"  • {a}")
        print(f"\n  Full report: {json.dumps(results, ensure_ascii=False, indent=2)}")
    # Silent when healthy (watchdog pattern)


if __name__ == "__main__":
    main()
