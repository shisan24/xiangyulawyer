# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""提取审委会 6 卷目录区（前 80 页）"""
import fitz, os, sys
sys.stdout.reconfigure(encoding="utf-8")
base = r"[本地路径]"
out = r"[本地路径]"
pairs = [("民商事卷 上 .pdf","民商上"),("民商事卷 下 .pdf","民商下"),("刑事卷 上 .pdf","刑事上"),
         ("刑事卷 下 .pdf","刑事下"),("行政卷 上.pdf","行政上"),("行政卷 下.pdf","行政下")]
for src, slug in pairs:
    fn = os.path.join(out, f"toc_full_{slug}.txt")
    if os.path.exists(fn):
        print(f"SKIP {slug}")
        continue
    doc = fitz.open(os.path.join(base, src))
    t = ""
    for i in range(min(80, doc.page_count)):
        t += f"=== p{i+1} ===\n" + doc[i].get_text()
    doc.close()
    open(fn, "w", encoding="utf-8").write(t)
    print(f"{slug}: {len(t)} chars")
print("DONE")
