# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""教材候选合并：20 本 principle → 领域 _all.md"""
import os, re, sys, glob
sys.stdout.reconfigure(encoding="utf-8")

base = r"[本地路径]"
files = sorted(glob.glob(os.path.join(base, "principle_*.md")))
entries = []
for fn in files:
    t = open(fn, encoding="utf-8").read()
    blocks = re.split(r"\n(?=- id: )", t)
    for b in blocks:
        if not b.startswith("- id: "):
            continue
        m = re.search(r"^  (?:title|term): (.+)$|^- (?:title|term): (.+)$", b, re.M)
        key = (m.group(1) or m.group(2)) if m else ""
        entries.append((os.path.basename(fn), key, b))

# 去重
seen, uniq = set(), []
for fn, key, b in entries:
    if key in seen:
        continue
    seen.add(key)
    uniq.append((fn, key, b))

# 领域分组
groups = {
    "民商": ["minshang", "zhishi"],
    "刑事": ["xingshi", "weichengnian"],
    "执行程序": ["zhixing", "lian", "shenpanguanli", "shenpjiandu", "guopei"],
    "行政环资": ["xingzheng", "huanzi"],
    "涉外": ["shewai", "shegangao"],
}
out = {g: [] for g in groups}
for fn, key, b in uniq:
    hit = "民商"
    for g, kws in groups.items():
        if any(k in fn for k in kws):
            hit = g
            break
    out[hit].append(b)

for g, items in out.items():
    outfn = os.path.join(base, f"principle_all_{g}.md")
    header = f"# principle 合并：{g}（{len(items)} 条）\n- 来源: faguan-peixun 20 本教材（2025 法官培训统编教材）\n\n"
    open(outfn, "w", encoding="utf-8").write(header + "\n".join(items) + "\n")
    print(f"{g}: {len(items)} 条 → principle_all_{g}.md")
print(f"总计: {len(entries)} → {len(uniq)} 条")
print("DONE")
