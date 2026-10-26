# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""记忆任务前置判断（v2.2，2026-10-07 修正）—— 任务 a1862a10bebb 使用。

v2 修正上一版的四个语义缺陷（由 09-30 独立核查发现并经复现确认）：
1. 健康核验必须有**有效回执**才算通过：CLI 缺失、空输出、非 JSON、缺有效健康字段 → health=unknown，
   不得记为 clean，也不得在理由里声称"健康正常"。
2. 本地检查状态与处置状态分开：state.local（容量/文件/健康）与 state.action（wake/skip/hold/reuse）。
3. 复用结论的前提是**存在与本轮问题指纹一致的完成回执**（memory-governance-receipt.json）；
   只有请求、没有完成回执时，按有上限的重试唤醒，避免"没评估过"被当成"已评估"。
4. 时段门禁：AGENTS.md 规定后台 08:00–22:00（北京时间）执行。窗口外只做本地检查并记录状态，
   不唤醒模型；到工作时间再分析。
5. （v2.1，2026-10-04）gap 比较与指纹化只用「可行动子集」：doctor._NON_ACTIONABLE_GAPS 中的非行动项（如采样摆动的 worker_capability_unavailable）不参与是否变化的比较、不进入指纹，避免同一积压因采样窗口不同反复唤醒、单槽回执互覆。

6. （v2.2，2026-10-07）唤醒判据改为「只在新出现的可行动项上唤醒」：可行动子集未新增（含已恢复/出清、非行动项来回摆动）只记 health_note 不唤醒——进场与出场各唤醒一次会成对吃掉每日唤醒预算（stall 进出对、worker_last_exit_failed 进出对实测各耗两次）。同时把worker_last_exit_failed、candidate_budget_paused 并入免打扰项。

7. （v2.3，2026-10-13）补「存量恶化」唤醒：可行动项未新增，但失败工作数较上轮增长≥25 且≥50 时同样唤醒。
   起因实测：10-12～10-13 固化渠道 429／network_error，失败工作从 0 涨到 892、待处理最老 4.9 小时，
   而 gap 名称始终是 work_failed（非新增），两天零唤醒、无人发现。

调度器约定：只输出**一行 JSON**，`{"wakeAgent": false}` 才跳过模型。
退出码：0 流程正常；2 本地源读取失败（明确失败，不得当成"无需处理"）。

测试接缝（仅测试用）：设 HERMES_PREFLIGHT_DOCTOR_JSON 时，直接以该文本作为 doctor 输出。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME") or r"[本地路径]")
MEM = HERMES / "memories"
STATUS = HERMES / "cron" / "lawyer-status"
STATE = STATUS / "memory-preflight.json"
RECEIPT = STATUS / "memory-governance-receipt.json"
LIMITS_DEFAULT = {"MEMORY.md": 6000, "USER.md": 3000}


def _as_int(value, fallback):
    try:
        return int(str(value).strip().split("#")[0].strip())
    except (TypeError, ValueError):
        return fallback


def load_limits():
    """容量限额只有一个来源：本机 config.yaml 的 memory.memory_char_limit / user_char_limit。

    2026-10-11 之前这里是写死的 6000/3000。用户把配置提到 10000/6000 后，脚本仍按旧值算阈值，
    就会每小时把「未超限」当「超阈值」来唤醒模型——与 memory-slimming 里「保留窗口只有一个来源、
    脚本内不得写死」同一条教训。故改成读配置：能被 PyYAML 解析就用它，否则用纯 stdlib 扫 memory 节，
    都拿不到才回落到默认值。
    """
    limits = dict(LIMITS_DEFAULT)
    try:
        text = (HERMES / "config.yaml").read_text(encoding="utf-8")
    except OSError:
        return limits
    try:
        import yaml
        mem = (yaml.safe_load(text) or {}).get("memory") or {}
        if mem.get("memory_char_limit"):
            limits["MEMORY.md"] = _as_int(mem["memory_char_limit"], limits["MEMORY.md"])
        if mem.get("user_char_limit"):
            limits["USER.md"] = _as_int(mem["user_char_limit"], limits["USER.md"])
        return limits
    except Exception:
        pass
    in_memory = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            in_memory = line.split(":")[0].strip() == "memory"
            continue
        if not in_memory or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key == "memory_char_limit" and value.strip():
            limits["MEMORY.md"] = _as_int(value, limits["MEMORY.md"])
        elif key == "user_char_limit" and value.strip():
            limits["USER.md"] = _as_int(value, limits["USER.md"])
    return limits


