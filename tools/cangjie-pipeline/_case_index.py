# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""case 池索引生成：民事 case_all.md + 刑事 case_all.md → 按案由分组的案例索引"""
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")

def build_index(src, out, title):
    t = open(src, encoding="utf-8").read()
    blocks = re.split(r"\n(?=- id: )", t)
    entries = []
    for b in blocks:
        if not b.startswith("- id: "):
            continue
        m = re.search(r"^- id: (\S+)", b, re.M)
        tm = re.search(r"^  (?:title|term): (.+)$|^- (?:title|term): (.+)$", b, re.M)
        if m and tm:
            entries.append((m.group(1), (tm.group(1) or tm.group(2)).strip().strip('"')))
    # 按案由关键词粗分组
    groups = {
        "合同": ["合同", "买卖", "借贷", "租赁", "承揽", "服务", "物业", "旅游"],
        "建设工程": ["建工", "工程", "施工", "发包", "承包", "价款"],
        "公司股权": ["公司", "股权", "股东", "出资", "决议", "解散", "清算", "合伙"],
        "婚姻家庭": ["婚姻", "夫妻", "离婚", "抚养", "继承", "遗嘱", "遗产", "彩礼", "监护"],
        "劳动": ["劳动", "加班", "工伤", "竞业", "工资", "退休", "社保"],
        "侵权": ["侵权", "伤害", "赔偿", "产品", "饲养", "高空", "名誉", "人身", "死亡"],
        "物权": ["物权", "所有权", "共有", "相邻", "土地", "承包", "征收", "宅基地", "登记"],
        "执行": ["执行", "异议", "拍卖", "参与分配", "冻结", "追加"],
        "金融票据": ["票据", "保险", "证券", "银行", "信用卡", "保理", "融资"],
        "刑事·人身": ["故意杀人", "故意伤害", "强奸", "猥亵", "绑架", "拐卖", "抢劫", "绑架"],
        "刑事·财产经济": ["盗窃", "诈骗", "敲诈", "侵占", "挪用", "非法经营", "集资", "洗钱", "走私", "税务", "虚开"],
        "刑事·毒品": ["毒品", "贩毒", "运毒", "制毒", "持有"],
        "刑事·职务": ["贪污", "受贿", "行贿", "渎职", "滥用职权"],
        "刑事·公共秩序": ["交通肇事", "危险驾驶", "妨害公务", "寻衅滋事", "黑社会", "涉黑", "传销", "赌博", "卖淫"],
        "刑事·程序证据": ["自首", "立功", "证据", "死刑", "时效", "管辖", "引渡", "没收"],
    }
    out_lines = [f"# {title}", "", f"- 来源: {os.path.basename(src)}（{len(entries)} 条精选案例）", "- 用法: 按案由找案例 → 回 candidates/{os.path.basename(src)} 查详情（案情/裁判要旨）", ""]
    assigned = {}
    for eid, key in entries:
        hit = "其他"
        for g, kws in groups.items():
            if any(k in key for k in kws):
                hit = g
                break
        assigned.setdefault(hit, []).append((eid, key))
    for g in list(groups.keys()) + ["其他"]:
        if g not in assigned:
            continue
        out_lines.append(f"## {g}（{len(assigned[g])}）")
        for eid, key in sorted(assigned[g], key=lambda x: int(re.search(r"\d+", x[0]).group())):
            out_lines.append(f"- {eid} {key[:80]}")
        out_lines.append("")
    open(out, "w", encoding="utf-8").write("\n".join(out_lines))
    print(f"{out}: {len(entries)} 条 → {len([1 for g in assigned if assigned[g]])} 组")

build_index(r"[本地路径]",
            r"[本地路径]", "民事案例池索引")
build_index(r"[本地路径]",
            r"[本地路径]", "刑事案例池索引")
print("DONE")
