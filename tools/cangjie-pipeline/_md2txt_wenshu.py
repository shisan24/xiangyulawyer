# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""OCR md → raw txt（去图片标记/标题符号）"""
import os, re, sys, glob
sys.stdout.reconfigure(encoding="utf-8")

slug = r"[本地路径]"
ocr = os.path.join(slug, "raw_ocr")
raw = os.path.join(slug, "raw")
os.makedirs(raw, exist_ok=True)

for f in sorted(glob.glob(os.path.join(ocr, "*.md"))):
    name = os.path.basename(f).replace(".md", "")
    t = open(f, encoding="utf-8").read()
    t = re.sub(r"!\[.*?\]\(.*?\)", "[图]", t)
    t = re.sub(r"^#{1,4}\s*", "", t, flags=re.M)
    t = re.sub(r"^---+\s*$", "", t, flags=re.M)
    out = os.path.join(raw, f"{name}.txt")
    open(out, "w", encoding="utf-8").write(t)
    print(f"{name}: {len(t)} chars")

# 合并统计
total = sum(len(open(f, encoding='utf-8').read()) for f in glob.glob(os.path.join(raw, "*.txt")))
print(f"合计: {total} chars, {len(glob.glob(os.path.join(raw, '*.txt')))} 文件")