LIMITS = load_limits()
RATIO = 0.85
DAY_WINDOW = (8, 22)          # 北京时间 08:00–22:00 才唤醒模型
WAKE_RETRY_AFTER = 1800       # 请求后 30 分钟未见完成回执，允许再次唤醒
MAX_WAKES_PER_DAY = 4         # 同一问题指纹每日最多唤醒次数
OK_RESULTS = {"ok", "registered", "pass", "healthy", ""}
# 只有这些取值才算"异常检查项"；running／configured／present 等是健康或信息性取值，
# 不能当成故障（否则 supervisor=running 会被报成"异常"）。
BAD_CHECK_VALUES = {"fail", "failed", "error", "degraded", "unhealthy", "missing", "stale",
                    "down", "stopped", "stopping", "broken", "not_running", "unavailable", "invalid"}
# 失败/积压类计数：持续存在的历史积压不是"每小时都要唤醒"的理由，只如实记录、供人查。
COUNT_FIELDS = (("failed_work", "失败工作"), ("terminal_failed_work", "终态失败"),
                ("candidate_failed", "候选失败"), ("pending_work", "待处理工作"),
                ("candidate_pending_evaluation", "待评估候选"))


# 非行动项 gap（对齐 doctor._NON_ACTIONABLE_GAPS，2026-10-04 核对）：doctor 分类里只提注意、
# 不驱动 degraded 的项；preflight 的比较与指纹化同样跳过它们——worker_capability_unavailable
# 会随采样窗口落在不同 pass 之间来回摆动，参与比较会让同一积压反复唤醒、单槽回执互覆。
NON_ACTIONABLE_GAPS = frozenset({
    "vector_threshold_unconfigured",
    "work_failed_terminal_only",
    "work_needs_review",
    "worker_capability_unavailable",
    # 2026-10-07 增补：worker_last_exit_failed 只看最后一张回执（busy 75 / watchdog 124 都算失败），
    # 在单槽回执下进出成对、当日 4/4 唤醒预算被它耗尽；真停摆由 work_backlog_stalled(12h) 与
    # supervisor stood_down 覆盖。candidate_budget_paused 是额度触顶的运营状态，不是故障。
    "worker_last_exit_failed",
    "candidate_budget_paused",
})


def actionable_gaps(raw) -> str:
    """把 gaps 串过滤为「可行动子集」并归一（去空白、排序），供比较与指纹化使用。"""
    items = sorted({g.strip() for g in str(raw or "").split(",") if g.strip()})
    return ",".join(g for g in items if g not in NON_ACTIONABLE_GAPS)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


# 存量恶化闸门（v2.3，2026-10-13）：只看「新出现的可行动项」会让 work_failed 这类**存量**在一个
# 很长窗口内持续放大却始终不触发——实测 10-12～10-13 固化渠道故障，失败工作从 0 涨到 892、
# 队列积压两天零唤醒，无人发现。故补一条：可行动项未新增时，失败工作数较上轮显著增长同样唤醒；
# 增量阈值与绝对下限同时满足才唤醒，避免小抖动吃掉当日唤醒预算（MAX_WAKES_PER_DAY=4）。
WORK_FAILED_GROWTH_MIN = 25
WORK_FAILED_FLOOR = 50
# 新增条目闸门（v2.4，2026-10-24）：MEMORY 瘦身后长期低于容量阈值，但新环境事实仍在写入；
# 只看容量会让新条目永不进分流（用户明确"不能总等我手动"）。基准＝上次评估回执里的
# metrics.memory_md.chars_raw（瘦身任务写回执时必须带），净增长达门槛才唤醒，避免小抖动。
MEMORY_GROWTH_MIN = 200


