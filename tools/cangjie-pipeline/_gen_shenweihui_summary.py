# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""生成审委会《审判手册-法条汇编清单（2025.10）》速查文件"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")

base = r"[本地路径]"
header = """# 人民法院审判委员会审判手册·法条汇编清单（2025.10 时效）

> 来源：《人民法院审判委员会审判手册》（最高人民法院审判管理办公室编，人民法院出版社 2025年10月第1版），民商事卷/刑事卷/行政卷共 6 册 PDF（[本地路径]）。
> 性质：**法条汇编工具书**（非案例集）——精选审委会讨论常用的现行有效法律、法规、司法解释及重要司法文件；部分已失效但常涉文件亦收录并标注。
> 用途：①法条时效快速核验对照（2025.10 快照，引用前仍应在线复核）；②"失效但仍常涉"文件清单；③审委会工作机制文件附录。
> 解析自 6 卷目录（共 580+ 条，审计底稿：shenweihui-anli/法规清单_*.txt、toc_full_*.txt、_stage2_survey_out.txt）。

## 民商事卷（约 198 条）

"""

def load(p):
    raw = open(os.path.join(base, p), encoding="utf-8").read()
    lines = raw.split("\n")
    out = []
    for ln in lines:
        if not ln.strip():
            continue
        parts = ln.split("\t")
        non_empty = [x for x in parts if x.strip()]
        if not non_empty:
            continue
        # 固定 3 列：分类 | 名称 | 版本信息（v3 已折叠内部换行）
        if len(non_empty) >= 2:
            name = non_empty[1]
            info = "\t".join(non_empty[2:])
        else:
            name = non_empty[0]
            info = ""
        info = info.replace("\r", "").strip()
        out.append(f"- **{name}**　{info}")
    return out

sections = [
    ("民商事卷", "法规清单_民商上.txt"),
    ("刑事卷", "法规清单_刑事上.txt"),
    ("行政卷", "法规清单_行政上.txt"),
]

doc = header
for title, fn in sections:
    items = load(fn)
    doc += f"\n## {title}（{len(items)} 条）\n\n"
    doc += "\n".join(items) + "\n"

out_fn = os.path.join(base, "审判手册法条汇编清单-2025.10.md")
open(out_fn, "w", encoding="utf-8").write(doc)
print(f"写入 {out_fn}: {len(doc)} chars")
# 校验
for title, fn in sections:
    items = load(fn)
    print(f"{title}: {len(items)} 条")
