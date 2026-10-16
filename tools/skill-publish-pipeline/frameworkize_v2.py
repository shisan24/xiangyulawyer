# -*- coding: utf-8 -*-
"""公开库框架化 v2：从清洗版生成骨架 SKILL.md。
修正：CRLF 归一、按块剔除（标题与其内容同去）、有序列表重编号、去重复标题。
用法: python frameworkize_v2.py <units.json> <sanitized_dir> <out_dir> <report.md>
"""
import json
import os
import re
import sys

DROP = re.compile(
    r"实测|实证|案验证|原稿|本案|该案|此案|本类|案例|判决|裁定|证据册|举证|质证|庭审|我方|用户|客户|律师"
    r"|贵司|贵方|本方|他方|对方|当事|委托人|本所|经办"
    r"|【主体】|【律所】|【某法院】|【某仲裁委】|【某单位】|【金额】|【案号】|【律师】|【文号】|【数量】|【本机标识】"
    r"|【主体】|【主体】|〔|亿元|【主体】|【主体】|【主体】|扩建|恢复原状|催签|补充协议"
    r"|\[本地路径\]|references/|scripts/|\d{1,3}(?:,\d{3})+|\d{4}-\d{2}-\d{2}|\d{4}年\d{1,2}月"
    r"|\d+万|\d+元|第\d+轮|电话|微信|邮箱|案卷|卷宗|归档|目录路径"
)
# 方法性内容信号：保留的最低门槛（"应/须"单字太宽，会把夹带案名金额的整行放进来，已移除）
KEEP_SIG = re.compile(
    r"应当|必须|不得|可以|建议|注意|风险|要件|步骤|流程|顺序|清单|检查|核对|区分|情形"
    r"|标准|规则|方法|框架|结构|分层|分级|判断|审查|起草|交付|目标|原则|边界|口径|前置|验收"
)
FM = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.S)
HEAD = re.compile(r"^(#{1,6})\s+(.*)$")


def parse_front(text):
    m = FM.match(text)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).split("\n"):
        if ":" in line and not line.startswith((" ", "\t", "-")):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm, text[m.end():]


def renumber(lines):
    n = 0
    out = []
    for ln in lines:
        m = re.match(r"^(\s*)(\d+)([.、)])(\s*)(.*)$", ln)
        if m:
            n += 1
            out.append(f"{m.group(1)}{n}{m.group(3)}{m.group(4)}{m.group(5)}")
        else:
            out.append(ln)
    return out


def frameworkize(text, unit):
    fm, body = parse_front(text)
    body = body.replace("\r", "")
    blocks, cur = [], []
    for ln in body.split("\n"):
        if HEAD.match(ln):
            if cur:
                blocks.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        blocks.append(cur)

    kept_blocks, kept_lines, dropped_lines, seen = [], 0, 0, set()
    for blk in blocks:
        head = blk[0] if HEAD.match(blk[0]) else None
        content, drop_cnt = [], 0
        for ln in (blk[1:] if head else blk):
            if not ln.strip():
                continue
            if HEAD.match(ln):
                if DROP.search(ln):
                    drop_cnt += 1
                    continue
                content.append(ln)
                continue
            if DROP.search(ln) or not KEEP_SIG.search(ln):
                drop_cnt += 1
                continue
            content.append(ln)
        dropped_lines += drop_cnt
        if head:
            if DROP.search(head):
                dropped_lines += 1
                continue
            if not content:          # 标题下内容全被剔除 → 标题同去
                dropped_lines += 1
                continue
            h = HEAD.match(head)
            title, level = h.group(2).strip(), len(h.group(1))
            content = renumber(content)
            if title.lower() == unit.lower() or title in seen:
                kept_blocks.append("\n".join(content))
                kept_lines += len(content)
                continue
            seen.add(title)
            content = [f"{'#' * level} {title}"] + content
        if not content:
            continue
        kept_blocks.append("\n".join(content))
        kept_lines += len(content)

    desc = fm.get("description", "").strip().strip('"')
    if desc.lower().startswith("use when "):
        desc = desc[9:].strip()
    head = [
        "---",
        f"name: {fm.get('name', unit)}",
        f"description: {desc}",
        "version: 1.0.0",
        "author: xiangyulawyer",
        "source: https://github.com/shisan24/xiangyulawyer",
        "---",
        "",
        "> © 2026 xiangyulawyer（github.com/shisan24/xiangyulawyer）· 本技能由作者从执业实务中提炼，"
        "公开版本仅保留方法框架与通用清单，不含任何个案信息。转载或引用请署名。",
        "",
        f"# {unit}",
        "",
    ]
    if desc:
        head += [f"**适用场景**：{desc}", ""]
    body_txt = re.sub(r"\n{3,}", "\n\n", "\n\n".join(kept_blocks).strip())
    if len(body_txt) < 200:
        body_txt = ("## 方法框架\n\n"
                    "本技能的具体工作流程与检查清单在作者本地环境中持续迭代，公开版本仅提供定位说明："
                    "触发条件见上方 description；适用阶段、输入材料、交付物形态请按个案确定。"
                    "如需完整方法，请联系作者。")
        kept_lines = 0
    return "\n".join(head) + "\n" + body_txt + "\n", kept_lines, dropped_lines


def main():
    units = json.load(open(sys.argv[1], encoding="utf-8"))
    src, out_dir = sys.argv[2], sys.argv[3]
    rep = open(sys.argv[4], "w", encoding="utf-8")
    rep.write("| 单元 | 保留行 | 剔除行 | 成稿字数 | 模式 |\n|---|---|---|---|---|\n")
    stats, missing = [], []
    for u in units:
        d = os.path.join(src, u["name"].replace("/", "__"))
        f = os.path.join(d, "SKILL.md")
        if not os.path.isfile(f):
            missing.append(u["name"])
            rep.write(f"| {u['name']} | - | - | - | 无 SKILL.md，跳过 |\n")
            continue
        text = open(f, "rb").read().decode("utf-8", "ignore")
        name = u["name"].split("/")[-1]
        out, kept, dropped = frameworkize(text, name)
        os.makedirs(os.path.join(out_dir, "skills", name), exist_ok=True)
        open(os.path.join(out_dir, "skills", name, "SKILL.md"), "w",
             encoding="utf-8", newline="\n").write(out)
        rep.write(f"| {u['name']} | {kept} | {dropped} | {len(out)} | "
                  f"{'框架' if kept > 0 else '仅定位说明'} |\n")
        stats.append((u["name"], kept, dropped, len(out)))
    rep.close()
    print(f"成稿 {len(stats)} 单元，缺 SKILL.md {len(missing)}：{missing}")
    print(f"平均保留行 {sum(s[1] for s in stats)/max(1,len(stats)):.0f}，"
          f"平均剔除行 {sum(s[2] for s in stats)/max(1,len(stats)):.0f}，"
          f"仅定位说明 {sum(1 for s in stats if s[1]==0)} 个")


if __name__ == "__main__":
    main()
