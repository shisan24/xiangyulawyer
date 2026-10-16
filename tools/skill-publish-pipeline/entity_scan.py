# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""按实体关键词 + 语义规则，逐单元输出实证样例（供人工判定清洗可行性）。"""
import json
import os
import re
import sys

TEXT_EXT = {".md", ".py", ".sh", ".bat", ".cmd", ".ps1", ".json", ".yaml", ".yml",
            ".txt", ".csv", ".html", ".js", ".ts", ".sql", ".xml", ".toml", ".ini",
            ".cfg", ".conf", ".template", ".tpl"}
MASK = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
NAME_LABEL = re.compile(r"(?:原告|被告|申请人|被申请人|上诉人|被上诉人|第三人|委托代理人|代理人"
                        r"|当事人|委托人|客户|法定代表人|股东|证人)[：:\s]{0,2}[\u4e00-\u9fa5]{2,4}")

units = json.load(open(sys.argv[1], encoding="utf-8"))
kws = [l.strip() for l in open(sys.argv[2], encoding="utf-8") if l.strip()]
out = open(sys.argv[3], "w", encoding="utf-8")
summary = []
for u in units:
    hits = {}
    samples = []
    for root, _d, files in os.walk(u["path"]):
        for fn in files:
            if os.path.splitext(fn)[1].lower() not in TEXT_EXT:
                continue
            fp = os.path.join(root, fn)
            try:
                lines = open(fp, "rb").read().decode("utf-8", "ignore").splitlines()
            except OSError:
                continue
            for i, ln in enumerate(lines):
                for k in kws:
                    if k in ln:
                        hits[k] = hits.get(k, 0) + 1
                        if len(samples) < 400:
                            rel = os.path.relpath(fp, u["path"])
                            samples.append((k, rel, i + 1, ln.strip()[:200]))
                for m in NAME_LABEL.findall(ln):
                    hits["<标签名>" + m] = hits.get("<标签名>" + m, 0) + 1
    if hits:
        out.write(f"\n## {u['name']}  （命中类型 {len(hits)}）\n")
        for k, c in sorted(hits.items(), key=lambda x: -x[1]):
            out.write(f"- {k} × {c}\n")
        out.write("样例:\n")
        for k, rel, n, ln in samples[:12]:
            out.write(f"  [{k}] {rel}:{n}: {ln}\n")
    summary.append((u["name"], len(hits), sum(hits.values())))
out.write("\n\n# 汇总（单元 / 命中类型数 / 命中总次数）\n")
for nm, t, c in sorted(summary, key=lambda x: -x[2]):
    out.write(f"{nm}\t{t}\t{c}\n")
out.close()
print("完成 ->", sys.argv[3])
