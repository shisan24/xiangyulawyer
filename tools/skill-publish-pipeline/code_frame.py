# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""代码框架化：把 .py 里"数据即敏感"的名单类列表替换为空模板。
理由：名单（客户/当事人/律所）本身就是敏感数据，机械替换成重复占位符既无用又暴露结构。
用法: python code_frame.py <in_dir> <out_dir> <report.md>
"""
import os
import re
import sys

# 名单类列表：列表字面量里出现 ≥3 个占位符
LIST_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\[((?:[^\[\]]|【[^】]*】)*?)\]",
    re.S,
)
PLACEHOLDER = re.compile(
    r"【(?:主体|律师|律所|某单位|某法院|某仲裁委|某当事人|某案件|金额|案号|文号|本机标识|地域|案卷名"
    r"|手机号|身份证号|银行卡号|统一社会信用代码|邮箱|固定电话|IP|微信ID|密钥已移除|本地路径|数量)】")
NOTE = "[]  # 名单类数据（主体/当事人/律所/本机标识/地域）在本机维护，不入公开版"
# 按**变量名**外置（声明式）：比"数占位符个数"可靠——占位符表一旦没跟上新增类型就会漏（实测漏过）。
FORCE_BLANK = {"LAWYER", "FIRM", "PARTY", "LOCAL_IDS", "GEO", "CITY", "COURT_LIST"}


def frame(text, log, rel):
    n = [0]

    def repl(m):
        body = m.group(2)
        if m.group(1) in FORCE_BLANK or len(PLACEHOLDER.findall(body)) >= 3:
            n[0] += 1
            return f"{m.group(1)} = {NOTE}"
        return m.group(0)

    out = LIST_RE.sub(repl, text)
    # 收敛重复占位项：`["【律所】", ...]` 会暴露"原本有两个不同律所名"这类结构信息
    out = re.sub(r'"(【[^】]+】)"(?:\s*,\s*"\1")+', r'"\1"', out)
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
