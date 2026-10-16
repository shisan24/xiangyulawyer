# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""法官培训教材：OCR md/txt → 统一 raw/part_NN.txt + blocks 切分
mineru 输出 md（raw_ocr/）、paddle 输出 txt（raw_ocr_paddle/）→ 归一化到 raw/
"""
import os, sys, glob, re
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT_BASE = r"[本地路径]"

def md_to_txt(md):
    """md 去表格线/图片引用 → 纯文本（保留段落结构）"""
    t = md
    t = re.sub(r"!\[.*?\]\(.*?\)", "", t)          # 图片
    t = re.sub(r"<table.*?</table>", "[表格]\n", t, flags=re.S)  # html 表格占位
    t = re.sub(r"\|[-: |]+\|", "", t)               # 表格分隔行
    t = re.sub(r"^\s*\|.*\|\s*$", "", t, flags=re.M)  # 表格行
    t = re.sub(r"[#>*`_~-]{1,6}\s*", "", t)          # md 符号（保守：不破坏正文）
    t = re.sub(r"={3,}", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

for slug in sorted(os.listdir(OUT_BASE)):
    base = os.path.join(OUT_BASE, slug)
    raw = os.path.join(base, "raw_ocr")
    rawp = os.path.join(base, "raw_ocr_paddle")
    outdir = os.path.join(base, "raw")
    if not os.path.isdir(outdir):
        os.makedirs(outdir, exist_ok=True)
    # 优先 mineru md，缺失时用 paddle txt
    n_ok = 0
    md_files = sorted(glob.glob(os.path.join(raw, "*.md")))
    txt_files = sorted(glob.glob(os.path.join(rawp, "*.txt")))
    for fn in md_files:
        name = os.path.basename(fn).replace(".md", "")
        out = os.path.join(outdir, f"{name}.txt")
        if os.path.exists(out) and os.path.getsize(out) > 500:
            n_ok += 1
            continue
        t = md_to_txt(open(fn, encoding="utf-8").read())
        if len(t.strip()) > 100:
            open(out, "w", encoding="utf-8").write(t)
            n_ok += 1
    # paddle 补充缺失份
    for fn in txt_files:
        name = os.path.basename(fn).replace(".txt", "")
        out = os.path.join(outdir, f"{name}.txt")
        if os.path.exists(out) and os.path.getsize(out) > 500:
            continue
        t = open(fn, encoding="utf-8").read()
        if len(t.strip()) > 100:
            open(out, "w", encoding="utf-8").write(t)
            n_ok += 1
    print(f"{slug}: {n_ok} 份就绪（md {len(md_files)} / paddle {len(txt_files)}）")
print("DONE")
