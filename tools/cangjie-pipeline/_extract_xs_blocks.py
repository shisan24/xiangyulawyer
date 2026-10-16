# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""刑事审判参考：22 个文字层 PDF blocks 提取（后台）
- 1-115 集指导案例合集（8887 页）：40 页/块
- 单本（21 个）：25 页/块
"""
import fitz, os, sys, glob
sys.stdout.reconfigure(encoding="utf-8")

ROOT = r"[本地路径] 集【清晰】"
OUT = r"[本地路径]"

# 用文件名关键词定位（glob 全目录）
names = {
    "合集1-115": "1-115集指导案例",
    "第18辑": "第18辑",
    "115集": "115集【清晰】",
    "118辑": "第118辑",
    "119辑": "第119辑",
    "120辑": "第120辑",
    "121辑": "第121辑",
    "122集": "总第122集",
    "123集": "总第123集",
    "124集": "总第124集",
    "130辑": "总第130辑",
    "131集": "总第131集",
    "132辑": "总第132辑",
    "135-136": "135-136",
    "137辑": "总第137辑",
    "141辑": "总第141辑",
    "142辑": "总第142辑",
    "143辑": "总第143辑",
    "144辑": "总第144辑",
    "145-146": "145-146",
    "147辑": "总第147辑",
    "148辑": "总第148辑",
}

# 定位文件
found = {}
for slug, kw in names.items():
    hits = [f for f in glob.glob(os.path.join(ROOT, "**", "*.pdf"), recursive=True) if kw in os.path.basename(f)]
    if hits:
        found[slug] = hits[0]
    else:
        print(f"!! 未找到: {slug} ({kw})")

print(f"定位 {len(found)}/{len(names)}")

def extract(src, outdir, block):
    os.makedirs(outdir, exist_ok=True)
    if os.path.exists(os.path.join(outdir, "pages_map.txt")):
        print(f"SKIP {os.path.basename(outdir)}")
        return
    doc = fitz.open(src)
    total = doc.page_count
    toc = ""
    for i in range(min(30, total)):
        toc += f"=== p{i+1} ===\n" + doc[i].get_text()
    open(os.path.join(outdir, "toc_sample.txt"), "w", encoding="utf-8").write(toc)
    pages_map = []
    for i in range(0, total, block):
        part = ""
        for j in range(i, min(i + block, total)):
            part += f"=== p{j+1} ===\n" + doc[j].get_text()
        pfn = os.path.join(outdir, f"part_{i // block:02d}.txt")
        open(pfn, "w", encoding="utf-8").write(part)
        pages_map.append(f"part_{i // block:02d}: p{i+1}-p{min(i + block, total)} ({len(part)} chars)")
    open(os.path.join(outdir, "pages_map.txt"), "w", encoding="utf-8").write("\n".join(pages_map))
    doc.close()
    print(f"{os.path.basename(outdir)}: {total}p / {len(pages_map)} blocks")

# 合集优先（最大）
if "合集1-115" in found:
    extract(found["合集1-115"], os.path.join(OUT, "合集1-115"), 40)
# 单本
for slug in names:
    if slug == "合集1-115" or slug not in found:
        continue
    extract(found[slug], os.path.join(OUT, slug), 25)
print("DONE")
