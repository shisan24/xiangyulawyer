# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Local L2 Memory MCP Server — wraps hybrid_search.py + direct ChromaDB access.
Replaces V3 ByteRover as the L2 Knowledge layer. All local, no cloud."""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hybrid_search import HybridSearch

hs = HybridSearch()

from mcp.server.fastmcp import FastMCP
mcp = FastMCP("l2-memory")

@mcp.tool()
def l2_query(query: str, top_k: int = 10) -> str:
    """Local hybrid search (BM25+jieba + ChromaDB/bge-m3 + RRF). Chinese-optimized."""
    result = hs.search(query, top_k=top_k)
    # Simplify output
    out = {"query": result["query"], "count": result["fused_count"], "results": []}
    for r in result["results"]:
        out["results"].append({
            "title": r.get("title", ""),
            "content": r.get("content", "")[:300],
            "score": r.get("rrf_score", 0),
            "source": r.get("source", ""),
            "path": r.get("path", ""),
        })
    return json.dumps(out, ensure_ascii=False, indent=2)

@mcp.tool()
def l2_curate(title: str, content: str, path: str = "", tags: str = "") -> str:
    """Save a fact/decision/knowledge to local L2 memory (ChromaDB + BM25)."""
    import time, uuid
    doc_id = path or f"curated/{uuid.uuid4().hex[:8]}"
    metadata = {"title": title, "source": "agent", "curated_at": time.strftime("%Y-%m-%d %H:%M")}
    if tags:
        metadata["tags"] = tags
    hs.index_documents([{"id": doc_id, "content": content, "metadata": metadata}])
    return json.dumps({"ok": True, "id": doc_id, "message": f"Curated: {title}"}, ensure_ascii=False)

@mcp.tool()
def l2_rebuild() -> str:
    """Rebuild BM25 index from ChromaDB. Run after bulk imports or if search seems stale."""
    hs.rebuild_bm25()
    return json.dumps({"ok": True, "message": "BM25 index rebuilt from ChromaDB"}, ensure_ascii=False)

@mcp.tool()
def l2_status() -> str:
    """Check L2 local memory status (ChromaDB collection count)."""
    try:
        count = hs.collection.count()
    except Exception:
        count = 0
    return json.dumps({"ok": True, "chromadb_path": hs.chroma_path, "doc_count": count}, ensure_ascii=False)

if __name__ == "__main__":
    mcp.run()
