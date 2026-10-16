# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""逐单元脱敏扫描：来源核验 + 敏感项分类统计。
用法: python scan_units.py <units.json> <out.json>
units.json = [{"name":..., "path":...}, ...]
"""
import json
import os
import re
import sys

TEXT_EXT = {".md", ".py", ".sh", ".bat", ".cmd", ".ps1", ".json", ".yaml", ".yml",
            ".txt", ".csv", ".html", ".htm", ".js", ".ts", ".sql", ".xml", ".toml",
            ".ini", ".cfg", ".conf", ".env", ".template", ".tpl"}

# 机械可清洗类（可正则替换为占位符，不损技能价值）
MECH = {
    "mobile":   r"(?<!\d)1[3-9]\d{9}(?!\d)",
    "idcard":   r"(?<!\d)\d{17}[\dXx](?!\d)",
    "uscc":     r"(?<![0-9A-HJ-NPQRTUWXY])[0-9A-HJ-NPQRTUWXY]{18}(?![0-9A-HJ-NPQRTUWXY])",
    "bankcard": r"(?<!\d)\d{16,19}(?!\d)",
    "landline": r"(?<!\d)0\d{2,3}[- ]?\d{7,8}(?!\d)",
    "email":    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "apikey":   r"(?:sk-[A-Za-z0-9_\-]{16,}|gho_[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{16,}"
                r"|AIza[0-9A-Za-z_\-]{30,}|Bearer\s+[A-Za-z0-9_\-\.]{20,})",
    "localpath": r"(?:[A-Za-z]:\\\\?(?:Users|Desktop|data|Hermes|xwechat)[^\s\"'，。）;；]*)"
                 r"|(?:[A-Za-z]:\\(?:Users|Desktop|data|Hermes)[^\s\"'，。）;；]*)",
    "wxid":     r"(?:wxid_[A-Za-z0-9_\-]+|@im\.bot|gh_[a-z0-9]{8,})",
    "ipv4":     r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)",
    "caseno":   r"[（(]\d{4}[）)][^，。；、\s]{0,40}?号",
}

# 语义个案类（需人工判定，机械替换会破坏技能价值）
SEM = {
    "name_labeled": r"(?:原告|被告|申请人|被申请人|上诉人|被上诉人|第三人|委托代理人|代理人"
                    r"|当事人|委托人|客户|法定代表人|股东|证人)[：:\s]{0,2}([\u4e00-\u9fa5]{2,4})",
    "amount":       r"\d[\d,]{2,}(?:\.\d{1,2})?\s*(?:万元|元)",
}

# 第三方来源痕迹（出现即判非自建，不得上传）
EXT = {
    "clawhub":   r"clawhub\.ai|clawhub\.com",
    "publisher": r"##\s*Publisher|Publisher:\s*<br>",
    "license_terms": r"License/Terms of Use",
    "skillhub":  r"skillhub\.cn|skills_store_cli",
    "vendor_deli": r"deli-cli|得理",
    "other_brand": r"ivangdavila|openclaw|clawdbot",
}


def scan_text(text, rules):
    out = {}
    for k, pat in rules.items():
        m = re.findall(pat, text)
        if m:
            out[k] = len(m)
    return out


def main():
    units = json.load(open(sys.argv[1], encoding="utf-8"))
    result = []
    for u in units:
        rec = {"name": u["name"], "path": u["path"], "files": 0, "bytes": 0,
               "mech": {}, "sem": {}, "ext": {}, "examples": {}, "skipped_bin": 0}
        for root, _dirs, files in os.walk(u["path"]):
            for fn in files:
                fp = os.path.join(root, fn)
                ext = os.path.splitext(fn)[1].lower()
                if ext not in TEXT_EXT:
                    rec["skipped_bin"] += 1
                    continue
                try:
                    raw = open(fp, "rb").read()
                    rec["bytes"] += len(raw)
                    text = raw.decode("utf-8", "ignore")
                except OSError:
                    continue
                rec["files"] += 1
                for tag, hits in scan_text(text, MECH).items():
                    rec["mech"][tag] = rec["mech"].get(tag, 0) + hits
                for tag, hits in scan_text(text, SEM).items():
                    rec["sem"][tag] = rec["sem"].get(tag, 0) + hits
                    if tag == "name_labeled":
                        for v in re.findall(SEM[tag], text)[:3]:
                            rec["examples"].setdefault("names", [])
                            if v not in rec["examples"]["names"]:
                                rec["examples"]["names"].append(v)
                for tag, hits in scan_text(text, EXT).items():
                    rec["ext"][tag] = rec["ext"].get(tag, 0) + hits
        result.append(rec)
    json.dump(result, open(sys.argv[2], "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    # 摘要
    print(f"{'单元':<48}{'文件':>5}{'机械':>6}{'语义':>6}{'三方':>6}")
    for r in sorted(result, key=lambda x: -(sum(x['mech'].values()) + sum(x['sem'].values()))):
        nm = r["name"].split("/")[-1][:46]
        print(f"{nm:<48}{r['files']:>5}{sum(r['mech'].values()):>6}"
              f"{sum(r['sem'].values()):>6}{sum(r['ext'].values()):>6}")
    print("\n三方痕迹明细:")
    for r in result:
        if r["ext"]:
            print(" ", r["name"], r["ext"])


if __name__ == "__main__":
    main()
