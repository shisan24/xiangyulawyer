# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""生成待扫描单元清单：自建法律技能（不含第三方 deli/ 与 legal 包根文件）。"""
import json
import os

S = r"[本地路径]"
TOP = ["legal-document-workflow", "legal-document-reference", "legal-opinion-delivery",
       "legal-deep-analysis", "legal-validation", "legal-translate", "legal-due-diligence",
       "legal-operations", "legal-compliance-bundle", "lawyer-workbench",
       "case-file-management", "case-filing-standard", "client-directory-maps",
       "contract-template-reference", "corporate-regulation-review", "de-ai-format-gate",
       "triple-model-review", "unjust-enrichment-council-calibration",
       "retainer-agreement-drafting", "soe-contract-effectiveness",
       "government-legal-counsel-contract", "pro-legal-strategist-v2",
       "execution-strategy-analysis", "lawyer-case-management-agent-template"]

units = []
legal = os.path.join(S, "legal")
for d in sorted(os.listdir(legal)):
    p = os.path.join(legal, d)
    if os.path.isdir(p) and d != "references":
        units.append({"name": f"legal/{d}", "path": p})
refs = os.path.join(legal, "references")
if os.path.isdir(refs):
    units.append({"name": "legal/references", "path": refs})
for t in TOP:
    p = os.path.join(S, t)
    if os.path.isdir(p):
        units.append({"name": t, "path": p})
    else:
        print("缺失:", t)

out = r"[本地路径]"
json.dump(units, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("单元数:", len(units), "->", out)
