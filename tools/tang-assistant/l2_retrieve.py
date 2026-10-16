#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
L2 记忆检索器 — CPU 缓存模式。
输入用户查询，返回语义最匹配的 L2 记忆片段。

用法:
    python l2_retrieve.py "用户消息" [--top-k 3] [--threshold 0.5]
    python l2_retrieve.py --update  # 从 MEMORY.md 重新同步 L2 条目
"""

import json, sys, os, requests
from pathlib import Path
import numpy as np

HERMES_HOME = Path.home() / ".hermes"
STORE_PATH = HERMES_HOME / "memory" / "l2_store.json"
OLLAMA_URL = "http://【本机端口】/api/embeddings"
MODEL = "nomic-embed-text"


def embed(text: str) -> list[float]:
    """Get embedding from Ollama"""
    resp = requests.post(OLLAMA_URL, json={"model": MODEL, "prompt": text}, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama error: {resp.status_code}")
    return resp.json()["embedding"]


def cosine(a, b):
    """Cosine similarity between two vectors"""
    a, b = np.array(a), np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def retrieve(query: str, top_k: int = 3, threshold: float = 0.5) -> list[dict]:
    """Retrieve top-K L2 facts matching the query"""
    if not STORE_PATH.exists():
        return []
    
    with open(STORE_PATH, 'r', encoding='utf-8') as f:
        store = json.load(f)
    
    if not store:
        return []
    
    q_emb = embed(query)
    
    results = []
    for fact in store:
        sim = cosine(q_emb, fact["embedding"])
        if sim >= threshold:
            results.append({
                "id": fact["id"],
                "content": fact["content"],
                "score": round(float(sim), 3),
                "access_count": fact.get("access_count", 0),
            })
    
    results.sort(key=lambda x: x["score"], reverse=True)
    
    # Update access counts
    for r in results[:top_k]:
        for fact in store:
            if fact["id"] == r["id"]:
                fact["access_count"] = fact.get("access_count", 0) + 1
    
    with open(STORE_PATH, 'w', encoding='utf-8') as f:
        json.dump(store, f, ensure_ascii=False)
    
    return results[:top_k]


def format_for_prompt(results: list[dict]) -> str:
    """Format retrieval results for system prompt injection"""
    if not results:
        return ""
    lines = ["[L2 记忆命中]"]
    for r in results:
        lines.append(f"- [{r['score']}] {r['content'][:200]}")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python l2_retrieve.py <query> [--top-k N] [--threshold T]")
        sys.exit(1)
    
    query = sys.argv[1]
    top_k = 3
    threshold = 0.5
    
    for i, arg in enumerate(sys.argv):
        if arg == "--top-k" and i+1 < len(sys.argv):
            top_k = int(sys.argv[i+1])
        if arg == "--threshold" and i+1 < len(sys.argv):
            threshold = float(sys.argv[i+1])
    
    results = retrieve(query, top_k=top_k, threshold=threshold)
    print(format_for_prompt(results))
