#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
agents-audit.py — Post-task AGENTS.md compliance auditor.

Scans a .docx for AGENTS.md violations:
  - AI-ism phrases (值得注意的是, 此外, 总而言之, etc.)
  - Emoji usage
  - Format issues (font, spacing)
  - Blank fields not annotated
  - File naming convention violations

Usage:
  python agents-audit.py --doc <file.docx>
  python agents-audit.py --text "<text to scan>"
  python agents-audit.py --checklist  (print the full checklist)
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HARNESS_DIR = Path(os.environ.get("HARNESS_DIR", Path.home() / ".harness"))

# ── Banned patterns (from AGENTS.md §9) ──
BANNED_PHRASES = [
    "值得注意的是",
    "此外",
    "总而言之",
    "综上所述",
    "首先其次最后",
    "不仅而且",
    "值得一提的是",
]

# Paragraph-level banned patterns (check if line starts with these)
BANNED_TRANSITIONS = [
    "首先，",
    "其次，",
    "最后，",
    "另外，",
]

# Emoji detection — common emoji only (tight pattern)
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U00002600-\U000026FF"  # misc symbols (☀⚠✅❌ etc)
    "\U00002708\U0000270C\U0000270F"  # ✈✌✏
    "\U00002764\U00002766\U00002767"  # ❤❦❧
    "]+", re.UNICODE
)


def load_docx_text(path):
    """Extract text from .docx."""
    try:
        import docx
        doc = docx.Document(path)
        paras = []
        for p in doc.paragraphs:
            if p.text.strip():
                paras.append(p.text.strip())
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        paras.append(cell.text.strip())
        return "\n".join(paras), doc
    except Exception as e:
        return None, str(e)


def scan_banned_phrases(text):
    """Find all banned AI phrases."""
    findings = []
    for phrase in BANNED_PHRASES:
        idx = 0
        while True:
            idx = text.find(phrase, idx)
            if idx == -1:
                break
            # Get context
            start = max(0, idx - 20)
            end = min(len(text), idx + len(phrase) + 20)
            findings.append({
                "phrase": phrase,
                "position": idx,
                "context": "..." + text[start:end] + "...",
            })
            idx += 1
    return findings


def scan_transitions(text):
    """Find paragraph-starting transitions ('首先，其次，最后，')."""
    findings = []
    lines = text.split("\n")
    transition_count = 0
    for line in lines:
        for t in BANNED_TRANSITIONS:
            if line.strip().startswith(t):
                transition_count += 1
                findings.append({
                    "phrase": t,
                    "line": line.strip()[:80],
                })
    # Only flag if >=2 transitions found (sequential pattern)
    flagged = transition_count >= 2
    return findings, flagged, transition_count


def scan_emojis(text):
    """Detect emoji characters."""
    matches = EMOJI_PATTERN.findall(text)
    return [{"emoji": m, "position": text.find(m)} for m in matches]


def scan_blank_fields(text):
    """Check for 【】 without annotation."""
    blanks = re.findall(r"【\s*】", text)
    return [{"blank": b} for b in blanks]


def scan_file_naming(filepath):
    """Check if filename follows convention."""
    name = os.path.basename(filepath)
    # Expected: YYYYMMDD【修订版】name.docx
    has_date_prefix = bool(re.match(r"^\d{8}", name))
    has_xiuding = "【修订版】" in name or "【" in name
    return {
        "filename": name,
        "has_date_prefix": has_date_prefix,
        "has_version_tag": has_xiuding,
    }


