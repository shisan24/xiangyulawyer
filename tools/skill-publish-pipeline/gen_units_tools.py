# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""生成「自建工具与插件」单元清单（含 per-unit 扩展名过滤与目录排除）。
用法: python gen_units_tools.py <out.json>
"""
import json
import sys

H = r"[本地路径]"
PN = H + r"\plugins"
PY = [".py"]
PYMD = [".py", ".md"]
CODE = [".py", ".js", ".json", ".md", ".yaml", ".html", ".css", ".sh", ".bat", ".cmd", ".toml", ".txt"]

GROUPS = [
    # 名称（决定仓库内路径）        源目录                                   扩展名   排除子目录
    ("tools/skill-publish-pipeline", r"[本地路径]", PYMD, ["__pycache__", "reports"]),
    ("tools/hermes-personal-scripts", H + r"\scripts", [".py", ".bat", ".sh", ".cmd"],
     ["__pycache__", "_orphans", "cron-session-close"]),
    ("tools/tang-assistant", r"[本地路径]", PYMD, ["__pycache__"]),
    # 注：拆书「每本书的工作目录」（如 zhixing-gongzuo-zhidao/）属书稿衍生，且会话进行中仍在写，
    # 不进公开库：正文/引文有版权风险、文件仍在变动。新增书目录时在此登记（2026-10-16 登记）。
    ("tools/cangjie-pipeline", r"[本地路径]", PY, ["__pycache__", "raw", "raw_ocr_paddle",
     "raw_clean", "src", "_extracted", "candidates", "pdf", "zip", "out", "_skill_backup",
     "_garble_ocr", "zhixing-gongzuo-zhidao", "ai-legal-claude"]),
    # 注：[本地路径] 整组已剔除——该组脚本内嵌名单型数据（属于数据本身，
    # 不是可框架化的工具），换谁发布都不该带上。范围排除项统一登记在 gen_publishable.py。
    ("tools/mineru", r"[本地路径]", PYMD, []),
    ("plugins/lawyer-workbench", PN + r"\lawyer-workbench", CODE, ["__pycache__", "_record_backups"]),
    ("plugins/digest-board", PN + r"\digest-board", CODE, ["__pycache__"]),
    ("plugins/memory-dashboard", PN + r"\memory-dashboard", CODE, ["__pycache__"]),
    ("plugins/provider-limits", PN + r"\provider-limits", CODE, ["__pycache__"]),
]

out = []
for name, path, exts, skip in GROUPS:
    import os
    if not os.path.isdir(path):
        print("缺失:", name, path)
        continue
    out.append({"name": name, "path": path, "exts": exts, "skip_dirs": skip})

json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"工具/插件单元 {len(out)} -> {sys.argv[1]}")
for u in out:
    print(f"  {u['name']:<34} {u['path']}")
