# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Lawyer workbench plugin API — runs inside the Hermes gateway.

Reuses the standalone adapter's data functions (case.md discovery, session
merge log) so the desktop pane has a gateway-native backend and does NOT
depend on the external 【IP】:8797 adapter process.

Mounted at /api/plugins/lawyer-workbench/ by the gateway plugin loader.
Read-only for case files; merge actions write only this plugin's own
session-merge.json.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import shutil
import hashlib
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

# The standalone adapter lives next to this plugin's workbench files.
ADAPTER_DIR = Path(r"[本地路径]")
# 角色卡目录（单一数据源：lawyer-os/roles/）
ROLES_DIR = Path(os.environ.get("HERMES_HOME", str(Path.home() / "AppData" / "Local" / "hermes"))) / "lawyer-os" / "roles"

# 期限台账（律师工作台「案件总览」读取显示）
# 唯一来源：lawyer-workbench.json 的 deadline_file；读不到配置时回退现任台账。
# 2026-09-30：配置曾指向 【本机标识】/记忆/案件时限台账.md —— 那是 2026-09-17 已被现任台账承接的旧表
# （旧表自身表头写明"已停更两个月，仅移入仍有效条目"，且含 2026-07-02／2026-07-22 两条已过期日期）。
# 代码这里一直读的是现任台账，错的是配置，故以配置为准并回退现任路径，避免两处各读一份。
_WORKBENCH_CONFIG = (
    Path(os.environ.get("HERMES_HOME", str(Path.home() / "AppData" / "Local" / "hermes")))
    / "lawyer-workbench.json"
)
DEADLINE_FALLBACK = Path(r"[本地路径]")


def deadline_file() -> Path:
    """返回期限台账路径：配置优先，缺失/不存在时回退现任台账。"""
    try:
        cfg = json.loads(_WORKBENCH_CONFIG.read_text(encoding="utf-8"))
        p = Path(str(cfg.get("deadline_file", "")).strip())
        if str(p) and p.exists():
            return p
    except (OSError, ValueError, TypeError):
        pass
    return DEADLINE_FALLBACK
# 「打开目录」允许的根路径
OPEN_ROOTS = (Path(r"[本地路径]"), Path(r"[本地路径]"))
# 可写回的记录文件（勾选待办）与允许根
# 可写回的记录文件：与面板展示待办的来源保持一致——读得到待办的文件就该能勾选。
# `_关键日期.md` 是期限类案件的待办载体（格式同为 `- [ ]`），此前只读不可写，
# 使该类事项在面板上点「已经办理」必然失败（2026-10-01 检查发现）。
WRITABLE_RECORDS = ("case.md", "常法工作索引.md", "_关键日期.md")
WRITE_ROOT = Path(r"[本地路径]")
# 记录写回前的集中备份目录（置于 HERMES_HOME 内：不受"临时工作区"整理影响，随月度快照一并备份）
RECORD_BACKUP_DIR = (
    Path(os.environ.get("HERMES_HOME", str(Path.home() / "AppData" / "Local" / "hermes")))
    / "plugins" / "lawyer-workbench" / "_record_backups"
)

router = APIRouter()

# build_payload 全库扫描耗时数秒，必须在线程池执行，不能阻塞 serve 事件循环。
# 前端每 30s 轮询一次；TTL 缓存避免每次请求都重建。
_PAYLOAD_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
_PAYLOAD_TTL = 180.0
# 适配层文件 mtime，用于"变化才 reload"（保留热更新，避免每请求 reload 约 4s）
_ADAPTER_FILE_MTIME = [0.0]


def _annotate_writable(data: dict) -> dict:
    """给每个事项标注其记录文件能否写回。

    判定与写入白名单**同源**（都用 WRITABLE_RECORDS），由后端算好交给前端，
    避免前端再拼一遍文件名规则——那正是"判定已经共享、前端又写一遍"的老毛病。
    缺 record_path 的事项标为不可写：宁可提前置灰说明，也别让用户点了才报错。
    """
    if not isinstance(data, dict):
        return data
    for m in (data.get("matters") or []):
        if not isinstance(m, dict):
            continue
        rp = str(m.get("record_path") or "").strip()
        name = Path(rp).name if rp else ""
        m["record_name"] = name
        m["record_writable"] = bool(name) and name in WRITABLE_RECORDS
    return data


