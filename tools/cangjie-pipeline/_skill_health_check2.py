# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""技能体检 v2：跨技能引用感知（标注"位于XX技能"或"XX references/..."的按目标技能查）"""
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")

SKILLS_ROOT = r"[本地路径]"
issues = []

# 技能名 → 目录映射
skill_dirs = {}
for root, dirs, files in os.walk(SKILLS_ROOT):
    if "SKILL.md" in files:
        rel = os.path.relpath(root, SKILLS_ROOT).replace("\\", "/")
        skill_dirs[rel.split("/")[-1]] = root

for rel in sorted(skill_dirs.values()):
    name = os.path.basename(rel)
    md = os.path.join(rel, "SKILL.md")
    try:
        t = open(md, encoding="utf-8").read()
    except Exception as e:
        issues.append(f"[读取失败] {name}: {e}")
        continue
    # 每处引用：找前置的"位于XX"或"XX references/"
    for m in re.finditer(r"references/([A-Za-z0-9_\-\u4e00-\u9fff\.%]+\.md)", t):
        ref = m.group(1)
        # 回看前 120 字找目标技能标注
        ctx = t[max(0, m.start()-120):m.start()]
        target = None
        for pat in [r"位于\s*([a-z0-9\-]+)[\s、）)]", r"见\s*([a-z0-9\-]+)\s+references", r"in\s+([a-z0-9\-]+)\s+references"]:
            mm = re.search(pat, ctx)
            if mm:
                target = mm.group(1)
                break
        if target and target in skill_dirs:
            p = os.path.join(skill_dirs[target], "references", ref)
            if not os.path.exists(p):
                issues.append(f"[跨技能broken-ref] {name} → {target}/references/{ref} 不存在")
            continue
        # 本技能查
        p = os.path.join(rel, "references", ref)
        if not os.path.exists(p):
            # 兜底：全局搜一次
            found = False
            for r2 in skill_dirs.values():
                if os.path.exists(os.path.join(r2, "references", ref)):
                    found = True
                    break
            if not found:
                issues.append(f"[broken-ref] {name} → references/{ref} 全局不存在")

    # scripts 引用（同样跨技能解析）
    for m in re.finditer(r"scripts/([A-Za-z0-9_\-\u4e00-\u9fff\.]+\.(?:py|ps1|bat|sh|cmd|js))", t):
        sc = m.group(1)
        ctx = t[max(0, m.start()-120):m.start()]
        target = None
        for pat in [r"位于\s*([a-z0-9\-]+)", r"见\s*([a-z0-9\-]+)\s+scripts", r"in\s+([a-z0-9\-]+)\s+scripts"]:
            mm = re.search(pat, ctx)
            if mm:
                target = mm.group(1)
                break
        if target and target in skill_dirs:
            p = os.path.join(skill_dirs[target], "scripts", sc)
            if not os.path.exists(p):
                issues.append(f"[跨技能broken-script] {name} → {target}/scripts/{sc} 不存在")
            continue
        p = os.path.join(rel, "scripts", sc)
        if not os.path.exists(p):
            found = False
            for r2 in skill_dirs.values():
                if os.path.exists(os.path.join(r2, "scripts", sc)):
                    found = True
                    break
            if not found:
                issues.append(f"[broken-script] {name} → scripts/{sc} 全局不存在")

print(f"=== 体检问题（跨技能感知后）: {len(issues)} ===")
for i in issues:
    print(" ", i)
print("DONE")
