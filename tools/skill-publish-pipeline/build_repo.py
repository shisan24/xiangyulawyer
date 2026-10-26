# -*- coding: utf-8 -*-
"""组装仓库：注水印、出 README 与技能总览、写 .gitignore。
用法: python build_repo.py <repo_dir> <mode: public|private> <slug> <units.json> [src_dir]
"""
import json
import os
import re
import sys

WATERMARK_TEXT = "© 2026 xiangyulawyer · github.com/shisan24/{slug} · 未经许可不得转载，引用请署名"
SKIP_EXT = {".json", ".yaml", ".yml", ".csv", ".toml", ".ini", ".cfg", ".xml"}
# 注释符按语言选，用错会直接坏文件（.bat 用 # 会报错、.js 用 # 会语法错误）
COMMENT = {".py": "#", ".sh": "#", ".txt": "#", ".env": "#", ".template": "#", ".tpl": "#",
           ".ps1": "#", ".bat": "REM", ".cmd": "REM", ".js": "//", ".ts": "//", ".css": "/*",
           ".html": "<!--", ".htm": "<!--"}
FM = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.S)
HEAD = re.compile(r"^(#!.*|# -\*-.*)$")


def watermark(path, slug):
    ext = os.path.splitext(path)[1].lower()
    base = os.path.basename(path).upper()
    # 许可/版权原文不得改动（无扩展名的 LICENSE 首行加注释会污染官方许可文本）
    if base in {"LICENSE", "LICENSE.TXT", "COPYING", "NOTICE", "COPYING.LESSER"} or not ext:
        return False
    if ext in SKIP_EXT:
        return False
    try:
        # utf-8-sig：剥掉行首 BOM。否则 BOM 会让 shebang/编码行匹配不上 HEAD，水印被插到第 1 行、
        # BOM 被挤到第 2 行，Python 直接语法错误（2026-10-16 实测坏过两个文件）。
        text = open(path, "rb").read().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return False
    if "xiangyulawyer" in text:
        return False
    line = WATERMARK_TEXT.format(slug=slug)
    if ext == ".md":
        m = FM.match(text)
        if m:
            # frontmatter 内补 author/source（若缺）
            fm = m.group(1)
            add = []
            if not re.search(r"^author:", fm, re.M):
                add.append("author: xiangyulawyer")
            if not re.search(r"^source:", fm, re.M):
                add.append(f"source: https://github.com/shisan24/{slug}")
            new_fm = fm + ("\n" + "\n".join(add) if add else "")
            text = "---\n" + new_fm + "\n---\n" + f"<!-- {line} -->\n\n" + text[m.end():]
        else:
            text = f"<!-- {line} -->\n\n" + text
    else:
        c = COMMENT.get(ext, "#")
        mark = f"{c} {line}" + ("" if c != "<!--" else " -->")
        lines = text.split("\n")
        ins = 0
        while ins < len(lines) and HEAD.match(lines[ins]):
            ins += 1
        lines.insert(ins, mark)
        text = "\n".join(lines)
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    return True