def _build_payload() -> dict:
    """调用适配层的 build_payload（按需导入，仅适配层文件变化时 reload）。"""
    import sys
    if str(ADAPTER_DIR) not in sys.path:
        sys.path.insert(0, str(ADAPTER_DIR))
    try:
        import importlib
        import lawyer_workbench_adapter as _adapter
        try:
            mtime = Path(_adapter.__file__).stat().st_mtime
        except OSError:
            mtime = 0.0
        if _ADAPTER_FILE_MTIME[0] != mtime:
            # 文件已变化（或首次调用后记录的基线）：reload 保证最新代码与索引逻辑生效，
            # 不必重启桌面 serve/gateway。文件未变化时直接复用已加载模块，省去 reload 开销。
            _adapter = importlib.reload(_adapter)
            _ADAPTER_FILE_MTIME[0] = mtime
        return _annotate_writable(_adapter.build_payload())
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "error": f"适配层模块导入失败：{exc}"}


def _cached_payload() -> dict:
    """TTL 缓存版 build_payload；失败结果不缓存，下次请求重建。"""
    now = time.time()
    cached = _PAYLOAD_CACHE.get("data")
    if cached is None or now - float(_PAYLOAD_CACHE.get("at", 0.0)) > _PAYLOAD_TTL:
        data = _build_payload()
        if data.get("ok"):
            _PAYLOAD_CACHE["data"] = data
            _PAYLOAD_CACHE["at"] = now
        return data
    return cached


def _merge_log_path() -> Path:
    return ADAPTER_DIR / "session-merge.json"


@router.get("/workbench")
async def workbench() -> dict:
    # 同步全库扫描(7-12s)必须在线程池执行，避免阻塞 serve 事件循环导致 WebSocket 断连
    return await asyncio.to_thread(_cached_payload)


@router.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "read_only": True,
        "plugin": "lawyer-workbench",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "adapter_dir": str(ADAPTER_DIR),
    }


