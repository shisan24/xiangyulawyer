# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""民事审判指导：M100 目录采样"""
import fitz, os, sys
sys.stdout.reconfigure(encoding="utf-8")
os.makedirs(r"[本地路径]", exist_ok=True)
doc = fitz.open(r"[本地路径]）\民事审判指导与参考  100.pdf")
t = ""
for i in range(min(40, doc.page_count)):
    t += f"=== p{i+1} ===\n" + doc[i].get_text()
doc.close()
open(r"[本地路径]", "w", encoding="utf-8").write(t)
print(f"chars: {len(t)}")
i = t.find("目录")
print(t[i:i+3000] if i >= 0 else "未找到目录，看前 2000 字:\n" + t[:2000])
