#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""版本绑定回执；completed必须提供当前通过的门禁记录。

不发送客户，不把旧回执当新版本验收。partial只写断点，不表示完成。
非零表示未登记，必须保留失败。--preview只读，不改任何回执或状态。

状态机（v2.1，与旧字段并存，不改变调用方语义）：
    partial            -> blocked（blocked_reason=resume）
    declined           -> declined
    completed + gate   -> checks_passed
    ... + --qa         -> qa_passed（qa 文件须含三件套哈希前缀，证明它看过同版）
    ... + --delivered-evidence -> delivered（须先 qa_passed）
旧字段 status/stage 原样保留，cron 侧无需改动。
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lawyer_quality_state import atomic_json, file_lock, validate_gate

CN_TZ = timezone(timedelta(hours=8))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


NEGATIVE_QA = re.compile(r"未通过|不通过|未复核|未闭环|未解决|未完成|不合格")


def qa_negative_line(text):
    """找出表示未通过的结论行。

    清零只认两种完整形态：「未通过：无」这类尾巴直接结束，或「0 项未通过」之后别无内容。
    零计数后面还挂着说明（如「0 项未通过：无效批注锚点」）仍算未通过——只看前面的零计数
    会把真实缺陷放行（2026-10-24 复核 2 指出）。
    """
    for line in text.splitlines():
        for m in NEGATIVE_QA.finditer(line):
            head = line[:m.start()].rstrip()
            tail = line[m.end():]
            zero_count = re.search(r"(?:^|[\s（(：:，,、])(?:0|零)\s*[项个条处]\s*$", head)
            if zero_count:
                if re.fullmatch(r"[\s：:，,、]*(无|0|零|none|None)?[。；;，,]?\s*", tail):
                    continue
                return line.strip()[:80]
            if re.fullmatch(r"[\s：:，,、]*(无|0|零|none|None)[。；;，,]?\s*", tail):
                continue
            return line.strip()[:80]
    return None


def qa_has_conclusion(text):
    """按行判定是否有明确的通过结论。

    全文短语命中会把「全部通过后再交付」（前置条件）和「并非全部通过」（否定）
    当成通过，也会把「结论：通过」「复核通过」漏掉（2026-10-25 复核 3 指出）。

    顺序：先认清零形态（「未通过：无」「0 项未通过」），它们本身含「未通过」，
    不能被下面的否定预筛拦掉；再对通过形态排除否定与条件句。
    """
    cleared = (
        r"未通过[\s：:，,]*[无零0][。；;]?",
        r"(?:0|零)\s*[项个条处]\s*未通过[。；;]?",
    )
    passed = (
        r"(?:复核|核验|检查|审查)?结论[\s：:]*通过[。；;]?",
        r"(?:复核|核验|检查|审查)(?:结论)?[\s：:]*通过[。；;]?",
        r"(?:全部|均已|均)?通过[。；;]?",
    )
    for line in text.splitlines():
        s = line.strip().strip("*-\u00b7# ").strip()
        if not s:
            continue
        if any(re.fullmatch(pat, s) for pat in cleared):
            return True
        if re.search(r"并非|不是|尚未|不通过|待|后再|仍需|未完成|无法", s):
            continue
        if any(re.fullmatch(pat, s) for pat in passed):
            return True
    return False


