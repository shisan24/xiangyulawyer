# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""文书范本 OCR 流水线：拆页(30页/份<4.5MB) → mineru pipeline 循环（断点续传）→ 合并转 txt
用法: python _ocr_wenshu.py
"""
import os, sys, subprocess, glob, re, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SRC = r"[本地路径] 2025-5-29 124052 1.pdf"
SLUG = r"[本地路径]"
PARTS = os.path.join(SLUG, "pdf_parts")
OUT = os.path.join(SLUG, "raw_ocr")
MINERU = r"[本地路径]"

import fitz
os.makedirs(PARTS, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

# 1) 拆页（30 页/份，按 <4.5MB 动态封口）
doc = fitz.open(SRC)
total = doc.page_count
print(f"total pages: {total}")
chunks = []
cur = []
cur_size = 0
for i in range(total):
    cur.append(i)
    cur_size += len(doc[i].get_contents() or b"") + 1000  # 粗略估算
    if len(cur) >= 30 or cur_size > 4_500_000:
        chunks.append(cur)
        cur = []
        cur_size = 0
if cur:
    chunks.append(cur)
doc.close()
print(f"chunks: {len(chunks)}")

part_files = []
for ci, pages in enumerate(chunks):
    fn = os.path.join(PARTS, f"part_{ci:02d}.pdf")
    if os.path.exists(fn) and os.path.getsize(fn) > 1000:
        part_files.append(fn)
        continue
    d = fitz.open()
    src = fitz.open(SRC)
    for p in pages:
        d.insert_pdf(src, from_page=p, to_page=p)
    src.close()
    d.save(fn)
    d.close()
    sz = os.path.getsize(fn) / 1048576
    part_files.append(fn)
    print(f"  {os.path.basename(fn)}: {len(pages)}p {sz:.1f}MB")

# 2) mineru 循环（断点续传：md 存在且 >1000B 则 SKIP）
ok, fail = 0, []
for fn in sorted(part_files):
    name = os.path.basename(fn).replace(".pdf", "")
    md_out = os.path.join(OUT, f"{name}.md")
    if os.path.exists(md_out) and os.path.getsize(md_out) > 1000:
        print(f"SKIP {name} (已存在 {os.path.getsize(md_out)}B)")
        ok += 1
        continue
    for attempt in range(3):
        try:
            r = subprocess.run(
                f'"{MINERU}" extract --model pipeline "{fn}" -o "{OUT}"',
                shell=True, capture_output=True, text=True, timeout=300, encoding='utf-8', errors='replace')
            if r.returncode == 0 and os.path.exists(md_out) and os.path.getsize(md_out) > 1000:
                print(f"OK {name} ({os.path.getsize(md_out)//1024}KB)")
                ok += 1
                break
            else:
                print(f"FAIL {name} attempt{attempt+1}: rc={r.returncode} {r.stderr[-150:]}")
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT {name} attempt{attempt+1}")
        except Exception as e:
            print(f"ERR {name} attempt{attempt+1}: {e}")
        time.sleep(5)
    else:
        fail.append(name)

print(f"\n完成: OK {ok} / FAIL {len(fail)} {fail}")
