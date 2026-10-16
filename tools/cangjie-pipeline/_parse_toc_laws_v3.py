# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""v3：审委会上卷目录 → 法规清单（修复：页码切块宽松化 + 块长过滤 + 名称折叠）
"""
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")

out = r"[本地路径]"
vols_up = ["民商上", "刑事上", "行政上"]

def load_pages(path):
    t = open(path, encoding="utf-8").read()
    pages = re.split(r"=== p\d+ ===\n", t)
    buf = []
    for pi, pg in enumerate(pages):
        if pi <= 3:  # 跳过版权页/出版说明（p1-p3）
            continue
        for ln in pg.split("\n"):
            s = ln.strip()
            if not s:
                continue
            if re.fullmatch(r"·\d+·", s):
                continue
            if "人民法院审判委员会审判手册" in s and len(s) < 45:
                continue
            buf.append(s)
    return buf

def parse_up(path):
    buf = load_pages(path)
    text = "\n".join(buf)
    text = re.sub(r"[.…·]{4,}", "\t", text)
    # 页码切块：\t (NNN) 行尾（容许空格）
    chunks = re.split(r"\t\s*\((\d{2,4})\)\s*$", text, flags=re.M)
    entries = []
    section = ""
    i = 0
    while i < len(chunks) - 1:
        body = chunks[i]
        i += 2  # 跳过页码
        body = body.strip()
        if not body or len(body) > 700:  # 版权页等大块噪声
            continue
        # 分类标题（可多个）
        parts = re.split(r"^([一二三四五六七八九十]+、[^\n]{1,24})$", body, flags=re.M)
        if len(parts) > 1:
            # 重组：偶索引为正文，奇索引为分类
            rebuilt = ""
            for k in range(1, len(parts), 2):
                section = parts[k]
                rebuilt += parts[k + 1] if k + 1 < len(parts) else ""
            body = rebuilt.strip()
        if not body:
            continue
        # 尾部信息括号
        mm = re.search(r"\(([^()]*)\)\s*$", body)
        if not mm:
            continue
        info = mm.group(1).strip()
        info = re.sub(r"\s+", " ", info)  # 折叠内部换行（目录原文跨行日期/文号）
        name = body[:mm.start()].strip()
        # 名称跨行折叠（去除换行空白）
        name = re.sub(r"\s+", "", name)
        if not name or len(name) > 80:
            continue
        entries.append((section, name, info))
    return entries

for vol in vols_up:
    entries = parse_up(os.path.join(out, f"toc_full_{vol}.txt"))
    fn = os.path.join(out, f"法规清单_{vol}.txt")
    with open(fn, "w", encoding="utf-8") as f:
        for section, name, info in entries:
            f.write(f"{section or '-'}\t{name}\t{info}\n")
    print(f"{vol}: {len(entries)} 条")

# 抽样检查
for vol in ["民商上", "刑事上", "行政上"]:
    print(f"\n===== {vol} 前 12 条 =====")
    print("\n".join(open(os.path.join(out, f"法规清单_{vol}.txt"), encoding="utf-8").read().split("\n")[:12]))
print("DONE")
