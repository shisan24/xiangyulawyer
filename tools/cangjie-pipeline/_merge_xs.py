# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""刑事候选合并：合集 hj1-16（f/p/c）+ 单本 xs118-148（p）→ 类型 _all.md（title 去重 + id 重排）
输出: framework_all / principle_all / case_all（刑事）
"""
import os, re, sys, glob
sys.stdout.reconfigure(encoding="utf-8")

base = r"[本地路径]"
specs = {
    "framework": ("f", "framework_hj*.md"),
    "principle": ("p", "principle_hj*.md"),
    "case": ("c", "case_hj*.md"),
    "principle_single": ("p", "principle_xs*.md"),
}

def extract(files):
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
                continue
            key = (tm.group(1) or tm.group(2)).strip().strip('"')
            entries.append((key, b))
    return entries

# 合集三类
for typ, (prefix, pat) in specs.items():
    if typ == "principle_single":
        continue
    files = sorted(glob.glob(os.path.join(base, pat)))
    entries = extract(files)
    seen, uniq = set(), []
    for key, b in entries:
        if key in seen:
            continue
        seen.add(key)
        uniq.append((key, b))
    out = f"# {typ} 候选池（刑事合并）\n- 来源: xingshi-shenpan-cankao（1-115 合集 16 组）\n- 组文件: {len(files)} 个\n- 原始条数: {len(entries)} → 去重后: {len(uniq)}\n\n"
    for i, (key, b) in enumerate(uniq, 1):
        new_id = f"{prefix}{i:03d}"
        b = re.sub(r"^- id: \S+", f"- id: {new_id}", b, count=1)
        out += b + "\n"
    outfn = os.path.join(base, f"{typ}_all.md")
    open(outfn, "w", encoding="utf-8").write(out)
    print(f"{typ}: {len(entries)} → {len(uniq)} 条 → {os.path.basename(outfn)}")

# 单本原则（单独文件，便于引用）
files = sorted(glob.glob(os.path.join(base, "principle_xs*.md")))
entries = extract(files)
seen, uniq = set(), []
for key, b in entries:
    if key in seen:
        continue
    seen.add(key)
    uniq.append((key, b))
out = "# principle 候选池（刑事单本 118-148 辑）\n- 来源: xingshi-shenpan-cankao 单本 21 本\n- 组文件: %d 个\n- 原始条数: %d → 去重后: %d\n\n" % (len(files), len(entries), len(uniq))
for i, (key, b) in enumerate(uniq, 1):
    new_id = f"p{i:03d}"
    b = re.sub(r"^- id: \S+", f"- id: {new_id}", b, count=1)
    out += b + "\n"
open(os.path.join(base, "principle_single_all.md"), "w", encoding="utf-8").write(out)
print(f"principle_single: {len(entries)} → {len(uniq)} 条 → principle_single_all.md")

# 校验
for typ in ["framework_all.md", "principle_all.md", "case_all.md", "principle_single_all.md"]:
    p = os.path.join(base, typ)
    if os.path.exists(p):
        t = open(p, encoding="utf-8").read()
        print(f"校验 {typ}: {len(re.findall(r'^- id: ', t, re.M))} 条")
print("DONE")
