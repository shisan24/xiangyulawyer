# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
案件时限扫描器
每周一扫描 案件时限台账.md，标记 ≤30 天的紧急/注意项目
"""
import os, re, datetime, json, sys
from pathlib import Path

# 状态集合唯一真源：scripts/lawyer_deadline_core.py（与 lawyer_ops、工作台面板共用）。
# 2026-10-24：本脚本原先硬取前三列、完全不看状态列，已办结与已开庭的条目仍会被报成紧急事项。
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from lawyer_deadline_core import TERMINAL_STATUS, MILESTONE_STATUS
except ImportError:  # 兜底：与 core 同名集合保持一致，两处都必须改时以 core 为准
    TERMINAL_STATUS = {'已完成', '已办结', '已处理', '已取消', '取消', '已撤销', '办结', '完成'}
    MILESTONE_STATUS = {'已开庭', '已提交', '已缴费', '已续冻', '已解除'}

# 台账唯一来源：lawyer-workbench.json 的 deadline_file（2026-09-30 更正：此前写死旧表
# 本机目录/记忆/案件时限台账.md —— 该表 2026-09-17 已被 D 盘现任台账承接并停更）。
_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / "AppData" / "Local" / "hermes"))
_FALLBACK = Path(r"[本地路径]")


def ledger_path() -> Path:
    try:
        cfg = json.loads((_HOME / "lawyer-workbench.json").read_text(encoding="utf-8"))
        p = Path(str(cfg.get("deadline_file", "")).strip())
        if str(p) and p.exists():
            return p
    except (OSError, ValueError, TypeError):
        pass
    return _FALLBACK


DEADLINE_FILE = str(ledger_path())

_TENTATIVE = ("约", "待核实", "待定", "待补", "另定", "未定", "暂定", "待确认", "以判决", "以送达")


def _is_tentative(value) -> bool:
    """台账里的约期/待核实表述 —— 与 lawyer_ops.parse_deadlines 的 pending 同义，不是解析错误。"""
    s = str(value or "").strip()
    return bool(s) and any(t in s for t in _TENTATIVE)


def scan():
    if not os.path.exists(DEADLINE_FILE):
        return "案件时限台账.md 不存在"

    with open(DEADLINE_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    today = datetime.date.today()
    alerts, issues, tentative = [], [], []
    completed, milestones = 0, []
    rows, header_seen = 0, False

    header = None
    # 按表头名称映射列，不硬取列位：真实台账是「案件｜事项｜期限｜状态｜备注」，
    # 状态在第 4 列；此前按 parts[4] 取到的是备注（2026-10-24 Codex 复核指出）。
    for num, line in enumerate(content.split("\n"), 1):
        if "|" not in line:
            continue
        raw = line.strip()
        if re.fullmatch(r"\|?[\s:|\-]+\|?", raw):      # 表头分隔行
            continue
        body = raw.strip()
        if body.startswith("|"):
            body = body[1:]
        if body.endswith("|"):
            body = body[:-1]
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", body)]
        if not any(cells):
            continue
        if header is None:
            if any(k in cells for k in ("案件", "案件名称")):
                header = cells
                header_seen = True
            continue
        if len(cells) != len(header):
            issues.append(f"第{num}行列数与表头不一致（{len(cells)}/{len(header)}），未纳入判断")
            continue
        row = dict(zip(header, cells))
        case = row.get("案件") or row.get("案件名称") or ""
        task = row.get("事项") or ""
        deadline = row.get("期限") or row.get("截止日") or row.get("截止日期") or ""
        status = row.get("状态") or ""
        if not case and not task:
            continue
        rows += 1

        if status in TERMINAL_STATUS:
            completed += 1
            continue
        if status in MILESTONE_STATUS:
            milestones.append(f"[{case}] {task}：{status}（事件已发生，不等于事项办结）")
            continue

        try:
            # 台账里期限常带 markdown 标记（**2026-10-28**、`2026-11-18`），先按 core._MD_STRIP
            # 同口径清掉再加解析；否则真实台账会被整片报成「既非日期也非约期」。
            clean = re.sub(r"[*`_]", "", deadline).strip()
            d = datetime.datetime.strptime(clean, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            if _is_tentative(deadline):
                # 约期/待核实是台账的正常表述，单独归类，不当作解析错误
                tentative.append(f"[{case}] {task}：{deadline}")
            else:
                # 既不是日期也不是约期表述＝真解析问题，必须出声，否则整表会被读成"没有紧急事项"
                issues.append(f"第{num}行 [{case}] {task}：期限既非 YYYY-MM-DD 也非约期表述（{deadline}），未纳入判断")
            continue

        remaining = (d - today).days
        if remaining <= 3:
            alerts.append(f"🔴 [{case}] {task} — {deadline} (仅剩{remaining}天!)")
        elif remaining <= 15:
            alerts.append(f"🟡 [{case}] {task} — {deadline} ({remaining}天)")
        elif remaining <= 30:
            alerts.append(f"🟢 [{case}] {task} — {deadline} ({remaining}天)")

    if not header_seen:
        issues.append("未识别到台账表头（需含「案件」列），本次扫描覆盖不完整")
    if rows == 0:
        issues.append("台账无数据行，尚不能据此确认案件期限已登记完整")

    out = ["📅 案件时限提醒:"] + alerts if alerts else ["✅ 无 ≤30天 的紧急事项"]
    if milestones:
        out.append(f"另有 {len(milestones)} 条为已发生事件（需确认后续动作，不按期限告警）：")
        out.extend("- " + x for x in milestones)
    if completed:
        out.append(f"已办结 {completed} 条，未纳入期限判断。")
    if tentative:
        out.append(f"另有 {len(tentative)} 条为约期或待核实，未纳入期限判断（逐条见台账）。")
    if issues:
        out.append(f"⚠️ 覆盖不完整（{len(issues)} 处）：下列条目未被上述判断覆盖，请核对原台账：")
        out.extend("- " + x for x in issues)
    return "\n".join(out)

if __name__ == "__main__":
    print(scan())
