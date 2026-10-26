# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
import os, pickle
import jieba
import chromadb
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
from rank_bm25 import BM25Okapi

for t in ['该律所','该律所','补充协议','违约金','诉讼时效','尽调','合同解除','违约责任','民法典','公司法','承办人']:
    jieba.add_word(t)

path = os.path.expanduser('[本地路径]')
ef = OllamaEmbeddingFunction(model_name='bge-m3:latest', url='http://本地端口/api/embeddings')
client = chromadb.PersistentClient(path=path)

try: client.delete_collection('legal_knowledge')
except: pass
col = client.create_collection('legal_knowledge', embedding_function=ef)

ct = '[本地路径]'
docs, ids, metas = [], [], []
for root, dirs, files in os.walk(ct):
    for f in files:
        if not f.endswith('.md') or f.startswith('_'):
            continue
        if f.endswith('.abstract.md') or f.endswith('.overview.md'):
            continue
        fpath = os.path.join(root, f)
        rel = os.path.relpath(fpath, ct)
        try:
            content = open(fpath, encoding='utf-8').read()
        except:
            continue
        title = rel.replace('.md', '').replace('/', ' > ')
        for ci in range(0, len(content), 800):
            chunk = content[ci:ci+800]
            cid = f"{rel}#{ci//800}" if len(content) > 800 else rel
            docs.append(chunk)
            ids.append(cid)
            metas.append({'path': rel, 'title': title, 'source': 'brv'})

print(f'Adding {len(docs)} chunks...')
col.add(documents=docs, metadatas=metas, ids=ids)

# Test
r = col.query(query_texts=['合同审查违约金'], n_results=3)
print(f'Vector test: {len(r["ids"][0])} results')
for i, (did, dist) in enumerate(zip(r['ids'][0], r['distances'][0])):
    print(f'  {i+1}. {did} dist={dist:.3f}')

# BM25 pickle
corpus = [list(jieba.cut_for_search(d)) for d in docs]
bm25 = BM25Okapi(corpus)
bdocs = [{'id': ids[i], 'content': docs[i], 'metadata': metas[i]} for i in range(len(ids))]
pickle_path = os.path.expanduser('[本地路径]')
with open(pickle_path, 'wb') as pf:
    pickle.dump({'documents': bdocs, 'corpus': corpus}, pf)
print(f'BM25 pickle: {len(bdocs)} docs')
print('Done!')
