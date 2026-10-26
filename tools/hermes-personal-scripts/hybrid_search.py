#!/usr/bin/env python
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
Hybrid Search v2: BM25 (rank_bm25 + jieba) + Vector (ChromaDB/bge-m3) + RRF 融合
参考文献:
  - BM25+jieba: https://blog.csdn.net/weixin_37763484/article/details/148516958
  - RRF深度解析: https://www.smallyoung.cn/docs/028-RAG混合检索与RRF算法深度解析
  - 端到端教程: https://cloud.tencent.com/developer/article/2654879
用法: python hybrid_search.py "查询文本" [--top-k 10] [--rebuild]
"""
import sys, os, pickle
import jieba
import chromadb
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
from rank_bm25 import BM25Okapi

# === 配置 ===
CHROMA_PATH = os.path.expanduser("[本地路径]")
COLLECTION_NAME = "legal_knowledge"
BM25_PICKLE = os.path.expanduser("[本地路径]")
OLLAMA_MODEL = "bge-m3:latest"
RRF_K = 60
CHUNK_SIZE = 800   # 文档分块大小（字符）
CHUNK_OVERLAP = 100  # 块间重叠

# === 法律词典 ===
LEGAL_DICT = []  # 名单类数据（主体/当事人/律所/本机标识/地域）在本机维护，不入公开版
for t in LEGAL_DICT:
    jieba.add_word(t)


def tokenize(text: str) -> list[str]:
    """jieba 分词，用于 BM25 索引和查询"""
    return list(jieba.cut_for_search(text))


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
              ) -> list[str]:
    """将长文本切分为重叠块，提升检索粒度"""
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        # 尽量在句号/换行处断开
        if end < len(text):
            for sep in ["\n\n", "\n", "。", "；", "，", " "]:
                pos = text.rfind(sep, start + size // 2, end)
                if pos > 0:
                    end = pos + 1
                    break
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


class HybridSearch:
    def __init__(self):
        # Vector
        self.ef = OllamaEmbeddingFunction(
            model_name=OLLAMA_MODEL,
            url="http://本地端口/api/embeddings"
        )
        self.client = chromadb.PersistentClient(path=CHROMA_PATH)
        self._ensure_collection()
        # BM25 state
        self.bm25: BM25Okapi | None = None
        self.documents: list[dict] = []  # [{"id","content","metadata"},...]
        self.bm25_corpus: list[list[str]] = []
        self._load_bm25_index()

    def _ensure_collection(self):
        try:
            self.collection = self.client.get_collection(
                COLLECTION_NAME, embedding_function=self.ef
            )
        except Exception:
            self.collection = self.client.create_collection(
                COLLECTION_NAME, embedding_function=self.ef
            )

    # ========== BM25 (rank_bm25 + jieba) ==========
    def _load_bm25_index(self):
        """从 pickle 加载 BM25 索引，无则从 ChromaDB 重建"""
        if os.path.exists(BM25_PICKLE):
            try:
                with open(BM25_PICKLE, "rb") as f:
                    saved = pickle.load(f)
                self.documents = saved["documents"]
                self.bm25_corpus = saved["corpus"]
                self.bm25 = BM25Okapi(self.bm25_corpus)
                print(f"[BM25] loaded {len(self.documents)} docs from pickle",
                      file=sys.stderr)
                return
            except Exception as e:
                print(f"[BM25] pickle load failed: {e}, rebuilding...",
                      file=sys.stderr)
        self._rebuild_bm25_from_chroma()

    def _rebuild_bm25_from_chroma(self):
        """从 ChromaDB 重建 BM25 索引"""
        try:
            all_data = self.collection.get(
                include=["documents", "metadatas"]
            )
            ids = all_data.get("ids", [])
            docs = all_data.get("documents", [])
            metas = all_data.get("metadatas", [])
            if not ids:
                return

            self.documents = []
            self.bm25_corpus = []
            for i in range(len(ids)):
                self.documents.append({
                    "id": ids[i],
                    "content": docs[i] or "",
                    "metadata": metas[i] or {},
                })
                self.bm25_corpus.append(tokenize(docs[i] or ""))

            self.bm25 = BM25Okapi(self.bm25_corpus)
            self._save_bm25_pickle()
            print(f"[BM25] indexed {len(self.documents)} docs + saved pickle",
                  file=sys.stderr)
        except Exception as e:
            print(f"[BM25 rebuild error] {e}", file=sys.stderr)

    def _save_bm25_pickle(self):
        """持久化 BM25 索引到磁盘"""
        try:
            os.makedirs(os.path.dirname(BM25_PICKLE), exist_ok=True)
            with open(BM25_PICKLE, "wb") as f:
                pickle.dump({
                    "documents": self.documents,
                    "corpus": self.bm25_corpus,
                }, f)
        except Exception as e:
            print(f"[BM25] pickle save failed: {e}", file=sys.stderr)

    def bm25_search(self, query: str, limit: int = 10) -> list[dict]:
        if not self.bm25 or not self.documents:
            return []
        tokens = tokenize(query)
        scores = self.bm25.get_scores(tokens)
        # 取 top-k
        indexed = [(scores[i], i) for i in range(len(scores)) if scores[i] > 0]
        indexed.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, idx in indexed[:limit]:
            doc = self.documents[idx]
            results.append({
                "source": "bm25",
                "score": round(score, 4),
                "content": (doc["content"] or "")[:500],
                "path": (doc["metadata"] or {}).get("path", doc["id"]),
                "title": (doc["metadata"] or {}).get("title", doc["id"]),
            })
        return results

    # ========== Vector (ChromaDB + bge-m3) ==========
    def vector_search(self, query: str, limit: int = 10) -> list[dict]:
        try:
            results = self.collection.query(query_texts=[query], n_results=limit)
            items = []
            ids = results.get("ids", [[]])[0]
            distances = results.get("distances", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            documents = results.get("documents", [[]])[0]
            for i in range(len(ids)):
                sim = 1.0 - distances[i] if distances[i] <= 2.0 else 0
                items.append({
                    "source": "vector",
                    "score": round(max(0, sim), 4),
                    "content": (documents[i] or "")[:500],
                    "path": (metadatas[i] or {}).get("path", ids[i]),
                    "title": (metadatas[i] or {}).get("title", ids[i]),
                })
            return items
        except Exception as e:
            print(f"[Vector error] {e}", file=sys.stderr)
            return []

    # ========== RRF 融合 ==========
    def rrf_fuse(self, bm25: list[dict], vector: list[dict], top_k: int = 10
                 ) -> list[dict]:
        scores: dict[str, float] = {}
        details: dict[str, dict] = {}
        for rank, item in enumerate(bm25):
            key = item["path"] or item["title"]
            scores[key] = scores.get(key, 0) + 1.0 / (RRF_K + rank + 1)
            details[key] = item
        for rank, item in enumerate(vector):
            key = item["path"] or item["title"]
            scores[key] = scores.get(key, 0) + 1.0 / (RRF_K + rank + 1)
            if key not in details:
                details[key] = item
            else:
                details[key]["source"] = "hybrid"

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [
            {"key": k, "rrf_score": round(v, 4), **details[k]}
            for k, v in ranked
        ]

    # ========== 统一检索入口 ==========
    def search(self, query: str, top_k: int = 10) -> dict:
        # 每路召回 3x 候选，给 RRF 更大的融合池（参考 RRF 论文最佳实践）
        fetch_n = top_k * 3
        bm25 = self.bm25_search(query, limit=fetch_n)
        vector = self.vector_search(query, limit=fetch_n)
        fused = self.rrf_fuse(bm25, vector, top_k)
        return {
            "query": query,
            "bm25_count": len(bm25),
            "vector_count": len(vector),
            "fused_count": len(fused),
            "results": fused,
        }

    # ========== 索引管理 ==========
    def index_documents(self, documents: list[dict]):
        """批量索引文档到 ChromaDB + BM25
        documents: [{"id":str, "content":str, "metadata":dict}, ...]
        """
        if not documents:
            return
        # ChromaDB
        ids = [d["id"] for d in documents]
        contents = [d["content"] for d in documents]
        metadatas = [d.get("metadata", {}) for d in documents]
        self.collection.add(documents=contents, metadatas=metadatas, ids=ids)
        # BM25
        self.rebuild_bm25()
        print(f"[index] {len(documents)} docs added", file=sys.stderr)

    def rebuild_bm25(self):
        """强制从 ChromaDB 重建 BM25 索引并持久化"""
        self._rebuild_bm25_from_chroma()

    def rebuild_all(self):
        """清空 ChromaDB 并从 ByteRover context-tree 重建"""
        try:
            self.client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        self.collection = self.client.create_collection(
            COLLECTION_NAME, embedding_function=self.ef
        )
        self._sync_from_brv()
        self._load_bm25_index()

    def _sync_from_brv(self):
        """从 ByteRover context-tree 同步到 ChromaDB（含分块）"""
        ct = os.path.join(os.getcwd(), ".brv", "context-tree")
        if not os.path.isdir(ct):
            print(f"[sync] context-tree not found", file=sys.stderr)
            return
        docs = []
        for root, _, files in os.walk(ct):
            for f in files:
                if not f.endswith(".md") or f.startswith("_"):
                    continue
                if f.endswith(".abstract.md") or f.endswith(".overview.md"):
                    continue
                path = os.path.join(root, f)
                rel = os.path.relpath(path, ct)
                try:
                    content = open(path, encoding="utf-8").read()
                except Exception:
                    continue
                title = rel.replace(".md", "").replace("/", " > ").replace("\\", " > ")
                # 长文档分块
                chunks = chunk_text(content)
                for ci, chunk in enumerate(chunks):
                    chunk_id = f"{rel}#{ci}" if len(chunks) > 1 else rel
                    chunk_title = f"{title} [{ci+1}/{len(chunks)}]" if len(chunks) > 1 else title
                    docs.append({
                        "id": chunk_id.replace("\\", "/"),
                        "content": chunk,
                        "metadata": {"path": rel, "title": chunk_title, "source": "brv",
                                     "chunk_index": ci, "total_chunks": len(chunks)},
                    })
        if docs:
            self.collection.add(
                documents=[d["content"] for d in docs],
                metadatas=[d["metadata"] for d in docs],
                ids=[d["id"] for d in docs],
            )
        print(f"[sync] {len(docs)} chunks from ByteRover CT", file=sys.stderr)


# ========== CLI ==========
if __name__ == "__main__":
    hs = HybridSearch()

    if len(sys.argv) < 2:
        print("Usage: python hybrid_search.py <query> [--top-k N] [--rebuild]")
        sys.exit(1)

    if sys.argv[1] == "--rebuild":
        hs.rebuild_all()
        sys.exit(0)

    query = sys.argv[1]
    top_k = 10
    if "--top-k" in sys.argv:
        idx = sys.argv.index("--top-k")
        top_k = int(sys.argv[idx + 1])

    result = hs.search(query, top_k=top_k)

    print(f"\n查询: {result['query']}")
    print(f"BM25(rank_bm25+jieba): {result['bm25_count']} | "
          f"Vector(bge-m3): {result['vector_count']} | "
          f"Fused(RRF): {result['fused_count']}")
    print("-" * 60)
    for i, r in enumerate(result["results"]):
        src = {"bm25": "🔤", "vector": "🧠", "hybrid": "🔀"}.get(r["source"], "?")
        score = r.get("rrf_score") or r.get("score", 0)
        print(f"{i+1}. {src} [{score}] {r['title']}")
        print(f"   {r['content'][:150]}")
        print()
