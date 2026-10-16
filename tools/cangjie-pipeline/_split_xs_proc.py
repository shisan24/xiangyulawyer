# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""程序证据域二次拆分：自首立功 / 证据认定 / 程序刑罚"""
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")

base = r"[本地路径]"

subs = {
    "自首立功": ["自首", "立功", "坦白", "投案", "归案", "揭发", "检举", "到案"],
    "证据认定": ["证据", "鉴定", "口供", "翻供", "非法证据", "证明", "推定", "零口供", "质证", "辨认", "声纹", "DNA", "检材", "血液酒精"],
    "程序刑罚": ["时效", "追诉", "管辖", "引渡", "缺席", "没收", "折抵", "缓刑", "假释", "减刑", "数罪并罚", "累犯", "罚金", "刑罚", "上诉", "再审", "认罪认罚", "并罚", "执行", "刑事和解"],
}

for tag in ["hj", "xs"]:
    for gname, items in [("程序证据", None)]:
        fn = os.path.join(base, f"principle_{tag}_{gname}.md")
        t = open(fn, encoding="utf-8").read()
        blocks = re.split(r"\n(?=- id: )", t)
        out = {}
        unc = []
        for b in blocks:
            if not b.startswith("- id: "):
                continue
            m = re.search(r"^  (?:title|term): (.+)$|^- (?:title|term): (.+)$", b, re.M)
            key = (m.group(1) or m.group(2)) if m else ""
            hit = None
            for sname, kws in subs.items():
                if any(k in key for k in kws):
                    hit = sname
                    break
            if hit:
                out.setdefault(hit, []).append(b)
            else:
                unc.append(b)
        for sname, items in out.items():
            newfn = os.path.join(base, f"principle_{tag}_{sname}.md")
            header = f"# principle 子集：{sname}（{len(items)} 条）\n- 来源: {fn} 二次拆分\n\n"
            open(newfn, "w", encoding="utf-8").write(header + "\n".join(items) + "\n")
            print(f"{tag}_{sname}: {len(items)} 条")
        # 未命中归入程序刑罚
        newfn = os.path.join(base, f"principle_{tag}_程序刑罚.md")
        with open(newfn, "a", encoding="utf-8") as f:
            f.write(header + "\n".join(unc) + "\n")
        print(f"{tag}_程序刑罚(追加): {len(unc)} 条")
print("DONE")