@router.post("/merge")
async def merge(body: dict) -> dict:
    key = str(body.get("key") or "").strip()
    action = str(body.get("action") or "").strip()
    target_matter = body.get("target_matter")
    if not key or action not in ("merged", "ignored", "unmerged"):
        return {"ok": False, "error": "参数需为 key 与 action=merged|ignored|unmerged"}

    def _do_merge() -> dict:
        # 与 /workbench 同源：先 reload 适配层，确保使用最新模块与归并台账逻辑
        _build_payload()
        path = _merge_log_path()
        try:
            if path.exists():
                log = json.loads(path.read_text(encoding="utf-8"))
            else:
                log = {}
            if not isinstance(log, dict):
                log = {}
            entries = log.setdefault("entries", [])
            entries[:] = [e for e in entries if not (isinstance(e, dict) and e.get("key") == key)]
            if action != "unmerged":
                entry = {"key": key, "action": action, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                if action == "merged" and isinstance(target_matter, dict):
                    entry["target_matter"] = {
                        "id": target_matter.get("id"),
                        "name": target_matter.get("name"),
                        "category": target_matter.get("category"),
                    }
                entries.append(entry)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            return {"ok": False, "error": f"归并台账写入失败：{exc}"}
        # 归并台账已变化，失效 /workbench 缓存
        _PAYLOAD_CACHE["data"] = None
        cnt: dict[str, int] = {}
        for e in entries:
            if isinstance(e, dict):
                a = str(e.get("action"))
                cnt[a] = cnt.get(a, 0) + 1
        return {"ok": True, "key": key, "action": action, "merge_stats": {"merged": cnt.get("merged", 0), "ignored": cnt.get("ignored", 0)}}

    return await asyncio.to_thread(_do_merge)


def _read_team() -> dict:
    """读取 lawyer-os/roles/ 角色卡目录，解析团队花名册。

    标题格式 `# 00 总台 · 分诊与派工`；解析失败时回退文件名。
    文件不存在或为空返回 count=0，前端做降级展示。
    """
    roles: list[dict[str, str]] = []
    if ROLES_DIR.exists():
        for p in sorted(ROLES_DIR.glob("*.md")):
            if p.name.lower() == "readme.md":
                continue
            rid, name, subtitle = "", p.stem, ""
            try:
                first = p.read_text(encoding="utf-8").splitlines()[0].strip()
            except (OSError, IndexError):
                first = ""
            m = re.match(r"^#\s*(\d{1,2})\s+(.+?)\s*·\s*(.+)$", first)
            if m:
                rid, name, subtitle = m.group(1), m.group(2).strip(), m.group(3).strip()
            else:
                parts = p.stem.split("-", 1)
                if len(parts) == 2 and parts[0].isdigit():
                    rid, name = parts[0], parts[1]
            roles.append({"id": rid, "name": name, "subtitle": subtitle, "file": p.name})
    return {
        "ok": True,
        "roles": roles,
        "count": len(roles),
        "dir": str(ROLES_DIR),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@router.get("/team")
async def team() -> dict:
    return await asyncio.to_thread(_read_team)


# ---------------------------------------------------------------------------
# 期限台账（/deadlines）· 打开目录（/open-folder）· 勾选待办写回（/toggle-todo）
# ---------------------------------------------------------------------------


def _is_within(path: Path, root: Path) -> bool:
    """判断 path 是否位于 root 之内（大小写不敏感，Windows）。"""
    p, r = str(path).lower(), str(root).lower().rstrip("\\/")
    return p == r or p.startswith(r + os.sep)


_TENTATIVE = ("约", "待核实", "待定", "待补", "另定", "未定", "暂定", "待确认", "以判决", "以送达")


def _is_tentative(value) -> bool:
    """台账里的约期/待核实表述 —— 与 lawyer_ops.parse_deadlines 的 pending 同义，不是解析错误。"""
    s = str(value or "").strip()
    return bool(s) and any(t in s for t in _TENTATIVE)


# ── 期限判定唯一真源：scripts/lawyer_deadline_core.py ──
# 「状态 × 日期质量」两维并列，不再用一个覆盖另一个；与 scripts/lawyer_ops.py 共用同一份规则
# （第 5 轮外部复核判定：仅靠注释互指的手动同步不足以收敛，须共享纯函数）。
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from lawyer_deadline_core import (  # noqa: E402
    CONFIG_KEY_SOON,
    DEFAULT_SOON_DAYS,
    MILESTONE_STATUS,
    TERMINAL_STATUS,
    bucket as _bucket,
    date_quality,
    needs_receipt,
    parse_date as _core_parse_date,
    resolve_window,
    status_class,
)


def _config_snapshot() -> dict:
    """工作台配置快照；读不到或顶层不是对象时返回空 dict（不抛错）。"""
    try:
        cfg = json.loads(_WORKBENCH_CONFIG.read_text(encoding="utf-8"))
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def soon_days() -> int:
    """面板临近窗口（天）：配置 `deadline_soon_days`，默认 30；解析全权交给 core。

    窗口是内部提醒用的天数阈值，不是任何法定期限；改配置即可调档，不必动代码。
    复核 F01：顶层非对象、bool/浮点、inf、越界一律安全回落，不用裸 int()。
    """
    return resolve_window(_config_snapshot(), CONFIG_KEY_SOON, DEFAULT_SOON_DAYS)


def _classify_deadlines(items: list[dict]) -> dict:
    """按共享核心分桶：需决定 / 临近 / 待核 / 更远 / 已排除（五桶互斥且完备）。

    每条同时带 `status_class`（done/event/open/unknown）与 `date_quality`
    （date/tentative/invalid）两个维度，便于前端按需展示；只分类与排序，
    不改状态、不自动关项、不推算诉讼期间。
    """
    today = datetime.now().date()
    window = soon_days()
    out: dict[str, list[dict]] = {k: [] for k in ("decide", "soon", "unverified", "far", "excluded")}
    for it in items:
        # 非 dict 元素不抛异常：安全取字段 + 由 core 归入 unverified 并计入 bad_items
        # （复核 F06），保证"五桶互斥且完备 + balanced 恒等式"对任意输入成立。
        src = it if isinstance(it, dict) else {}
        row = {"case": src.get("case", ""), "matter": src.get("matter", ""),
               "due": src.get("due", ""), "status": src.get("status", ""),
               "note": src.get("note", ""), "due_kind": src.get("due_kind", ""),
               "status_class": status_class(src.get("status", "")),
               "date_quality": date_quality(src.get("due", ""))}
        if not isinstance(it, dict):
            row["structure"] = f"非对象元素（{type(it).__name__}）"
        d = _core_parse_date(src.get("due", ""))
        if d is not None:
            row["days_left"] = (d - today).days
        name, reason = _bucket(it, today, window)
        row["bucket"] = name
        row["reason"] = reason
        out[name].append(row)
    out["soon"].sort(key=lambda x: x.get("days_left", 0))
    out["far"].sort(key=lambda x: x.get("days_left", 0))
    out["decide"].sort(key=lambda x: x.get("days_left", 10 ** 6))
    counts = {k: len(v) for k, v in out.items()}
    bad = sum(1 for x in items if not isinstance(x, dict))
    return {**out, "soon_days": window, "counts": counts, "bad_items": bad,
            # 覆盖恒等式：五类之和＝台账数据行数，前端与复核方可直接对账。
            "total": sum(counts.values()), "balanced": sum(counts.values()) == len(items)}


def _read_deadlines() -> dict:
    """解析案件期限台账 markdown 表格。来源单一（配置→回退现任台账），并回传来源与覆盖状态。"""
    src = deadline_file()
    items: list[dict[str, str]] = []
    meta: dict[str, Any] = {"file": str(src), "file_name": src.name}
    if not src.exists():
        # 来源缺失不得呈现成"没有期限"：明确报覆盖不完整，前端据此显示提示而非空清单。
        return {"ok": False, "coverage": "missing", "items": [], "count": 0,
                "error": f"期限台账不存在：{src}", **meta}
    try:
        text = src.read_text(encoding="utf-8")
        meta["file_mtime"] = datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError as exc:
        return {"ok": False, "coverage": "unreadable", "items": [], "count": 0,
                "error": f"期限台账读取失败：{exc}", **meta}
    issues: list[str] = []
    header_seen, rows = False, 0
    for num, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cols = [c.strip() for c in s.strip("|").split("|")]
        if not cols:
            continue
        if cols[0] and set(cols[0]) <= set("-: "):  # 分隔行 |---|---|（首格必须非空，否则空行会被误吞）
            continue
        if cols[0] in ("案件", "案件名称"):
            header_seen = True
            continue
        if not cols[0]:
            # 首格为空＝该行没有案件身份：不能静默跳过，否则漏算却仍报 complete（复核 N03）。
            issues.append(f"第{num}行首列（案件）为空，未纳入且需人工核对")
            continue
        if len(cols) < 4:
            issues.append(f"第{num}行列数不足，未纳入")
            continue
        rows += 1
        due_raw = cols[2]
        # 日期质量由共享核心判定（date / tentative / invalid），与 lawyer_ops 同源。
        due_kind = date_quality(due_raw)
        if due_kind == "invalid":
            # 真解析问题：**保留该行**并标 invalid（复核 R02：此前在此剔除，导致
            # 同一事项在脚本里被保留、在面板里消失，items 数与台账源行数不闭合）。
            issues.append(f"第{num}行 [{cols[0]}]：期限既非日期也非约期表述（{due_raw}）")
        # 约期/待核实/待核对的条目都进 items（面板要能看到），只是标记日期性质
        items.append({
            "case": cols[0],
            "matter": cols[1],
            "due": due_raw,
            "status": cols[3],
            "note": cols[4] if len(cols) > 4 else "",
            "due_kind": due_kind,
            # 供前端直接复用共享核心的状态判定，避免前端再写一套终态正则（复核 F05）
            "status_class": status_class(cols[3]),
        })
    if not header_seen:
        issues.append("未识别到台账表头（需含「案件」列），本次解析覆盖不完整")
    if rows == 0:
        issues.append("台账无数据行，尚不能据此确认案件期限已登记完整")
    return {
        "ok": True,
        "coverage": "complete" if not issues else "partial",
        "items": items,
        "count": len(items),
        "issues": issues[:20],
        "issue_count": len(issues),
        # U12：只呈现「下一动作」的三类分类（不改状态、不自动关项）。
        "next_actions": {
            **_classify_deadlines(items),
            **({"source_warning": f"台账解析覆盖不完整（{len(issues)} 项），未纳入的条目不在清单内"}
               if issues else {}),
        },
        **meta,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@router.get("/deadlines")
async def deadlines() -> dict:
    return await asyncio.to_thread(_read_deadlines)


def _open_target(raw: str) -> dict:
    if not raw.strip():
        return {"ok": False, "error": "缺少 path"}
    try:
        p = Path(raw).resolve()
    except OSError as exc:
        return {"ok": False, "error": f"路径无效：{exc}"}
    if not any(_is_within(p, root) for root in OPEN_ROOTS):
        return {"ok": False, "error": "路径不在允许范围"}
    if not p.exists():
        return {"ok": False, "error": "路径不存在"}
    try:
        os.startfile(str(p))  # noqa: S606 — Windows 专用
    except OSError as exc:
        return {"ok": False, "error": f"打开失败：{exc}"}
    return {"ok": True, "opened": str(p)}


@router.post("/open-folder")
async def open_folder(body: dict) -> dict:
    return await asyncio.to_thread(_open_target, str(body.get("path") or "").strip())


# 待办写回的每文件锁：同一记录的读→核→写全程串行，避免并发勾选互相覆盖
_TODO_LOCKS: dict[str, Any] = {}
_TODO_LOCKS_GUARD = threading.Lock()


def _todo_lock(key: str) -> threading.Lock:
    with _TODO_LOCKS_GUARD:
        return _TODO_LOCKS.setdefault(key, threading.Lock())


def _toggle_todo_sync(record: str, text: str, done: bool,
                      expected_sha256: str = "", line_no: int | None = None) -> dict:
    """把记录文件中的一条待办标记为完成/未完成（2026-09-30 加固）。

    加固点（对应 09-30 独立核查 P1）：
    - 版本核对：请求带 expected_sha256 时，与当前文件哈希不一致即拒绝（面板显示的是旧状态）
    - 唯一定位：同名待办多于一处时拒绝并回报行号，不再默默改第一处；带 line_no 时按行精确命中
    - 串行化：同一文件的读→核→写全程持锁，两次并发勾选不再丢失彼此改动
    - 写后读回：写入后重读比对，不一致立即从备份回滚并报失败
    - 保留原始行尾：按字节解码、按行原样写回，不做事先 CRLF 规范化

    - 只允许 case.md / 常法工作索引.md，且位于 [本地路径] 内
    - 匹配 `- [ ] text` / `- text`（标完成）或 `- [x] text`（取消完成）
    - 写前备份到 _record_backups/
    """
    if not record or not text:
        return {"ok": False, "error": "缺少 record_path 或 text"}
    p = Path(record)
    if p.name not in WRITABLE_RECORDS:
        return {"ok": False, "error": "只支持写回 " + " / ".join(WRITABLE_RECORDS)}
    try:
        rp = p.resolve()
    except OSError as exc:
        return {"ok": False, "error": f"路径无效：{exc}"}
    if not _is_within(rp, WRITE_ROOT):
        return {"ok": False, "error": "记录文件不在允许范围"}
    if not rp.exists():
        return {"ok": False, "error": "记录文件不存在"}

    pat_open = re.compile(r"^(\s*)[-*]\s*\[[ ~]\]\s+" + re.escape(text) + r"\s*$")
    pat_plain = re.compile(r"^(\s*)[-*]\s+" + re.escape(text) + r"\s*$")
    pat_done = re.compile(r"^(\s*)[-*]\s*\[[xX]\]\s+" + re.escape(text) + r"\s*$")

    with _todo_lock(str(rp).lower()):
        try:
            raw = rp.read_bytes()
        except OSError as exc:
            return {"ok": False, "error": f"读取失败：{exc}"}
        cur_sha = hashlib.sha256(raw).hexdigest()
        if expected_sha256 and expected_sha256.strip().lower() != cur_sha:
            return {"ok": False, "current_sha256": cur_sha,
                    "error": "记录文件在面板读取之后已被修改，已拒绝写入；请刷新后重试"}
        try:
            text_all = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            return {"ok": False, "error": f"文件编码异常，拒绝写回：{exc}"}

        lines = re.split(r"(?<=\n)", text_all)   # 逐行原样保留行尾（CRLF 不丢）
        if lines and lines[-1] == "":
            lines.pop()

        hits = []            # [(行序, 类型)]，全部命中都要看清，不能再默默取第一处
        for i, raw_line in enumerate(lines):
            body_line = raw_line.rstrip("\r\n")
            if done:
                if pat_open.match(body_line) or pat_plain.match(body_line):
                    hits.append((i, "open"))
            elif pat_done.match(body_line):
                hits.append((i, "done"))

        if not hits:
            return {"ok": False, "error": "未找到匹配的待办行（内容可能已变更，请刷新后重试）"}

        if line_no:
            target = int(line_no) - 1
            if not any(i == target for i, _ in hits):
                return {"ok": False, "match_lines": [i + 1 for i, _ in hits],
                        "error": f"第 {line_no} 行不是该待办（文件已变更），已拒绝写入；请刷新后重试"}
        elif len(hits) > 1:
            return {"ok": False, "match_lines": [i + 1 for i, _ in hits],
                    "error": (f"同名待办共 {len(hits)} 处（第 "
                              + "、".join(str(i + 1) for i, _ in hits)
                              + " 行），无法确定目标，已拒绝写入；请刷新后按具体条目勾选")}
        else:
            target = hits[0][0]

        raw_line = lines[target]
        body_line = raw_line.rstrip("\r\n")
        eol = raw_line[len(body_line):] or "\n"
        m = pat_open.match(body_line) or pat_plain.match(body_line) or pat_done.match(body_line)
        lines[target] = f"{m.group(1) if m else ''}- [x] {text}{eol}" if done \
            else f"{m.group(1) if m else ''}- [ ] {text}{eol}"
        new_text = "".join(lines)
        if new_text == text_all:
            return {"ok": False, "error": "内容未发生实际变化，已跳过写入"}
        new_bytes = new_text.encode("utf-8")

        try:
            RECORD_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            bak = RECORD_BACKUP_DIR / f"{rp.stem}-{stamp}-{uuid.uuid4().hex[:6]}{rp.suffix}"
            shutil.copy2(rp, bak)
        except OSError as exc:
            return {"ok": False, "error": f"备份失败，未写入任何改动：{exc}"}

        try:
            tmp = rp.with_name(f"{rp.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
            tmp.write_bytes(new_bytes)
            # 临界区复核：临时文件已写好，替换前再核一次目标（绕过锁的并发改动不得被覆盖）
            now_sha = hashlib.sha256(rp.read_bytes()).hexdigest()
            if now_sha != cur_sha:
                tmp.unlink(missing_ok=True)
                return {"ok": False, "current_sha256": now_sha,
                        "error": "写入临界区发现记录文件被并发修改，已放弃写入；请刷新后重试"}
            os.replace(tmp, rp)
        except OSError as exc:
            return {"ok": False, "error": f"写入失败（备份已存 {bak}）：{exc}"}

        try:
            back = rp.read_bytes()
        except OSError as exc:
            return {"ok": False, "backup": str(bak), "error": f"写入后读回失败（备份已存 {bak}）：{exc}"}
        if back != new_bytes:
            try:
                shutil.copy2(bak, rp)
                rolled = "已回滚到写入前内容"
            except OSError as exc:
                rolled = f"回滚失败，请手工用备份恢复：{exc}"
            return {"ok": False, "backup": str(bak), "error": f"写入后读回不一致，判定失败（{rolled}）"}

        _PAYLOAD_CACHE["data"] = None  # 写回成功：失效 /workbench 缓存，确保下次拉取到最新状态
        return {"ok": True, "record": str(rp), "text": text, "done": done, "line": target + 1,
                "backup": str(bak), "sha256": hashlib.sha256(back).hexdigest()}


@router.post("/toggle-todo")
async def toggle_todo(body: dict) -> dict:
    record = str(body.get("record_path") or "").strip()
    text = str(body.get("text") or "").strip()
    done = bool(body.get("done", True))
    expected = str(body.get("expected_sha256") or "").strip()
    raw_line = body.get("line_no", body.get("line"))
    try:
        line_no = int(raw_line) if raw_line not in (None, "", 0) else None
    except (TypeError, ValueError):
        return {"ok": False, "error": "line_no 必须是整数"}
    return await asyncio.to_thread(_toggle_todo_sync, record, text, done, expected, line_no)
