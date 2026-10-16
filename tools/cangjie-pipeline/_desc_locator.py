# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""区分体检报出的 desc超60 技能：活跃 vs .archive，输出路径"""
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")

SKILLS_ROOT = r"[本地路径]"

# 体检报出的 73 个技能名
report = """corporate-governance-review governance-document-review internal-regulation-review regulation-review-methodology kanban-codex-lane autoskill-local-skill-manager cangjie-skill capabilities case-file-management cold-email context-optimizer adversarial-critique bayesian-synthesis multi-perspective-analysis comfyui pretext touchdesigner-mcp crossframe-casebook crossframe-critical crossframe-debate crossframe-dialogue crossframe-essay crossframe-notebook crossframe-org crossframe-public crossframe-review crossframe-suite crossframe-teach cyberbullying-first-aid defuddle case-retrieval case-retrieval-report legal-retrieval litigation-intake-assessment litigation-strategy-report cross-machine-operations hermes-self-evolution-pipeline kanban-governance-starter kanban-orchestrator kanban-worker mcp-setup memory-governance-starter skill-governance-starter system-maintenance google-calendar-automation greenhelix-agent-cost-optimization harness-dataset-design hermes-memory hermes-web-interface json-canvas kdocs-skill multi-agent-task-orchestrator obsidian-bases obsidian-cli obsidian-markdown office-pyword outlook-calendar-automation packaging-hermes-system personal-api teams-meeting-pipeline ecosystem-scan self-improving-agent skill skill-factory skillify dev-workflow github-workflow hermes-s6-container-supervision plan task-intelligence tiangong-wps-word-automation-cn windows-ai-toolchain xmind"""
names = report.split()

by_name = {}
for root, dirs, files in os.walk(SKILLS_ROOT):
    if "SKILL.md" in files:
        rel = os.path.relpath(root, SKILLS_ROOT).replace("\\", "/")
        base = rel.split("/")[-1]
        if base in names:
            by_name.setdefault(base, []).append(rel)

print(f"{'技能名':<40} {'状态':<8} 路径")
print("-" * 100)
for n in sorted(names):
    paths = by_name.get(n, [])
    if not paths:
        print(f"{n:<40} {'未找到':<8} (技能库外或深层目录)")
    else:
        for p in paths:
            state = "ARCHIVE" if p.startswith(".archive/") else "活跃"
            print(f"{n:<40} {state:<8} {p}")
