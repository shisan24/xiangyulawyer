# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""本机「技能 + 自建工具 + 自建插件」指纹（cron monitor 用：指纹不变则跳过 agent）。

真源：[本地路径] gen_watchlist.py 生成；
已剔除 client-directory-maps、deli/、legal 包根文件、第三方插件等不可公开单元）。
指纹 = 各单元文件相对路径 + 字节长度 + 内容 sha256 的累积哈希；输出确定（无时间戳）。
清单缺失时输出固定标记，使其与上轮不同、从而唤醒 agent 去修，而不是静默停摆。
"""
import hashlib
import json
import os

WATCHLIST = r"[本地路径]"
SKIP_DIR = {"__pycache__", ".git", ".idea", "node_modules"}


def fingerprint():
    if not os.path.isfile(WATCHLIST):
        return None
    data = json.load(open(WATCHLIST, encoding="utf-8"))
    h = hashlib.sha256()
    n = 0
    for u in sorted(data["units"], key=lambda x: x["name"]):
        root = u["path"]
        if not os.path.isdir(root):
            h.update(f"MISSING|{u['name']}|".encode())
            continue
        exts = set(u.get("exts") or []) or None
        skip = set(u.get("skip_dirs") or [])
        for r, dirs, files in os.walk(root):
            dirs.sort()
            dirs[:] = [d for d in dirs if d not in SKIP_DIR and d not in skip]
            for f in sorted(files):
                if exts and os.path.splitext(f)[1].lower() not in exts:
                    continue
                fp = os.path.join(r, f)
                try:
                    blob = open(fp, "rb").read()
                except OSError:
                    continue
                h.update(f"{u['name']}|{os.path.relpath(fp, root)}|{len(blob)}|".encode())
                h.update(hashlib.sha256(blob).digest())
                n += 1
    return len(data["units"]), n, h.hexdigest()[:32]


if __name__ == "__main__":
    r = fingerprint()
    if r is None:
        print("watchlist-missing units=0 files=0 fp=00000000000000000000000000000000")
    else:
        cu, cf, hx = r
        print(f"units={cu} files={cf} fp={hx}")
