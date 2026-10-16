# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Cron：供应商额度/余额看门狗（no-agent，零 token）。

按 plugins/provider-limits/state/config.json 的阈值检查订阅窗口与账户余额：
  · 有新告警 / 级别升级 / 冷却期满  → 打印提醒（stdout 直接投递）
  · 全部正常                        → 不输出（静默，不产生任何消息）
  · 之前的告警消失                  → 打印一条「已恢复」
  · --daily                         → 无论有无告警都打印一份额度日报
  · --force                         → 忽略冷却，立即重发全部当前告警

排程（hermes cron create --no-agent --script provider_limits_watchdog.py）：
  · 整点看门狗  0 * * * *
  · 每早日报    0 8 * * *   （加 --daily）

阈值、静默名单、冷却时长都在 config.json 里改，不用动这个脚本。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from lawyer_quality_state import atomic_json, file_lock

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / "AppData" / "Local" / "hermes")
sys.path.insert(0, str(HERMES_HOME / "hermes-agent"))

PLUGIN_API = HERMES_HOME / "plugins" / "provider-limits" / "dashboard" / "plugin_api.py"
STATE_FILE = HERMES_HOME / "plugins" / "provider-limits" / "state" / "alert_state.json"

LEVEL_TEXT = {"critical": "严重", "warn": "提醒"}


def _load_plugin():
    spec = importlib.util.spec_from_file_location("provider_limits_api", PLUGIN_API)
    module = importlib.util.module_from_spec(spec)
    sys.modules["provider_limits_api"] = module
    spec.loader.exec_module(module)
    return module


def _read_state() -> tuple[dict, str | None]:
    """返回 (状态, 错误说明)。文件不存在＝首次运行（不是错误）；存在但读不出＝观测故障。"""
    if not STATE_FILE.exists():
        return {}, None
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, f"{type(exc).__name__}"
    if not isinstance(data, dict):
        return {}, "结构异常（非对象）"
    return data, None


def _write_state(state: dict) -> str | None:
    """返回 None＝成功，否则返回错误说明。保存失败必须让调用方知道，不能静默。"""
    try:
        atomic_json(STATE_FILE, state)
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _alert_line(alert: dict) -> str:
    detail = f"：{alert['detail']}" if alert.get("detail") else ""
    return f"- [{LEVEL_TEXT.get(alert.get('level'), alert.get('level'))}] " \
           f"{alert.get('provider')} {alert.get('title')}{detail}"


def _digest(data: dict) -> list[str]:
    lines: list[str] = []
    stamp = _parse(data.get("fetched_at"))
    local = stamp.astimezone() if stamp else datetime.now().astimezone()
    lines.append(f"额度日报（{local.strftime('%m-%d %H:%M')}）")
    lines.append("")
    subs = [e for e in data.get("subscription", []) if e.get("status") == "ok"]
    if subs:
        lines.append("订阅")
        for entry in subs:
            plan = f"（{entry['plan']}）" if entry.get("plan") else ""
            windows = "｜".join(f"{w['label']} {round(w.get('pct') or 0)}%" for w in entry.get("windows") or [])
            joined = "；".join(entry.get("details") or [])
            details = joined if len(joined) <= 80 else f"{joined[:78]}…"
            extra = f"｜{details}" if details else ""
            lines.append(f"- {entry['name']}{plan}：{windows}{extra}")
    others = [e for e in data.get("subscription", []) if e.get("status") != "ok"]
    balances = [e for e in data.get("balance", []) if e.get("status") == "ok"]
    if balances:
        lines.append("")
        lines.append("账户余额")
        for entry in balances:
            balance = entry.get("balance") or {}
            amount = balance.get("amount")
            currency = str(balance.get("currency") or "").upper()
            symbol = {"USD": "$", "CNY": "¥"}.get(currency, "")
            text = f"{'-' if (amount or 0) < 0 else ''}{symbol}{abs(amount):.2f}" if amount is not None else "—"
            tail = []
            if currency and not symbol:
                tail.append(currency)
            rate = entry.get("rate") or {}
            if rate.get("days_left") is not None:
                tail.append(f"日均 ${rate.get('daily_usd')}｜约 {rate['days_left']} 天")
            lines.append(f"- {entry['name']}：{text}" + (f"（{'，'.join(tail)}）" if tail else ""))
    skipped = [f"{e['name']} {e.get('error') or ''}".strip() for e in others + data.get("balance", [])
               if e.get("status") not in ("ok",)]
    if skipped:
        lines.append("")
        lines.append("未取到：" + "；".join(skipped[:6]))
    usage = data.get("local_usage") or {}
    if usage.get("available"):
        cells = "｜".join(f"{p['label']} ${p['cost_usd']:.2f}" for p in usage.get("periods") or [])
        lines.append("")
        lines.append(f"本机消耗（Hermes 估算）：{cells}")
    return lines


