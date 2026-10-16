# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""盘点法官培训教材 20 本：文件名+页数+大小"""
import os, sys, fitz
sys.stdout.reconfigure(encoding="utf-8")

base = r"[本地路径]）"
for fn in sorted(os.listdir(base)):
    if not fn.lower().endswith(".pdf"):
        continue
    p = os.path.join(base, fn)
    try:
        doc = fitz.open(p)
        n = doc.page_count
        doc.close()
        sz = os.path.getsize(p) / 1024 / 1024
        print(f"{n:>5}页 {sz:>7.1f}M  {fn}")
    except Exception as e:
        print(f"ERROR {fn}: {e}")
print("DONE")
