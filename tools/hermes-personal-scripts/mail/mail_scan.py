#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""邮件巡检（只读）— 阿里企业邮箱 IMAP

只做四件事：连接、列出新邮件、读头部和正文摘要、写报告。
不发信、不删信、不改状态（全部用 BODY.PEEK，不置 \\Seen）、不移动邮件。

2026-09-29 加固（失败告警 + 未送达补报）：
- 「送达位点」last_delivered_uid 与扫描位点 last_uid 分离：扫描到的邮件进入 pending，
  只有运行 --commit-delivered 才登记为已送达；上次运行中断的邮件在下轮以「补报」区自动重列。
- 扫描时回读执行库：上次巡检运行未成功完成时，在输出首部给出 ⚠️ 警示。
- 超出单次条数上限的邮件记入 deferred 并持续警示，人工处理后 --clear-deferred。

用法:
  python mail_scan.py                        # 上次位置之后的新邮件（首次=最近24小时）
  python mail_scan.py --since-hours 72       # 按时间窗口扫描（忽略状态文件）
  python mail_scan.py --reset                # 清状态，重新按时间窗口扫
  python mail_scan.py --folder INBOX --limit 50
  python mail_scan.py --commit-delivered     # 登记本轮简报已送达（推进送达位点并清空待送达）
  python mail_scan.py --clear-deferred       # 已人工处理完超限邮件后清除警示
  python mail_scan.py --status               # 只看本地状态（不连邮箱）

输出:
  out/scan_<时间戳>.json   结构化数据（供后续处理）
  out/digest_<时间戳>.md   可读摘要
  stdout                   摘要正文（供定时任务直接投递）
