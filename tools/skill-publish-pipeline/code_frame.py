# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""代码框架化：把 .py 里"数据即敏感"的名单类列表替换为空模板。
理由：名单（客户/当事人/律所）本身就是敏感数据，机械替换成重复占位符既无用又暴露结构。
用法: python code_frame.py <in_dir> <out_dir> <report.md>
"""
import ast
import os
import re
import sys

# 名单类列表的判据（2026-10-20 改为 AST 判定）：
# 旧的整段正则 LIST_RE 会把「元组列表」也当名单切（MECH_RULES 被切成半截 → IndentationError），
# 正则收敛还会把 `("A", "A")` 收敛成 `("A")`（元组被压成字符串 → 运行时 ValueError）。
# AST 判定能精确区分「字符串列表」与「元组/字典规则表」，且拿得到真实行号范围。
PLACEHOLDER = re.compile(
    r"【(?:主体|律师|律所|某单位|某法院|某仲裁委|某当事人|某案件|金额|案号|文号|本机标识|地域|案卷名"
    r"|手机号|身份证号|银行卡号|统一社会信用代码|邮箱|固定电话|IP|微信ID|密钥已移除|本地路径|数量)】")
NOTE = "[]  # 名单类数据（主体/当事人/律所/本机标识/地域）在本机维护，不入公开版"
# 按**变量名**外置（声明式）：比"数占位符个数"可靠——占位符表一旦没跟上新增类型就会漏（实测漏过）。
# 2026-10-19 补：LEGAL_TERMS/LEGAL_DICT（jieba 法律词典，含真实律所名与案件昵称）、
# LITERAL_FIXES（脱敏器的逐字替换表——原文本就是被替换掉的私密原文，整表发布＝把私密原文当搜索键公开）。
FORCE_BLANK = {"LAWYER", "FIRM", "PARTY", "LOCAL_IDS", "GEO", "CITY", "COURT_LIST",
               "LEGAL_TERMS", "LEGAL_DICT", "LITERAL_FIXES"}
# 遮蔽后的通用词重复出现同样暴露结构（`"该律所"` ＝ 原文有三个不同律所名）。
# 收敛只作用于这些已知通用词，不碰其它重复字符串。
GENERIC_ITEMS = {"该律所", "客户单位", "承办人", "本机目录", "本地端口", "本机地址", "某项目",
                 "某案件", "第三方同步盘", "当地", "金额", "案卷名称", "邮箱", "数量", "已移除"}


def frame(text, log, rel):
    n = [0]
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    lines = text.split("\n")
    edits = []  # (起始行索引, 结束行索引, 变量名)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name) or not node.end_lineno:
            continue
        name, val = tgt.id, node.value
        blank = name in FORCE_BLANK
        if not blank and isinstance(val, ast.List) and len(val.elts) >= 3:
            # 兜底判据：整表都是遮蔽后的占位符（名单被机械替换后的形态）
            strs = [e.value for e in val.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(strs) == len(val.elts) and all(PLACEHOLDER.search(s) for s in strs):
                blank = True
        if blank:
            edits.append((node.lineno - 1, node.end_lineno - 1, name))
    for s, e, name in sorted(edits, reverse=True):
        indent = re.match(r"\s*", lines[s]).group(0)
        lines[s:e + 1] = [f"{indent}{name} = {NOTE}"]
        n[0] += 1
    out = "\n".join(lines)
    # 收敛重复占位项：`["该律所", "该律所", ...]` 会暴露"原本有两个不同律所名"这类结构信息。
    # 前后加元组/列表边界断言：`("A", "A")` 是规则表条目，收敛会把元组压成字符串（运行时崩）。
    out = re.sub(r'(?<![(\[])"(【[^】]+】)"(?:\s*,\s*"\1")+(?![)\]])', r'"\1"', out)
    # 收敛重复的通用词项（遮蔽后的「该律所」「客户单位」等），理由同上
    def _gen(m):
        return f'"{m.group(1)}"' if m.group(1) in GENERIC_ITEMS else m.group(0)

    out, k = re.subn(r'(?<![(\[])"([^"\n]{1,10})"(?:\s*,\s*"\1")+(?![)\]])', _gen, out)
    if k:
        log.append(f"{rel}\t收敛重复通用词 {k} 处")
    if n[0]:
        log.append(f"{rel}\t替换名单列表 {n[0]} 处")
    return out


def main():
    src, dst = sys.argv[1], sys.argv[2]
    log = []
    kept = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in files:
            sp = os.path.join(root, fn)
            rel = os.path.relpath(sp, src)
            dp = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(dp), exist_ok=True)
            if not fn.endswith(".py"):
                open(dp, "w", encoding="utf-8", newline="\n").write(
                    open(sp, "rb").read().decode("utf-8", "ignore"))
                kept += 1
                continue
            text = open(sp, "rb").read().decode("utf-8", "ignore")
            # 直接用 frame() 的返回值；不要再走一条"仅按占位符个数"的旁路
            # （旁路会绕过 FORCE_BLANK，且占位符表漏项时静默失效——两条都实测踩过）
            text = frame(text, log, rel)
            open(dp, "w", encoding="utf-8", newline="\n").write(text)
            kept += 1
    open(sys.argv[3], "w", encoding="utf-8").write("\n".join(log) + "\n")
    print(f"框架化输出 {kept} 个文件；替换名单列表 {len(log)} 处")
    for l in log:
        print("  ", l)


if __name__ == "__main__":
    main()
