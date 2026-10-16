# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Digest Board backend — 待办提要列表（分类 + 处理状态 + 案件归并）。

Mounted under /api/plugins/digest-board/ by the gateway plugin loader.

数据：
  <hermes_home>/cron/output/7d2b5b26a02c/<YYYY-MM-DD_HH-MM-SS>.md   每次运行输出
  <hermes_home>/cron/output/_digest_latest.md                        最新提要
状态（用户操作，本机保存）：
  <plugin_dir>/state.json    {"records": [{"key","text","state","at","date","category","important"}]}
    state: open / done / deleted / later；important: 标星（不随次日收起、也不受 7 天窗口限制）
显示规则：
  1. state=done/deleted 的条目不出现在待办（在「已完成/已删除」里可恢复）；
  2. EXPIRING_CATS 里的「非重要」条目，在最后一次出现于提要的次日收起（「原文」视图仍可回看）；
  3. 同一分类内，开头公共前缀相同的条目按案件聚拢，返回 case / case_count 供前端加小标题。
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

JOB_ID = "7d2b5b26a02c"
MAX_DAYS = 7          # 列表聚合窗口（天）
CARRY_DAYS = 14       # 「稍后」未再出现时的保留窗口（天）
MATCH_RATIO = 0.80    # 跨日 / 状态匹配阈值
# 次日收起：这些分类中「非重要」的条目，第二天起不再出现在待办（「原文」视图仍可回看）。
# 调整范围只改这一行，例如 EXPIRING_CATS = {"其他", "工作建议"} 让建议也次日收起。
EXPIRING_CATS = {"其他"}
CASE_SEP_RE = re.compile(r"[：:，,（(、;；【\[]")   # 案件标签 = 条目开头至首个分隔符
CASE_MIN_PREFIX = 2   # 判为同一案件所需的最短公共前缀（字符）
CASE_LABEL_MAX = 16   # 案件标签显示上限（字符）
DATE_HEAD_RE = re.compile(r"^[\d/\-\.\s年月日号]+$")
GENERIC_HEADS = {"建议", "提醒", "注意", "待办", "待决", "在等", "时限", "事项"}
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
PUNCT_RE = re.compile(r"[\s，。、：；！？（）()【】\[\]「」“”\"'·—–\-]+")

# 法律工作识别（v1 规则：先剔除易误伤词，再命中关键词）
LEGAL_EXCLUDE = ["方案", "答案", "档案"]
LEGAL_KWS = ["案", "诉", "执行", "法院", "仲裁", "律师", "开庭", "送达", "调查令", "函",
             "协议", "合同", "意见书", "委托", "保全", "再审", "答辩", "庭审", "立案",
             "证据", "文书", "会见", "缴", "催", "欠租", "住建", "国土"]

STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"


def _hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "hermes"
    return Path.home() / ".hermes"


# ── 文本 ─────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return PUNCT_RE.sub("", str(text or "").strip().lower())


def _is_legal(text: str) -> bool:
    t = str(text or "")
    for w in LEGAL_EXCLUDE:
        t = t.replace(w, "")
    return any(k in t for k in LEGAL_KWS)


def _category(section: str, text: str) -> str:
    if not _is_legal(text):
        return "其他"
    s = section or ""
    if "时限" in s:
        return "案件时限"
    if "建议" in s:
        return "工作建议"
    return "案件进展"


# ── 案件归并 / 日期 ─────────────────────────────────────────────────

def _today_local():
    """本机日期（用于「次日收起」，按本地时区即北京时间）。"""
    return datetime.now().astimezone().date()


def _case_head(text: str) -> str:
    """条目开头至首个分隔符的一段，作为案件/主题候选名。"""
    head = CASE_SEP_RE.split(str(text or "").strip(), 1)[0].strip()
    return head.strip("《》「」【】“”\"' ")


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _clean_label(label: str) -> str:
    """标签截断后去掉尾部的连接符与标点。"""
    return str(label or "").strip()[:CASE_LABEL_MAX].rstrip(" -—–·、,，:：/.")


def _arrange_cases(items: list) -> list:
    """同一分类内把同一案件的条目聚到一起，分类与组内均保持原先后顺序。"""
    order, buckets = [], {}
    for it in items:
        cat = it["category"]
        if cat not in buckets:
            buckets[cat] = []
            order.append(cat)
        buckets[cat].append(it)

    arranged = []
    for cat in order:
        groups = []          # [{"heads": [...], "keys": [...], "rows": [...]}]
        for it in buckets[cat]:
            head = _case_head(it["text"])
            key = _normalize(head)
            target = None
            if key and key not in GENERIC_HEADS and not DATE_HEAD_RE.match(head):
                for g in groups:
                    if any(_common_prefix(key, k) >= CASE_MIN_PREFIX for k in g["keys"]):
                        target = g
                        break
            if target is None:
                groups.append({"heads": [head], "keys": [key] if key else [], "rows": [it]})
                target = groups[-1]
            else:
                target["rows"].append(it)
                target["heads"].append(head)
                if key:
                    target["keys"].append(key)

        for g in groups:
            label = g["heads"][0].strip()
            if len(g["rows"]) > 1:
                lcp = g["heads"][0]
                for h in g["heads"][1:]:
                    lcp = lcp[: _common_prefix(lcp, h)]
                lcp = lcp.strip()
                if len(lcp) >= 4:          # 公共前缀够具体才用它当标签
                    label = lcp
            if (_normalize(label) in GENERIC_HEADS or not label
                    or DATE_HEAD_RE.match(label)):
                label = ""                 # 通用词/日期开头：不做案件标签、不显示
            for it in g["rows"]:
                it["case"] = _clean_label(label)
                it["case_count"] = len(g["rows"])
                arranged.append(it)
    return arranged


