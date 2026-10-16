# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""PaddleOCR-VL 通道（AI Studio 云端）：处理法官培训教材书 10-19
与 mineru 通道（书 0-9）双通道并行。断点续传：txt 存在且 >500B 则 SKIP。
用法: python _ocr_paddle.py [start_idx] [end_idx]
"""
import os, sys, asyncio, glob, time, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# uv cache 的 paddleocr_mcp 环境（自带 SDK 依赖）
UVPY = r"[本地路径]"
PKG = r"[本地路径]"

sys.path.insert(0, PKG)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from paddleocr_mcp.inference.paddleocr_vl.aistudio import PaddleOCRVLAIStudioInference

SRC_BASE = r"[本地路径]）"
OUT_BASE = r"[本地路径]"
TOKEN = "【密钥已移除】"
MODEL = "PaddleOCR-VL-1.6"

BOOKS = [
    ("minshang-1", "民商事审判实务4第1册.pdf"), ("minshang-2", "民商事审判实务4第2册.pdf"),
    ("minshang-3", "民商事审判实务4第3册.pdf"), ("minshang-4", "民商事审判实务4第4册.pdf"),
    ("minshang-5", "民商事审判实务4第5册.pdf"), ("minshang-6", "民商事审判实务4第6册.pdf"),
    ("xingshi-1", "刑事审判实务上册3.pdf"), ("xingshi-2", "刑事审判实务下册3.pdf"),
    ("zhixing", "执行案件办理实务11.pdf"), ("xingzheng", "行政审判实务8.pdf"),
    ("zhishi-chanquan", "知识产权审判实务5.pdf"), ("huanzi", "环境资源审判实务7.pdf"),
    ("shenpan-jiandu-1", "审判监督实务上册9.pdf"), ("shenpan-jiandu-2", "审判监督实务下册9.pdf"),
    ("shewai", "涉外商事海事审判实务和国际司法协助.pdf"), ("shegangao", "涉港澳民商事审判实务和区际司法协助14.pdf"),
    ("lian-kejian", "立案工作实务2.pdf"), ("guojia-peichang", "国家赔偿审判实务10.pdf"),
    ("weichengnianren", "未成年人审判实务13.pdf"), ("shenpan-guanli", "审判管理实务12.pdf"),
]

async def ocr_one(infer, fn, out_txt):
    """单份 PDF → 文本（3 次重试）"""
    for attempt in range(4):
        try:
            from paddleocr_mcp.inference.types import InferenceRequest
            req = InferenceRequest(input_data=fn, file_type="pdf")
            result = await infer.predict(req)
            text = str(getattr(result, "markdown", "") or "")
            if text and len(text.strip()) > 100:
                open(out_txt, "w", encoding="utf-8").write(text)
                return True, len(text)
            print(f"    短输出 a{attempt+1} ({len(text)}字) {os.path.basename(fn)}")
        except Exception as e:
            msg = str(e)
            if "队列已满" in msg or "queue" in msg.lower():
                print(f"    队列满 a{attempt+1}，等 60s {os.path.basename(fn)}")
                await asyncio.sleep(60)
                continue
            print(f"    ERR a{attempt+1}: {msg[:100]} {os.path.basename(fn)}")
        await asyncio.sleep(10)
    return False, 0

async def process_book(infer, slug, fname, parts_dir, out_dir):
    src = os.path.join(SRC_BASE, fname)
    os.makedirs(parts_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    # 拆页（复用 mineru 逻辑；若 mineru 已拆则直接复用）
    part_files = sorted(glob.glob(os.path.join(parts_dir, "part_*.pdf")))
    if not part_files:
        doc = fitz.open(src)
        total = doc.page_count
        chunks, cur, cur_size = [], [], 0
        for i in range(total):
            cur.append(i)
            cur_size += len(doc[i].get_contents() or b"") + 1000
            if len(cur) >= 30 or cur_size > 4_500_000:
                chunks.append(cur); cur, cur_size = [], 0
        if cur:
            chunks.append(cur)
        doc.close()
        for ci, pages in enumerate(chunks):
            fn = os.path.join(parts_dir, f"part_{ci:02d}.pdf")
            if os.path.exists(fn) and os.path.getsize(fn) > 1000:
                part_files.append(fn); continue
            d = fitz.open(); s = fitz.open(src)
            for p in pages:
                d.insert_pdf(s, from_page=p, to_page=p)
            s.close(); d.save(fn); d.close()
            part_files.append(fn)
    print(f"[{slug}] {fname}: {len(part_files)} 份")

    # 待处理清单
    todo = []
    for fn in sorted(part_files):
        name = os.path.basename(fn).replace(".pdf", "")
        out_txt = os.path.join(out_dir, f"{name}.txt")
        if os.path.exists(out_txt) and os.path.getsize(out_txt) > 500:
            continue
        todo.append((fn, out_txt))
    if not todo:
        print(f"[{slug}] 全部已完成")
        return
    # 2 并发（避免撞 AI Studio 队列上限）
    sem = asyncio.Semaphore(2)
    async def worker(fn, out_txt):
        async with sem:
            return await ocr_one(infer, fn, out_txt)
    results = await asyncio.gather(*[worker(fn, ot) for fn, ot in todo])
    ok = sum(1 for r, _ in results if r)
    fail = len(todo) - ok
    print(f"[{slug}] OK {ok} / FAIL {fail}")

async def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    infer = PaddleOCRVLAIStudioInference(token=TOKEN, model=MODEL, request_timeout=180, poll_timeout=600)
    await infer.start()
    try:
        for slug, fname in BOOKS[start:end]:
            base = os.path.join(OUT_BASE, slug)
            await process_book(infer, slug, fname, os.path.join(base, "pdf_parts"), os.path.join(base, "raw_ocr_paddle"))
    finally:
        await infer.stop()
    print("=== PADDLE 通道完成 ===")

if __name__ == "__main__":
    asyncio.run(main())
