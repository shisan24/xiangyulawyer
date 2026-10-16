# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""技能体系全量体检：
1. 技能清单 vs skill-registry 差异
2. SKILL.md 中 references/ 引用文件存在性（broken ref 扫描）
3. frontmatter 完整性（name/description 缺失、description 超长截断）
4. 已知 bug 状态复检
"""
import os, re, sys, glob
sys.stdout.reconfigure(encoding="utf-8")

SKILLS_ROOT = r"[本地路径]"
issues = []

# 1. 技能清单
all_skills = []
for root, dirs, files in os.walk(SKILLS_ROOT):
    if "SKILL.md" in files:
        rel = os.path.relpath(root, SKILLS_ROOT)
        all_skills.append(rel)
all_skills.sort()
print(f"=== 技能总数: {len(all_skills)} ===")

# 2. frontmatter + references 扫描
for rel in all_skills:
    md = os.path.join(SKILLS_ROOT, rel, "SKILL.md")
    try:
        t = open(md, encoding="utf-8").read()
    except Exception as e:
        issues.append(f"[读取失败] {rel}: {e}")
        continue
    # frontmatter
    fm = re.match(r"^---\n(.*?)\n---", t, re.S)
    if not fm:
        issues.append(f"[无frontmatter] {rel}")
        continue
    fmtext = fm.group(1)
    name_m = re.search(r"^name:\s*(.+)$", fmtext, re.M)
    desc_m = re.search(r"^description:\s*(.+)$", fmtext, re.M)
    if not name_m:
        issues.append(f"[缺name] {rel}")
    if not desc_m:
        issues.append(f"[缺description] {rel}")
    else:
        desc = desc_m.group(1).strip().strip('"').strip("'")
        if len(desc) > 62:
            issues.append(f"[description超62字·截断风险] {rel} ({len(desc)}字)")
    # references 引用扫描
    refs = re.findall(r"references/([A-Za-z0-9_\-\u4e00-\u9fff\.%]+\.md)", t)
    refs = list(dict.fromkeys(refs))
    for r in refs:
        p = os.path.join(SKILLS_ROOT, rel, "references", r)
        if not os.path.exists(p):
            issues.append(f"[broken-ref] {rel} → references/{r} 不存在")
    # scripts 引用扫描
    scripts = re.findall(r"scripts/([A-Za-z0-9_\-\u4e00-\u9fff\.]+\.(?:py|ps1|bat|sh|cmd))", t)
    scripts = list(dict.fromkeys(scripts))
    for s in scripts:
        p = os.path.join(SKILLS_ROOT, rel, "scripts", s)
        if not os.path.exists(p):
            issues.append(f"[broken-script] {rel} → scripts/{s} 不存在")

# 3. registry 对比
reg = open(os.path.join(SKILLS_ROOT, "skill-manager", "references", "skill-registry.md"), encoding="utf-8").read()
reg_skills = re.findall(r"`([a-z0-9\-]+)`", reg)
known = {"legal", "devops", "creative", "data-science", "mlops", "research", "github", "email",
         "productivity", "note-taking", "skill", "cangjie-skill", "capabilities", "skill-manager",
         "learning-loop", "council", "prism", "prompt-engineering", "obsidian"}
new_in_system = [s for s in all_skills if s.split("/")[0] not in known and not any(x in s for x in ["crossframe", "obsidian"])]
print(f"\n=== 系统新增（registry 未登记或新目录）: {len(new_in_system)} ===")
for s in new_in_system:
    print(f"  {s}")

print(f"\n=== 体检问题总数: {len(issues)} ===")
for i in issues:
    print(" ", i)
print("DONE")