def audit_document(doc_path):
    """Full audit of a .docx file against AGENTS.md rules."""
    text, doc_or_error = load_docx_text(doc_path)
    if text is None:
        return {"error": str(doc_or_error)}

    results = {
        "file": doc_path,
        "char_count": len(text),
        "violations": {},
    }

    # 1. Banned AI phrases
    banned = scan_banned_phrases(text)
    if banned:
        results["violations"]["banned_phrases"] = {
            "count": len(banned),
            "details": banned,
        }

    # 2. Transition patterns (首先其次最后)
    transitions, flagged, tcount = scan_transitions(text)
    if flagged:
        results["violations"]["ai_transitions"] = {
            "count": tcount,
            "details": transitions,
        }

    # 3. Emojis
    emojis = scan_emojis(text)
    if emojis:
        results["violations"]["emojis"] = {
            "count": len(emojis),
            "details": emojis,
        }

    # 4. Blank fields without annotation
    blanks = scan_blank_fields(text)
    if blanks:
        results["violations"]["blank_fields"] = {
            "count": len(blanks),
            "note": "空白字段未批注",
        }

    # 5. File naming
    naming = scan_file_naming(doc_path)
    if not naming["has_date_prefix"]:
        results["violations"]["file_naming"] = naming

    # Calculate compliance score
    total_violations = sum(
        v.get("count", 1) if isinstance(v, dict) else 1
        for v in results["violations"].values()
    )
    results["total_violations"] = total_violations
    results["compliance_score"] = max(0, 100 - total_violations * 10)
    results["verdict"] = "PASS" if results["compliance_score"] >= 70 else "FAIL"

    # Log violations for flywheel pattern detection
    log_violations(doc_path, results)

    return results


# ── Violation Log (Flywheel 3: violation→pattern→rule) ──────────────

VIOLATIONS_LOG = HARNESS_DIR / "violations.jsonl"


