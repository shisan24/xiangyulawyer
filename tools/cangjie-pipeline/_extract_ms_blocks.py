# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""民事审判指导：后期 17 本文字层 blocks 提取（后台任务）
名单：M76-86 + M91 + M96-100（2018-2024）
"""
import fitz, os, sys
sys.stdout.reconfigure(encoding="utf-8")

BASE = r"[本地路径]）"
OUT = r"[本地路径]"
BLOCK = 25

targets = [
    "M76民事审判指导与参考76.pdf",
    "M77民事审判指导与参考—总第77辑—2019年第1辑.pdf",
    "M78民事审判指导与参考 总第78辑.pdf",
    "M79民事审判指导与参考 总第79辑.pdf",
    "M80民事审判指导与参考 2019年第4辑 总第80辑 202006.pdf",
    "M81民事审判指导与参考 2020年第1辑 总第81辑 202101.pdf",
    "M82民事审判指导与参考 2020年第2辑 总第82辑 202106.pdf",
    "M83民事审判指导与参考 2020年第3辑 总第83辑 202108.pdf",
    "M84民事审判指导与参考 2020年第4辑 总第84辑 202110.pdf",
    "M85民事审判指导与参考 2021年第1辑 总第85辑 202111.pdf",
    "M86民事审判指导与参考 总第86辑.pdf",
    "M91民事审判指导与参考 总第91辑.pdf",
    "M96 民事审判指导与参考 总第96辑 .pdf",
    "M97 民事审判指导与参考  总第97辑.pdf",
    "M98 民事审判指导与参考  总第98辑.pdf",
    "M99 民事审判指导与参考  总第99辑.pdf",
    "民事审判指导与参考  100.pdf",
]

for fn in targets:
    slug = fn.split("民事审判指导与参考")[0].replace(" ", "").replace(".pdf", "") or "M100"
    slug = slug if slug else "M100"
    outdir = os.path.join(OUT, slug)
    os.makedirs(outdir, exist_ok=True)
    if os.path.exists(os.path.join(outdir, "pages_map.txt")):
        print(f"SKIP {slug}（已提取）")
        continue
    src = os.path.join(BASE, fn)
    try:
        doc = fitz.open(src)
        total = doc.page_count
        # toc 采样（前 30 页）
        toc = ""
        for i in range(min(30, total)):
            toc += f"=== p{i+1} ===\n" + doc[i].get_text()
        open(os.path.join(outdir, "toc_sample.txt"), "w", encoding="utf-8").write(toc)
        pages_map = []
        for i in range(0, total, BLOCK):
            part = ""
            for j in range(i, min(i + BLOCK, total)):
                part += f"=== p{j+1} ===\n" + doc[j].get_text()
            pfn = os.path.join(outdir, f"part_{i // BLOCK:02d}.txt")
            open(pfn, "w", encoding="utf-8").write(part)
            pages_map.append(f"part_{i // BLOCK:02d}: p{i+1}-p{min(i + BLOCK, total)} ({len(part)} chars)")
        open(os.path.join(outdir, "pages_map.txt"), "w", encoding="utf-8").write("\n".join(pages_map))
        doc.close()
        print(f"{slug}: {total}p / {len(pages_map)} blocks")
    except Exception as e:
        print(f"ERR {slug}: {e}")
print("DONE")
