#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""读取待办事项，输出未完成项。"""
import os

TODO_FILE = r"[本地路径]"

if not os.path.exists(TODO_FILE):
    print("⚠️ 待办事项文件不存在。")
    exit(0)

with open(TODO_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# 去掉空行和纯注释行
lines = [l for l in content.split("\n") if l.strip() and not l.strip().startswith("<!--")]

# 检查是否有实际待办内容（非标题、非注释）
has_content = any(
    l.strip() and not l.startswith("#") and "待补充" not in l
    for l in lines
)

if not has_content:
    print("📋 今日待办：暂无记录。\n\n有事情随时发给我，我帮你记到待办清单里。")
else:
    print("📋 今日待办清单：\n")
    print(content)