def log_violations(doc_path, results):
    """Append violation details to JSONL log for pattern detection."""
    violations = results.get("violations", {})
    if not violations:
        return

    entry = {
        "file": os.path.basename(doc_path),
        "timestamp": datetime.now().isoformat(),
        "total_violations": results.get("total_violations", 0),
        "violations": violations,
    }

    VIOLATIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(VIOLATIONS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_violations():
    """Load all violation records."""
    if not VIOLATIONS_LOG.exists():
        return []
    records = []
    with open(VIOLATIONS_LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def violation_report():
    """Cluster violations and suggest new AGENTS.md rules."""
    records = load_violations()
    if not records:
        return {"total_runs": 0, "patterns": [], "suggestions": []}

    # Cluster by phrase type
    phrase_counts = defaultdict(lambda: {"count": 0, "runs": 0, "files": set()})
    for rec in records:
        banned = rec["violations"].get("banned_phrases", {})
        for detail in banned.get("details", []):
            phrase = detail["phrase"]
            phrase_counts[phrase]["count"] += 1
            phrase_counts[phrase]["files"].add(rec["file"])

        transitions = rec["violations"].get("ai_transitions", {})
        if transitions.get("count", 0) >= 2:
            phrase_counts["AI过渡词(首先其次最后等)"]["count"] += transitions["count"]
            phrase_counts["AI过渡词(首先其次最后等)"]["files"].add(rec["file"])

    # Detect patterns (same phrase in 3+ different files)
    patterns = []
    suggestions = []
    for phrase, info in sorted(phrase_counts.items(), key=lambda x: x[1]["count"], reverse=True):
        if len(info["files"]) >= 3:
            patterns.append({
                "phrase": phrase,
                "total_occurrences": info["count"],
                "unique_files": len(info["files"]),
                "files": sorted(info["files"]),
            })
            suggestions.append(
                f"违规 '{phrase}' 在 {len(info['files'])} 个文档中出现 {info['count']} 次，"
                f"建议在 AGENTS.md §9 或 agents-checklist 中强化检测规则"
            )

    return {
        "total_runs": len(records),
        "total_violations": sum(r.get("total_violations", 0) for r in records),
        "patterns": patterns,
        "suggestions": suggestions,
    }


# ── AGENTS.md Auto-Append ────────────────────────────────────────────

# ── Hash Lock ────────────────────────────────────────────────────────

def hash_file(path):
    """SHA256 hash of a file (first 16 chars)."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def record_hash_lock(agents_path):
    """Record the current AGENTS.md hash."""
    h = hash_file(agents_path)
    lock_path = HARNESS_DIR / "agents-hash.txt"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as f:
        f.write(f"{h} {datetime.now().isoformat()}\n")
    return h


def verify_hash_lock(agents_path):
    """Verify AGENTS.md hash matches last recorded."""
    lock_path = HARNESS_DIR / "agents-hash.txt"
    if not lock_path.exists():
        return {"status": "no_lock", "note": "hash lock not initialized"}

    with open(lock_path, encoding="utf-8") as f:
        parts = f.read().strip().split()
        last_hash = parts[0] if parts else ""
        last_ts = parts[1] if len(parts) > 1 else ""

    current_hash = hash_file(agents_path)
    valid = current_hash == last_hash

    return {
        "status": "valid" if valid else "TAMPERED",
        "current_hash": current_hash,
        "last_known_hash": last_hash,
        "last_known_ts": last_ts,
    }


def find_agents_md():
    """Find AGENTS.md in known locations."""
    candidates = [
        Path.home() / "workspace" / "AGENTS.md",
        Path.home() / ".." / "承办人" / "本机目录" / "AGENTS.md",
        Path("[本地路径]"),
        HARNESS_DIR.parent / "workspace" / "AGENTS.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def get_next_section_number(agents_path):
    """Find the highest section number and return next."""
    with open(agents_path, encoding="utf-8") as f:
        content = f.read()
    numbers = re.findall(r"^## (\d+)\.", content, re.MULTILINE)
    if numbers:
        return max(int(n) for n in numbers) + 1
    return 15


def get_section_boundary(agents_path, section_num):
    """Find the line number where a section ends (next ## header or EOF)."""
    with open(agents_path, encoding="utf-8") as f:
        lines = f.readlines()

    # Find the last section's end
    in_target = False
    for i, line in enumerate(lines):
        if line.startswith(f"## {section_num}."):
            in_target = True
        elif in_target and line.startswith("## ") and not line.startswith("### "):
            return i  # Insert before next section
    return len(lines)  # End of file


def append_rule(agents_path, section, rule_text, trigger_event="", date=None):
    """Append a new rule to AGENTS.md.

    Args:
        agents_path: Path to AGENTS.md
        section: Section name (e.g. "合同审查") or section number to append to
        rule_text: The rule content (one or more bullet points)
        trigger_event: What triggered this rule (for annotation)
        date: Date string (default: today)
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    with open(agents_path, encoding="utf-8") as f:
        content = f.read()
        lines = content.split("\n")

    # Try to find the section by name
    section_pattern = ""
    new_lines = []

    if section.isdigit():
        section_num = int(section)
        section_pattern = f"## {section_num}."
        insert_after = get_section_boundary(agents_path, section_num)
    else:
        # Search for section by name
        found = False
        for i, line in enumerate(lines):
            if section in line and line.startswith("## "):
                found = True
                # Find end of this section (next ## or EOF)
                j = i + 1
                while j < len(lines) and not (lines[j].startswith("## ") and not lines[j].startswith("### ")):
                    j += 1
                insert_after = j
                break
        if not found:
            # Create new section at end
            insert_after = len(lines)
            next_num = get_next_section_number(agents_path)
            new_lines.append(f"## {next_num}. {section}（{date} 新增")
            if trigger_event:
                new_lines.append(f"> 触发：{trigger_event}")
            new_lines.append("")

    # Build the rule entry
    annotation = ""
    if trigger_event and section.isdigit():
        annotation = f"（{date} 新增 — 触发：{trigger_event}）"
    elif trigger_event:
        annotation = ""  # already in header

    if annotation:
        new_lines.append(f"> {annotation}")

    # Add rule content
    for rule_line in rule_text.strip().split("\n"):
        new_lines.append(rule_line)

    new_lines.append("")

    # Insert
    result_lines = lines[:insert_after] + new_lines + lines[insert_after:]
    new_content = "\n".join(result_lines)

    # Write back
    with open(agents_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    # Also sync to 本机目录 if possible
    sync_path = None
    for candidate in [
        Path("[本地路径]"),
        Path.home() / ".." / "承办人" / "本机目录" / "AGENTS.md",
    ]:
        if candidate.parent.exists():
            sync_path = candidate
            break

    if sync_path:
        with open(sync_path, "w", encoding="utf-8") as f:
            f.write(new_content)

    # Record hash lock
    record_hash_lock(agents_path)

    return {
        "ok": True,
        "appended_to": str(agents_path),
        "synced_to": str(sync_path) if sync_path else None,
        "lines_added": len(new_lines),
        "hash": hash_file(agents_path),
    }


def cmd_append_rule(args):
    """CLI handler for --append-rule."""
    agents_path = find_agents_md()
    if not agents_path:
        print(json.dumps({"error": "AGENTS.md not found"}, ensure_ascii=False))
        return

    rule_text = args.rule
    if not rule_text or rule_text == "__stdin__":
        # Read from stdin
        rule_text = sys.stdin.read().strip()

    if not rule_text:
        print(json.dumps({"error": "No rule text provided"}, ensure_ascii=False))
        return

    result = append_rule(
        agents_path,
        args.section or "15",
        rule_text,
        args.trigger or "",
        args.date,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="AGENTS.md compliance auditor")
    parser.add_argument("--doc", help="Path to .docx to audit")
    parser.add_argument("--text", help="Raw text to scan")
    parser.add_argument("--checklist", action="store_true", help="Print compliance checklist")

    # ── Auto-append rule ──
    parser.add_argument("--append-rule", dest="rule", nargs="?", const="__stdin__", default=None,
                        help="Rule text to append (or pipe from stdin)")
    parser.add_argument("--section", default=None,
                        help="Section name or number to append to (e.g. '合同审查' or '12')")
    parser.add_argument("--trigger", default=None,
                        help="What triggered this rule (for annotation)")
    parser.add_argument("--date", default=None,
                        help="Date (YYYY-MM-DD, default: today)")

    # ── Hash lock ──
    parser.add_argument("--verify-hash", action="store_true", help="Verify AGENTS.md hash integrity")
    parser.add_argument("--record-hash", action="store_true", help="Record current AGENTS.md hash")
    parser.add_argument("--violations-report", action="store_true", help="Cluster violations and suggest new rules")

    args = parser.parse_args()

    if args.checklist:
        checklist_path = HARNESS_DIR / "agents-checklist.md"
        if checklist_path.exists():
            with open(checklist_path, encoding="utf-8") as f:
                print(f.read())
        else:
            print("Checklist not found:", checklist_path)
        return

    if args.doc:
        results = audit_document(args.doc)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.text:
        banned = scan_banned_phrases(args.text)
        emojis = scan_emojis(args.text)
        print(json.dumps({
            "banned_phrases": len(banned),
            "emojis": len(emojis),
            "banned_details": banned,
            "emoji_details": emojis,
        }, ensure_ascii=False, indent=2))
    elif args.rule is not None:
        cmd_append_rule(args)
    elif args.verify_hash:
        agents_path = find_agents_md()
        if agents_path:
            result = verify_hash_lock(agents_path)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"error": "AGENTS.md not found"}, ensure_ascii=False))
    elif args.record_hash:
        agents_path = find_agents_md()
        if agents_path:
            h = record_hash_lock(agents_path)
            print(json.dumps({"ok": True, "hash": h}, ensure_ascii=False))
        else:
            print(json.dumps({"error": "AGENTS.md not found"}, ensure_ascii=False))
    elif args.violations_report:
        result = violation_report()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
