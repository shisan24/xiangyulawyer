# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""民事审判指导：早期 8 本文字层 blocks 提取（后台）
名单：M1/3/4/5/7/9/12/24（2000-2005，低优先备用）
"""
import fitz, os, sys
sys.stdout.reconfigure(encoding="utf-8")

BASE = r"[本地路径]）"
OUT = r"[本地路径]"
BLOCK = 25

targets = [
    "M1民事审判指导与参考·2000年·第1卷（总第1卷）.pdf",
    "M3民事审判指导与参考  2000年第3卷  总第3卷.pdf",
    "M4民事审判指导与参考·2000年第4卷·总第4卷_.pdf",
    "M5民事审判指导与参考  2001年第1卷  总第5卷.pdf",
    "M7民事审判指导与参考  2001年  第3卷  总第7卷.pdf",
    "M9民事审判指导与参考  2002年第1卷  总第9卷.pdf",
    "M12民事审判指导与参考  2002年第4卷  总第12卷.pdf",
    "M24民事审判指导与参考  2005年第4辑  总第24集.pdf",
]

for fn in targets:
    slug = fn.split("民事审判指导与参考")[0].replace(" ", "").replace(".pdf", "")
    outdir = os.path.join(OUT, slug)
    os.makedirs(outdir, exist_ok=True)
    if os.path.exists(os.path.join(outdir, "pages_map.txt")):
        print(f"SKIP {slug}")
        continue
    doc = fitz.open(os.path.join(BASE, fn))
    total = doc.page_count
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
print("DONE")
