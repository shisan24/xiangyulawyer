# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""hermes-full-20260809 全量打包（含依赖，不脱敏，第二台电脑迁移）
排除：__pycache__/*.pyc/.hub/.curator_backups/日志/缓存/运行时文件"""
import os, sys, zipfile, time
sys.stdout.reconfigure(encoding="utf-8")

HOME = r"[本地路径]"
DOT = r"[本地路径]"
PKG = r"[本地路径]"
ZIP = r"[本地路径]"

# 排除规则（相对路径子串或文件名）
EXCLUDE_DIRS = {"__pycache__", ".hub", ".curator_backups", "logs", "cache", "checkpoints",
                "attachments", "audio_cache", "image_cache", "pastes", "pending_messages",
                "state-snapshots", "sessions", "bootstrap-cache", "byterover", "chroma_legal",
                "lsp", "bin", "webui", "desktop", "gateway-service", "openviking-service",
                "shared", "runtime", "sandboxes", "kanban.db-shm", "kanban.db-wal"}
EXCLUDE_FILES = {"*.pyc", "*.pid", "*.lock", "*.log", "sessions.db", "gateway_state.json",
                 "cron_daemon.log", "cron_ticker.log", "desktop-build-stamp.json",
                 "web-ui-build-stamp.json", "channel_directory.json.bak.weixin-cleanup"}

def excluded(rel):
    parts = rel.replace("\\", "/").split("/")
    for p in parts:
        if p in EXCLUDE_DIRS:
            return True
    base = parts[-1]
    if base in EXCLUDE_FILES:
        return True
    if base.endswith(".pyc"):
        return True
    return False

# 收集 (源路径, 包内路径)
items = []
def add(src, arc, skip_hidden=True):
    if not os.path.exists(src):
        print(f"  ⚠ 不存在跳过: {src}")
        return
    if os.path.isfile(src):
        if not excluded(arc):
            items.append((src, arc))
    else:
        for root, dirs, files in os.walk(src):
            # 剪枝排除目录
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
            for f in files:
                if f.endswith(".pyc"):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, src).replace("\\", "/")
                arcname = arc + "/" + rel
                if not excluded(arcname):
                    items.append((full, arcname))

print("=== 收集文件清单 ===")
# 1. hermes 家目录（关键内容）
for d in ["skills", "memories", "scripts", "cron", "plugins", "hooks", "desktop-plugins",
          "platforms", "weixin", "whatsapp", "scope-recall", "node", "pets", "pastes"]:
    add(os.path.join(HOME, d), "hermes-home/" + d)
for f in ["config.yaml", "profile.yaml", "state.db", "kanban.db", "verification_evidence.db",
          "projects.db", "skills_versions.json", "AGENTS.md", "SOUL.md", "knowledge-base-sync.json",
          "memory_store.db.bak", "processes.json"]:
    add(os.path.join(HOME, f), "hermes-home/" + f)
# profiles/
add(os.path.join(HOME, "profiles"), "hermes-home/profiles")
# 2. [本地路径] + AGENTS 副本）
add(os.path.join(DOT, ".env"), "dot-hermes/.env")
add(os.path.join(DOT, "AGENTS.md"), "dot-hermes/AGENTS.md")
# 3. venv（hermes-agent）
add(os.path.join(HOME, "hermes-agent", "venv"), "venv")
# 4. uv venv（paddleocr）
add(r"[本地路径]", "venv-uv")
# 5. PaddleOCR 模型
add(r"[本地路径]", "paddleocr-models")
# 6. 拆书资产
add(r"[本地路径]", "cangjie")
# 7. data 杂项
for f in ["法天使合同起草审查指南_知识库.yaml", "合同纠纷裁判规则_YAML提取.yaml",
          "合同审查评测知识库.yaml", "已学习项目.md"]:
    add(os.path.join(r"[本地路径]", f), "data-misc/" + f)
# 8. 模板库
add(r"[本地路径]", "模板库")
# 9. 工作流/全景
add(r"[本地路径]", "docs/工作流全景图.md")
add(r"[本地路径]", "docs/技能全景地图.md")

print(f"共 {len(items)} 个文件")
total = sum(os.path.getsize(s) for s, _ in items)
print(f"原始大小: {total/1024/1024:.0f} MB")

# 写清单
with open(os.path.join(PKG, "MANIFEST.txt"), "w", encoding="utf-8") as f:
    f.write(f"# hermes-full-20260809 清单\n# 文件数: {len(items)}\n# 原始大小: {total/1024/1024:.0f} MB\n# 打包时间: {time.strftime('%Y-%m-%d %H:%M')}\n")

print("=== 压缩打包（后台）===")
# zip 打包（level 1 快速，3.7G 数据压缩级别高会太慢）
with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
    for i, (src, arc) in enumerate(items):
        zf.write(src, arc)
        if i % 2000 == 0:
            print(f"  {i}/{len(items)} ...")
print(f"完成: {ZIP}")
