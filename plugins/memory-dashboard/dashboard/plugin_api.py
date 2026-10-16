# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Memory dashboard backend — reads MEMORY.md/USER.md + the scope-recall v3 store.

Mounted under /api/plugins/memory-dashboard/ by the gateway plugin loader.
Runs inside the gateway process; stdlib + sqlite3 only.

2026-09-29: the scope-recall section was rewritten for the v3.x store
(scope-recall 3.2.0 / schema 1110). The pre-3.x tables it used before
(memories / journal_entries / journal_digest_runs) no longer exist; the
numbers now come from claims / work_items / source_events / instance_meta
plus the worker status file.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

# 容量限额只有一个来源：HERMES_HOME/config.yaml 的 memory.memory_char_limit / user_char_limit。
# 与 scripts/memory_preflight.py 的 load_limits() 同源同口径——脚本内不得写死，否则配置改了
# 看板/巡检仍按旧值判。2026-10-11 配置已提到 10000/6000、preflight 已跟随，而本插件仍写死
# 6000/3000，看板显示的配额因此过期。下面 LIMITS_DEFAULT 只在 config.yaml 读不到时回落。
LIMITS_DEFAULT = {"MEMORY.md": 10000, "USER.md": 6000}
# 检查阈值与 memory_preflight.py（cron 前置巡检）保持一致：超过 quota*RATIO 触发核查
CHECK_RATIO = 0.85


def _hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "hermes"
    return Path.home() / ".hermes"


def _as_int(value, fallback):
    try:
        return int(str(value).strip().split("#")[0].strip())
    except (TypeError, ValueError):
        return fallback


def load_limits() -> dict:
    """读 config.yaml 的 memory 节；逻辑与 scripts/memory_preflight.py 的 load_limits() 等价。

    能被 PyYAML 解析就用它，否则用纯 stdlib 扫 memory 节；都拿不到才回落到 LIMITS_DEFAULT。
    """
    limits = dict(LIMITS_DEFAULT)
    try:
        text = (_hermes_home() / "config.yaml").read_text(encoding="utf-8")
    except OSError:
        return limits
    try:
        import yaml

        mem = (yaml.safe_load(text) or {}).get("memory") or {}
        if mem.get("memory_char_limit"):
            limits["MEMORY.md"] = _as_int(mem["memory_char_limit"], limits["MEMORY.md"])
        if mem.get("user_char_limit"):
            limits["USER.md"] = _as_int(mem["user_char_limit"], limits["USER.md"])
        return limits
    except Exception:
        pass
    in_memory = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            in_memory = line.split(":")[0].strip() == "memory"
            continue
        if not in_memory or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key == "memory_char_limit" and value.strip():
            limits["MEMORY.md"] = _as_int(value, limits["MEMORY.md"])
        elif key == "user_char_limit" and value.strip():
            limits["USER.md"] = _as_int(value, limits["USER.md"])
    return limits


def _memory_stats() -> dict:
    home = _hermes_home()
    limits = load_limits()
    out = {}
    for name, quota in (("MEMORY.md", limits["MEMORY.md"]), ("USER.md", limits["USER.md"])):
        path = home / "memories" / name
        if not path.exists():
            out[name] = {"exists": False}
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        # 字符口径与 memory_preflight.py（cron 前置巡检）一致：换行统一为 \n 后计字符，CRLF 不重复计
        norm = text.replace("\r\n", "\n").replace("\r", "\n")
        blocks = re.split(r"\r?\n§\r?\n", text)
        threshold = int(quota * CHECK_RATIO)
        out[name] = {
            "exists": True,
            "chars": len(norm),        # 主口径：与前置巡检/闸门一致
            "chars_raw": len(text),    # 原口径（CRLF 各计 1 字符），保留供对照
            "bytes": len(raw),
            "quota": quota,
            "threshold": threshold,
            "over_threshold": len(norm) > threshold,
            "blocks": len(blocks),
            "pct": round(len(norm) / quota * 100, 1),
            "mtime": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(),
        }
    return out


def _scope_recall_stats() -> dict:
    """Scope-recall v3.x health: claims / work queue / capture / worker."""
    home = _hermes_home()
    db = home / "scope-recall" / "memory.sqlite3"
    out: dict = {"exists": db.exists()}
    if not out["exists"]:
        return out
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        out["claims"] = cur.execute(
            "SELECT COUNT(*) FROM claims WHERE COALESCE(suppressed, 0) = 0"
        ).fetchone()[0]
        out["claims_by_kind"] = {
            r["kind"]: r["n"]
            for r in cur.execute(
                "SELECT kind, COUNT(*) AS n FROM claims "
                "WHERE COALESCE(suppressed, 0) = 0 GROUP BY kind ORDER BY n DESC"
            )
        }

        states = {
            r["state"]: r["n"]
            for r in cur.execute(
                "SELECT state, COUNT(*) AS n FROM work_items GROUP BY state"
            )
        }
        out["work_states"] = states
        out["work_pending"] = states.get("pending", 0)
        out["work_failed"] = states.get("failed", 0)

        out["sources_total"] = cur.execute(
            "SELECT COUNT(*) FROM source_events"
        ).fetchone()[0]
        out["sources_last"] = cur.execute(
            "SELECT MAX(recorded_at) FROM source_events"
        ).fetchone()[0]
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        out["sources_last_24h"] = cur.execute(
            "SELECT COUNT(*) FROM source_events WHERE substr(recorded_at, 1, 19) >= ?",
            (cutoff,),
        ).fetchone()[0]

        row = cur.execute("SELECT memory_epoch FROM instance_meta LIMIT 1").fetchone()
        out["epoch"] = row[0] if row else None
        out["db_size_mb"] = round(db.stat().st_size / 1024 / 1024, 1)
        conn.close()

        out["worker"] = None
        worker_path = home / "scope-recall" / "runtime-worker-status.json"
        if worker_path.exists():
            try:
                w = json.loads(worker_path.read_text(encoding="utf-8"))
                out["worker"] = {
                    k: w.get(k)
                    for k in (
                        "status",
                        "last_success_at",
                        "finished_at",
                        "pending_work",
                        "failed",
                        "failed_work",
                        "terminal_failed_work",
                        "completed",
                        "worker_pid",
                    )
                }
            except (OSError, ValueError) as exc:
                out["worker"] = {"error": str(exc)}
    except (sqlite3.Error, OSError, ValueError) as exc:
        out["error"] = str(exc)
    return out


@router.get("/stats")
async def stats() -> dict:
    return {
        "memory": _memory_stats(),
        "scope_recall": _scope_recall_stats(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/memories")
async def memories(limit: int = 20) -> dict:
    """Recent scope-recall claims (v3.x store), newest first."""
    db = _hermes_home() / "scope-recall" / "memory.sqlite3"
    if not db.exists():
        return {"items": []}
    limit = max(1, min(limit, 100))
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT claim_id, subject, predicate, kind FROM claims "
            "WHERE COALESCE(suppressed, 0) = 0 ORDER BY rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        return {"items": [], "error": str(exc)}
    return {"items": [dict(r) for r in rows]}

