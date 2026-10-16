#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""把"僵尸" cron 运行会话补上结束标记，使其在桌面端恢复可写。

背景：桌面端 `open-cron-run.ts` 的规则是——`ended_at` 有值即可写；为空且调度器不拥有它
的就是僵尸，按只读打开。僵尸产生于运行没走到 `_finalize_cron_session`（超时被杀、
进程中断、提前退出）。代码里明确：一旦被关闭，它会重新变成可写。

本脚本只做一件事：补 `ended_at` + `end_reason`。不改动消息、不动其它来源的会话。

判定：source='cron' 且 ended_at IS NULL，且**距最后一次消息活动**超过 CUTOFF_SECONDS。
     用「距最后活动」而不是「距开始」：任务可能正常结束却没写成 ended_at，
     按开始时间筛会漏掉运行时长还没到阈值的那些。

end_reason 取**调度器自己的词汇**（`cron.scheduler._finalize_cron_session` 的判据）：
末条消息是真实助手正文（`[SILENT]` 也算）→ `cron_complete`；
末条是工具结果、待调用、用户提示或空内容 → `cron_incomplete_no_output`。
不要再用自造的原因词：桌面写闸门与上游对"已结算运行"的保护（#131433）只认这两个词，
用别的词补上的行仍会被清戳、第二天又回到只读。

用法：
    python reap_cron_zombies.py              # dry-run，只报告
    python reap_cron_zombies.py --apply      # 执行（写库，先写回退台账）
    python reap_cron_zombies.py --rollback   # 按最新台账把 ended_at 置回 NULL
