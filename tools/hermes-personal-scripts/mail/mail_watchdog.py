#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""邮件线看护（no_agent 定时任务专用，零模型依赖）

检查项：
  ① 巡检任务最近 26 小时内的失败/未知执行——失败通知被系统静默（已确认签名、投递失败等）的，此处补告警；
  ② 已扫描但未送达的邮件（state.json 送达位点落后 / pending 非空）持续超过 90 分钟——告警；
  ③ 白天超过 16 小时没有任何一次巡检运行动静（completed 行与 state.json last_run 均无）——疑似未运行/停摆告警（每日至多一条）；
  ④ 巡检任务最近一次投递失败（jobs.json last_delivery_error 新近非空）。

输出非空 = 由调度器按 no_agent 规则投递；输出为空 = 静默。
同一事项只告警一次（watchdog_state.json 去重；事项消解后新事项键可再次触发）。
--explain 打印判断过程（不写状态）；--selftest 打印一条合成告警样例。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
HOME = BASE.parent.parent
MAIL_STATE = BASE / "state.json"
WSTATE = BASE / "watchdog_state.json"
JOBS = HOME / "cron" / "jobs.json"
DB = HOME / "cron" / "executions.db"
JOB_ID = "34c9b0072750"
CN_TZ = timezone(timedelta(hours=8))

EXEC_WINDOW_HOURS = 26.0        # 失败执行的回看窗口
UNDELIVERED_AGE_MIN = 90.0      # 未送达持续多久才告警（避开运行中窗口）
STALE_AFTER_HOURS = 16.0        # 超过该时长没有巡检运行动静（completed/last_run）→ 停摆告警
STALE_HOUR_FROM = 8             # 仅在该时针之后做停摆判断

CN = {"suppressed_acked": "（该错误此前被系统『确认』过，默认不再重复提醒，此处补报）",
      "suppressed": "（失败提醒被系统静默，此处补报）",
      "failed": "（失败提醒本身投递失败，此处补报）",
      "queued": "（失败提醒仍在送达队列）"}


def now():
    return datetime.now(CN_TZ)


def _parse_dt(s):
    try:
        dt = datetime.fromisoformat(str(s))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CN_TZ)
        return dt
    except Exception:
        return None


OBS_ERRORS = []          # 本轮观测源故障：读不到 ≠ 没有内容，必须出声


def obs_error(source, detail):
    OBS_ERRORS.append({"source": source, "detail": detail})


def load_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def load_json_obs(path, source, default=None):
    """读 JSON 并登记观测故障；不把读取异常折叠成"没有内容"。"""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        obs_error(source, f"{path.name} 读取失败（{type(exc).__name__}）")
        return default


def save_wstate(ws):
    tmp = WSTATE.parent / (WSTATE.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(ws, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, WSTATE)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _db():
    return sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=5)


def recent_failed_executions():
    """最近窗口内、通知未可靠送达的失败/未知执行。"""
    out = []
    if not DB.exists():
        obs_error("执行库", "cron/executions.db 不存在，无法核对巡检失败记录")
        return out
    try:
        con = _db()
        rows = con.execute(
            "SELECT id, status, finished_at, error, delivery_outcome FROM executions "
            "WHERE job_id=? AND status IN ('failed','unknown') "
            "ORDER BY finished_at DESC LIMIT 20", (JOB_ID,)).fetchall()
        con.close()
    except Exception as exc:
        obs_error("执行库", f"失败记录查询失败（{type(exc).__name__}）")
        return out
    for rid, status, finished, err, outcome in rows:
        fin = _parse_dt(finished)
        if fin is None:
            continue
        if (now() - fin).total_seconds() / 3600.0 > EXEC_WINDOW_HOURS:
            continue
        outcome = outcome or ""
        if outcome in ("delivered", "queued"):
            continue  # 已投递/在途的不重复告警
        first = (err or "").strip().splitlines()[0][:100] if (err or "").strip() else ""
        out.append({"key": f"exec:{rid}", "status": status,
                    "when": fin.strftime("%Y-%m-%d %H:%M"), "error": first, "outcome": outcome})
    return out


