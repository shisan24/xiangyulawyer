#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
fact-provenance.py — fact_store 溯源追踪器

每条 fact_store add 操作同时记录 provenance:
  - source_uri: 来源路径/对话ID
  - source_hash: 来源内容 hash
  - added_by: 添加者（agent session / user）
  - supersedes: 替换了哪个旧 fact_id
  - valid_until: 过期时间（None = 永久）

Provenance 日志存储在 .harness/provenance.jsonl (append-only)

Usage:
  python fact-provenance.py log --fact-id <id> --source <uri> [--hash <sha>] [--supersedes <id>] [--ttl-days <n>]
  python fact-provenance.py check --fact-id <id>   # 检查是否过期
  python fact-provenance.py list [--stale]          # 列出所有/过期事实
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HARNESS_DIR = Path(os.environ.get("HARNESS_DIR", Path.home() / ".harness"))
PROVENANCE_FILE = HARNESS_DIR / "provenance.jsonl"
USAGE_FILE = HARNESS_DIR / "fact-usage.json"


# ── Usage Tracking (Flywheel 2: probe→use→rate→trust) ──────────────

def load_usage():
    """Load fact usage statistics."""
    if not USAGE_FILE.exists():
        return {}
    with open(USAGE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_usage(data):
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def record_usage(fact_id: int, context: str = ""):
    """Record that a fact was retrieved (probed/searched/used)."""
    data = load_usage()
    key = str(fact_id)
    if key not in data:
        data[key] = {"retrievals": 0, "ratings": [], "last_used": None, "contexts": []}
    data[key]["retrievals"] += 1
    data[key]["last_used"] = datetime.now().isoformat()
    if context:
        data[key]["contexts"].append(context[:200])
        if len(data[key]["contexts"]) > 10:
            data[key]["contexts"] = data[key]["contexts"][-10:]
    save_usage(data)
    return data[key]


def record_rating(fact_id: int, rating: str):
    """Record user/agent rating for a fact (helpful/unhelpful)."""
    data = load_usage()
    key = str(fact_id)
    if key not in data:
        data[key] = {"retrievals": 0, "ratings": [], "last_used": None, "contexts": []}
    data[key]["ratings"].append({
        "rating": rating,
        "timestamp": datetime.now().isoformat(),
    })
    save_usage(data)
    return data[key]


def usage_stats():
    """Compute usage statistics for all facts."""
    data = load_usage()
    if not data:
        return {"total_facts": 0, "total_retrievals": 0, "facts": []}

    facts = []
    total_retrievals = 0
    for fid, info in data.items():
        retrievals = info.get("retrievals", 0)
        total_retrievals += retrievals
        ratings = info.get("ratings", [])
        helpful = sum(1 for r in ratings if r["rating"] == "helpful")
        unhelpful = sum(1 for r in ratings if r["rating"] == "unhelpful")
        trust = (helpful / len(ratings) * 100) if ratings else 50

        facts.append({
            "fact_id": int(fid),
            "retrievals": retrievals,
            "ratings_total": len(ratings),
            "helpful": helpful,
            "unhelpful": unhelpful,
            "trust_score": round(trust, 1),
            "last_used": info.get("last_used"),
        })

    facts.sort(key=lambda x: x["retrievals"], reverse=True)

    # Detect cold facts (zero usage, low trust)
    cold_facts = [f for f in facts if f["retrievals"] == 0]

    return {
        "total_facts": len(facts),
        "total_retrievals": total_retrievals,
        "avg_retrievals": round(total_retrievals / len(facts), 1) if facts else 0,
        "cold_facts": len(cold_facts),
        "cold_pct": round(len(cold_facts) / len(facts) * 100, 1) if facts else 0,
        "top_used": facts[:5],
        "cold": cold_facts[:5],
    }


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def log_provenance(fact_id: int, source_uri: str, source_content: str = "",
                   supersedes: int = None, ttl_days: int = None):
    """Append a provenance record."""
    entry = {
        "fact_id": fact_id,
        "source_uri": source_uri,
        "source_hash": hash_content(source_content) if source_content else "",
        "added_at": datetime.now().isoformat(),
        "added_by": os.environ.get("HERMES_SESSION_ID", "manual"),
        "supersedes": supersedes,
        "valid_until": (datetime.now() + timedelta(days=ttl_days)).isoformat() if ttl_days else None,
    }

    PROVENANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROVENANCE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def check_fact(fact_id: int) -> dict:
    """Check if a fact has provenance and whether it's expired."""
    if not PROVENANCE_FILE.exists():
        return {"fact_id": fact_id, "status": "unknown", "note": "no provenance data"}

    records = []
    with open(PROVENANCE_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("fact_id") == fact_id:
                    records.append(r)
            except json.JSONDecodeError:
                continue

    if not records:
        return {"fact_id": fact_id, "status": "unknown", "note": "no provenance record"}

    latest = records[-1]
    now = datetime.now()
    expired = False
    if latest.get("valid_until"):
        valid_until = datetime.fromisoformat(latest["valid_until"])
        expired = now > valid_until

    return {
        "fact_id": fact_id,
        "status": "expired" if expired else "valid",
        "source_uri": latest["source_uri"],
        "added_at": latest["added_at"],
        "superseded_by": None,  # Would need to scan all records
        "valid_until": latest.get("valid_until"),
    }


def list_facts(stale_only: bool = False):
    """List all facts with provenance, optionally only stale ones."""
    if not PROVENANCE_FILE.exists():
        return []

    facts = {}
    with open(PROVENANCE_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                fid = r["fact_id"]
                facts[fid] = r  # Last write wins
            except json.JSONDecodeError:
                continue

    result = []
    now = datetime.now()
    for fid, rec in sorted(facts.items()):
        expired = False
        if rec.get("valid_until"):
            expired = now > datetime.fromisoformat(rec["valid_until"])
        if stale_only and not expired:
            continue
        result.append({
            "fact_id": fid,
            "source_uri": rec["source_uri"],
            "added_at": rec["added_at"],
            "expired": expired,
        })

    return result


def main():
    parser = argparse.ArgumentParser(description="fact_store provenance tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("log", help="Log a new provenance record")
    p.add_argument("--fact-id", type=int, required=True)
    p.add_argument("--source", required=True, help="Source URI (file path, session ID, etc.)")
    p.add_argument("--content", default="", help="Source content for hashing")
    p.add_argument("--supersedes", type=int, default=None)
    p.add_argument("--ttl-days", type=int, default=None, help="Auto-expire after N days")

    p = sub.add_parser("check", help="Check a fact's provenance status")
    p.add_argument("--fact-id", type=int, required=True)

    p = sub.add_parser("list", help="List all provenance records")
    p.add_argument("--stale", action="store_true", help="Only show expired facts")

    # ── Usage tracking (Flywheel 2) ──
    p = sub.add_parser("use", help="Record fact retrieval/usage")
    p.add_argument("--fact-id", type=int, required=True)
    p.add_argument("--context", default="", help="What was the fact used for")

    p = sub.add_parser("rate", help="Rate a fact (helpful/unhelpful)")
    p.add_argument("--fact-id", type=int, required=True)
    p.add_argument("--rating", required=True, choices=["helpful", "unhelpful"])

    p = sub.add_parser("stats", help="Show fact usage statistics")

    args = parser.parse_args()

    if args.command == "log":
        result = log_provenance(args.fact_id, args.source, args.content,
                                args.supersedes, args.ttl_days)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "check":
        result = check_fact(args.fact_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "list":
        results = list_facts(args.stale)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.command == "use":
        result = record_usage(args.fact_id, args.context)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "rate":
        result = record_rating(args.fact_id, args.rating)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "stats":
        result = usage_stats()
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