"""
import argparse
import collections
import datetime
import json
import pathlib
import sqlite3
import sys
import time

H = pathlib.Path(r"[本地路径]")
DB = H / "state.db"
# 距【最后一次活动】多久算已安静下来。
# 早期版本用"距开始时间 1 小时"，会漏掉正常运行后收尾失败的会话——
# 实测：任务 10:19 就 finish_reason=stop 正常结束了，但 ended_at 一直为空，
# 而它开始才 46 分钟，落在 1 小时阈值内，点开仍是只读。
CUTOFF_SECONDS = 600
CRON_COMPLETE = "cron_complete"
CRON_INCOMPLETE = "cron_incomplete_no_output"
LEDGER = H / "cache" / "scratch" / "cron-zombie-reap-ledger.json"
BATCH = 50


def connect(readonly=True):
    uri = f"file:{DB.as_posix()}?mode={'ro' if readonly else 'rw'}"
    con = sqlite3.connect(uri, uri=True, timeout=20)
    con.execute("PRAGMA busy_timeout=20000")
    return con


def classify(con, sid):
    """调度器的分类判据：末条消息是真实助手正文才算 complete。"""
    try:
        row = con.execute(
            "SELECT role, COALESCE(content, ''), COALESCE(tool_calls, '') "
            "FROM messages WHERE session_id = ? ORDER BY rowid DESC LIMIT 1", (sid,)).fetchone()
    except sqlite3.Error:
        return CRON_INCOMPLETE          # 读不到就按未完成记，宁严不宽
    if row and row[0] == "assistant" and row[1].strip() and not row[2].strip():
        return CRON_COMPLETE
    return CRON_INCOMPLETE


def find_zombies():
    """ended_at 为空、且**已经安静下来**的 cron 运行，各自附上 end_reason。

    判定依据是**最后活动时间**（消息表的最大 timestamp），不是开始时间：
    任务可能跑很久后正常结束，只是 `_finalize_cron_session` 那一步没写成，
    会话就此留在"未关闭"状态，桌面端按只读打开。
    """
    con = connect()
    try:
        rows = list(con.execute(
            "SELECT s.id, s.started_at, "
            "       (SELECT MAX(m.timestamp) FROM messages m WHERE m.session_id = s.id) AS last_act "
            "FROM sessions s WHERE s.source='cron' AND s.ended_at IS NULL"))
        now = time.time()
        out = []
        for sid, st, last_act in rows:
            try:
                t = float(last_act)
            except (TypeError, ValueError):
                t = float(st or 0)
            if now - t > CUTOFF_SECONDS:
                out.append((sid, st, classify(con, sid)))
    finally:
        con.close()
    return out


def report(zs):
    by_day = collections.Counter()
    by_job = collections.Counter()
    by_reason = collections.Counter()
    for sid, st, reason in zs:
        try:
            by_day[datetime.datetime.fromtimestamp(float(st)).strftime("%m-%d")] += 1
        except (TypeError, ValueError, OSError):
            by_day["?"] += 1
        parts = str(sid).split("_")
        by_job[parts[1] if len(parts) > 1 else "?"] += 1
        by_reason[reason] += 1
    print(f"  按日期（近 8 天）: {dict(sorted(by_day.items(), reverse=True)[:8])}")
    print(f"  按任务 id（前 8）: {dict(by_job.most_common(8))}")
    print(f"  按 end_reason: {dict(by_reason)}")
    oldest = min((float(st) for _, st, _ in zs if st), default=None)
    if oldest:
        print(f"  最早一条: {datetime.datetime.fromtimestamp(oldest):%Y-%m-%d %H:%M}")


def apply_reap(zs):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    # 按时间戳命名，不覆盖历史台账——每次执行都留下独立的回退依据。
    ledger = LEDGER.with_name(f"{LEDGER.stem}-{stamp}.json")
    ledger.write_text(json.dumps(
        {"applied_at": time.time(),
         "ids": [s for s, _, _ in zs],
         "reasons": {s: r for s, _, r in zs}}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  回退台账已写: {ledger}")
    con = connect(readonly=False)
    ok = err = 0
    try:
        for i in range(0, len(zs), BATCH):
            chunk = zs[i:i + BATCH]
            grouped = collections.defaultdict(list)
            for sid, _st, reason in chunk:
                grouped[reason].append(sid)
            try:
                with con:  # 每个批次一个事务
                    for reason, ids in grouped.items():
                        marks = ",".join("?" * len(ids))
                        cur = con.execute(
                            f"UPDATE sessions SET ended_at=?, end_reason=? "
                            f"WHERE id IN ({marks}) AND ended_at IS NULL",
                            [time.time(), reason] + ids)
                        ok += cur.rowcount or 0
            except sqlite3.Error as e:
                err += len(chunk)
                print(f"    批次 {i//BATCH+1} 失败: {type(e).__name__}: {e}")
    finally:
        con.close()
    print(f"  已补结束标记 {ok} 条，失败 {err} 条")


def rollback():
    cands = sorted(LEDGER.parent.glob(f"{LEDGER.stem}-*.json"))
    if not cands:
        print("  没有台账，无法回退")
        return 1
    src = cands[-1]
    print(f"  使用台账: {src.name}（按时间取最新；如需指定历史台账请手工传入）")
    data = json.loads(src.read_text(encoding="utf-8"))
    ids = data.get("ids") or []
    reasons = data.get("reasons") or {}
    con = connect(readonly=False)
    n = 0
    try:
        for i in range(0, len(ids), BATCH):
            chunk = ids[i:i + BATCH]
            grouped = collections.defaultdict(list)
            for sid in chunk:
                # 旧台账没有 reasons 字段：回退时按出现过的原因词逐一匹配。
                grouped[reasons.get(sid) or "cron_zombie_reap"].append(sid)
            with con:
                for reason, group in grouped.items():
                    marks = ",".join("?" * len(group))
                    cur = con.execute(
                        f"UPDATE sessions SET ended_at=NULL, end_reason=NULL "
                        f"WHERE id IN ({marks}) AND end_reason=?", group + [reason])
                    n += cur.rowcount or 0
    finally:
        con.close()
    print(f"  已回退 {n} 条")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="执行写入")
    ap.add_argument("--rollback", action="store_true", help="按台账回退")
    a = ap.parse_args()
    if a.rollback:
        return rollback()
    zs = find_zombies()
    print(f"僵尸候选: {len(zs)} 条（source=cron, ended_at 为空, 距最后活动 > {CUTOFF_SECONDS//60} 分钟）")
    if not zs:
        print("  无需处理")
        return 0
    report(zs)
    if not a.apply:
        print("  （dry-run，未写入。确认后加 --apply）")
        return 0
    apply_reap(zs)
    left = find_zombies()
    print(f"  处理后剩余僵尸: {len(left)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