def active_run_exists():
    """巡检任务当前是否正在运行（避免把运行中窗口误报为『未送达』）。"""
    if not DB.exists():
        obs_error("执行库", "cron/executions.db 不存在，无法判断巡检是否正在运行")
        return False
    try:
        con = _db()
        rows = con.execute(
            "SELECT claimed_at FROM executions WHERE job_id=? AND status IN ('claimed','running') "
            "ORDER BY claimed_at DESC LIMIT 3", (JOB_ID,)).fetchall()
        con.close()
    except Exception as exc:
        obs_error("执行库", f"运行状态查询失败（{type(exc).__name__}）")
        return False
    for (claimed,) in rows:
        dt = _parse_dt(claimed)
        if dt and (now() - dt).total_seconds() < 3 * 3600:
            return True
    return False


def last_completed_at():
    """最近一次“巡检有动静”的时间：completed 行 与 state.json last_run 取较新者。

    2026-10-02 容错：调度器/网关更新重启会把已实际运行的一轮留成非终态（unknown），
    只认 completed 行会把“运行过但记账被截断”误报为“停摆”。巡检每次运行都会刷新
    state.json 的 last_run，故一并采信；真正的失败/未知执行由 ① 项（exec: 键）
    专责告警，本项只用于识别“完全没有运行动静”的停摆。
    """
    if not DB.exists():
        obs_error("执行库", "cron/executions.db 不存在，无法判断最近一次成功巡检")
        return None
    try:
        con = _db()
        row = con.execute(
            "SELECT finished_at FROM executions WHERE job_id=? AND status='completed' "
            "ORDER BY finished_at DESC LIMIT 1", (JOB_ID,)).fetchone()
        con.close()
    except Exception as exc:
        obs_error("执行库", f"完成时间查询失败（{type(exc).__name__}）")
        return None
    dt = _parse_dt(row[0]) if row else None
    st = load_json(MAIL_STATE, {}) or {}
    if isinstance(st, dict):
        inbox = st.get("INBOX")
        if isinstance(inbox, dict):
            lr = _parse_dt(inbox.get("last_run"))
            if lr and (dt is None or lr > dt):
                dt = lr
    return dt


def undelivered_info():
    st = load_json_obs(MAIL_STATE, "邮件状态", {}) or {}
    if not isinstance(st, dict):
        obs_error("邮件状态", "state.json 结构异常，未能读取送达位点")
        return None
    e = st.get("INBOX")
    if not isinstance(e, dict):
        obs_error("邮件状态", "state.json 缺少 INBOX 送达位点")
        return None
    if "last_uid" not in e:
        obs_error("邮件状态", "缺少 last_uid 字段，未能读取送达位点")
        return None
    raw_uid = e.get("last_uid")
    raw_del = e.get("last_delivered_uid", e.get("last_uid"))
    for _label, _val in (("last_uid", raw_uid), ("last_delivered_uid", raw_del)):
        if isinstance(_val, bool):
            obs_error("邮件状态", f"{_label} 为布尔值，未能读取")
            return None
        if isinstance(_val, float) and not _val.is_integer():
            obs_error("邮件状态", f"{_label} 为小数，未能读取")
            return None
    try:
        last_uid = int(raw_uid or 0)
        del_uid = int(raw_del if raw_del is not None else 0)
    except (TypeError, ValueError):
        obs_error("邮件状态", "送达位点字段非数值，未能读取")
        return None
    if last_uid < 0 or del_uid < 0:
        obs_error("邮件状态", "送达位点字段为负数，未能读取")
        return None
    pending = e.get("pending", [])
    if pending is None:
        pending = []
    if not isinstance(pending, list):
        obs_error("邮件状态", "pending 字段非列表，未能核验未送达数量")
        return None
    gap = max(0, last_uid - del_uid)
    if gap <= 0 and not pending:
        return None
    return {"last_uid": last_uid, "delivered_uid": del_uid, "gap": gap, "pending": len(pending)}


