# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""v2：审委会上卷目录 → 法规清单；下卷正文粗扫法规标题
"""
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")

out = r"[本地路径]"
vols_up = ["民商上", "刑事上", "行政上"]
vols_dn = ["民商下", "刑事下", "行政下"]

def load_pages(path):
    t = open(path, encoding="utf-8").read()
    pages = re.split(r"=== p\d+ ===\n", t)
    buf = []
    for pg in pages:
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
    # 去除点线页码占位
    text = re.sub(r"[.…]{5,}", "\t", text)
    # 按页脚页码切块（页码 2-4 位）
    chunks = re.split(r"\t\((\d{2,4})\)(?:\t|$|\n)", text)
    entries = []
    section = ""
    i = 0
    while i < len(chunks) - 1:
        body = chunks[i]
        page = chunks[i + 1]
        i += 2
        body = body.strip()
        if not body:
            continue
        # 分类标题行（X、Y）
        msec = re.search(r"([一二三四五六七八九十]+、[^\n]{1,20})\n", body)
        if msec:
            section = msec.group(1)
            body = body.replace(msec.group(1), "").strip()
        if not body:
            continue
        # 信息括号 = 最后一个 (..)
        mm = re.search(r"\(([^()]*)\)\s*$", body)
        if not mm:
            continue
        info = mm.group(1).strip()
        name = body[:mm.start()].strip()
        if not name:
            continue
        entries.append((section, name, info, page))
    return entries

def scan_down(path):
    """下卷正文粗扫：法规标题行（中华人民共和国XX法 / 最高人民法院... / XX条例等独立行）"""
    buf = load_pages(path)
    hits = []
    for i, s in enumerate(buf):
        if re.fullmatch(r"(中华人民共和国|最高人民检察院|最高人民法院|国务院|全国人大常委会)[^（(（]{2,50}", s):
            hits.append(s)
    # 去重保序
    seen = set()
    uniq = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq

for vol in vols_up:
    entries = parse_up(os.path.join(out, f"toc_full_{vol}.txt"))
    fn = os.path.join(out, f"法规清单_{vol}.txt")
    with open(fn, "w", encoding="utf-8") as f:
        for section, name, info, page in entries:
            f.write(f"{section}\t{name}\t{info}\t{page}\n")
    print(f"{vol}: {len(entries)} 条")

for vol in vols_dn:
    hits = scan_down(os.path.join(out, f"toc_full_{vol}.txt"))
    fn = os.path.join(out, f"法规粗扫_{vol}.txt")
    with open(fn, "w", encoding="utf-8") as f:
        f.write("\n".join(hits))
    print(f"{vol}: 粗扫 {len(hits)} 个标题候选")
print("DONE")
