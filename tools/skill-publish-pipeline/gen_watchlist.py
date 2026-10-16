# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""生成 cron 监控清单（技能 + 自建工具 + 自建插件），作为唯一真源。
用法: python gen_watchlist.py <out.json> [tools_units.json]
"""
import json
import os
import sys

W = r"[本地路径]"
skills_src = os.path.join(W, "reports", "units.json")
tools_src = sys.argv[2] if len(sys.argv) > 2 else os.path.join(W, "reports", "tools-units-src.json")

EXCLUDE_SKILLS = {"client-directory-maps"}

units = []
for u in json.load(open(skills_src, encoding="utf-8")):
    n = u["name"].split("/")[-1]
    if n in EXCLUDE_SKILLS:
        continue
    units.append({"name": n, "path": u["path"], "exts": None, "skip_dirs": []})
for u in json.load(open(tools_src, encoding="utf-8")):
    units.append({"name": u["name"], "path": u["path"],
                  "exts": u.get("exts"), "skip_dirs": u.get("skip_dirs") or []})

json.dump({"units": units}, open(sys.argv[1], "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"监控单元 {len(units)} -> {sys.argv[1]}")
