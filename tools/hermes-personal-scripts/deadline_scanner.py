# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
案件时限扫描器
每周一扫描 案件时限台账.md，标记 ≤30 天的紧急/注意项目
"""
import os, re, datetime, json
from pathlib import Path

# 台账唯一来源：lawyer-workbench.json 的 deadline_file（2026-09-30 更正：此前写死旧表
# 【本机标识】/记忆/案件时限台账.md —— 该表 2026-09-17 已被 D 盘现任台账承接并停更）。
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
    rows, header_seen = 0, False

    # 解析表格行: | 案件 | 事项 | 截止日 | 剩余天数 | 状态 |
    for num, line in enumerate(content.split("\n"), 1):
        if "|" not in line or line.strip().startswith("|-"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if not parts:
            continue
        if parts[0] in ("案件", "案件名称"):
            header_seen = True
            continue
        if len(parts) < 3:
            issues.append(f"第{num}行列数不足，未纳入判断")
            continue
        rows += 1

        case, task, deadline = parts[0], parts[1], parts[2]

        try:
            d = datetime.datetime.strptime(deadline, "%Y-%m-%d").date()
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
    if tentative:
        out.append(f"另有 {len(tentative)} 条为约期或待核实，未纳入期限判断（逐条见台账）。")
    if issues:
        out.append(f"⚠️ 覆盖不完整（{len(issues)} 处）：下列条目未被上述判断覆盖，请核对原台账：")
        out.extend("- " + x for x in issues)
    return "\n".join(out)

if __name__ == "__main__":
    print(scan())
