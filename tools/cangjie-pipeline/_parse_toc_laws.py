# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""解析审委会 6 卷目录 → 法规清单（法规名 | 版本信息）
块模式：法规标题（可跨行）→ 信息行（日期/文号）→ 页码 (NNN)
"""
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")

out = r"[本地路径]"
vols = ["民商上", "民商下", "刑事上", "刑事下", "行政上", "行政下"]

def parse_toc(path):
    t = open(path, encoding="utf-8").read()
    # 分页
    pages = re.split(r"=== p\d+ ===\n", t)
    buf = []
    for pg in pages:
        lines = pg.split("\n")
        cleaned = []
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            # 去页眉页码与书名重复行
            if re.fullmatch(r"·\d+·", s) or re.fullmatch(r"[-—]+", s):
                continue
            if "人民法院审判委员会审判手册" in s and len(s) < 40:
                continue
            cleaned.append(s)
        buf.extend(cleaned)
    # 合并成逻辑块：法规名行（以"法/条例/规定/解释/意见/通知/批复/纪要/决定/规则/细则/办法/规程/手册"结尾）+ 信息行 + 页码
    entries = []
    i = 0
    n = len(buf)
    while i < n:
        line = buf[i]
        m = re.search(r"\((\d{2,4})\)\s*$", line)  # 页码结尾
        if m:
            # 回溯收集法规名+信息：往前找"法规名"行（包含 法/条例/解释 等或日期行）
            j = i - 1
            info = ""
            name_parts = []
            while j >= 0 and len(entries) < 10000:
                prev = buf[j]
                if re.search(r"[（(]\d{4}", prev):  # 信息行（含年份）
                    info = prev
                    j -= 1
                    continue
                if "法" in prev or "条例" in prev or "规定" in prev or "解释" in prev or "意见" in prev or "通知" in prev or "批复" in prev or "纪要" in prev or "决定" in prev or "规则" in prev or "细则" in prev or "办法" in prev or "规" in prev or "准" in prev or "章" in prev or "节" in prev or re.search(r"^[一二三四五六七八九十]+、", prev) or re.search(r"^（?[一二三四五六七八九十]+）", prev):
                    name_parts.insert(0, prev)
                    j -= 1
                    # 法规名通常 2-5 行，碰到分类标题（X、Y）或空块就停
                    if re.search(r"^[一二三四五六七八九十]+、", prev) or re.search(r"^[（(]?[一二三四五六七八九十]+[)）]", prev) or len(name_parts) >= 6:
                        break
                else:
                    break
            if name_parts:
                entries.append((name_parts, info))
                i += 1
                continue
        i += 1
    return entries

for vol in vols:
    entries = parse_toc(os.path.join(out, f"toc_full_{vol}.txt"))
    fn = os.path.join(out, f"法规清单_{vol}.txt")
    with open(fn, "w", encoding="utf-8") as f:
        for name_parts, info in entries:
            name = "".join(name_parts)
            f.write(f"{name}\t{info}\n")
    print(f"{vol}: {len(entries)} 条 → {fn}")
print("DONE")
