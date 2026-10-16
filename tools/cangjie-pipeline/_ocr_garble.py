# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""M83/M84 乱码段补扫：PaddleOCR-VL AI Studio 批量 OCR（旋转已修正的 garble PDF）
断点续传：输出存在且 >500B 则 SKIP；并发 2；重试 4 次；队列满等待 60s"""
import os, sys, time, glob

PKG = r"[本地路径]"
sys.path.insert(0, PKG)

TOKEN = None
# 从 config.yaml 读 token
cfg = os.path.expandvars(r"%LOCALAPPDATA%\hermes\config.yaml")
if os.path.exists(cfg):
    for line in open(cfg, encoding="utf-8"):
        if "PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN" in line:
            TOKEN = line.split(":", 1)[1].strip().strip('"').strip("'")
            break
if not TOKEN:
    print("ERROR: 未找到 PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN")
    sys.exit(1)

from paddleocr_mcp.inference.paddleocr_vl.aistudio import PaddleOCRVLAIStudioInference
from paddleocr_mcp.inference.types import InferenceRequest

MODEL = "PaddleOCR-VL-1.6"
PROBE = r"[本地路径]"
OUT = r"[本地路径]"
os.makedirs(OUT, exist_ok=True)

async def run_one(infer, pdf_path, out_txt):
    if os.path.exists(out_txt) and os.path.getsize(out_txt) > 500:
        print(f"SKIP {os.path.basename(pdf_path)} (已有输出)")
        return True
    req = InferenceRequest(input_data=pdf_path, file_type="pdf")
    for attempt in range(4):
        try:
            res = await infer.predict(req)
            txt = res.markdown or ""
            if len(txt) > 500:
                open(out_txt, "w", encoding="utf-8").write(txt)
                print(f"OK {os.path.basename(pdf_path)} → {len(txt)}字")
                return True
            print(f"短输出 {os.path.basename(pdf_path)} ({len(txt)}字)，重试")
        except Exception as e:
            msg = str(e)
            if "队列已满" in msg or "queue" in msg.lower():
                print(f"队列满 {os.path.basename(pdf_path)}，等 60s (attempt {attempt+1})")
                time.sleep(60)
            else:
                print(f"失败 {os.path.basename(pdf_path)}: {msg[:80]} (attempt {attempt+1})")
                time.sleep(10)
    print(f"FAIL {os.path.basename(pdf_path)} 4 次重试后放弃")
    return False

import asyncio

async def main():
    jobs = []
    for pdf_path in sorted(glob.glob(os.path.join(PROBE, "garble_m*.pdf"))):
        base = os.path.basename(pdf_path).replace(".pdf", "")
        out_txt = os.path.join(OUT, base + ".txt")
        jobs.append((pdf_path, out_txt))
    print(f"共 {len(jobs)} 个任务")
    # 并发 2
    sem = asyncio.Semaphore(2)
    async def worker(infer, j):
        async with sem:
            return await run_one(infer, j[0], j[1])
    infer = PaddleOCRVLAIStudioInference(token=TOKEN, model=MODEL, request_timeout=180, poll_timeout=600)
    await infer.start()
    try:
        results = await asyncio.gather(*[worker(infer, j) for j in jobs])
        ok = sum(1 for r in results if r)
        print(f"DONE: {ok}/{len(jobs)}")
    finally:
        await infer.stop()

asyncio.run(main())
