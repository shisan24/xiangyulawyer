# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""脱敏清洗：标识符层正则 + 实体名单 + 机构/法院名 + 行级联动遮蔽。
只读源目录，输出到 staging 副本；全过程写替换日志。
用法: python sanitize.py <units.json> <out_dir> <log.json> [mode]
  mode = full（私有库：清洗后全量） | frame（公开库：仅骨架，另由 frameworkize 处理）
"""
import json
import os
import re
import sys

TEXT_EXT = {".md", ".py", ".sh", ".bat", ".cmd", ".ps1", ".json", ".yaml", ".yml",
            ".txt", ".csv", ".html", ".htm", ".js", ".ts", ".sql", ".xml", ".toml",
            ".ini", ".cfg", ".conf", ".template", ".tpl", ".env"}
SKIP_DIR = {"__pycache__", ".git", ".idea", "node_modules"}
# 运行期状态与非源码文件：任何单元都不上
SKIP_NAME_PAT = ("*.bak", "*.bak-*", "*state.json", "*.pyc", "*.log", "*.zip")


def _skip_name(fn):
    import fnmatch
    return any(fnmatch.fnmatch(fn, p) for p in SKIP_NAME_PAT)

# ---------- 一、标识符层（正则，最高确定性） ----------
MECH_RULES = [
    ("apikey",   r"(?:sk-[A-Za-z0-9_\-]{16,}|gho_[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{16,}"
                 r"|AIza[0-9A-Za-z_\-]{30,}|Bearer\s+[A-Za-z0-9_\-\.]{20,})", "【密钥已移除】"),
    ("idcard",   r"(?<!\d)\d{17}[\dXx](?!\d)", "【身份证号】"),
    ("mobile",   r"(?<!\d)1[3-9]\d{9}(?!\d)", "【手机号】"),
    ("bankcard", r"(?<!\d)\d{16,19}(?!\d)", "【银行卡号】"),
    ("uscc",     r"(?<![0-9A-HJ-NPQRTUWXY])[0-9A-HJ-NPQRTUWXY]{18}(?![0-9A-HJ-NPQRTUWXY])",
                 "【统一社会信用代码】"),
    ("caseno",   r"[（(]\d{4}[）)][^，。；、\s]{0,40}?号", "【案号】"),
    ("email",    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "【邮箱】"),
    ("landline", r"(?<!\d)0\d{2,3}[- ]?\d{7,8}(?!\d)", "【固定电话】"),
    ("ipv4",     r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)", "【IP】"),
    ("wxid",     r"(?:wxid_[A-Za-z0-9_\-]+|@im\.bot)", "【微信ID】"),
    # 本机绝对路径（含用户名）→ 统一占位
    ("localpath", r"(?:[A-Za-z]:\\{1,2}(?:Users|Desktop|data|Hermes|xwechat|tools|AI-Caches)"
                   r"[^\s\"'，。）;；)】]*)", "[本地路径]"),
    # 盘符路径（含裸 `[本地路径]` 与代码片段里的路径）
    ("drivepath", r"(?<![\\\w])[A-Za-z]:\\{1,2}[^\s\"'，。）;；`】)]*", "[本地路径]"),
    # MSYS 风格路径（[本地路径] 之类）
    ("msyspath", r"(?<![\[本地路径])/(?:c|d|e)/[A-Za-z0-9._\-/]*", "[本地路径]"),
    # 用户主目录简写路径（[本地路径] 之类，此前只处理了盘符路径，漏掉这一类）
    ("homedir", r"~[\\/][^\s\"'，。）;；)】`]*", "[本地路径]"),
    # 公文/鉴定/请示类文号（〔20xx〕…号；此前只匹配圆括号案号，漏方括号文号）
    ("docnum", r"[〔\[【]\d{4}[〕\]】][^\s，。；、]{0,30}?号", "【文号】"),
    # 千分位金额与"亿"级金额：真实交易金额常写成 【金额】 / 【金额】
    ("money", r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?(?:\s*(?:元|万元|亿元))?", "【金额】"),
    ("money_yi", r"\d+(?:\.\d+)?\s*亿(?:元)?", "【金额】"),
    # 正斜杠盘符路径（[本地路径] ；此前 drivepath 只匹配反斜杠，整类漏掉）
    ("winpath_fwd", r"(?<![\[本地路径])[A-Za-z]:/[^\s\"'，。）;；`】)]*", "[本地路径]"),
    # 密钥/口令赋值：含裸 hex token（sk-/gho_/AIza 之外的一整类，实测漏过活密钥；大小写不敏感）
    ("secret_assign", r"((?i:token|key|secret|password|passwd|access[_-]?token|api[_-]?key)"
                      r"\s*[:=]\s*[\"'])[^\"'\s]{12,}([\"'])", r"\1【密钥已移除】\2"),
    # 掩码/截断邮箱（`【邮箱】` 这类：前缀+域名已足以指向具体个人）
    ("email_masked", r"[A-Za-z0-9._%+-]{1,}[…\.]{1,}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "【邮箱】"),
    # 户/套/幢/栋 等个案标的数量（不加汉字负向断言：`【数量】旧房` 这类正是要遮的）
    ("count", r"\d+\s*(?:户|套|幢|栋)", "【数量】"),
    # 案卷文件名特征（`【案卷名】.pdf`、`5.18收-XX.pdf`；也覆盖不带 .pdf 的行内引用）
    ("casename", r"(?:决定书|裁定书|判决书|通知书|告知书|处罚决定书)\s*\d{1,4}\s*号[\u4e00-\u9fa5]{0,8}"
                 r"|\d{1,4}\s*号[\u4e00-\u9fa5]{0,8}(?=\.pdf)"
                 r"|(?<!\d)\d{1,2}\.\d{1,2}\s*收(?=[-\u4e00-\u9fa5]*\.pdf)", "【案卷名】"),
    # 本机服务端口/环回地址（暴露本机服务拓扑）
    ("localport", r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0):\d{2,5}", "【本机端口】"),
]

# ---------- 二、实体名单（按类别替换） ----------
LAWYER = []  # 名单类数据（主体/当事人/律所/本机标识/地域）在本机维护，不入公开版
FIRM = []  # 名单类数据（主体/当事人/律所/本机标识/地域）在本机维护，不入公开版
# 已知当事人/客户/项目主体（来自案件目录名与已核实清单）
PARTY = []  # 名单类数据（主体/当事人/律所/本机标识/地域）在本机维护，不入公开版
# 本机身份标识（用户名/邮箱前缀/自有域名/自媒体账号名）
# 这些词同样属于识别信息，放在名单里处理；公开版由 code_frame.py 统一外置为空模板。
LOCAL_IDS = []  # 名单类数据（主体/当事人/律所/本机标识/地域）在本机维护，不入公开版
# 地域名单：公开版由 code_frame.py 按变量名外置为空模板，规则在本地照常工作。
# 如需公开执业地，清空此列表即可恢复原口径。
GEO = []  # 名单类数据（主体/当事人/律所/本机标识/地域）在本机维护，不入公开版
# ---------- 三、机构全名 / 具体法院（正则） ----------
_GEO = "|".join(GEO)
ORG_RE = re.compile(r"(?:" + _GEO + r")?[\u4e00-\u9fa5]{2,10}(?:有限责任公司|【某单位】|有限公司)")
COURT_RE = re.compile(r"(?:" + _GEO + r")[\u4e00-\u9fa5]{0,8}?(?:人民法院|人民检察院)")
ARB_RE = re.compile(r"(?:" + _GEO + r")[\u4e00-\u9fa5]{0,4}?(?:仲裁委员会|仲裁委)")

ENTITY_RULES = []
for w in LAWYER:
    ENTITY_RULES.append((re.escape(w), "【律师】", "lawyer"))
for w in FIRM:
    ENTITY_RULES.append((re.escape(w), "【律所】", "firm"))
for w in PARTY:
    ENTITY_RULES.append((re.escape(w), "【主体】", "party"))
for w in LOCAL_IDS:
    ENTITY_RULES.append((re.escape(w), "【本机标识】", "localid"))
for w in GEO:
    ENTITY_RULES.append((re.escape(w), "【地域】", "geo"))
ENTITY_RULES.append((ORG_RE.pattern, "【某单位】", "org"))
ENTITY_RULES.append((COURT_RE.pattern, "【某法院】", "court"))
ENTITY_RULES.append((ARB_RE.pattern, "【某仲裁委】", "arb"))

AMOUNT_RE = re.compile(r"\d[\d,]*(?:\.\d{1,2})?\s*(?:万元|元|亿元)")

# ---------- 四、逐字修正（第三方厂商/CLI 品牌名等，须与已发布内容一致，保证重跑可复现） ----------
LITERAL_FIXES = [
    ("- 法条引用必须核实原文再写进批注：优先得理 CLI（用法见 search-retrieval 的 deli-cli-guide），"
     "元典 MCP `rh_ft_detail`（fgmc 可用简称模糊匹配，如\"建设工程质量保证金管理办法\"）或 `rh_ft_search` 作备选",
     "- 法条引用必须核实原文再写进批注：用所属法规库逐条核对原文（元典 MCP `rh_ft_detail`，"
     "fgmc 支持简称模糊匹配，如\"建设工程质量保证金管理办法\"；`rh_ft_search` 作备选）"),
    ("法条核验按所属法规库核实原文", "法条核验按所属法规库核实原文"),
    ("使用所属法规库检索", "使用所属法规库检索"),
]


def sanitize_text(text, log, unit):
    """返回 (清洗后文本, 是否发生替换)。命中实体的行，联动遮蔽该行金额。"""
    changed = False
    for old, new in LITERAL_FIXES:
        if old in text:
            text = text.replace(old, new)
            log["literal"] = log.get("literal", 0) + text.count(new)
            changed = True
    for name, pat, rep in MECH_RULES:
        new, n = re.subn(pat, rep, text)
        if n:
            log["mech"][name] = log["mech"].get(name, 0) + n
            text, changed = new, True
    entity_pat = re.compile("|".join(f"(?:{p})" for p, _r, _c in ENTITY_RULES))
    out_lines = []
    for ln in text.split("\n"):
        if entity_pat.search(ln):
            nl = ln
            for pat, rep, cat in ENTITY_RULES:
                nl, n = re.subn(pat, rep, nl)
                if n:
                    log["entity"][cat] = log["entity"].get(cat, 0) + n
            nl, n = AMOUNT_RE.subn("【金额】", nl)
            if n:
                log["amount_masked"] = log["amount_masked"] + n
            if nl != ln:
                changed = True
            out_lines.append(nl)
        else:
            out_lines.append(ln)
    log["units"][unit] = log["units"].get(unit, 0) + (1 if changed else 0)
    return "\n".join(out_lines), changed


def main():
    units = json.load(open(sys.argv[1], encoding="utf-8"))
    out_dir = sys.argv[2]
    log = {"mech": {}, "entity": {}, "amount_masked": 0, "units": {}, "files": 0,
           "files_changed": 0, "skipped": []}
    for u in units:
        allowed = set(u.get("exts") or TEXT_EXT)
        for root, dirs, files in os.walk(u["path"]):
            dirs[:] = [d for d in dirs if d not in SKIP_DIR and d not in set(u.get("skip_dirs") or [])]
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                src = os.path.join(root, fn)
                rel = os.path.relpath(src, u["path"])
                if ext not in allowed or _skip_name(fn):
                    log["skipped"].append(f"{u['name']}/{rel}")
                    continue
                dst = os.path.join(out_dir, u["name"].replace("/", "__"), rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if ext not in TEXT_EXT:
                    log["skipped"].append(f"{u['name']}/{rel}")
                    continue
                try:
                    raw = open(src, "rb").read()
                    text = raw.decode("utf-8")
                except (OSError, UnicodeDecodeError) as e:
                    log["skipped"].append(f"{u['name']}/{rel} ({type(e).__name__})")
                    continue
                clean, changed = sanitize_text(text, log, u["name"])
                open(dst, "w", encoding="utf-8", newline="").write(clean)
                log["files"] += 1
                log["files_changed"] += 1 if changed else 0
    json.dump(log, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"文件 {log['files']}，发生替换 {log['files_changed']}，跳过 {len(log['skipped'])}")
    print("机械类:", log["mech"])
    print("实体类:", log["entity"], "金额联动:", log["amount_masked"])


if __name__ == "__main__":
    main()