"""
from __future__ import annotations

import argparse
import email
import email.policy
import imaplib
import json
import os
import re
import sqlite3
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
STATE_PATH = BASE / "state.json"
OUT_DIR = BASE / "out"
CN_TZ = timezone(timedelta(hours=8))

# 所属定时任务（cron/jobs.json 中的 id）：用于回读上次执行状态
JOB_ID = "34c9b0072750"
HERMES_HOME = BASE.parent.parent          # <HERMES_HOME>/scripts/mail -> <HERMES_HOME>
sys.path.insert(0, str(HERMES_HOME / "scripts"))
CRON_DB = HERMES_HOME / "cron" / "executions.db"

FAILURE_LOOKBACK_HOURS = 30               # 上次失败警示的回看窗口
PENDING_CAP = 200                         # 待送达清单上限（超出部分转 deferred 警示）

# 重点线索（命中即进入"重点"分组；只作排序提示，不作结论）
HOT_KEYWORDS = [
    "法院", "仲裁", "判决", "裁定", "传票", "开庭", "立案", "举证", "送达",
    "检察院", "公安", "执行", "律师函", "催款", "催告", "合同", "协议",
    "委托", "授权", "鉴定", "诉讼", "答辩", "上诉", "再审", "保全", "异议",
    "合规", "尽调", "标书", "投标", "比选",
]
NOISE_PATTERNS = (
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
    "mailer-daemon", "postmaster", "notifications@", "automated@",
    "newsletter", "marketing",
)


def decode_hdr(raw) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def strip_html(html: str) -> str:
    txt = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)
    txt = re.sub(r"&nbsp;?", " ", txt)
    txt = re.sub(r"&(amp|lt|gt|quot|#39);", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def body_snippet(msg) -> "tuple[str, list[tuple[str, bytes]]]":
    """返回 (正文摘要, [(附件文件名, 字节内容)])"""
    attachments, texts = [], []
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ctype = part.get_content_type()
        disp = str(part.get("Content-Disposition") or "")
        fname = decode_hdr(part.get_filename())
        if fname and "attachment" in disp.lower():
            try:
                attachments.append((fname, part.get_payload(decode=True) or b""))
            except Exception:
                attachments.append((fname, b""))
            continue
        if part.is_multipart():
            continue
        if ctype == "text/plain":
            try:
                texts.append(part.get_content())
            except Exception:
                pass
        elif ctype == "text/html":
            try:
                texts.append(strip_html(part.get_content()))
            except Exception:
                pass
    body = re.sub(r"\s+", " ", " ".join(t for t in texts if t)).strip()
    return body[:400], attachments


def safe_name(name: str, fallback: str = "attachment") -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", (name or "").strip())
    return name.strip(". ")[:120] or fallback


def save_parts(parts, base_dir: Path, subject: str, uid: int) -> list:
    """附件写到 base_dir/<日期>_<主题简称>/，返回已保存的绝对路径列表"""
    day = datetime.now(CN_TZ).strftime("%Y%m%d")
    folder = Path(base_dir) / f"{day}_{safe_name(subject, '无主题')[:40]}"
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    for fname, payload in parts:
        if not payload:
            continue
        target = folder / safe_name(fname, f"uid{uid}_attachment")
        if target.exists():
            target = folder / f"{target.stem}_{uid}{target.suffix}"
        target.write_bytes(payload)
        saved.append(str(target))
    return saved


def classify(subject: str, sender: str, body: str) -> str:
    low = f"{subject} {sender}".lower()
    if any(p in low for p in NOISE_PATTERNS):
        return "通知类"
    joined = f"{subject} {body}"
    return "重点" if any(k in joined for k in HOT_KEYWORDS) else "常规"


def connect():
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(CFG["host"], int(CFG.get("port", 993)), ssl_context=ctx)
    conn.login(CFG["user"], CFG["password"])
    return conn


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    tmp = STATE_PATH.parent / (STATE_PATH.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def _first_line(text: str) -> str:
    stripped = (text or "").strip()
    return stripped.splitlines()[0][:120] if stripped else ""


def last_failure() -> "dict | None":
    """回读本任务上一次终态执行；未成功完成且发生在回看窗口内时返回摘要。"""
    if not CRON_DB.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{CRON_DB.as_posix()}?mode=ro", uri=True, timeout=5)
        row = con.execute(
            "SELECT status, finished_at, error, delivery_outcome FROM executions "
            "WHERE job_id=? AND status IN ('completed','failed','unknown') "
            "ORDER BY finished_at DESC LIMIT 1", (JOB_ID,)).fetchone()
        con.close()
    except Exception:
        return None
    if not row:
        return None
    status, finished, err, outcome = row[0], row[1] or "", row[2] or "", row[3] or ""
    if status == "completed":
        return None
    when = ""
    try:
        dt = datetime.fromisoformat(finished)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CN_TZ)
        if datetime.now(CN_TZ) - dt > timedelta(hours=FAILURE_LOOKBACK_HOURS):
            return None
        when = dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        when = str(finished)[:16]
    return {"status": status, "when": when, "error": _first_line(err), "outcome": outcome}


def scan(folder: str, since_hours: int, use_state: bool, limit: int,
         save_attachments: bool = False, attachments_dir: str = "", only_uids=None):
    conn = connect()
    try:
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"无法打开文件夹 {folder}")

        state = load_state() if use_state else {}
        entry = state.setdefault(folder, {}) if use_state else {}
        last_uid = int(entry.get("last_uid", 0)) if use_state else 0
        if use_state and "last_delivered_uid" not in entry:
            # 升级迁移：以当前位点为送达基线，避免把历史邮件整体重报
            entry["last_delivered_uid"] = last_uid
            entry["last_delivered_at"] = entry.get("last_run")
        delivered_uid = int(entry.get("last_delivered_uid", last_uid)) if use_state else 0
        prev_pending = [x for x in entry.get("pending", []) if int(x.get("uid", 0)) > delivered_uid] if use_state else []
        deferred = list(entry.get("deferred", [])) if use_state else []

        if last_uid:
            typ, data = conn.uid("SEARCH", None, f"UID {last_uid + 1}:*")
        else:
            since_date = (datetime.now(CN_TZ) - timedelta(hours=since_hours)).strftime("%d-%b-%Y")
            typ, data = conn.uid("SEARCH", None, f"(SINCE {since_date})")
        if typ != "OK":
            raise RuntimeError("SEARCH 失败")

        uids = [int(u) for u in (data[0].split() or []) if int(u) > last_uid]
        uids.sort()
        if only_uids:
            uids = [u for u in only_uids if u in uids] or list(only_uids)
        skipped_uids = []
        if len(uids) > limit:
            skipped_uids = uids[:-limit]
            uids = uids[-limit:]

        items = []
        for uid in uids:
            typ, raw = conn.uid(
                "FETCH", str(uid),
                "(RFC822.SIZE FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)])",
            )
            if typ != "OK" or not raw or not isinstance(raw[0], tuple):
                continue
            meta = raw[0][1]
            size = 0
            m = re.search(rb"RFC822\.SIZE (\d+)", raw[0][0] or b"")
            if m:
                size = int(m.group(1))
            flags = re.findall(rb"\\Seen|\\Answered|\\Flagged", raw[0][0] or b"")
            hdr = email.message_from_bytes(meta, policy=email.policy.default)

            subject = decode_hdr(hdr.get("Subject"))
            sender_name, sender_addr = parseaddr(decode_hdr(hdr.get("From")))

            snippet, attachments, saved_files = "", [], []
            need_full = bool(size) and (
                size <= int(CFG.get("max_fetch_bytes", 300000))
                or (save_attachments and size <= int(CFG.get("max_attachment_fetch_bytes", 20000000)))
            )
            if need_full:
                typ2, raw2 = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
                if typ2 == "OK" and raw2 and isinstance(raw2[0], tuple):
                    msg = email.message_from_bytes(raw2[0][1], policy=email.policy.default)
                    snippet, att_parts = body_snippet(msg)
                    attachments = [n for n, _ in att_parts]
                    if save_attachments and att_parts and attachments_dir:
                        saved_files = save_parts(att_parts, Path(attachments_dir), subject or f"uid{uid}", uid)
            date_raw = hdr.get("Date")
            try:
                dt = parsedate_to_datetime(str(date_raw)).astimezone(CN_TZ)
                date_str = dt.strftime("%m-%d %H:%M")
            except Exception:
                date_str = str(date_raw or "")[:20]

            items.append({
                "uid": uid,
                "date": date_str,
                "from_name": sender_name or sender_addr,
                "from_addr": sender_addr,
                "to": decode_hdr(hdr.get("To")),
                "cc": decode_hdr(hdr.get("Cc")),
                "subject": subject or "(无主题)",
                "message_id": str(hdr.get("Message-ID") or ""),
                "unread": not any(f == b"\\Seen" for f in flags),
                "size": size,
                "attachments": attachments,
                "saved_attachments": saved_files,
                "snippet": snippet,
                "group": classify(subject, sender_addr, snippet),
                "folder": folder,
            })

        newest = max([i["uid"] for i in items], default=last_uid)
        if only_uids:
            use_state = False
        if use_state:
            now_iso = datetime.now(CN_TZ).isoformat(timespec="seconds")
            dset = {int(d.get("uid", 0)) for d in deferred}
            for uid in skipped_uids:
                if uid not in dset:
                    deferred.append({"uid": uid, "skipped_at": now_iso})
            pending = prev_pending + list(items)
            if len(pending) > PENDING_CAP:
                overflow = pending[:len(pending) - PENDING_CAP]
                pending = pending[len(pending) - PENDING_CAP:]
                for it in overflow:
                    uid2 = int(it.get("uid", 0))
                    if uid2 not in dset:
                        deferred.append({"uid": uid2, "skipped_at": now_iso, "reason": "待送达超上限"})
            entry["pending"] = pending
            entry["last_uid"] = newest
            entry["last_run"] = now_iso
            entry["deferred"] = deferred
            save_state(state)

        return {"folder": folder, "items": items, "prev_pending": prev_pending,
                "deferred": deferred,
                "last_failure": (last_failure() if use_state else None),
                "scanned_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
                "since_uid": last_uid, "delivered_uid": delivered_uid,
                "truncated": bool(skipped_uids)}
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _receipt_line(item) -> "str | None":
    saved = item.get("saved_attachments") or []
    if not saved:
        return None
    from lawyer_quality_state import inspect_receipt
    lines = []
    for folder in dict.fromkeys(Path(p).parent for p in saved):
        try:
            rec = inspect_receipt(folder)
            status, version = rec.get('status'), rec.get('version_state')
            if version == 'no_receipt': text = '未见处理回执，尚未认定完成'
            elif status == 'partial': text = '部分完成，继续断点：' + (rec.get('resume') or rec.get('note') or '待核')
            elif status == 'declined': text = '已明确暂不处理：' + (rec.get('note') or '见回执')
            elif version == 'changed_after_receipt': text = '版本已变化，先核差异，不覆盖用户后保存稿，不自动重做'
            elif status == 'completed' and version == 'current_version_matched':
                text = '本机交付回执版本匹配，不代表客户接收；仅覆盖绑定产物，未绑定附件仍须逐件核对'
            else: text = '历史回执，未绑定当前版本；只作历史线索，不自动覆盖或重出'
            lines.append(f'{folder.name}：{text}')
        except (OSError, ValueError, TypeError, KeyError):
            lines.append(f'{folder.name}：回执读取异常，未认定完成，保留原稿')
    return '；'.join(lines)


def render_md(result: dict) -> str:
    items = result["items"]
    prev = result.get("prev_pending") or []
    lines = [f"# 邮件巡检 {result['scanned_at']}（{result['folder']}）", ""]
    warned = False
    lf = result.get("last_failure")
    if lf:
        lines.append(
            "⚠️ 上次巡检运行未成功完成（%s，%s：%s）——未送达邮件（如有）已并入下方补报，请留意。"
            % (lf.get("when") or "时间未知", lf.get("status"), lf.get("error") or "见执行记录"))
        warned = True
    deferred = result.get("deferred") or []
    if deferred:
        uid_list = ", ".join(str(d.get("uid")) for d in deferred[:60])
        lines.append(
            "⚠️ 有 %d 封邮件超出单次条数上限未展开（uid: %s）。处理：`mail_scan.py --uids %s --json-only` 补取后，运行 `mail_scan.py --clear-deferred`。"
            % (len(deferred), uid_list, uid_list))
        warned = True
    if warned:
        lines.append("")
    if prev:
        lines.append(f"## 补报（此前扫描未送达 {len(prev)} 封，须并入本轮处理）")
        for i in prev:
            flag = "未读" if i["unread"] else "已读"
            att = f"　附件：{'、'.join(i['attachments'])}" if i["attachments"] else ""
            lines.append(f"- **{i['subject']}**")
            lines.append(f"  - 发件人：{i['from_name']} <{i['from_addr']}>　{i['date']}　{flag}{att}")
            if i.get("snippet"):
                lines.append(f"  - 摘要：{i['snippet'][:200]}")
            for path in i.get("saved_attachments", []):
                lines.append(f"  - 已下载：{path}")
            rc = _receipt_line(i)
            if rc:
                lines.append(f"  - 附件处理：{rc}")
        lines.append("")
    for group in ("重点", "常规", "通知类"):
        rows = [i for i in items if i["group"] == group]
        if not rows:
            continue
        lines.append(f"## {group}（{len(rows)} 封）")
        for i in rows:
            flag = "未读" if i["unread"] else "已读"
            att = f"　附件：{'、'.join(i['attachments'])}" if i["attachments"] else ""
            lines.append(f"- **{i['subject']}**")
            lines.append(f"  - 发件人：{i['from_name']} <{i['from_addr']}>　{i['date']}　{flag}{att}")
            if i["snippet"]:
                lines.append(f"  - 摘要：{i['snippet'][:200]}")
            for path in i.get("saved_attachments", []):
                lines.append(f"  - 已下载：{path}")
            rc = _receipt_line(i)
            if rc:
                lines.append(f"  - 附件处理：{rc}")
        lines.append("")
    if not items and not prev:
        lines.append("无新邮件。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default=CFG.get("default_folder", "INBOX"))
    ap.add_argument("--since-hours", type=int, default=24)
    ap.add_argument("--limit", type=int, default=int(CFG.get("max_messages", 80)))
    ap.add_argument("--reset", action="store_true", help="忽略状态文件，按时间窗口重扫")
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--uids", default="", help="只处理指定 UID（逗号分隔），不推进状态位点")
    ap.add_argument("--save-attachments", dest="save_attachments", action="store_true",
                    default=bool(CFG.get("save_attachments", True)), help="保存附件到附件目录")
    ap.add_argument("--no-save-attachments", dest="save_attachments", action="store_false")
    ap.add_argument("--attachments-dir", default=CFG.get("attachments_dir", ""))
    ap.add_argument("--commit-delivered", action="store_true",
                    help="登记本轮简报已送达（推进送达位点并清空待送达）")
    ap.add_argument("--clear-deferred", action="store_true", help="清除超限未展开警示")
    ap.add_argument("--status", action="store_true", help="仅显示本地状态（不连邮箱）")
    args = ap.parse_args()

    if args.status:
        st = load_state()
        show = {}
        for f, e in st.items():
            if not isinstance(e, dict):
                continue
            lu = int(e.get("last_uid", 0) or 0)
            du = int(e.get("last_delivered_uid", lu) or 0)
            show[f] = {
                "last_uid": lu,
                "last_delivered_uid": du,
                "undelivered": max(0, lu - du),
                "pending": len(e.get("pending", []) or []),
                "deferred": len(e.get("deferred", []) or []),
                "last_run": e.get("last_run"),
                "last_delivered_at": e.get("last_delivered_at"),
            }
        print(json.dumps({"state": show, "last_failure": last_failure()}, ensure_ascii=False, indent=1))
        return

    if args.commit_delivered:
        st = load_state()
        e = st.setdefault(args.folder, {})
        if "last_delivered_uid" not in e:
            e["last_delivered_uid"] = int(e.get("last_uid", 0))
        e["last_delivered_uid"] = int(e.get("last_uid", 0))
        cleared = len(e.get("pending", []) or [])
        e["pending"] = []
        e["last_delivered_at"] = datetime.now(CN_TZ).isoformat(timespec="seconds")
        save_state(st)
        print("OK 已登记送达：%s 送达位点=%s，清空待送达 %d 封" % (args.folder, e["last_delivered_uid"], cleared))
        return

    if args.clear_deferred:
        st = load_state()
        e = st.setdefault(args.folder, {})
        n = len(e.get("deferred", []) or [])
        e["deferred"] = []
        save_state(st)
        print("OK 已清除 %d 条超限未展开记录（%s）" % (n, args.folder))
        return

    # 显式给出 --since-hours 时按时间窗口扫描；否则用状态位点（首次=最近24小时）
    use_state = ("--since-hours" not in sys.argv) and not args.reset

    only_uids = [int(x) for x in re.split(r"[,\s]+", args.uids) if x.strip().isdigit()] or None
    result = scan(args.folder, args.since_hours, use_state, args.limit,
                  save_attachments=args.save_attachments, attachments_dir=args.attachments_dir,
                  only_uids=only_uids)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(CN_TZ).strftime("%Y%m%d_%H%M")
    (OUT_DIR / f"scan_{ts}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    md = render_md(result)
    (OUT_DIR / f"digest_{ts}.md").write_text(md, encoding="utf-8")
    if not args.json_only:
        print(md)
    else:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
