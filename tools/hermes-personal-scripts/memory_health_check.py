# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
Memory Health Check v4 — 严格按照 hermes-memory 三层记忆架构
架构: Built-in MEMORY.md ($分隔) + L2 ByteRover/ChromaDB + L3 state.db
参考: hermes-memory/references/three-layer-memory-v2.md
       hermes-memory/references/importance-levels.md
       hermes-memory/references/memory-slimming-workflow.md
"""
import os, json, datetime, glob, hashlib, sys

# Force unbuffered output for cron subprocess
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

MEMORY_LIMIT = 6000      # Built-in MEMORY.md char limit（2026-08-04 桌面端配额 4000→6000）
WARN_PCT = 75            # >75% warning
CRIT_PCT = 85            # >85% critical (new entries may be blocked at >90%)
TARGET_PCT = 60          # 瘦身目标 (per importance-levels.md)
TARGET_ENTRIES = 8       # 瘦身目标条目数 (per memory-slimming-workflow.md)

# === 路径 ===
local_appdata = os.path.expandvars(r"%LOCALAPPDATA%")
hermes_sync = None  # 2026-08-03: 取消第三方同步盘同步，无同步目录
mem_dir = os.path.join(local_appdata, "hermes", "memories")
os.makedirs(mem_dir, exist_ok=True)

now = datetime.datetime.now().isoformat(timespec="seconds")

try:
    status = {"checked_at": now, "healthy": True, "alerts": []}

    # ═══════════════════════════════════════
    #  Built-in MEMORY.md ($分隔条目分析)
    # ═══════════════════════════════════════
    def analyze_memory_md():
        mem_path = os.path.join(mem_dir, "MEMORY.md")
        if not os.path.exists(mem_path):
            return {"chars": 0, "entries": 0, "pct": 0.0, "sections": [], "exists": False}

        with open(mem_path, encoding="utf-8") as f:
            text = f.read()

        # Split by §, count per section
        raw_sections = text.split("§")
        sections = []
        total_chars = 0
        for i, s in enumerate(raw_sections):
            s = s.strip()
            if not s or len(s) < 10:
                continue
            # Extract first 80 chars as preview
            preview = s[:80].replace("\n", " ").strip()
            sections.append({"idx": i + 1, "chars": len(s), "preview": preview})
            total_chars += len(s)

        pct = round(total_chars / MEMORY_LIMIT * 100, 1)
        return {
            "chars": total_chars,
            "entries": len(sections),
            "pct": pct,
            "sections": sections,
            "exists": True,
            "file_bytes": os.path.getsize(mem_path),
        }

    builtin = analyze_memory_md()
    status["builtin"] = builtin

    # 告警判断 (per importance-levels.md thresholds)
    if builtin["pct"] > CRIT_PCT:
        status["alerts"].append(
            f"CRITICAL: Built-in memory {builtin['pct']}% ({builtin['chars']}/{MEMORY_LIMIT} chars, {builtin['entries']} entries). "
            f"Target: ≤{TARGET_PCT}%, ≤{TARGET_ENTRIES} entries. 需执行 memory-cleanup 瘦身流程 (diagnose→migrate→compress→verify)."
        )
        status["healthy"] = False
    elif builtin["pct"] > WARN_PCT:
        status["alerts"].append(
            f"WARNING: Built-in memory {builtin['pct']}% ({builtin['chars']}/{MEMORY_LIMIT} chars, {builtin['entries']} entries). "
            f"超过 {WARN_PCT}% 警戒线，建议近期瘦身."
        )
    elif builtin["entries"] > TARGET_ENTRIES:
        status["alerts"].append(
            f"INFO: {builtin['entries']} entries (target ≤{TARGET_ENTRIES}), "
            f"可合并冗余条目减少 token 消耗."
        )

    # ═══════════════════════════════════════
    #  L2: ByteRover Context Tree + ChromaDB
    # ═══════════════════════════════════════
    l2 = {}
    # ByteRover CT
    brv_ct = "[本地路径]"
    manifest_path = os.path.join(brv_ct, "_manifest.json")
    brv_ok = os.path.isdir(brv_ct)
    l2["byterover_ct"] = brv_ok
    if brv_ok:
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest = json.load(f)
                l2["brv_active_context"] = len(manifest.get("active_context", []))
                l2["brv_total_tokens"] = manifest.get("total_tokens", "?")
                l2["brv_files"] = sum(1 for _ in glob.glob(os.path.join(brv_ct, "*.md")))
                if l2["brv_active_context"] == 0:
                    status["alerts"].append("WARNING: ByteRover active_context 为空 — dream 未执行或 review 未通过")
            except:
                l2["brv_active_context"] = "parse_error"
        else:
            l2["brv_active_context"] = "no_manifest"
    else:
        status["alerts"].append("WARNING: ByteRover Context Tree 不存在 ([本地路径])")
        status["healthy"] = False

    # ChromaDB
    chroma_dir = os.path.expanduser("[本地路径]")
    l2["chromadb"] = os.path.isdir(chroma_dir)
    if not l2["chromadb"]:
        status["alerts"].append("WARNING: ChromaDB 目录缺失 (chroma_legal)")
        status["healthy"] = False

    # BM25 index
    bm25_path = os.path.join(chroma_dir, "bm25_index.pkl")
    l2["bm25_pickle"] = os.path.exists(bm25_path)
    if not l2["bm25_pickle"]:
        status["alerts"].append("WARNING: BM25 pickle 索引缺失 (chroma_legal/bm25_index.pkl)")

    status["l2_knowledge"] = l2

    # ═══════════════════════════════════════
    #  L3: state.db (FTS5 session_search)
    # ═══════════════════════════════════════
    state_db = os.path.join(local_appdata, "hermes", "state.db")
    l3 = {}
    l3["state_db_exists"] = os.path.exists(state_db)
    if l3["state_db_exists"]:
        l3["state_db_mb"] = round(os.path.getsize(state_db) / (1024 * 1024), 1)
        # Check WAL
        wal = state_db + "-wal"
        if os.path.exists(wal):
            wal_size = os.path.getsize(wal)
            l3["wal_bytes"] = wal_size
            if wal_size > 10 * 1024 * 1024:  # >10MB WAL
                status["alerts"].append(f"WARNING: state.db WAL 文件过大 ({wal_size//1024//1024}MB)，建议执行 checkpoint")
        else:
            l3["wal_bytes"] = 0
    else:
        status["alerts"].append("CRITICAL: state.db 不存在 — 会话记录丢失")
        status["healthy"] = False
    status["l3_context"] = l3

    # ═══════════════════════════════════════
    #  L1: AGENTS.md (规则源)
    # ═══════════════════════════════════════
    agents_local = os.path.join(os.path.expanduser("~"), ".hermes", "AGENTS.md")
    l1 = {}
    # 2026-08-03: 取消第三方同步盘同步，无双副本，仅单侧存在性检查
    l1["agents_local"] = os.path.exists(agents_local)
    l1["agents_sync"] = False
    l1["hash_match"] = "n/a"
    if not l1["agents_local"]:
        status["alerts"].append("CRITICAL: AGENTS.md 本地副本不存在")
        status["healthy"] = False
    status["l1_constitution"] = l1

except Exception as e:
    status = {
        "checked_at": now,
        "healthy": False,
        "alerts": [f"CRITICAL: 健康检查脚本异常 — {type(e).__name__}: {e}"],
        "error": str(e),
    }

# ═══════════════════════════════════════
#  Write output
# ═══════════════════════════════════════
# Status JSON
status_path = os.path.join(mem_dir, ".health_status.json")
with open(status_path, "w", encoding="utf-8") as f:
    json.dump(status, f, ensure_ascii=False, indent=2)

# Alert file
alert_path = os.path.join(mem_dir, ".ALERT")
if status["alerts"]:
    with open(alert_path, "w", encoding="utf-8") as f:
        f.write("\n".join(status["alerts"]))
else:
    if os.path.exists(alert_path):
        os.remove(alert_path)

# Terminal output
print(f"[{now}]")
builtin = status.get("builtin", {"pct": "?", "chars": "?", "entries": "?"})
if builtin:
    print(f"Built-in: {builtin.get('pct','?')}% ({builtin.get('chars','?')}/{MEMORY_LIMIT}c, {builtin.get('entries','?')} entries)")
    if builtin.get("entries", 0) > 0 and builtin.get("entries", 0) <= 10:
        for s in builtin.get("sections", []):
            print(f"  §{s['idx']}: {len(s['preview'])}c \"{s['preview']}\"")

l2 = status.get("l2_knowledge", {})
print(f"L2: CT={'OK' if l2.get('byterover_ct') else 'MISSING'} Chroma={'OK' if l2.get('chromadb') else 'MISSING'} BM25={'OK' if l2.get('bm25_pickle') else 'MISSING'}")

l3 = status.get("l3_context", {})
print(f"L3: state.db={'OK' if l3.get('state_db_exists') else 'MISSING'} WAL={l3.get('wal_bytes',0)}B")

l1 = status.get("l1_constitution", {})
print(f"L1: AGENTS.md local={'OK' if l1.get('agents_local') else 'MISSING'} sync={'OK' if l1.get('agents_sync') else 'MISSING'}")

print(f"Status: {'HEALTHY' if status['healthy'] else '⚠️  ALERTS (' + str(len(status['alerts'])) + ')'}")
if status["alerts"]:
    for a in status["alerts"]:
        print(f"  - {a}")

sys.stdout.flush()