# ── 读提要文件 ───────────────────────────────────────────────────────

def _extract_digest(text: str) -> str:
    marker = "## Response"
    idx = text.find(marker)
    body = text[idx + len(marker):] if idx >= 0 else text
    return body.strip()


def _load_days() -> list:
    """最近 30 天的提要，按日期倒序（同日取最新一次运行）。"""
    home = _hermes_home()
    out_dir = home / "cron" / "output"
    days = {}

    def _add(date: str, body: str, mtime: float) -> None:
        prev = days.get(date)
        if prev and prev["mtime"] >= mtime:
            return
        days[date] = {"date": date, "body": body, "mtime": mtime}

    job_dir = out_dir / JOB_ID
    if job_dir.is_dir():
        for path in sorted(job_dir.glob("*.md")):
            m = DATE_RE.match(path.name)
            if not m:
                continue
            try:
                body = _extract_digest(path.read_text(encoding="utf-8", errors="replace"))
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if body.startswith("## 待办提要"):
                _add(m.group(1), body, mtime)

    latest = out_dir / "_digest_latest.md"
    if latest.exists():
        try:
            body = latest.read_text(encoding="utf-8", errors="replace").strip()
            m = DATE_RE.search(body.split("\n", 1)[0] if body else "")
            if body and body.startswith("## 待办提要") and m:
                _add(m.group(1), body, latest.stat().st_mtime)
        except OSError:
            pass

    return sorted(days.values(), key=lambda d: d["date"], reverse=True)


def _parse_items(body: str) -> list:
    """把提要正文解析成 [{section, text}]，跳过覆盖说明。"""
    items = []
    section = ""
    for raw in str(body or "").split("\n"):
        line = raw.rstrip()
        if line.startswith("### "):
            section = line[4:].strip()
            continue
        if line.startswith("## ") or not line.strip():
            continue
        if "覆盖说明" in section:
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append({"section": section, "text": stripped[2:].strip()})
        elif items and not stripped.startswith("#"):
            # 续行并入上一条
            items[-1]["text"] = (items[-1]["text"] + " " + stripped).strip()
    return [it for it in items if it["text"]]


# ── 状态存取 ─────────────────────────────────────────────────────────

def _load_state() -> tuple[list, str | None]:
    """返回 (记录, 错误说明)。文件不存在＝首次；存在但读不出＝观测故障（不得当空集合）。"""
    if not STATE_PATH.exists():
        return [], None
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], f"{type(exc).__name__}"
    if not isinstance(data, dict):
        return [], "结构异常（非对象）"
    records = data.get("records", [])
    if not isinstance(records, list):
        return [], "records 字段结构异常"
    return records, None


def _save_state(records: list) -> None:
    """唯一临时名 + 原子替换 + 失败清理；保存失败抛 RuntimeError（不静默丢状态）。"""
    payload = {"records": records, "updated_at": datetime.now(timezone.utc).isoformat()}
    tmp = STATE_PATH.with_name(STATE_PATH.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, STATE_PATH)
    except OSError as exc:
        # 保存失败必须让请求失败：静默返回会让用户以为操作已生效，而状态其实被丢弃
        raise RuntimeError(f"操作记录保存失败：{exc}") from exc
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _find_record(nk: str, records: list):
    best, score = None, 0.0
    for rec in records:
        rk = str(rec.get("key") or "")
        if rk == nk:
            return rec
        s = difflib.SequenceMatcher(None, nk, rk).ratio()
        if s > score:
            best, score = rec, s
    if best is not None and score >= MATCH_RATIO:
        return best
    return None


def _similar(a: str, b: str) -> bool:
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= MATCH_RATIO


def _short_id(nk: str) -> str:
    return hashlib.sha1(nk.encode("utf-8")).hexdigest()[:10]


# ── 组装 ─────────────────────────────────────────────────────────────

