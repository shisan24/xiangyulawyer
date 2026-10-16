# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""第二阶段拆书侦察：5 子目录代表性 PDF 文字层质量采样
策略：每目标抽 20 页（从第 5 页起均匀抽样），统计均字/页 + 空页数
"""
import fitz, os, glob, sys

base = r"[本地路径]"

def sample(pdf_path, n=20, start=5):
    doc = fitz.open(pdf_path)
    total = doc.page_count
    step = max(1, (total - start) // n)
    chars, empty = [], 0
    pages = range(start, total, step)[:n]
    for i in pages:
        t = doc.load_page(i).get_text()
        c = len(t.strip())
        chars.append(c)
        if c < 10:
            empty += 1
    doc.close()
    avg = sum(chars) / len(chars) if chars else 0
    return total, avg, empty

targets = {}

# 1. 文书范本（全量 1 本）
ws = glob.glob(os.path.join(base, "律师常用法律文书范本及精细化写作精要", "*.pdf"))
targets["文书范本"] = [(os.path.basename(p), p) for p in ws]

# 2. 审委会（6 本全量）
sw = sorted(glob.glob(os.path.join(base, "人民法院审判委员会", "*.pdf")))
targets["审委会"] = [(os.path.basename(p), p) for p in sw]

# 3. 法官培训教材（抽 4 代表：民商事4第1册 / 刑事3上册 / 行政8 / 立案2）
fg = sorted(glob.glob(os.path.join(base, "全国法官培训统编教材（2025）", "*.pdf")))
picks_fg = [f for f in fg if any(k in os.path.basename(f) for k in
            ["民商事审判实务4第1册", "刑事审判实务上册3", "行政审判实务8", "立案工作实务2"])]
targets["法官培训"] = [(os.path.basename(p), p) for p in picks_fg]

# 4. 民事审判指导（抽 4：M1 早期 / M25 中期 / M50 中后期 / 100 末期）
ms = sorted(glob.glob(os.path.join(base, "民事审判指导与参考（1-100）", "*.pdf")))
picks_ms = []
for key in ["M1民事审判指导", "M25民事审判指导", "M50民事审判指导", "民事审判指导与参考  100"]:
    for f in ms:
        if os.path.basename(f).startswith(key):
            picks_ms.append(f)
            break
targets["民事审判"] = [(os.path.basename(p), p) for p in picks_ms]

# 5. 刑事审判参考（抽 5：1-40 辑目录首本 / 41-77 首本 / 78-109 首本 / 135-148 首本 / 1-115 合集首本）
xs_root = os.path.join(base, "刑事审判参考1-148 集【清晰】")
xs = glob.glob(os.path.join(xs_root, "1.刑事审判参考1-40辑", "*.pdf"))
xs += glob.glob(os.path.join(xs_root, "2.刑事审判参考41-77辑", "*.pdf"))
xs += glob.glob(os.path.join(xs_root, "3.刑事审判参考78-109辑", "*.pdf"))
xs += glob.glob(os.path.join(xs_root, "8.刑事审判参考135-148 辑", "*.pdf"))
xs += glob.glob(os.path.join(xs_root, "7.刑事审判参考1-115辑", "*.pdf"))
picks_xs = []
for f in sorted(xs):
    bn = os.path.basename(f)
    if "1-115辑" in os.path.dirname(f) and not picks_xs and bn.lower().endswith(".pdf"):
        picks_xs.append(f)
    elif picks_xs and os.path.dirname(picks_xs[-1]) != os.path.dirname(f) and bn.lower().endswith(".pdf"):
        picks_xs.append(f)
targets["刑事"] = [(os.path.basename(p), p) for p in picks_xs[:5]]

print(f"{'类别':<6} {'文件':<50} {'页数':>6} {'MB':>7} {'均字/页':>8} {'空页':>4}")
print("-" * 90)
for cat, items in targets.items():
    for name, path in items:
        try:
            total, avg, empty = sample(path)
            mb = os.path.getsize(path) / 1048576
            print(f"{cat:<6} {name[:48]:<50} {total:>6} {mb:>7.1f} {avg:>8.0f} {empty:>4}")
        except Exception as e:
            print(f"{cat:<6} {name[:48]:<50} ERROR: {e}")
