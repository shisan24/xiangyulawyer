# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""第二阶段全量侦察：逐本检测文字层（3 页采样：5%、50%、95% 页）
分类：>=100 字/页=文字层 | 10-100=稀疏 | <10=扫描
"""
import fitz, os, glob, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

base = r"[本地路径]"

def classify(path):
    try:
        doc = fitz.open(path)
        total = doc.page_count
        if total == 0:
            return 0, 0, "空PDF"
        probes = [max(0, min(total-1, int(total * r))) for r in (0.05, 0.5, 0.95)]
        chars = []
        for i in probes:
            c = len(doc.load_page(i).get_text().strip())
            chars.append(c)
        doc.close()
        avg = sum(chars) / len(chars)
        if avg >= 100:
            cat = "文字层"
        elif avg >= 10:
            cat = "稀疏"
        else:
            cat = "扫描"
        return total, avg, cat
    except Exception as e:
        return -1, -1, f"ERR:{e}"

groups = [
    ("民事审判(100)", glob.glob(os.path.join(base, "民事审判指导与参考（1-100）", "*.pdf"))),
    ("法官培训(20)", glob.glob(os.path.join(base, "全国法官培训统编教材（2025）", "*.pdf"))),
    ("刑事-1_40辑", glob.glob(os.path.join(base, "刑事审判参考1-148 集【清晰】", "1.刑事审判参考1-40辑", "*.pdf"))),
    ("刑事-41_77辑", glob.glob(os.path.join(base, "刑事审判参考1-148 集【清晰】", "2.刑事审判参考41-77辑", "*.pdf"))),
    ("刑事-78_109辑", glob.glob(os.path.join(base, "刑事审判参考1-148 集【清晰】", "3.刑事审判参考78-109辑", "*.pdf"))),
    ("刑事-110_117辑", glob.glob(os.path.join(base, "刑事审判参考1-148 集【清晰】", "4.刑事审判参考110-117辑", "*.pdf"))),
    ("刑事-118_121辑", glob.glob(os.path.join(base, "刑事审判参考1-148 集【清晰】", "5.刑事审判参考118-121辑", "*.pdf"))),
    ("刑事-122_134辑", glob.glob(os.path.join(base, "刑事审判参考1-148 集【清晰】", "6.刑事审判参考122-134辑", "*.pdf"))),
    ("刑事-1_115合集", glob.glob(os.path.join(base, "刑事审判参考1-148 集【清晰】", "7.刑事审判参考1-115辑", "*.pdf"))),
    ("刑事-135_148辑", glob.glob(os.path.join(base, "刑事审判参考1-148 集【清晰】", "8.刑事审判参考135-148 辑", "*.pdf"))),
]

summary = {}
for gname, files in groups:
    stats = {"文字层": 0, "稀疏": 0, "扫描": 0, "ERR": 0}
    print(f"\n===== {gname}（{len(files)} 本）=====")
    for f in sorted(files):
        bn = os.path.basename(f)
        total, avg, cat = classify(f)
        stats[cat if cat in stats else "ERR"] += 1
        flag = "" if cat == "文字层" else "  <<<"
        print(f"  {cat:<4} 页{total:>5} 均{avg:>6.0f}字  {bn[:60]}{flag}")
    summary[gname] = stats

print("\n\n===== 汇总 =====")
total_tc = total_sc = total_sp = 0
for g, s in summary.items():
    print(f"{g:<16} 文字层 {s['文字层']:>3} | 稀疏 {s['稀疏']:>3} | 扫描 {s['扫描']:>3} | ERR {s['ERR']:>3}")
    total_tc += s["文字层"]; total_sc += s["扫描"]; total_sp += s["稀疏"]
print(f"\n合计: 文字层 {total_tc} / 稀疏 {total_sp} / 扫描 {total_sc}")