README_PUBLIC = """# xiangyulawyer · 律师法律作业技能框架

本库是 **@xiangyulawyer**（GitHub [@shisan24](https://github.com/shisan24)）在 Hermes 桌面客户端中
长期使用的**法律作业技能框架**的公开版本。

公开版本只保留每个技能的**定位说明、适用场景与方法框架**，不含任何个案信息、当事人信息、
客户资料、案号与本机环境。完整方法在作者本地环境中持续迭代，未公开。

## 这里面有什么

- `skills/` —— 法律作业技能骨架（`SKILL.md`），按技能名分目录
- `tools/` —— 自建工具脚本（发布管线、本机运维、拆书管线、文档解析等）
- `plugins/` —— 自建 Hermes 桌面插件（律师工作台、摘要看板、记忆看板、额度看板）
- `技能总览.md` —— 全部技能一览（名称 / 适用场景 / 内容形态）
- 覆盖范围：合同审查与修订、诉讼与二审、证据整理、尽职调查、常法顾问、类案与法规检索、
  刑事辩护、执行、婚姻家事、工伤人损、政府法务等

## 怎么用

1. 在 Hermes（或任何支持 skill 目录约定的客户端）中，将需要的技能目录复制到该客户端的
   `skills/` 下；
2. 触发方式见每个 `SKILL.md` 的 `description`（中文触发语已在其中写明）；
3. 骨架不含具体清单与脚本，请结合自身办案规范补全后再使用；
4. `tools/` 与 `plugins/` 内的脚本依赖本机路径与个人配置，需改造后使用。

## 版权与使用条件

- **许可：CC BY-NC 4.0**（署名—非商业性使用 4.0 国际）。许可全文见本库 [LICENSE](LICENSE)，
  官方文本：https://creativecommons.org/licenses/by-nc/4.0/legalcode.zh-hans
- 在上述许可范围内，你可以自由使用、转载、改编，条件是**保留署名与来源链接**、**不得用于商业目的**。
  商业使用需另行取得作者授权。
- 本库内容为通用方法框架，**不构成法律意见**；据此办案的风险由使用者自行承担。

> 本库不含任何真实案件、当事人或客户的识别信息。如你认为某处仍涉及你的信息，请提出，我们会立即处理。
"""

README_PRIVATE = """# 法律作业技能库（私有备份）

作者本人（xiangyulawyer）Hermes 法律技能库的**脱敏全量备份**：保留全部方法与脚本，
已对标识符层做机械脱敏（手机号、身份证号、银行卡号、统一社会信用代码、案号、邮箱、
微信 ID、本机绝对路径、密钥）并对已知主体名称做占位替换。

- 用途：跨设备同步与版本留痕，**非公开发布**。
- 已知残余：个案叙述中的自然人与机构名称未逐句穷尽，金额/日期仅在命中实体的行上联动遮蔽。
- 若本库需要转为公开，须先做一轮逐文件语义审查。
"""


def build_index(repo_dir, units, mode):
    rows = []
    for u in units:
        name = u["name"].split("/")[-1]
        f = os.path.join(repo_dir, "skills", name, "SKILL.md")
        desc, kind = "", "—"
        if os.path.isfile(f):
            text = open(f, "rb").read().decode("utf-8", "ignore")
            m = FM.match(text)
            if m:
                for ln in m.group(1).split("\n"):
                    if ln.startswith("description:"):
                        desc = ln.split(":", 1)[1].strip().strip('"')
            kind = "框架" if "如需完整方法" not in text else "仅定位说明"
        rows.append((name, desc, kind))
    out = ["# 技能总览", "",
           f"共 {len(rows)} 项。@" + ("公开框架版" if mode == "public" else "私有全量版"), "",
           "| 技能 | 适用场景 | 内容形态 |", "|---|---|---|"]
    for n, d, k in sorted(rows):
        out.append(f"| `{n}` | {d} | {k} |")
    open(os.path.join(repo_dir, "技能总览.md"), "w", encoding="utf-8", newline="\n").write(
        "\n".join(out) + "\n")


def main():
    repo_dir, mode, slug = sys.argv[1], sys.argv[2], sys.argv[3]
    units = json.load(open(sys.argv[4], encoding="utf-8"))
    n = 0
    for root, _d, files in os.walk(repo_dir):
        if ".git" in root:
            continue
        for fn in files:
            if watermark(os.path.join(root, fn), slug):
                n += 1
    open(os.path.join(repo_dir, "README.md"), "w", encoding="utf-8", newline="\n").write(
        README_PUBLIC if mode == "public" else README_PRIVATE)
    open(os.path.join(repo_dir, ".gitignore"), "w", encoding="utf-8", newline="\n").write(
        "__pycache__/\n*.pyc\n*.bak\n*.bak-*\n.env\n*.tmp\n.DS_Store\n")
    build_index(repo_dir, units, mode)
    print(f"注水印 {n} 个文件；README 与技能总览已写入 {repo_dir}")


if __name__ == "__main__":
    main()
