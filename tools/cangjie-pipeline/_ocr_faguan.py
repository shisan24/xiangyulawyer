# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""法官培训教材 20 本 OCR 流水线：拆页(30页/份) → mineru pipeline（断点续传）→ md
用法: python _ocr_faguan.py [book_idx]  # 可选：只跑指定下标
"""
import os, sys, subprocess, glob, re, time, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz

SRC_BASE = r"[本地路径]）"
OUT_BASE = r"[本地路径]"
MINERU = r"[本地路径]"

BOOKS = [  # (slug, 文件名)
    ("minshang-1", "民商事审判实务4第1册.pdf"), ("minshang-2", "民商事审判实务4第2册.pdf"),
    ("minshang-3", "民商事审判实务4第3册.pdf"), ("minshang-4", "民商事审判实务4第4册.pdf"),
    ("minshang-5", "民商事审判实务4第5册.pdf"), ("minshang-6", "民商事审判实务4第6册.pdf"),
    ("xingshi-1", "刑事审判实务上册3.pdf"), ("xingshi-2", "刑事审判实务下册3.pdf"),
    ("zhixing", "执行案件办理实务11.pdf"), ("xingzheng", "行政审判实务8.pdf"),
    ("zhishi-chanquan", "知识产权审判实务5.pdf"), ("huanzi", "环境资源审判实务7.pdf"),
    ("shenpan-jiandu-1", "审判监督实务上册9.pdf"), ("shenpan-jiandu-2", "审判监督实务下册9.pdf"),
    ("shewai", "涉外商事海事审判实务和国际司法协助.pdf"), ("shegangao", "涉港澳民商事审判实务和区际司法协助14.pdf"),
    ("lian-kejian", "立案工作实务2.pdf"), ("guojia-peichang", "国家赔偿审判实务10.pdf"),
    ("weichengnianren", "未成年人审判实务13.pdf"), ("shenpan-guanli", "审判管理实务12.pdf"),
]

def process_book(slug, fname):
    src = os.path.join(SRC_BASE, fname)
    slug_dir = os.path.join(OUT_BASE, slug)
    parts_dir = os.path.join(slug_dir, "pdf_parts")
    out_dir = os.path.join(slug_dir, "raw_ocr")
    os.makedirs(parts_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    # 1) 拆页
    doc = fitz.open(src)
    total = doc.page_count
    chunks = []
    cur, cur_size = [], 0
    for i in range(total):
        cur.append(i)
        cur_size += len(doc[i].get_contents() or b"") + 1000
        if len(cur) >= 30 or cur_size > 4_500_000:
            chunks.append(cur); cur, cur_size = [], 0
    if cur:
        chunks.append(cur)
    doc.close()

    part_files = []
    for ci, pages in enumerate(chunks):
        fn = os.path.join(parts_dir, f"part_{ci:02d}.pdf")
        if os.path.exists(fn) and os.path.getsize(fn) > 1000:
            part_files.append(fn); continue
        d = fitz.open()
        s = fitz.open(src)
        for p in pages:
            d.insert_pdf(s, from_page=p, to_page=p)
        s.close()
        d.save(fn); d.close()
        part_files.append(fn)
    print(f"[{slug}] {fname}: {total}p → {len(chunks)} 份")

    # 2) mineru 循环
    ok, fail = 0, []
    for fn in sorted(part_files):
        name = os.path.basename(fn).replace(".pdf", "")
        md_out = os.path.join(out_dir, f"{name}.md")
        if os.path.exists(md_out) and os.path.getsize(md_out) > 1000:
            ok += 1
            continue
        for attempt in range(3):
            try:
                r = subprocess.run(
                    f'"{MINERU}" extract --model pipeline "{fn}" -o "{out_dir}"',
                    shell=True, capture_output=True, text=True, timeout=300, encoding='utf-8', errors='replace')
                if r.returncode == 0 and os.path.exists(md_out) and os.path.getsize(md_out) > 1000:
                    ok += 1
                    print(f"  OK {name} ({os.path.getsize(md_out)//1024}KB)")
                    break
                else:
                    print(f"  FAIL {name} a{attempt+1}: rc={r.returncode} {r.stderr[-120:]}")
            except subprocess.TimeoutExpired:
                print(f"  TIMEOUT {name} a{attempt+1}")
            except Exception as e:
                print(f"  ERR {name} a{attempt+1}: {e}")
            time.sleep(5)
        else:
            fail.append(name)
    print(f"[{slug}] 完成: OK {ok} / FAIL {len(fail)} {fail[:5]}")
    return ok, fail

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        start, end = int(sys.argv[1]), int(sys.argv[2])
        items = BOOKS[start:end]
    elif len(sys.argv) == 2:
        items = [BOOKS[int(sys.argv[1])]]
    else:
        items = BOOKS
    total_ok = total_fail = 0
    for slug, fname in items:
        ok, fail = process_book(slug, fname)
        total_ok += ok; total_fail += len(fail)
    print(f"\n=== 全部完成: OK {total_ok} / FAIL {total_fail} ===")
