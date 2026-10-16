# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""principle_all.md 按主题拆分子文件（供速查提炼器定向读取）"""
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")

base = r"[本地路径]"
src = os.path.join(base, "principle_all.md")
t = open(src, encoding="utf-8").read()
blocks = re.split(r"\n(?=- id: )", t)
entries = []
for b in blocks:
    if b.startswith("- id: "):
        m = re.search(r"^  title: (.+)$|^- title: (.+)$", b, re.M)
        key = (m.group(1) or m.group(2)) if m else ""
        entries.append((key, b))

# 主题分类关键词
groups = {
    "建工": ["建工", "工程", "施工", "优先受偿", "实际施工人", "挂靠", "转包", "分包", "黑白合同", "中标", "招投标", "质保金", "垫资", "工期", "验收", "竣工验收", "折价补偿"],
    "借贷担保": ["民间借贷", "利率", "LPR", "职业放贷", "转贷", "复利", "借款", "担保", "保证", "抵押", "质押", "让与担保", "债务加入", "追偿", "定金", "担保人"],
    "合同物权": ["合同", "解除", "违约金", "情势变更", "不可抗力", "买卖", "租赁", "物业", "旅游", "服务", "所有权", "物权", "土地承包", "共有", "相邻", "预告登记", "居住权", "宅基地", "征收", "消费者", "预付"],
    "婚姻继承": ["婚姻", "夫妻", "离婚", "继承", "遗嘱", "遗赠", "抚养", "探望", "监护", "彩礼", "家庭", "同居", "重婚", "家暴", "保护令", "子女", "父母", "遗产"],
    "侵权劳动": ["侵权", "伤害", "饲养", "高空", "产品", "消费", "食品", "名誉", "人格", "赔偿", "误工", "劳动", "加班", "工伤", "竞业", "就业", "用工", "工资", "退休", "社保", "派遣"],
    "程序执行": ["执行", "异议", "诉讼", "证据", "举证", "鉴定", "自认", "保全", "虚假诉讼", "管辖", "时效", "期限", "送达", "再审", "上诉", "起诉", "撤销之诉", "参与分配", "破产"],
}

assigned = {}
unassigned = []
for key, b in entries:
    hit = None
    for gname, kws in groups.items():
        if any(k in key for k in kws):
            hit = gname
            break
    if hit:
        assigned.setdefault(hit, []).append((key, b))
    else:
        unassigned.append((key, b))

# 未命中兜底：按 source_chapter 关键词再分
for key, b in unassigned:
    hit = None
    for gname, kws in groups.items():
        if any(k in b for k in kws):
            hit = gname
            break
    assigned.setdefault(hit or "程序执行", []).append((key, b))

for gname, items in assigned.items():
    fn = os.path.join(base, f"principle_sub_{gname}.md")
    header = f"# principle 子集：{gname}（{len(items)} 条）\n- 来源: principle_all.md 主题拆分\n\n"
    with open(fn, "w", encoding="utf-8") as f:
        f.write(header)
        for key, b in items:
            f.write(b + "\n")
    print(f"{gname}: {len(items)} 条 → {os.path.basename(fn)}")
print(f"总计 {sum(len(v) for v in assigned.values())} 条（源 {len(entries)}）")
