# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""刑事 principle 按主题拆分（合集 694 + 单本 435 → 8 域子文件）"""
import os, re, sys, glob
sys.stdout.reconfigure(encoding="utf-8")

base = r"[本地路径]"

groups = {
    "危害公共安全": ["交通肇事", "危险驾驶", "危险作业", "爆炸", "放火", "枪支", "弹药", "醉驾", "飙车", "以危险方法危害公共安全", "破坏交通", "妨害安全驾驶", "失火", "重大责任事故", "安全事故", "危险物质"],
    "侵犯财产": ["盗窃", "抢劫", "抢夺", "诈骗", "敲诈勒索", "侵占", "职务侵占", "挪用资金", "拒不执行", "拒不支付", "掩饰", "隐瞒犯罪所得", "销赃", "赃物", "碰瓷", "抢夺罪"],
    "经济犯罪": ["非法经营", "传销", "集资", "非法吸收", "洗钱", "金融凭证", "贷款", "票据", "信用卡", "内幕", "证券", "期货", "走私", "出口退税", "虚开", "逃税", "税收", "商标", "著作权", "专利", "商业秘密", "虚假广告", "开设赌场", "赌博", "卖淫", "组织卖淫", "容留", "淫秽", "帮信", "拒不支付劳动报酬"],
    "毒品犯罪": ["毒品", "贩毒", "运毒", "制毒", "藏毒", "吸毒", "麻精药品", "制毒物品", "罂粟", "大麻", "冰毒", "海洛因", "氯胺酮", "美沙酮"],
    "职务犯罪": ["贪污", "受贿", "行贿", "挪用公款", "渎职", "玩忽职守", "滥用职权", "私分", "巨额财产", "徇私", "受贿罪", "贪污罪"],
    "人身犯罪": ["故意杀人", "故意伤害", "过失致人死亡", "强奸", "猥亵", "绑架", "拐卖", "非法拘禁", "正当防卫", "防卫过当", "侮辱", "诽谤", "寻衅滋事", "聚众斗殴", "虐待", "遗弃", "故意伤害罪", "杀人"],
    "黑恶犯罪": ["黑社会", "恶势力", "套路贷", "软暴力", "保护伞", "涉黑"],
    "程序证据": ["自首", "立功", "坦白", "死刑", "证据", "鉴定", "口供", "翻供", "非法证据", "证明", "时效", "追诉", "管辖", "引渡", "缺席审判", "没收", "折抵", "缓刑", "假释", "减刑", "数罪并罚", "累犯", "罚金", "刑罚", "上诉", "再审", "认罪认罚"],
}

def classify(key, b):
    for gname, kws in groups.items():
        if any(k in key for k in kws):
            return gname
    return None

for src in ["principle_all.md", "principle_single_all.md"]:
    t = open(os.path.join(base, src), encoding="utf-8").read()
    blocks = re.split(r"\n(?=- id: )", t)
    assigned = {}
    unassigned = 0
    for b in blocks:
        if not b.startswith("- id: "):
            continue
        m = re.search(r"^  (?:title|term): (.+)$|^- (?:title|term): (.+)$", b, re.M)
        key = (m.group(1) or m.group(2)) if m else ""
        g = classify(key, b)
        if g:
            assigned.setdefault(g, []).append(b)
        else:
            unassigned += 1
            assigned.setdefault("程序证据", []).append(b)  # 兜底
    tag = "hj" if src == "principle_all.md" else "xs"
    for gname, items in assigned.items():
        fn = os.path.join(base, f"principle_{tag}_{gname}.md")
        header = f"# principle 子集：{gname}（{len(items)} 条）\n- 来源: {src} 主题拆分\n\n"
        open(fn, "w", encoding="utf-8").write(header + "\n".join(items) + "\n")
    print(f"{src}: 未分类兜底 {unassigned} 条")
    for gname in groups:
        print(f"  {gname}: {len(assigned.get(gname, []))} 条")
print("DONE")
