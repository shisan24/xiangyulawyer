# -*- coding: utf-8 -*-
"""终检：机械敏感项 + 实体 + 水印覆盖率。

教训（2026-10-16）：旧版只覆盖 6 类规则（漏 `~` 路径、〔〕文号、千分位金额），
实体只做字面子串匹配 → 得出"机械 0／实体 0"的**假通过**，真实客户案情仍上线。
现在机械规则**直接复用 sanitize.py**，口径单一来源；实体用名单 + 允许误报白名单。
用法: python verify_clone.py <dir> <entity_keywords.txt>
"""
import importlib.util
import os
import re
import sys


def load_sanitize():
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("_san", os.path.join(here, "sanitize.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TEXT_EXT = {".md", ".py", ".sh", ".bat", ".cmd", ".ps1", ".json", ".yaml", ".yml",
            ".txt", ".csv", ".html", ".htm", ".js", ".ts", ".sql", ".xml", ".toml",
            ".ini", ".cfg", ".conf", ".template", ".tpl"}
ALLOW = {"恢复执行", "案件资料", "专利PTE", "执行异议之诉", "再审", "保全"}

# 独立写法的粗筛：**故意不复用 sanitize 的规则**。
# 同源规则口径一致，但同源盲区也会一起漏（实测：sanitize 与旧终检同时漏掉大写 TOKEN、
# 正斜杠路径、`数量旧房`），所以终检必须叠加一套自己的宽网。
COARSE = {
    "apikey形": r"(?i)\b(?:token|apikey|api[_-]?key|secret|password|passwd)\b\s*[:=]",
    "长串密钥候选": r"(?<![A-Za-z0-9])[A-Za-z0-9_\-]{32,64}(?![A-Za-z0-9])",
    "盘符路径": r"[A-Za-z]:[\\/]",
    "主目录路径": r"~[\\/]",
    "文号": r"[〔\[（(]\d{4}[〕\]）)][^\s，。；、]{0,30}?号",
    "数量标的": r"\d+\s*(?:户|套|幢|栋)",
    "千分位数字": r"\d{1,3}(?:,\d{3})+",
    "长数字串": r"(?<!\d)\d{15,}(?!\d)",
    "邮箱或域名": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "openid 形": r"(?<![A-Za-z0-9])o[A-Za-z0-9_\-]{27}",
    "用户名形": r"(?i)(?:users|home)[\\/]\s*[A-Za-z0-9_.\-]{3,20}",
}


def main():
    root, kwfile = sys.argv[1], sys.argv[2]
    san = load_sanitize()
    kws = [l.strip() for l in open(kwfile, encoding="utf-8") if l.strip()]
    files = marked = 0
    mech, ent, coarse = {}, {}, {}
    for r, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git"}]
        for f in fs:
            if os.path.splitext(f)[1].lower() not in TEXT_EXT:
                continue
            p = os.path.join(r, f)
            rel = os.path.relpath(p, root)
            try:
                t = open(p, "rb").read().decode("utf-8", "ignore")
            except OSError:
                continue
            files += 1
            if "xiangyulawyer" in t:
                marked += 1
            for name, pat, _rep in san.MECH_RULES:
                for m in re.findall(pat, t):
                    mech.setdefault(name, []).append(f"{rel}: {str(m)[:40]}")
            for k in kws:
                if k in t and k not in ALLOW:
                    ent.setdefault(k, []).append(rel)
            for cname, cpat in COARSE.items():
                for m in re.findall(cpat, t):
                    coarse.setdefault(cname, []).append(f"{rel}: {str(m)[:50]}")
    print(f"文本文件 {files}，含水印 {marked}（{marked / max(1, files):.0%}）")
    print("机械命中:", {k: len(v) for k, v in mech.items()} or "无")
    for k, v in list(mech.items())[:10]:
        for x in v[:4]:
            print(f"   [{k}] {x}")
    total = sum(len(v) for v in ent.values())
    print("实体命中:", total or "无")
    for k, v in ent.items():
        print(f"   {k} × {len(v)}: {', '.join(v[:5])}")
    print("独立粗筛命中:", {k: len(v) for k, v in coarse.items()} or "无")
    for k, v in coarse.items():
        for x in v[:4]:
            print(f"   [{k}] {x}")


if __name__ == "__main__":
    main()
