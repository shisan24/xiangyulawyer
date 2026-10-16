# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""民事审判指导候选合并：17 本 × 5 类 → 类型 _all.md（title 去重 + id 重排）
类型: framework / principle / case / counter-example / glossary
"""
import os, re, sys, glob
sys.stdout.reconfigure(encoding="utf-8")

base = r"[本地路径]"
id_prefix = {"framework": "f", "principle": "p", "case": "c", "counter-example": "ce", "glossary": "g"}

for typ, prefix in id_prefix.items():
    files = sorted(glob.glob(os.path.join(base, f"{typ}_M*.md")))
    entries = []
    for fn in files:
        t = open(fn, encoding="utf-8").read()
        blocks = re.split(r"\n(?=- id: )", t)
        for b in blocks:
            if not b.startswith("- id: "):
                continue
            m = re.search(r"^- id: (\S+)", b, re.M)
            if not m:
                continue
            tm = re.search(r"^  (?:title|term): (.+)$|^- (?:title|term): (.+)$", b, re.M)
            if not tm:
                print(f"  跳过无 title/term: {os.path.basename(fn)}/{m.group(1)}")
                continue
            key = (tm.group(1) or tm.group(2)).strip().strip('"')
            entries.append((m.group(1), key, b))
    # 去重
    seen = set()
    uniq = []
    for eid, key, block in entries:
        if key in seen:
            print(f"  去重: {key}")
            continue
        seen.add(key)
        uniq.append((eid, key, block))
    # 重排 id
    out = f"# {typ} 候选池（合并）\n- 来源: minshi-shenpan-zhidao（17 本文字层辑）\n- 组文件: {len(files)} 个\n- 原始条数: {len(entries)} → 去重后: {len(uniq)}\n\n"
    for i, (eid, key, block) in enumerate(uniq, 1):
        new_id = f"{prefix}{i:03d}"
        block = re.sub(r"^- id: \S+", f"- id: {new_id}", block, count=1)
        out += block + "\n"
    outfn = os.path.join(base, f"{typ}_all.md")
    open(outfn, "w", encoding="utf-8").write(out)
    print(f"{typ}: {len(entries)} → {len(uniq)} 条 → {os.path.basename(outfn)}")

# 校验
for typ in id_prefix:
    p = os.path.join(base, f"{typ}_all.md")
    if os.path.exists(p):
        t = open(p, encoding="utf-8").read()
        print(f"校验 {typ}_all.md: {len(re.findall(r'^- id: ', t, re.M))} 条")
print("DONE")