def failed_work_count():
    """读运行中监督进程的对账文件取失败工作数。无子进程开销；读不到返回 None＝本轮不判。"""
    best = None
    try:
        files = sorted((HERMES / "scope-recall").glob("runtime-supervisor-*.json"))
    except OSError:
        return None
    for p in files:
        try:
            v = json.loads(p.read_text(encoding="utf-8")).get("failed_work")
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(v, int) and (best is None or v > best):
            best = v
    return best


def load_json(p: Path) -> dict:
    """读状态文件。文件不存在＝首次运行（返回空）；**解析失败**才留证据副本（唯一名，
    纳秒+进程号，避免同一秒内多次调用互相覆盖）；读不到（权限/占用）不动原文件。"""
    if not p.exists():
        return {}
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        stamp = time.strftime("%Y%m%d%H%M%S") + f"-{time.time_ns() % 1000000000:09d}-{os.getpid()}"
        try:
            p.replace(p.with_name(f"{p.name}.corrupt-{stamp}"))
        except OSError:
            pass
        return {}
    return data if isinstance(data, dict) else {}


def save_json(p: Path, data: dict) -> None:
    """原子保存：唯一临时名 + 替换，避免半写留下坏 JSON 或并发互相覆盖。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def in_window(now: float) -> bool:
    h = int(time.strftime("%H", time.localtime(now)))
    return DAY_WINDOW[0] <= h < DAY_WINDOW[1]


def _exe_candidates() -> list[str]:
    cands = [
        shutil.which("scope-recall.exe"),
        str(HERMES / "hermes-agent" / "venv" / "Scripts" / "scope-recall.exe"),
        shutil.which("scope-recall"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "scope-recall" / "scope-recall.exe"),
    ]
    return [c for c in cands if c and Path(c).exists()]


def doctor() -> tuple[str, str]:
    """返回 (ok|degraded|unknown|unavailable, 说明)。

    判定规则（v2）：
      ok           —— 有效 JSON、含 status/health 字段且值为正常
      degraded     —— 有效 JSON、含 status/health 字段且值为异常（附检查项与计数）
      unknown      —— 空输出／非 JSON／结构无效／缺少有效健康字段（**不得视为健康**）
      unavailable  —— 找不到 CLI（**不得视为健康**）
    """
    rc = None                      # 进程退出码；stub 路径没有真实进程，保持 None
    stub = os.environ.get("HERMES_PREFLIGHT_DOCTOR_JSON")
    if stub is not None:
        raw = stub
    else:
        exes = _exe_candidates()
        if not exes:
            return "unavailable", "未找到 scope-recall CLI"
        p, last_err, raw = None, "", ""
        # 关键：剥掉 PYTHONPATH/PYTHONHOME 再调用子进程。
        # 调度器会把 hermes-agent 树钉进 PYTHONPATH（pin_hermes_tree_on_pythonpath），
        # 这会干扰 scope-recall CLI 自己 venv 的模块解析——实测报
        # ModuleNotFoundError: No module named 'rpds.rpds'，进程在打印任何输出前就崩掉，
        # 表现为「无输出（exit=1）」。桌面 shell 里没有这个钉法，所以只在 cron 环境复现。
        env = {k: v for k, v in os.environ.items()
               if k.upper() not in ("PYTHONPATH", "PYTHONHOME")}
        for exe in exes:
            try:
                r = subprocess.run([exe, "doctor", "--host", "hermes", "--instance-root", str(HERMES)],
                                   capture_output=True, text=True, timeout=120,
                                   cwd=str(HERMES), env=env)
            except (OSError, subprocess.TimeoutExpired) as e:
                last_err = f"{Path(exe).name}: {e}"
                continue
            if (r.stdout or "").strip():
                raw = r.stdout.strip()
                rc = r.returncode
                break
            detail = (r.stderr or "").strip().splitlines()
            hint = detail[-1][:120] if detail else ""
            last_err = f"{Path(exe).name}: 无输出（exit={r.returncode}）{('｜' + hint) if hint else ''}"
        if not raw:
            return "unknown", f"doctor 无有效输出（{last_err}）"

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "unknown", "doctor 输出不可解析（非 JSON）"
    if not isinstance(data, dict) or not data:
        return "unknown", f"doctor 响应结构无效（{type(data).__name__}／空对象），健康状态未知"
    if not any(k in data for k in ("status", "health", "state")):
        return "unknown", "doctor 响应缺少有效健康字段，健康状态未知"

    # 顶层 status/health/state 判定——按已安装 doctor 的真实协议（scope_recall/maintenance/doctor.py
    # 的 _classify_status）：ok；degraded＝操作者必须处理的行动项；attention＝值得查看（终态失败、
    # 证据等待等非行动项）。协议之外的取值一律不当作正常：
    # null／空值／未定义取值 → unknown；degraded 不再因为"检查项看起来没异常"被降级为笔记。
    BAD_TOP = ("error", "fail", "failed", "unhealthy", "down", "unavailable",
               "broken", "critical", "not_running", "stopped")
    ACT_TOP = ("degraded",)                      # 协议：actionable，保留为问题
    NOTE_TOP = ("attention", "warn", "warning")  # 协议：值得查看，记为提示
    OK_TOP = ("ok", "healthy", "up", "normal", "ready", "operational", "fine", "good")
    problems, note_reports, unknown_reason = [], [], None
    auth_value = None            # 权威健康值：按 status → health → state 取第一个可用值
    seen_classes = set()         # 各别名字段给出的结论类别，用于发现互相矛盾
    for key in ("status", "health", "state"):
        if key not in data:
            continue
        raw = data.get(key)
        if raw is None:
            if unknown_reason is None:
                unknown_reason = f"doctor 返回 {key}=null（未给出健康值），健康状态未知"
            continue
        v = str(raw).strip().lower()
        if not v:
            if unknown_reason is None:
                unknown_reason = f"doctor 返回 {key}=空值（未给出健康值），健康状态未知"
            continue
        if v in BAD_TOP or v in ACT_TOP:
            problems.append(f"doctor 报 {key}={raw}")
            seen_classes.add("degraded")
        elif v in NOTE_TOP:
            note_reports.append(f"{key}={raw}")
            seen_classes.add("attention")
        elif v not in OK_TOP:
            if unknown_reason is None:
                unknown_reason = f"doctor 响应含未定义健康值 {key}={raw!r}，健康状态未知"
            continue
        else:
            seen_classes.add("ok")
        if auth_value is None:
            auth_value = v
    raw_checks = data.get("checks")
    checks = raw_checks if isinstance(raw_checks, list) else []
    bad = [c.get("name") for c in checks
           if isinstance(c, dict) and str(c.get("result", "")).strip().lower() in BAD_CHECK_VALUES]
    notes = []
    if bad:
        detail_bad = "doctor 异常检查项：" + "/".join(str(x) for x in bad[:6])
        # 权威值可用时，检查项异常作为独立诊断：producer 的顶层分类由 capability_gaps 决定，
        # 不按 checks 枚举，故不能据 checks 推翻顶层结论（复核 B1c-N02）。
        if auth_value in OK_TOP:
            notes.append(detail_bad + "（顶层仍为正常，作为诊断保留）")
        else:
            problems.append(detail_bad)
    if not isinstance(raw_checks, list):
        # 只作信息记录：doctor 没给检查清单时，"检查项无异常"这句话无从核实
        notes.append("doctor 未提供检查清单（checks 缺失或非列表）")
    for key, label in COUNT_FIELDS:
        v = data.get(key)
        if isinstance(v, int) and v > 0:
            notes.append(f"{label} {v} 项")
    oldest = data.get("oldest_pending_at")
    if notes and isinstance(oldest, str) and oldest:
        notes.append(f"最早待处理 {oldest[:16]}")
    hot = next((c.get("result") for c in checks
                if isinstance(c, dict) and c.get("name") == "hot_patched"), None)
    if hot and str(hot).lower() in ("mismatch", "differs", "patched"):
        notes.append(f"代码热补丁状态 {hot}")
    if note_reports:
        notes.append("doctor 标注 " + "/".join(note_reports) + "（值得查看，非行动项）")
    if unknown_reason:
        if rc is not None and rc not in (0, 1):
            unknown_reason += f"；进程退出码 {rc} 亦异常"
        return "unknown", unknown_reason
    if len(seen_classes) > 1:
        # 顶层别名字段互相矛盾（如 status=ok 与 health=attention）：不允许用提示掩盖冲突
        return "unknown", ("doctor 顶层健康字段互相矛盾（" + "/".join(sorted(seen_classes))
                           + "），健康状态未知")
    # 退出码按**权威健康值**校验（producer 的 _classify_status 只由 status 决定，cli.py:270-277）：
    # status=ok ⇒ rc=0；attention/degraded ⇒ rc=1。checks 明细不回推期望码，
    # 否则会把 producer 合法的 ok+rc0（某 check 记 invalid 但未产生 gap）误判成矛盾（复核 B1c-N02）。
    if rc is not None and auth_value is not None:
        expected = 0 if auth_value in OK_TOP else 1
        if rc not in (0, 1) or rc != expected:
            return "unknown", (f"doctor 退出码 {rc} 与权威健康值 {auth_value!r} 不一致"
                               f"（按协议期望 {expected}），健康状态未知")
    if problems:
        gaps = sorted(str(g) for g in (data.get("capability_gaps") or []) if isinstance(g, str) and g)
        return "degraded", "；".join(problems) + (f"｜gaps={','.join(gaps)}" if gaps else "")
    return "ok", "；".join(notes) or "doctor 正常"


def emit(payload: dict, code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return code


def main() -> int:
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    # 状态损坏不能当"首次空态"：留唯一证据副本后，本轮不发起模型分析
    # （预算与请求记录未知时唤醒会绕开每日上限）。
    state_broken = False
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                state_broken = True
                state = {}
        except (OSError, json.JSONDecodeError):
            state_broken = True
            state = {}
        if state_broken:
            stamp = time.strftime("%Y%m%d%H%M%S") + f"-{time.time_ns() % 1000000000:09d}-{os.getpid()}"
            try:
                STATE.replace(STATE.with_name(f"{STATE.name}.corrupt-{stamp}"))
            except OSError:
                pass
    else:
        state = {}

    # ── 本地检查 ─────────────────────────────────────────────
    files, capacity_problems, info = {}, [], {}
    for name, limit in LIMITS.items():
        p = MEM / name
        if not p.exists():
            return emit({"wakeAgent": True, "local": "failed",
                         "reason": f"{name} 不存在（读取失败，不得视为空记忆）", "fail": True}, 2)
        try:
            raw_bytes = p.read_bytes()
        except OSError as e:
            return emit({"wakeAgent": True, "local": "failed",
                         "reason": f"{name} 读取失败：{e}", "fail": True}, 2)
        text_crlf = raw_bytes.decode("utf-8")
        text_norm = text_crlf.replace("\r\n", "\n")
        thr = int(limit * RATIO)
        files[name] = sha(text_crlf)
        info[name] = {"chars_normalized": len(text_norm), "chars_raw": len(text_crlf),
                      "bytes": len(raw_bytes), "limit": limit, "threshold": thr}
        if len(text_norm) > thr:
            capacity_problems.append(f"{name} {len(text_norm)}/{limit} 超过检查阈值 {thr}")

    health, detail = doctor()
    health_verified = health in ("ok", "degraded")
    info["health"] = {"status": health, "verified": health_verified, "detail": detail}

    problems = list(capacity_problems)
    # v2.4（2026-10-24）：新增条目同样触发分流——MEMORY 瘦身后长期低于容量阈值，
    # 只看容量会让新事实永不进分流。基准取上次评估回执的 metrics.memory_md.chars_raw
    # （瘦身任务写回执时必须带该字段），净增长达门槛才唤醒，避免小抖动吃掉每日预算。
    _prev_mem = (((load_json(RECEIPT).get("metrics") or {}).get("memory_md") or {})
                 .get("chars_raw"))
    _cur_mem = (info.get("MEMORY.md") or {}).get("chars_raw")
    if isinstance(_prev_mem, int) and isinstance(_cur_mem, int):
        _mem_grew = _cur_mem - _prev_mem
        if _mem_grew >= MEMORY_GROWTH_MIN:
            problems.append(f"MEMORY.md 自上次评估新增 {_mem_grew} 字符"
                            f"（{_prev_mem}→{_cur_mem}），需判去向")
    health_note = None
    health_gaps = ""
    health_gaps_actionable = ""
    failed_seen = failed_work_count()   # 失败工作数（v2.3 存量闸门用；同时写入状态供下轮比较）
    if health == "degraded":
        detail_main = detail.split("｜gaps=")[0]
        if "｜gaps=" in detail:
            health_gaps = detail.split("｜gaps=", 1)[1].strip()
        health_gaps_actionable = actionable_gaps(health_gaps)
        prev_raw = str(state.get("health_gaps") or "")
        prev_act = actionable_gaps(prev_raw)
        cur_set = {g for g in health_gaps_actionable.split(",") if g}
        prev_set = {g for g in prev_act.split(",") if g}
        added = cur_set - prev_set
        removed = prev_set - cur_set
        # v2.3（2026-10-13）「存量恶化」判据与「新增可行动项」并列，互不遮蔽：work_failed 这类存量
        # 放大时 gap 名称不变，若只在"未新增"分支里判断，一旦同时冒出别的 gap 就永远看不见它。
        # 实测起因：10-12～10-13 固化渠道 429／network_error，失败工作 0→892，两天零唤醒。
        failed_prev = _as_int(state.get("work_failed_seen"), -1)
        grew = ((failed_seen - failed_prev)
                if (failed_seen is not None and failed_prev >= 0) else None)
        growth_fired = (grew is not None and grew >= WORK_FAILED_GROWTH_MIN
                        and failed_seen >= WORK_FAILED_FLOOR)
        if added:
            # v2.2（2026-10-07）：只在「新出现的可行动项」上唤醒。纯清空/恢复不唤醒，
            # 否则进场与出场成对消耗每日唤醒预算（MAX_WAKES_PER_DAY=4）。
            problems.append(f"scope-recall：{detail_main}（新增可行动项：{','.join(sorted(added))}）")
        if growth_fired:
            problems.append(
                f"scope-recall：失败工作数显著增长 {failed_prev}→{failed_seen}（+{grew}，"
                f"阈值 {WORK_FAILED_GROWTH_MIN}／下限 {WORK_FAILED_FLOOR}）——存量恶化，需查固化渠道与队列")
        if not added and not growth_fired:
            # 可行动子集未新增、存量也未显著恶化（含仅非行动项来回摆动、已恢复/出清）：只记笔记。
            # 比较与 health_note 都只用可行动子集（指纹因此对非行动项漂移免疫）；
            # 容量问题仍独立参与 problems，不受此分支影响。
            growth_note = "" if grew is None else f"；失败工作 {failed_prev}→{failed_seen}（+{grew}，未达唤醒阈值）"
            health_note = (f"{detail_main}（可行动项未新增，现={health_gaps_actionable or '无'}"
                           f"；已恢复={','.join(sorted(removed)) or '无'}{growth_note}）——只记录不唤醒")
    elif health in ("unknown", "unavailable"):
        # 拿不到有效健康回执（调度环境 doctor 无输出，原因已知未定位）：
        # 只记录"未核验"，不当作正常，也不因此反复唤醒模型——唤醒解决不了根因。
        health_note = detail

    fingerprint = sha(json.dumps({"problems": sorted(problems), "health_note": health_note,
                                  "files": files}, ensure_ascii=False))

    # ── 处置判定 ─────────────────────────────────────────────
    if state_broken:
        # 坏状态已留唯一证据副本、不覆盖原件：本轮不写新状态、不发起模型分析，只保留可见诊断
        return emit({"wakeAgent": False, "local": "ok", "action": "hold_state",
                     "reason": "预检状态文件损坏或不可读，已保留唯一证据副本；本轮不发起模型分析"
                               "（未知预算下唤醒会绕开每日上限），请核查 cron/lawyer-status/",
                     "problems": sorted(problems)})
    receipt = load_json(RECEIPT)
    receipt_matches = (receipt.get("fingerprint") == fingerprint
                       and bool(receipt.get("completed_at")))
    requested_at = float(state.get("requested_at") or 0)
    same_problem = (state.get("fingerprint") == fingerprint)
    if not same_problem:
        # 指纹变化＝换了新问题：旧请求记录不再压住它（当日唤醒计数仍保留，避免换指纹绕过上限）
        requested_at = 0.0
    pending = requested_at and not receipt_matches
    wakes_today = state.get("wakes_today", {}).get(today, 0)

    base = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "info": info, "files": files,
            "problems": sorted(problems), "fingerprint": fingerprint, "health_note": health_note,
            "health_gaps": health_gaps, "health_gaps_actionable": health_gaps_actionable, "local": "ok", "health_verified": health_verified,
            "work_failed_seen": failed_seen}

    # 唤醒预算与"已请求未回执"必须跨 action 保留：原实现只有 wake/hold_pending/hold_budget
    # 带这两项，clean/hold_health/reuse/hold_window 一保存就把当日计数清掉，
    # 同一问题下一轮又能唤醒，MAX_WAKES_PER_DAY 形同虚设。
    carry = {"wakes_today": dict(state.get("wakes_today", {})), "requested_at": requested_at}

    if not problems and health_verified and not health_note:
        clean_reason = ("容量未超阈值且健康核验通过" if detail.strip() == "doctor 正常"
                        else f"容量未超阈值；健康检查无异常，另有记录待人工查看（{detail}）")
        save_json(STATE, {**base, **carry, "action": "clean", "result": "clean"})
        return emit({"wakeAgent": False, "local": "ok", "health_verified": True,
                     "action": "clean", "reason": clean_reason, "state": info})

    if not problems and health_note:
        action = "hold_no_new_action" if health_verified else "hold_health"
        result = "verified_degraded_no_new_action" if health_verified else "health_unverified"
        description = "已核验异常，但没有新增可行动项" if health_verified else "健康未核验"
        save_json(STATE, {**base, **carry, "action": action, "result": result})
        return emit({"wakeAgent": False, "local": "ok", "health_verified": health_verified,
                     "action": action,
                     "reason": f"容量未超阈值；{description}（{health_note}）——只记录状态、不算正常、不重复唤醒",
                     "problems": [], "health_note": health_note, "state": info})

    if receipt_matches:
        save_json(STATE, {**base, **carry, "action": "reuse", "result": "reuse_previous",
                          "receipt_completed_at": receipt.get("completed_at")})
        return emit({"wakeAgent": False, "local": "ok", "health_verified": health_verified,
                     "action": "reuse", "reason": "本轮问题指纹已有完成回执，复用结论（未到复评时点）",
                     "problems": sorted(problems)})

    if not in_window(now):
        save_json(STATE, {**base, **carry, "action": "hold_window", "result": "hold_night"})
        return emit({"wakeAgent": False, "local": "ok", "health_verified": health_verified,
                     "action": "hold_window",
                     "reason": f"北京时间 {DAY_WINDOW[0]}:00–{DAY_WINDOW[1]}:00 之外不唤醒模型，"
                               f"本地检查已完成并记录，待工作时间分析",
                     "problems": sorted(problems)})

    if pending and (now - requested_at) < WAKE_RETRY_AFTER:
        save_json(STATE, {**base, **carry, "action": "hold_pending", "result": "hold_pending"})
        return emit({"wakeAgent": False, "local": "ok", "health_verified": health_verified,
                     "action": "hold_pending",
                     "reason": "已请求分析、尚未拿到完成回执；在重试间隔内不重复唤醒",
                     "problems": sorted(problems)})

    if wakes_today >= MAX_WAKES_PER_DAY:
        save_json(STATE, {**base, **carry, "action": "hold_budget", "result": "hold_budget"})
        return emit({"wakeAgent": False, "local": "ok", "health_verified": health_verified,
                     "action": "hold_budget",
                     "reason": f"同一问题今日已唤醒 {wakes_today} 次（上限 {MAX_WAKES_PER_DAY}），"
                               f"仍无完成回执；先记录状态、不再重复唤醒",
                     "problems": sorted(problems)})

    wakes = dict(state.get("wakes_today", {}))
    wakes[today] = wakes_today + 1
    save_json(STATE, {**base, "action": "wake", "requested_at": now, "wakes_today": wakes,
                      "result": "wake"})
    return emit({"wakeAgent": True, "local": "ok", "health_verified": health_verified,
                 "action": "wake", "fingerprint": fingerprint,
                 "reason": "；".join(problems) if problems else "容量与健康均有新变化",
                 "state": info})


if __name__ == "__main__":
    sys.exit(main())