def qa_binds_artifacts(qa_path, bound):
    """qa 文件必须绑定三件套哈希、含明确通过结论，且不得含未通过的结论。

    只有哈希、没有明确结论的 qa 不得升级为 qa_passed：形式齐全不等于实质复核
    （2026-10-24 复核 2 指出）。
    """
    if not qa_path or not Path(qa_path).exists():
        return False, "qa 文件不存在"
    text = Path(qa_path).read_text(encoding="utf-8", errors="replace")
    missing = [a["role"] for a in bound["artifacts"] if a["sha256"][:12] not in text]
    if missing:
        return False, "qa 文件未包含以下哈希：%s" % ",".join(missing)
    bad = qa_negative_line(text)
    if bad:
        return False, "qa 文件含未通过结论，不得升 qa_passed：%s" % bad
    if not qa_has_conclusion(text):
        return False, "qa 文件没有明确的通过结论（只有哈希不足以升级 qa_passed）"
    return True, ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="邮件附件目录")
    ap.add_argument("--status", default="completed", choices=["completed", "declined", "partial"])
    ap.add_argument("--note", required=True, help="本机交付摘要或未完步骤；不能代表对外发送")
    ap.add_argument("--gate", type=Path, help="completed必须指定当前门禁JSON")
    ap.add_argument("--resume", default="", help="partial的下一步与断点")
    ap.add_argument("--qa", type=Path, help="复核记录；提供且哈希对得上才升到 qa_passed")
    ap.add_argument("--delivered-evidence", type=Path, help="对外发送凭据；提供才升到 delivered")
    ap.add_argument("--decision-basis", help="declined 的依据，格式「对象|理由」；明确不办理不能只凭一个状态关闭")
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args(argv)
    folder = Path(a.folder).expanduser().resolve()
    try:
        if not folder.is_dir():raise ValueError(f"目录不存在：{folder}")
        if a.status=="completed" and not a.gate:raise ValueError("completed必须提供--gate；不得仅凭生成文件记完成")
        if a.status=="partial" and not a.resume:raise ValueError("partial必须提供--resume，保留可接续断点")
        if a.status=="declined":
            if not a.decision_basis or "|" not in a.decision_basis:
                raise ValueError("declined 必须提供 --decision-basis '对象|理由'：明确不办理也要留依据，不能只写一个状态")
            _obj, _, _reason = a.decision_basis.partition("|")
            if not _obj.strip() or not _reason.strip():
                # 只查有没有竖线会让「|理由」「对象|」通过写入端，
                # 回读却判 declined_unverified（2026-10-25 复核 3）。
                raise ValueError("--decision-basis 的对象与理由都不能为空")
        bound=validate_gate(a.gate,folder,register=True) if a.status=="completed" else None
        if bound and {x['role'] for x in bound['artifacts']}!={'path','expected','ledger'}:
            raise ValueError("完成回执必须绑定修订/批注版、净版基线与台账三件套")

        # 状态机
        if a.status == "partial":
            state, blocked_reason = "blocked", a.resume
        elif a.status == "declined":
            state, blocked_reason = "declined", ""
        else:
            state, blocked_reason = "checks_passed", ""
            if a.qa:
                ok, why = qa_binds_artifacts(a.qa, bound)
                if not ok:
                    raise ValueError("qa 记录未绑定同版产物：%s" % why)
                state = "qa_passed"
            if a.delivered_evidence:
                if state != "qa_passed":
                    raise ValueError("delivered 之前必须先到 qa_passed（提供 --qa）")
                if not Path(a.delivered_evidence).exists():
                    raise ValueError("发送凭据不存在：%s" % a.delivered_evidence)
                state = "delivered"

        rec={"schema":"mail-handled/v2", "handled_at":datetime.now(CN_TZ).isoformat(timespec="seconds"),
             "status":a.status,"note":a.note,"by":"hermes-cron","resume":a.resume,
             "version_evidence":bound,"stage":"local_delivered" if bound else "in_progress",
             "external_delivery_verified": state == "delivered",
             "state": state, "blocked_reason": blocked_reason}
        if bound:
            # 只有走过 register=True 的完整门禁校验才写这个标记；
            # 回读端据此区分「当前完成」与「历史记录」（复核 2 的 Q2）。
            rec["full_gate_binding"] = True
        if a.status == "declined":
            obj, _, reason = a.decision_basis.partition("|")
            rec["decision_basis"] = {"object": obj.strip(), "reason": reason.strip()}
        if a.qa:
            rec["qa_evidence"] = {"path": str(Path(a.qa).resolve()), "sha256": sha256_file(a.qa)}
        if a.delivered_evidence:
            rec["delivery_evidence"] = {"path": str(Path(a.delivered_evidence).resolve()),
                                        "sha256": sha256_file(a.delivered_evidence)}
        if a.preview:print(json.dumps(rec,ensure_ascii=False,indent=2));return 0
        p=folder/"_处理回执.json"
        with file_lock(folder/".handled.lock"):
            if p.exists():
                old=p.read_bytes()
                history=folder/"_回执历史";history.mkdir(exist_ok=True)
                from time import time_ns
                (history/f"处理回执-{time_ns()}.json").write_bytes(old)
                try:
                    prev = json.loads(old.decode("utf-8"))
                    hist = list(prev.get("state_history") or [])
                except Exception:
                    hist = []
                hist.append({"state": prev.get("state") or prev.get("status") or "unknown",
                             "at": prev.get("handled_at", ""), "note": prev.get("note", "")[:120]})
                rec["state_history"] = hist[-20:]
            atomic_json(p,rec)
        print(f"OK 本机处理回执已写，未对外发送：{p}（state={rec['state']}）");return 0
    except (OSError,ValueError,TypeError) as exc:
        print(f"处理回执未登记：{exc}",file=sys.stderr);return 2

if __name__=="__main__":sys.exit(main())
