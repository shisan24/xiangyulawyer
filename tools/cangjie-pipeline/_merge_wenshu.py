# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""文书范本候选合并：分组文件 → 类型 _all.md（title/term 去重 + id 重排）
类型: framework / principle / case / counter-example / glossary
"""
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")

base = r"[本地路径]"

# 类型 → 组文件（按顺序）
groups = {
    "framework": ["framework_g1.md", "framework_g2.md"],
    "principle": ["principle_g1.md", "principle_g2a.md", "principle_g2b.md"],
    "case": ["case_g1.md", "case_g2a.md", "case_g2b.md"],
    "counter-example": ["counter-example_g1.md", "counter-example_g2a.md", "counter-example_g2b.md"],
    "glossary": ["glossary_g1.md", "glossary_g2.md"],
}

id_prefix = {"framework": "f", "principle": "p", "case": "c", "counter-example": "ce", "glossary": "g"}

for typ, files in groups.items():
    entries = []  # (id, title/term, block)
    for fn in files:
        p = os.path.join(base, fn)
        if not os.path.exists(p):
            print(f"!! 缺失 {fn}")
            continue
        t = open(p, encoding="utf-8").read()
        # 切条目：^- id: 开始
        blocks = re.split(r"\n(?=- id: )", t)
        for b in blocks:
            if not b.startswith("- id: "):
                continue
            m = re.search(r"^- id: (\S+)", b, re.M)
            if not m:
                continue
            # 提取 title 或 term（兼容缩进 `  title:` 与行内 `- title:` 两种格式）
            tm = re.search(r"^  (?:title|term): (.+)$|^- (?:title|term): (.+)$", b, re.M)
            if not tm:
                print(f"  跳过无 title/term 条目: {m.group(1)} in {fn}")
                continue
            key = (tm.group(1) or tm.group(2)).strip().strip('"')
            entries.append((m.group(1), key, b))
    # 去重（按 title/term）
    seen = set()
    uniq = []
    for eid, key, block in entries:
        if key in seen:
            print(f"  去重: {key}")
            continue
        seen.add(key)
        uniq.append((eid, key, block))
    # id 重排
    prefix = id_prefix[typ]
    n = len(uniq)
    header = f"# {typ} 候选池（合并）\n- 来源: wenshu-fanben-xiezuo\n- 组文件: {', '.join(files)}\n- 原始条数: {len(entries)} → 去重后: {n}\n- 去重键: title/term\n\n"
    out = header
    for i, (eid, key, block) in enumerate(uniq, 1):
        new_id = f"{prefix}{i:03d}"
        block = re.sub(r"^- id: \S+", f"- id: {new_id}", block, count=1)
        out += block + "\n"
    outfn = os.path.join(base, f"{typ}_all.md")
    open(outfn, "w", encoding="utf-8").write(out)
    print(f"{typ}: {len(entries)} → {n} 条 → {os.path.basename(outfn)} ({len(out)}B)")

# 校验
for typ in groups:
    p = os.path.join(base, f"{typ}_all.md")
    t = open(p, encoding="utf-8").read()
    n = len(re.findall(r"^- id: ", t, re.M))
    print(f"校验 {typ}_all.md: {n} 条")
print("DONE")