def build_payload() -> dict:
    days = _load_days()
    records, state_err = _load_state()
    today = _today_local()
    pending, seen = [], []

    for day in days[:MAX_DAYS]:
        for it in _parse_items(day["body"]):
            nk = _normalize(it["text"])
            if not nk or any(_similar(nk, s) for s in seen):
                continue
            seen.append(nk)
            rec = _find_record(nk, records)
            state = str(rec.get("state", "open")) if rec else "open"
            if state in ("done", "deleted"):
                continue            # 已勾选完成 / 删除：不再出现在待办
            category = it["section"] and _category(it["section"], it["text"]) or "其他"
            important = bool(rec.get("important")) if rec else False
            if category in EXPIRING_CATS and not important and day["date"] < today.isoformat():
                continue            # 非重要条目：第二天起收起
            pending.append({
                "id": _short_id(nk), "text": it["text"], "category": category,
                "section": it["section"], "date": day["date"], "state": state,
                "important": important,
            })

    # 「稍后」未再出现、或标星后未再出现的记录，继续展示
    for rec in records:
        state = str(rec.get("state") or "open")
        if state in ("done", "deleted"):
            continue
        rk = str(rec.get("key") or "")
        if not rk or any(_similar(rk, s) for s in seen):
            continue
        important = bool(rec.get("important"))
        if not important:
            if state != "later":
                continue
            try:
                age = (today - datetime.strptime(rec.get("date", ""), "%Y-%m-%d").date()).days
            except ValueError:
                age = 0
            if age > CARRY_DAYS:
                continue
        pending.append({
            "id": _short_id(rk), "text": rec.get("text", ""), "category": rec.get("category", "其他"),
            "section": "", "date": rec.get("date", ""), "state": state,
            "important": important,
        })

    pending = _arrange_cases(pending)

    def _state_list(state: str) -> list:
        out = [r for r in records if r.get("state") == state and r.get("text")]
        out.sort(key=lambda r: str(r.get("at", "")), reverse=True)
        return [{
            "id": _short_id(str(r.get("key") or "")), "text": r.get("text", ""),
            "category": r.get("category", "其他"), "date": r.get("date", ""),
            "state": state, "at": r.get("at", ""),
        } for r in out[:80]]

    return {
        "pending": pending,
        "done": _state_list("done"),
        "deleted": _state_list("deleted"),
        "days": [d["date"] for d in days[:MAX_DAYS]],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # 操作记录读不出时如实告知（面板可据此提示），不把坏状态当成"没有记录"
        "state_error": state_err,
    }


class ActionBody(BaseModel):
    text: str
    action: str
    category: str = ""
    date: str = ""


def set_action(body) -> dict:
    text = str(body.text or "").strip()
    action = str(body.action or "").strip()
    if not text or action not in ("done", "later", "delete", "open", "important", "normal"):
        return {"ok": False, "error": "bad request"}
    nk = _normalize(text)
    records, state_err = _load_state()
    if state_err:
        # 状态读不出时不得当空集合继续写：否则会把既有操作记录整体覆盖掉
        return {"ok": False, "error": f"操作记录不可读（{state_err}），本次未写入"}
    rec = _find_record(nk, records)

    if action in ("important", "normal"):        # 标星 / 取消标星
        flag = action == "important"
        if rec is None:
            rec = {
                "key": nk, "text": text, "state": "open",
                "at": datetime.now(timezone.utc).isoformat(),
                "date": str(body.date or ""), "category": str(body.category or "其他"),
            }
            records.append(rec)
        elif not flag and str(rec.get("state") or "open") == "open":
            # 只是为标星而存在的记录：取消标星后直接清掉，不留无用记录
            records = [r for r in records if r is not rec]
            _save_state(records)
            return {"ok": True, "state": "open", "important": False}
        rec["important"] = flag
        rec["text"] = text
        if body.category:
            rec["category"] = body.category
        _save_state(records)
        return {"ok": True, "state": str(rec.get("state") or "open"), "important": flag}

    if action == "open":
        if rec is not None and rec.get("important"):
            rec["state"] = "open"                # 标星记录保留标星，恢复为待办
            rec["at"] = datetime.now(timezone.utc).isoformat()
            rec["text"] = text
        else:
            records = [r for r in records if r is not rec]
        _save_state(records)
        return {"ok": True, "state": "open"}
    state = {"done": "done", "later": "later", "delete": "deleted"}[action]
    if rec is not None:
        rec["state"] = state
        rec["at"] = datetime.now(timezone.utc).isoformat()
        rec["text"] = text
        if body.category:
            rec["category"] = body.category
    else:
        records.append({
            "key": nk, "text": text, "state": state,
            "at": datetime.now(timezone.utc).isoformat(),
            "date": str(body.date or ""), "category": str(body.category or "其他"),
        })
    _save_state(records)
    return {"ok": True, "state": state}


# ── 路由 ─────────────────────────────────────────────────────────────

@router.get("/items")
async def items() -> dict:
    try:
        return build_payload()
    except Exception as exc:  # never 500 the pane
        return {"pending": [], "done": [], "deleted": [], "days": [], "error": str(exc)}


@router.post("/action")
async def action(body: ActionBody) -> dict:
    try:
        return set_action(body)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/digests")
async def digests() -> dict:
    try:
        days = _load_days()
        return {"items": [{"date": d["date"], "markdown": d["body"]} for d in days[:MAX_DAYS]],
                "generated_at": datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        return {"items": [], "error": str(exc)}
