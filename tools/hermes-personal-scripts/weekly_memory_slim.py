#!/usr/bin/env python
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Weekly Memory Slim v1 — no_agent, runs in cron. Reads MEMORY.md, removes stale entries."""
import os, re, datetime

MEM_DIR = os.path.expandvars(r"%LOCALAPPDATA%\hermes\memories")
TARGET_PCT = 75.0
MEMORY_LIMIT = 6000  # 2026-08-04 桌面端配额 4000→6000

def slim():
    path = os.path.join(MEM_DIR, "MEMORY.md")
    if not os.path.exists(path):
        print("[SLIM] MEMORY.md not found")
        return

    with open(path, encoding="utf-8") as f:
        text = f.read()

    entries = text.split("§")
    chars_before = sum(len(e) for e in entries if e.strip())
    pct_before = round(chars_before / MEMORY_LIMIT * 100, 1)

    if pct_before < TARGET_PCT:
        print(f"[SLIM] {pct_before}% < {TARGET_PCT}%, no action")
        return

    # Rules to identify stale entries
    stale_patterns = [
        r"MinerU.*\d+\.\d+\.\d+",      # Version-specific MinerU entries
        r"\d{4}-\d{2}-\d{2}系统v\d",    # Old system version entries
        r"hermes-agent-cn-desktop\.exe",  # CN Desktop shell historical
        r"capabilities v\d+\.\d+\.\d+",   # Old capabilities versions
    ]

    kept, removed = [], []
    for e in entries:
        stripped = e.strip()
        if not stripped or len(stripped) < 10:
            removed.append(stripped)
            continue
        is_stale = any(re.search(p, stripped) for p in stale_patterns)
        if is_stale:
            removed.append(stripped[:80] + "...")
        else:
            kept.append(e)

    new_text = "§".join(kept)
    chars_after = sum(len(e) for e in kept if e.strip())
    pct_after = round(chars_after / MEMORY_LIMIT * 100, 1)

    # Only write if significant reduction
    if chars_before - chars_after > 50:
        # Backup
        backup = path + f".bak.{datetime.date.today().isoformat()}"
        with open(backup, "w", encoding="utf-8") as f:
            f.write(text)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        print(f"[SLIM] {pct_before}% → {pct_after}% ({chars_before}→{chars_after}c) "
              f"removed={len(removed)} backup={os.path.basename(backup)}")
    else:
        print(f"[SLIM] {pct_before}% → {pct_after}% ({len(removed)} removed)")

if __name__ == "__main__":
    slim()