def _main_locked() -> int:
    argv = sys.argv[1:]
    daily = "--daily" in argv
    force = "--force" in argv
    override = None
    if "--cooldown-hours" in argv:
        try:
            override = float(argv[argv.index("--cooldown-hours") + 1])
        except (IndexError, ValueError):
            override = None

    try:
        api = _load_plugin()
        config = api._config()
        cooldown_hours = float(override if override is not None else (config.get("cooldown_hours") or 12.0))
        data = api._cached_overview(force=True)
    except Exception as exc:
        print(f"额度看门狗运行失败：{type(exc).__name__}: {exc}")
        return 1
    if not isinstance(data, dict) or not isinstance(data.get("alerts"), list):
        # 观测未知：不得据此判定"已恢复"（否则一次查询异常会伪造一批恢复通知）
        print("额度看门狗：额度概览未返回有效 alerts（观测未知），本轮不判定恢复、不更新状态")
        return 2
    alerts = data["alerts"]

    now = datetime.now(timezone.utc)
    state, state_err = _read_state()
    if state_err:
        print(f"额度看门狗：状态文件读取失败（{state_err}），本轮不判定恢复、不覆盖状态")
        return 2
    seen = dict(state.get("seen") or {})
    current = {a["id"] for a in alerts}

    fresh: list[dict] = []
    escalated: list[dict] = []
    for alert in alerts:
        record = seen.get(alert["id"])
        if force or record is None or (alert.get("level") == "critical" and record.get("level") != "critical"):
            (escalated if record else fresh).append(alert)
            continue
        last = _parse(record.get("notified_at"))
        if last is None or (now - last).total_seconds() >= cooldown_hours * 3600:
            fresh.append(alert)

    recovered = [{"id": aid, "provider": rec.get("provider"), "title": rec.get("title")}
                 for aid, rec in seen.items() if aid not in current]

    output: list[str] = []
    if daily:
        output.extend(_digest(data))
        if recovered:
            output.append("")
            output.append("已恢复：" + "；".join(f"{r['provider']} {r['title']}" for r in recovered))
    else:
        notify = fresh + escalated
        if notify:
            output.append(f"额度提醒（{len(notify)} 条）")
            output.extend(_alert_line(a) for a in notify[:8])
            if len(notify) > 8:
                output.append(f"- 另有 {len(notify) - 8} 条，见桌面右侧「额度与余额」面板")
        if recovered:
            if output:
                output.append("")
            output.append("已恢复：" + "；".join(f"{r['provider']} {r['title']}" for r in recovered))

    for alert in fresh + escalated:
        seen[alert["id"]] = {"level": alert.get("level"), "title": alert.get("title"),
                             "provider": alert.get("provider"), "notified_at": now.isoformat(timespec="seconds")}
    for record in recovered:
        seen.pop(record["id"], None)

    save_err = None if '--preview' in argv else _write_state({"seen": seen, "last_run": now.isoformat(timespec="seconds"),
                             "last_alert_count": len(alerts), "last_alert_ids": sorted(current)})
    if save_err:
        print(f"额度看门狗：状态保存失败（{save_err}）——去重记录未落盘，下轮可能重复提醒")
        return 3

    if output:
        print("\n".join(output))
    return 0


def main() -> int:
    # 日报和整点看门狗的读-判定-写必须处于同一互斥区，原子替换并非事务锁。
    try:
        with file_lock(STATE_FILE.with_suffix('.lock'), timeout=15):
            return _main_locked()
    except (OSError, TimeoutError) as exc:
        print(f'额度检查未完成：共享状态正在使用或不可写（{type(exc).__name__}），未覆盖去重记录')
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