def delivery_error_info():
    jobs = load_json_obs(JOBS, "任务定义", {}) or {}
    jlist = jobs.get("jobs") if isinstance(jobs, dict) else None
    if not isinstance(jlist, list):
        obs_error("任务定义", "jobs 字段缺失或非列表，未能核验投递错误")
        return None
    for j in jlist:
        if isinstance(j, dict) and j.get("id") == JOB_ID:
            err = j.get("last_delivery_error")
            lrun = _parse_dt(j.get("last_run_at"))
            if err and lrun and (now() - lrun).total_seconds() < EXEC_WINDOW_HOURS * 3600:
                return {"when": lrun.strftime("%Y-%m-%d %H:%M"), "error": str(err)[:140]}
            return None
    obs_error("任务定义", f"未找到目标任务 {JOB_ID}，未能核验投递错误")
    return None


def compose(findings):
    lines = ["⚠️ 邮件巡检看护（自动告警）"]
    for f in findings:
        lines.append(f"- {f['text']}")
    lines.append(f"（检查时间 {now().strftime('%Y-%m-%d %H:%M')}）")
    return "\n".join(lines)


def collect_findings(ws, in_progress):
    findings = []
    alerted = set(ws.get("alerted", []))

    for f in recent_failed_executions():
        if f["key"] not in alerted:
            note = CN.get(f["outcome"], "")
            findings.append({"key": f["key"], "type": "exec",
                             "text": "巡检运行未成功：%s（%s：%s）%s。相关未送达内容将由下轮巡检自动补报。"
                                     % (f["when"], f["status"], f["error"] or "见执行记录", note)})

    u = undelivered_info()
    mail_state_obs = any(e["source"] == "邮件状态" for e in OBS_ERRORS)
    if mail_state_obs or in_progress:
        # 观测失败或巡检正在运行：本轮无法判断是否已送达 —— 冻结计时，既不清空也不新增
        pass
    elif u:
        key = f"undelivered:{u['last_uid']}"
        tracked = ws.setdefault("undelivered_since", {})
        for k in list(tracked):
            try:
                if int(str(k).split(":")[1]) <= u["delivered_uid"]:
                    tracked.pop(k, None)
            except Exception:
                tracked.pop(k, None)
        since = _parse_dt(tracked.get(key))
        if since is None:
            tracked[key] = now().isoformat(timespec="seconds")
        elif (now() - since).total_seconds() >= UNDELIVERED_AGE_MIN * 60 and key not in alerted:
            mins = int((now() - since).total_seconds() // 60)
            n = u["pending"] or u["gap"]
            findings.append({"key": key, "type": "undelivered",
                             "text": "有 %d 封邮件已扫描但超过 %d 分钟未送达（补报待处理）——下次巡检会自动补报；若巡检长时间未运行，请核查。" % (n, mins)})
    else:
        # 只有确认"确实没有未送达项"时才清空计时
        ws["undelivered_since"] = {}

    lc = last_completed_at()
    if lc is not None and now().hour >= STALE_HOUR_FROM and not in_progress:
        hours = (now() - lc).total_seconds() / 3600.0
        if hours > STALE_AFTER_HOURS:
            key = f"stale:{now().strftime('%Y-%m-%d')}"
            if key not in alerted:
                findings.append({"key": key, "type": "stale",
                                 "text": "已超过 %.0f 小时无任何巡检运行动静（最近一次运行/完成 %s）——巡检可能未运行，请核查。"
                                         % (hours, lc.strftime("%Y-%m-%d %H:%M"))})

    d = delivery_error_info()
    if d:
        key = f"delivery:{d['when']}"
        if key not in alerted:
            findings.append({"key": key, "type": "delivery",
                             "text": "巡检最近一次投递未成功（%s）：%s" % (d["when"], d["error"])})

    # 观测源（执行库／邮件状态／任务定义）读取失败：读不到不等于"没有问题"。
    # 合并成一条，且关键信息放在前 180 字符内——非零退出时调度器的失败摘要会压平并截断正文
    # （hermes-agent/cron/scheduler_failure_copy.py:112-118），正文必须自带能被读到的结论。
    seen_sources = []
    for e in OBS_ERRORS:
        if e["source"] not in seen_sources:
            seen_sources.append(e["source"])
    # 源级身份：每个失败源一个键（observe:<源>）。持续故障不重复提醒；新增源单独提醒一次；
    # 源恢复只清该源的键；全部恢复后清空。既避免集合抖动重报（复核 B1b-N03），
    # 又不让一个持续故障吞掉新增源的失明（复核 B1c-N03）。
    # 本条置于 findings 首位：失败摘要只保留前 180 字符。
    if seen_sources:
        fresh = [s for s in seen_sources if f"observe:{s}" not in alerted]
        if fresh:
            findings.insert(0, {"key": f"observe:{fresh[0]}", "type": "observe",
                                "text": "看护检查未完成：%d 个观测源读取失败（%s）——本轮不能据此认为邮件巡检正常，请核查。"
                                        % (len(seen_sources), "/".join(sorted(seen_sources)))})
        # 源级键由本函数统一维护（main 追加时去重）：保留仍在故障的源、清掉已恢复的源、
        # 补齐本轮所有故障源的键 —— 使持续故障不重报、每个新增源只提醒一次
        kept = [k for k in ws.get("alerted", [])
                if not str(k).startswith("observe:")
                or str(k)[len("observe:"):] in seen_sources]
        for s in seen_sources:
            k = f"observe:{s}"
            if k not in kept:
                kept.append(k)
        ws["alerted"] = kept
    else:
        ws["alerted"] = [k for k in ws.get("alerted", []) if not str(k).startswith("observe:")]
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--explain", action="store_true", help="打印判断过程，不写状态、不投递")
    ap.add_argument("--selftest", action="store_true", help="打印合成告警样例")
    args = ap.parse_args()

    if args.selftest:
        sample = [
            {"key": "exec:TEST", "type": "exec",
             "text": "巡检运行未成功：2026-09-28 17:37（failed：RuntimeError: Connection error.）（失败提醒被系统静默，此处补报）。相关未送达内容将由下轮巡检自动补报。"},
            {"key": "undelivered:TEST", "type": "undelivered",
             "text": "有 3 封邮件已扫描但超过 95 分钟未送达（补报待处理）——下次巡检会自动补报；若巡检长时间未运行，请核查。"},
        ]
        print(compose(sample))
        return 0

    OBS_ERRORS.clear()   # 每次运行独立：避免重入或测试时残留上一轮故障
    wstate_unusable = False
    try:
        if not WSTATE.exists():
            ws = {}                      # 首次运行允许初始化，不算观测故障
        else:
            ws = load_json_obs(WSTATE, "看护状态", None)
            if ws is None:
                # 读取失败已登记为观测故障：不覆盖原文件（保留可恢复证据），按空状态继续判断
                wstate_unusable = True
                ws = {}
            elif not isinstance(ws, dict):
                obs_error("看护状态", "watchdog_state.json 结构异常（非对象），未覆盖原文件")
                wstate_unusable = True
                ws = {}
        ws.setdefault("alerted", [])
        in_progress = active_run_exists()
        findings = collect_findings(ws, in_progress)
        new = [f for f in findings if f["key"] not in set(ws.get("alerted", []))]
        if args.explain:
            print("in_progress:", in_progress)
            print("findings:", json.dumps(findings, ensure_ascii=False))
            print("obs_errors:", json.dumps(OBS_ERRORS, ensure_ascii=False))
            print("would_alert:", bool(new))
            if new:
                print("---- 告警样例 ----")
                print(compose(new))
            else:
                print("（无新告警项，静默）")
            return 3 if OBS_ERRORS else 0
        if new:
            print(compose(new))
            ws["alerted"] = list(dict.fromkeys(
                list(ws.get("alerted", [])) + [f["key"] for f in new]))[-200:]
            ws["last_alert_at"] = now().isoformat(timespec="seconds")
        if wstate_unusable:
            # 坏状态不覆盖原文件：保留可恢复证据，避免用空状态顶掉去重记录与未送达计时
            print("⚠️ 邮件巡检看护：看护状态文件不可用，本轮未写入新状态（原文件保留）；"
                  "请核查 scripts/mail/watchdog_state.json。")
        else:
            save_wstate(ws)
    except Exception as exc:  # 脚本自身异常也要出声，不能静默失效
        print(f"⚠️ 邮件巡检看护脚本异常：{type(exc).__name__}: {exc}")
        return 3
    # 观测源故障存在时非零退出，让调度器也看到"检查未完成"（非零时 stdout 会随失败信息保留）
    return 3 if OBS_ERRORS else 0


if __name__ == "__main__":
    raise SystemExit(main())
