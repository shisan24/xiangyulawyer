# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""生成"可发布单元"清单：从单元总表里按声明式排除清单过滤。

把排除项写进代码（而不是临时 python 一行流），是为了让范围可审计、可复现——
范围一旦靠临时命令拼，漏项与被误删都不会留痕。
用法: python gen_publishable.py <units.json> <out.json>
"""
import json
import sys

# 排除项与理由（改这里就等于改范围，须留痕）
EXCLUDE = {
    # 内容即客户目录图，无法框架化
    "client-directory-maps": "客户目录图",
    # 第三方来源的残缺技能（正文自述"从 chenshi.ai 下载完整版 / hermes skills install CSlawyer1985/…"）
    "enforcement-case-assistant": "第三方来源残缺技能",
}

units = json.load(open(sys.argv[1], encoding="utf-8"))
kept, dropped = [], []
for u in units:
    short = u["name"].split("/")[-1]
    if short in EXCLUDE:
        dropped.append(f"{u['name']}（{EXCLUDE[short]}）")
    else:
        kept.append(u)
json.dump(kept, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"可发布单元 {len(kept)}；排除 {len(dropped)}：")
for d in dropped:
    print("  -", d)
