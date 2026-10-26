# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""从案件目录名提取实体关键词（当事人/客户名），用于筛查技能库中的实名痕迹。"""
import json
import os
import re

DIRS = [r"[本地路径]",
        r"[本地路径]"]
STOP = set("""案件 纠纷 资料 待归档 进行中 其他 法律意见书 一案 三案 两案 再审 执行
施工合同 建设工程 建设工程施工合同 民间借贷 租赁 服务 有限公司 公司 案 号 等 系列
非诉 诉讼 保全 复议 异议 之诉 恢复 解除 限高 咨询 项目 文件 材料 明细 台账 汇编 打印""".split())

toks = {}
for d in DIRS:
    if not os.path.isdir(d):
        continue
    for n in os.listdir(d):
        core = re.sub(r"[（(].*?[）)]", "", n)
        core = re.sub(r"\d{4,8}|[0-9]{2,}|号", "", core)
        parts = re.split(r"[-+&、,，/\\s]|VS|vs|Vs|诉", core)
        for p in parts:
            p = p.strip().strip("的")
            if len(p) < 2:
                continue
            if p in STOP or p.endswith("纠纷") or p.endswith("案件"):
                continue
            toks[p] = toks.get(p, 0) + 1

# 手工补入已核实的主体/人名/客户
extra = ["承办人", "承办人", "该律所", "客户单位", "该律所", "客户单位", "承办人", "客户单位", "客户单位"]
for e in extra:
    toks[e] = toks.get(e, 0) + 1

words = sorted(toks, key=lambda x: (-toks[x], x))
out = r"[本地路径]"
with open(out, "w", encoding="utf-8") as f:
    for w in words:
        if len(w) >= 2:
            f.write(w + "\n")
print("关键词数:", len(words), "->", out)
print("样例:", " / ".join(words[:40]))
