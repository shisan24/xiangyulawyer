# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""把源单元清单映射为 staging 副本的单元清单（供清洗后复扫/框架化使用）。
用法: python gen_staging_units.py <units.json> <staging_dir> <out.json>
"""
import json
import os
import sys

units = json.load(open(sys.argv[1], encoding="utf-8"))
staging = sys.argv[2]
out = []
for u in units:
    p = os.path.join(staging, u["name"].replace("/", "__"))
    if os.path.isdir(p):
        out.append({"name": u["name"], "path": p})
json.dump(out, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"staging 单元 {len(out)} / 源单元 {len(units)} -> {sys.argv[3]}")
