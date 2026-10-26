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
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

JOB_ID = "7d2b5b26a02c"
MAX_DAYS = 7          # 列表聚合窗口（天）
CARRY_DAYS = 14       # 「稍后」未再出现时的保留窗口（天）
MATCH_RATIO = 0.80    # 跨日 / 状态匹配阈值
# 操作记录保留策略（R9）：完成/删除的非标星记录超过保留期即清理（留档 state-pruned.json）；
# 未办、稍后、标星的记录不受期限与上限约束。
STATE_MAX_AGE_DAYS = 365
STATE_MAX_RECORDS = 800
# 次日收起：这些分类中「非重要」的条目，第二天起不再出现在待办（「原文」视图仍可回看）。
# 调整范围只改这一行，例如 EXPIRING_CATS = {"其他", "工作建议"} 让建议也次日收起。
EXPIRING_CATS = {"其他", "已结清"}
CASE_SEP_RE = re.compile(r"[：:，,（(、;；【\[]")   # 案件标签 = 条目开头至首个分隔符
CASE_MIN_PREFIX = 2   # 判为同一案件所需的最短公共前缀（字符）
CASE_LABEL_MAX = 16   # 案件标签显示上限（字符）
DATE_HEAD_RE = re.compile(r"^[\d/\-\.\s年月日号]+$")
GENERIC_HEADS = {"建议", "提醒", "注意", "待办", "待决", "在等", "时限", "事项"}
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
PUNCT_RE = re.compile(r"[\s，。、：；！？（）()【】\[\]「」“”\"'·—–\-]+")

# ── 提要正文识别（2026-10-19 迭代 R1）────────────────────────────────
# 提要输出格式自 2026-10-13 起由「## 待办提要（日期）」改为
# 「# 每日待办提要｜2026年10月X日」＋「## 【时限】」「## 【冲突】」式分节。
# 旧判定 `body.startswith("## 待办提要")` 使此后每次运行的提要整份被丢弃——
# 看板停在 10-12（10-13/10-15/10-16/10-17 四次运行全部不可见），且没有任何提示。
# 现按**正文特征**识别，并只认已知分节词，避免把同一 job 目录里的其它输出误收。
SECTION_RE = re.compile(r"^#{2,4}\s*(.*)$")
DIGEST_TITLE_RE = re.compile(r"^#{1,3}\s*.*待办提要")
KNOWN_SECTIONS = ("时限", "承诺", "在等", "进行中", "冲突", "新增", "已结清", "已完成",
                  "系统账", "持续未变", "来源", "建议", "覆盖", "待你定", "待办")


def _is_digest_body(body: str) -> bool:
    """判断一段正文是不是一份提要点。

    两条路径：①首部有「待办提要」标题（新旧两种标题都算）；②有 ≥2 条 `- ` 条目，
    且存在命中 KNOWN_SECTIONS 的分节标题。仅靠"有列表"会误收其它任务的输出，
    故保留第二条路径的分节词约束。
    """
    text = str(body or "")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    if any(DIGEST_TITLE_RE.match(ln) for ln in lines[:3]):
        return True
    items = [ln for ln in lines if ln.startswith("- ")]
    if len(items) < 2:
        return False
    for ln in lines:
        m = SECTION_RE.match(ln)
        if m and any(w in m.group(1) for w in KNOWN_SECTIONS):
            return True
    return False

# 法律工作识别（v1 规则：先剔除易误伤词，再命中关键词）
LEGAL_EXCLUDE = ["方案", "答案", "档案"]
LEGAL_KWS = ["案", "诉", "执行", "法院", "仲裁", "律师", "开庭", "送达", "调查令", "函",
             "协议", "合同", "意见书", "委托", "保全", "再审", "答辩", "庭审", "立案",
             "证据", "文书", "会见", "缴", "催", "欠租", "住建", "国土"]

STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"

# /items 的结果缓存（2026-10-19 R7）：前端 60s 轮询，而每次 build_payload 都要重读
# 最近 7 天的提要文件（新格式单份 8–34KB）并解析 state.json（现 64KB）。
# 缓存 TTL 与轮询周期对齐；写操作（set_action）会立即失效缓存。
_PAYLOAD_CACHE: dict = {"at": 0.0, "data": None}
_PAYLOAD_TTL = 60.0


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


# 提要的分节名每次措辞不同（实测同时存在「在等你的决定」14 条与「在等你拍板」5 条、
# 「新发生」7 条与「新增」1 条），直接当分类会让面板裂成十几个标签。这里把同义分节
# 归到固定五档，原文 section 仍保留供追溯。
SECTION_KINDS = (
    ("时限", ("时限", "截止", "到期", "期限")),
    ("待决策", ("决定", "拍板", "待你定", "冲突", "待确认", "待核", "待人工")),
    ("进行中", ("进行中", "推进", "办理中")),
    ("已结清", ("已结清", "已完成", "已结束")),
    ("系统", ("技术", "系统账", "运行现状", "覆盖", "来源与版本")),
)


def _section_kind(section: str) -> str:
    """把提要分节归到固定五档；无分节或推不出的按「新增」处理。"""
    s = str(section or "")
    for kind, kws in SECTION_KINDS:
        if any(k in s for k in kws):
            return kind
    return "新增"


_DUE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DUE_CN = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_DUE_ANCHOR = re.compile(r"(计至|截至|截止|届满|到期|最迟|不迟于|开庭|期限)")


def _first_date_in(seg: str, today):
    """从一段文字里取第一个可解析日期。"""
    m = _DUE_ISO.search(seg)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except ValueError:
            return None
    m = _DUE_CN.search(seg)
    if m:
        try:
            return datetime(today.year, int(m.group(1)), int(m.group(2))).date()
        except ValueError:
            return None
    return None


def _due_of(text: str, today) -> tuple[str, int | None]:
    """取条目里**期限所指**的那个日期，并算剩余天数。

    不能简单取第一个日期：实测「刘珊珊调卷·落款10月13日、计至10月20日」取到 10-13
    会显示"已过 7 天"，而真实期限是 10-20。做法：先找期限语义词（计至/届满/开庭/期限…）
    后 24 字内的日期，找不到再回退到第一个日期。
    只对【时限】分节的条目调用——正文里的叙述性历史日期（执行期、「已开庭」）不是期限。
    取不到或距今 >400 天时返回 ("", None)，不推算。
    """
    t = str(text or "")
    d = None
    for m in _DUE_ANCHOR.finditer(t):
        d = _first_date_in(t[m.end():m.end() + 24], today)
        if d is not None:
            break
    if d is None:
        d = _first_date_in(t, today)
    if d is None or abs((d - today).days) > 400:
        return "", None
    return d.isoformat(), (d - today).days


def _split_item(text: str) -> tuple[str, str]:
    """把条目拆成「标题」和「详情」。

    标题＝作者加粗的那句（提要里每条都把事项名加粗）；没有加粗就取首个句号/分号前。
    面板默认只显示标题一行——实测 43 条 × 平均 150 字正文，一屏放不下三条，
    正文全铺开是"看着乱"的主因。
    """
    t = str(text or "").strip()
    m = FP_BOLD_RE.match(t)
    if m and m.group(1).strip():
        return m.group(1).replace("*", "").strip(), t[m.end():].lstrip("：:，,。 ；;\n")
    for sep in ("。", "；", "\n"):
        i = t.find(sep)
        if 6 <= i <= 60:
            return t[:i].replace("*", "").strip(), t[i + 1:].lstrip()
    return ((t[:48] + "…") if len(t) > 48 else t).replace("*", "").strip(), ""


def _category(section: str, text: str) -> str:
    if not _is_legal(text):
        return "其他"
    return _section_kind(section)


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


# ── 事项指纹：跨日重复合并（2026-10-19 迭代 R2）────────────────────────
# 新格式提要里，同一事项每天重写一遍（措辞不同、信息增量），长度也远大于旧格式：
# 「客户单位 12 份调查令催办」在 10-13/10-15/10-16/10-17 各一条，逐字相似度低于
# MATCH_RATIO（0.80）而无法去重——看板因此堆成 58 条，其中 40 余条是同一批事项的
# 每日快照。做法：取开头加粗标题（或缺省的首个分句）作**事项指纹**，按指纹合并为
# 一条（保留最新日期的表述，回填最早出现日与出现天数）。
# 指纹太短或命中通用词时返回空 → 不作合并，宁可多显示一条，也不把两件事并成一件。
FINGERPRINT_MIN = 4
FP_SUBSTR_MIN = 6      # 连续子串判据：短指纹至少这么长且完整出现在长指纹里
FP_PREFIX_MIN = 8      # 公共前缀判据：前缀至少这么长，且不少于较短者的 6 成
FP_BOLD_RE = re.compile(r"^\*\*(.+?)\*\*")


def _fingerprint(text: str) -> str:
    """条目的事项指纹（用于跨日合并）；无法安全判定时返回空串。"""
    t = str(text or "").strip()
    m = FP_BOLD_RE.match(t)
    head = m.group(1) if m else _case_head(t)
    head = re.sub(r"[（(][^（()）]*[)）]", "", head)        # 去掉括号补充（含「（新）」）
    head = re.split(r"[：:，,；;。！？!?｜|]", head)[0]
    key = _normalize(head)
    if len(key) < FINGERPRINT_MIN or key in GENERIC_HEADS:
        return ""
    return key


def _fp_similar(a: str, b: str) -> bool:
    """两个事项指纹是否指同一事项。

    合并是"宁可少并、不可错并"：错并把两条独立事项压成一条，用户会丢掉一条待办且无从察觉。
    三条保守判据，任一条成立才算同一事项：
      ① 完全相同；
      ② 较短者（≥6 字符）是较长者的**连续子串**——如「客户单位公司合规管理」⊂「客户单位公司合规管理建设研究意见」；
      ③ 公共前缀 ≥8 字符且 ≥ 较短者的 6 成——覆盖「安全生产管理协议四方确认」／「安全生产管理协议甲方立场」。
    刻意不采用整体相似度（如 2-gram Jaccard）：同案不同事项（「客户单位某项目住宅…」与
    「客户单位某项目车位…」）共享大半字面，整体相似度会把它们误并。
    """
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= FP_SUBSTR_MIN and short in long:
        return True
    n = _common_prefix(a, b)
    return n >= FP_PREFIX_MIN and n >= 0.6 * len(short)


# ── 主体（案件/工作线）归并 ────────────────────────────────────────────
# 提要里同一件事常常并存多条：同一份提要内部重复表述、跨日换了措辞、还有一条
# 「汇总条目」把十几项串成一句（而每项另有专条）。实测 60 条里 11 条是客户单位、
# 4 条客户单位调查令、4 条续封、2 条客户单位开庭日几乎同文——用户看到的就是「乱」。
# 做法：①先按主体（案件名）归组；②同主体内用保守判据把同一件事并成一条；
# ③纯过程/自检残片不进列表。主体只认**台账案件列 + 固定工作线**，不从正文自动
# 抽词——实测自动抽词会产出「日唯一的」「本窗口办」这类残片，把「文件夹整理」
# 错归到别的案件名下（错归比不归更糟）。
LEDGER_PATH = Path(r"[本地路径]")
BUILTIN_SUBJECTS = ("公众号", "拆书", "执行工作指导", "邮件", "自进化", "磁盘清理",
                    "文件夹整理", "技能库", "法律库", "临时工作区", "checkpoint", "记忆")
_SUBJECT_CACHE: dict = {"at": 0.0, "list": []}


def _subject_vocab() -> list[str]:
    """主体词表：案件期限台账的案件列（人工维护、可靠）+ 固定工作线；按长度倒序。"""
    now = time.monotonic()
    if _SUBJECT_CACHE["list"] and now - _SUBJECT_CACHE["at"] < 300:
        return _SUBJECT_CACHE["list"]
    names: list[str] = list(BUILTIN_SUBJECTS)
    try:
        for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip().startswith("|"):
                continue
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cols) < 4 or cols[0] in ("案件", "当事人", ""):
                continue
            names.append(cols[0])
            for part in re.split(r"[诉与及、/]", cols[0]):
                if 2 <= len(part) <= 8:
                    names.append(part)
    except OSError:
        pass
    vocab = sorted({n for n in names if 2 <= len(n) <= 10}, key=len, reverse=True)
    _SUBJECT_CACHE.update(at=now, list=vocab)
    return vocab


def _subject_of(text: str) -> str:
    """条目所属主体；**只认加粗标题**，认不出返回空串。

    实测在全文里找主体词会错归：「客户单位两案意见书」正文里提了一句「客户单位 12 份调查令」
    就被归进客户单位组。作者点名的案件在标题里，正文提到别的案件不等于属于它。
    """
    t = str(text or "")
    m = FP_BOLD_RE.match(t.strip())
    head = m.group(1) if m else t[:40]
    for v in _subject_vocab():
        if v in head:
            return v
    # 「客户单位案：目录证据材料补齐了…」——作者在标题里点名了案件，取「案」前那一段。
    # 只在「案」后紧跟冒号/逗号时采用，避免把「客户单位两案意见书」切成「客户单位两」。
    m2 = re.match(r"^([\u4e00-\u9fa5·]{2,5})案[：:，,]", head)
    if m2 and m2.group(1) not in GENERIC_HEADS:
        return m2.group(1)
    return ""


# 事项词（二级折叠用）：同主体内命中同一事项词的多条，只展开最新一条。
# 只收**业务事项**，不收「合同」「案件」这类泛词——泛词会把不相干的事项并在一起。
MATTER_KEYWORDS = ("调查令", "续封", "续冻", "冻结", "开庭", "上诉状", "上诉", "答辩状", "答辩",
                   "举证", "立案", "送达", "执行", "保全", "鉴定", "调卷", "退费", "归档",
                   "意见书", "协议", "证据材料", "清单", "管辖异议", "时效", "催办",
                   "和解", "调解", "申报", "备案", "上诉评估", "回执", "署名", "用章")


def _topic_of(text: str) -> str:
    """条目的业务事项词（同主体内二级折叠用）；命中多个时取最长者。"""
    m = FP_BOLD_RE.match(str(text or "").strip())
    head = m.group(1) if m else str(text or "")[:60]
    hits = [k for k in MATTER_KEYWORDS if k in head]
    if not hits:
        return ""
    return max(hits, key=len)


NOISE_PATTERNS = (
    re.compile(r"^\d{1,4}-\d{1,2}-\d{1,2}[ T]\d{1,2}:\d{2}(:\d{2})?\s*$"),  # 纯时间戳残片
    # 状态陈述：「台账其余条目…无变化」「本轮无新证据」——是进展说明，不是待办。
    # 这类条目会被归到正文里提到的案件组（实测归到客户单位），把真正要办的事挤下去。
    re.compile(r"^(台账其余|其余.{0,12}(项|条|事项).{0,10}(无变化|未变|不变))"),
    re.compile(r"^(本轮|本期)(无变化|无新证据|无进展)"),
    re.compile(r"在阈内"),                                              # 容量自检
    re.compile(r"已更新并回读持续事项台账"),                             # 过程陈述
    re.compile(r"根因找到并已恢复"),                                     # 已恢复的状态陈述
)


def _is_noise(text: str) -> bool:
    """不是待办、也不值得占位的残片与过程陈述（只认确定模式，宁留勿删）。"""
    return any(p.search(str(text or "").strip()) for p in NOISE_PATTERNS)


def _longest_common(a: str, b: str) -> int:
    """最长公共连续子串长度（短文本，截 200 字内）。"""
    a, b = str(a)[:200], str(b)[:200]
    if not a or not b:
        return 0
    best = 0
    prev = [0] * (len(b) + 1)
    for ch in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            if ch == y:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _same_matter(a: str, b: str) -> bool:
    """**已确定同一主体**的两条是否同一件事（保守；仍宁少并不错并）。

    除指纹三判据外补两条：
      ① 共享日期串（同一天开庭、同一期限）且正文有 ≥4 字公共片段；
      ② 加粗标题的最长公共连续片段 ≥8 字——覆盖「客户单位案开庭日已从卷内原件核到…」
         与「新读到的日期：客户单位案开庭…」这类同一事实的两种写法。
    """
    fa, fb = _fingerprint(a), _fingerprint(b)
    if fa and fb and _fp_similar(fa, fb):
        return True
    if (set(DATE_RE.findall(str(a))) & set(DATE_RE.findall(str(b)))) and _longest_common(a, b) >= 4:
        return True
    return _longest_common(fa, fb) >= 8


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


# ── 结构化提要（digest-panel/1，2026-10-21）──────────────────────────
# 提要是写给人看的散文：分节名天天变（「在等你的决定」「在等你拍板」同时存在）、
# 日期混着叙述（执行期、已开庭日）、进展说明混在待办里。插件在散文上做正则推理，
# 猜错就会把过期项藏掉、把进展当待办。这层改为：cron 每天把判断结果落成 JSON，
# 插件直读；读不到再回退解析 md。
PANEL_DIR = Path(r"[本地路径]")
PANEL_SCHEMA = "digest-panel/1"
_PANEL_DISABLED = False          # export 时置 True，避免「读上次导出→再导出」自我循环

_PANEL_KIND = {
    "时限": "时限", "待决策": "待决策", "进行中": "进行中", "在等": "待决策",
    "冲突": "待决策", "进展": "新增", "系统": "系统", "其他": "其他", "新增": "新增",
}


def _load_panel_days() -> list:
    """读 cron 产出的结构化提要（digest-panel/1），按日期倒序。

    每条转换成 `_parse_items` 的等价结构（section/text），下游代码不用改；
    另带 title/detail/subject_raw/due_date，供 item 构造时直接采用。
    读不到、schema 不符、条目为空都返回 []，调用方回退到 md 解析。
    """
    if _PANEL_DISABLED or not PANEL_DIR.is_dir():
        return []
    out = {}
    for path in sorted(PANEL_DIR.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or str(doc.get("schema")) != PANEL_SCHEMA:
            continue
        date_s = str(doc.get("date") or "")
        if not DATE_RE.fullmatch(date_s):
            continue
        rows = []
        for it in (doc.get("items") or []):
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or "").strip()
            if not title:
                continue
            kind = str(it.get("kind") or "新增")
            detail = str(it.get("detail") or "").strip()
            rows.append({
                "section": _PANEL_KIND.get(kind, "新增"),
                "text": f"**{title}**：{detail}" if detail else f"**{title}**",
                "title": title, "detail": detail,
                "due_date": str(it.get("due_date") or ""),
                "subject_raw": str(it.get("subject") or ""),
            })
        if rows:
            out[date_s] = {"date": date_s, "body": "", "items": rows,
                           "mtime": path.stat().st_mtime}
    return sorted(out.values(), key=lambda d: d["date"], reverse=True)


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
            if _is_digest_body(body):
                _add(m.group(1), body, mtime)

    latest = out_dir / "_digest_latest.md"
    if latest.exists():
        try:
            body = latest.read_text(encoding="utf-8", errors="replace").strip()
            m = DATE_RE.search(body.split("\n", 1)[0] if body else "")
            if body and _is_digest_body(body) and m:
                # 陈旧兜底文件：_digest_latest.md 旧流程写入，实测停在 2026-09-29。
                # 只有它不比 job 目录里已读到的日期更旧才采纳，避免陈年提要混进活跃窗口
                # （窗口是「最近 7 个日期」，多一份旧日期就会挤掉一份真正在范围内的）。
                newest = max((d["date"] for d in days.values()), default="")
                if m.group(1) >= newest:
                    _add(m.group(1), body, latest.stat().st_mtime)
        except OSError:
            pass

    return sorted(days.values(), key=lambda d: d["date"], reverse=True)


def _parse_items(body: str) -> list:
    """把提要正文解析成 [{section, text}]。

    兼容两种体例（2026-10-19 R1）：
      旧：`## 待办提要（日期）` ＋ `### 分节` ＋ `- 条目`
      新：`# 每日待办提要｜日期` ＋ `## 【分节】` ＋ `- **条目**`
    文档标题行（含「待办提要」）不当作分节；只有**缩进**的续写才并入上一条，
    其余非条目行（“本轮覆盖…”这类说明段）一律忽略——把说明段并进条目会污染条目文本，
    连带影响状态匹配与写回定位。
    """
    items = []
    section = ""
    for raw in str(body or "").split("\n"):
        line = raw.rstrip()
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            m = SECTION_RE.match(s)
            title = (m.group(1) if m else s.lstrip("#")).strip().strip("【】[]").strip()
            section = "" if ("待办提要" in title or not title) else title
            continue
        if "覆盖" in section:
            continue
        if s.startswith("- "):
            items.append({"section": section, "text": s[2:].strip()})
            continue
        if items and (line.startswith("  ") or line.startswith("\t")):
            items[-1]["text"] = (items[-1]["text"] + " " + s).strip()
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
    """唯一临时名 + 原子替换 + 失败清理；保存失败抛 RuntimeError（不静默丢状态）。

    保存前先做**记录清理**（2026-10-19 R9）：state.json 只增不减——完成的条目会一直留着，
    新格式提要的条目文本又长（>500 字符），文件会持续膨胀（现 64KB/61 条），
    每次读取都要解析它。清理规则保守：只丢「非标星的 done/deleted 且超过保留期」，
    未办/稍后/标星一律保留；被丢弃的记录追加到 state-pruned.json 留档，可人工回退。
    """
    records, dropped = _prune_records(records)
    if dropped:
        _archive_pruned(dropped)
    payload = {
        "records": records,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
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


PRUNED_PATH = STATE_PATH.with_name("state-pruned.json")


def _prune_records(records: list) -> tuple[list, list]:
    """返回 (保留的记录, 被丢弃的记录)；只丢非标星的 done/deleted 且超过保留期或超出硬上限的。"""
    now = datetime.now(timezone.utc)
    keep, dropped = [], []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        state = str(rec.get("state") or "open")
        if state in ("done", "deleted") and not rec.get("important"):
            try:
                at = datetime.fromisoformat(str(rec.get("at") or ""))
            except ValueError:
                at = None          # 时间戳缺失/不可解析：保留（不拿不准的时间戳做删除依据）
            if at is not None and (now - at).days > STATE_MAX_AGE_DAYS:
                dropped.append(rec)
                continue
        keep.append(rec)
    if len(keep) > STATE_MAX_RECORDS:
        # 注意：置 None 不会改变 len(keep)，必须用独立的剩余配额计数——
        # 曾写成 `if len(keep) <= STATE_MAX_RECORDS: break`，导致条件永真、把记录全丢光。
        excess = len(keep) - STATE_MAX_RECORDS
        order = sorted(range(len(keep)), key=lambda i: str(keep[i].get("at") or ""))
        for i in order:
            if excess <= 0:
                break
            st = str(keep[i].get("state") or "open")
            if st in ("done", "deleted") and not keep[i].get("important"):
                dropped.append(keep[i])
                keep[i] = None
                excess -= 1
        keep = [r for r in keep if r is not None]
    return keep, dropped


def _archive_pruned(items: list) -> None:
    """把被清理的记录追加留档（保留最近 1000 条）；留档失败不阻断保存。"""
    if not items:
        return
    try:
        prev = []
        if PRUNED_PATH.exists():
            data = json.loads(PRUNED_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                prev = data
        prev.extend(items)
        PRUNED_PATH.write_text(json.dumps(prev[-1000:], ensure_ascii=False, indent=1), encoding="utf-8")
    except (OSError, ValueError):
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


def _find_record_full(nk: str, text: str, records: list, rid: str = ""):
    """定位这条待办对应的操作记录，并给出**匹配级别**。

    返回 (记录 或 None, 级别)：级别 ∈ "exact" / "fingerprint" / None。

    ① exact：前端带回的 `id`（= sha1(归一化文本)[:10]）或精确 key —— 用户勾的就是这一条；
    ② fingerprint：同一事项换了措辞（提要每天重写）—— **不能当成同一条**：
       提要在后续日期常对同一事项提出**新的诉求**（10-16 勾了「赵磊开庭」，10-17 的
       「未获到庭信息、请告知实际到庭情况」是新事），按事项名隐藏会让这些新诉求静默消失。
       故调用方对 fingerprint 命中的 done 记录只做**标注**，仍显示该条（见 build_payload）。
    不再退回字符串相似度：长文本下「某项目住宅…」与「某项目车位…」ratio>0.99 会被错并，
    而同一事项换措辞只有 0.5–0.8 —— 相似度区分不了这两类，错并比漏匹配更糟。
    """
    for rec in records:
        rk = str(rec.get("key") or "")
        if rk == nk or (rid and _short_id(rk) == rid):
            return rec, "exact"
    fp = _fingerprint(text)
    if fp:
        for rec in records:
            rfp = _fingerprint(str(rec.get("text") or ""))
            if rfp and _fp_similar(fp, rfp):
                return rec, "fingerprint"
    return None, None


def _similar(a: str, b: str) -> bool:
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= MATCH_RATIO


def _short_id(nk: str) -> str:
    return hashlib.sha1(nk.encode("utf-8")).hexdigest()[:10]


# ── 组装 ─────────────────────────────────────────────────────────────

def build_payload() -> dict:
    md_days = _load_days()
    panel_days = _load_panel_days()
    if panel_days:
        # 结构化数据覆盖同日的 md 解析结果：同一天以 cron 显式给出的判断为准，
        # 其余日期仍用 md（panel 可能只产出了最近一两天）。
        by_date = {d["date"]: d for d in md_days}
        for d in panel_days:
            by_date[d["date"]] = d
        days = sorted(by_date.values(), key=lambda d: d["date"], reverse=True)
    else:
        days = md_days
    records, state_err = _load_state()
    today = _today_local()
    pending, seen = [], []
    merged_fp: list[tuple[str, dict]] = []

    noise = 0
    for day in days[:MAX_DAYS]:
        for it in (day.get("items") or _parse_items(day["body"])):
            nk = _normalize(it["text"])
            if not nk or any(_similar(nk, s) for s in seen):
                continue
            seen.append(nk)
            if _is_noise(it["text"]):
                noise += 1            # 残片/过程陈述：不进列表，只计数（用户能看到「另有 N 条」）
                continue
            rec_level = _find_record_full(nk, it["text"], records)
            rec, level = rec_level
            state = str(rec.get("state", "open")) if rec else "open"
            if state == "deleted" or (state == "done" and level == "exact"):
                continue            # 用户明确删掉 / 勾掉的就是这一条：不再出现
            # 仅事项名命中的 done（level=fingerprint）：**仍然显示**，只标注「已办过」——
            # 提要常对同一事项提出新诉求，按事项名隐藏会让新诉求静默消失（2026-10-19 R5 复核）。
            done_like = bool(rec and level == "fingerprint" and state == "done")
            category = it["section"] and _category(it["section"], it["text"]) or "其他"
            important = bool(rec.get("important")) if rec else False
            if category in EXPIRING_CATS and not important and day["date"] < today.isoformat():
                continue            # 非重要条目：第二天起收起
            # 同一事项的跨日重复：保留最新日期的表述（days 已按日期倒序），补记首见日与天数
            fp = _fingerprint(it["text"])
            subj = str(it.get("subject_raw") or "") or _subject_of(it["text"])
            prev = None
            if fp:
                for known_fp, known_item in merged_fp:
                    if _fp_similar(fp, known_fp):
                        prev = known_item
                        break
            if prev is None and subj:
                # 同主体内的同一件事（换措辞 / 同一份提要里写了两遍）并进已有条目；
                # 只在**主体已确认相同**时才用宽松判据——跨主体一律不动。
                for _kfp, known_item in merged_fp:
                    if known_item.get("subject") == subj and _same_matter(it["text"], known_item.get("text", "")):
                        prev = known_item
                        break
            if prev is not None:
                prev["first_seen"] = day["date"]
                prev["seen_days"] = int(prev.get("seen_days") or 1) + 1
                prev["merged_count"] = int(prev.get("merged_count") or 0) + 1
                # 合并进已有条目时，仍要保留「这条此前办过」的标注——否则用户看不到新诉求
                # 挂在哪条已办事项上（R5 端到端用例抓到的回归）。
                if done_like and not prev.get("done_like"):
                    prev["done_like"] = True
                    prev["done_at"] = str(rec.get("at") or "")[:10]
                continue
            item = {
                "id": _short_id(nk), "text": it["text"], "category": category,
                "subject": subj,
                "section": it["section"], "date": day["date"],
                "state": "open" if done_like else state,
                "important": important,
                "first_seen": day["date"], "seen_days": 1,
                "done_like": done_like,
                "done_at": str(rec.get("at") or "")[:10] if done_like else "",
            }
            if it.get("due_date"):
                # 结构化提要：cron 已在写提要时核过「期限所指的那一天」，直接采用。
                # 插件不再用正则重算——重算正是之前把落款日当期限、把过期项藏掉的来源。
                item["due_date"] = it["due_date"]
                try:
                    item["days_left"] = (date.fromisoformat(it["due_date"]) - today).days
                except ValueError:
                    item["days_left"] = None
            elif category == "时限":
                # 只在【时限】分节算到期：正文里的叙述性日期（执行期、已开庭日）不是期限
                item["due_date"], item["days_left"] = _due_of(item["text"], today)
            if it.get("title"):
                item["title"], item["detail"] = it["title"], str(it.get("detail") or "")
            else:
                item["title"], item["detail"] = _split_item(item["text"])
            if fp:
                merged_fp.append((fp, item))
            pending.append(item)

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

    # 时限类置顶并按到期日升序（已过期的排最前）——这是列表里唯一有客观先后的一类，
    # 律师打开面板第一眼要看到的应该是「哪条期限要到了/已经过了」。
    _limit_rows = [i for i in pending if i.get("category") == "时限" and i.get("days_left") is not None]
    if _limit_rows:
        _limit_ids = {id(i) for i in _limit_rows}
        pending = sorted(_limit_rows, key=lambda x: x["days_left"]) + [i for i in pending if id(i) not in _limit_ids]

    # 事项词与二级折叠（第二次优化）：同主体 + 同事项词（如「客户单位·调查令」）只展开最新一条，
    # 其余标 dup_of——前端收成「同事项另 N 条」，点开即全部，不丢信息。
    for it in pending:
        it["topic"] = _topic_of(it.get("text", ""))
        it["dup_of"] = ""
    _first_by_key: dict = {}
    for it in sorted(pending, key=lambda x: str(x.get("date") or ""), reverse=True):
        subj, topic = str(it.get("subject") or ""), str(it.get("topic") or "")
        if not subj or not topic:
            continue
        key = (subj, topic, str(it.get("category") or ""))   # 同一案件的不同分节不互相折叠
        first = _first_by_key.get(key)
        if first is None:
            _first_by_key[key] = it
        else:
            it["dup_of"] = str(first.get("id") or "")

    # 主体分组索引（第二次优化）：同一案件/工作线 ≥2 条时给前端折叠用。
    # 不改条目本身——展开就回到全部，避免"合并即丢信息"。
    groups: list[dict] = []
    _seen_subj: list[str] = []
    for it in pending:
        s = str(it.get("subject") or "")
        if s and s not in _seen_subj:
            _seen_subj.append(s)
    for s in _seen_subj:
        members = [i for i in pending if str(i.get("subject") or "") == s]
        if len(members) < 2:
            continue
        groups.append({
            "subject": s,
            "count": len(members),
            "latest": max(str(i.get("date") or "") for i in members),
            "ids": [i.get("id") for i in members],
        })
    groups.sort(key=lambda g: -g["count"])

    def _state_list(state: str) -> list:
        out = [r for r in records if r.get("state") == state and r.get("text")]
        out.sort(key=lambda r: str(r.get("at", "")), reverse=True)
        return [{
            "id": _short_id(str(r.get("key") or "")), "text": r.get("text", ""),
            "category": r.get("category", "其他"), "date": r.get("date", ""),
            "state": state, "at": r.get("at", ""),
        } for r in out[:80]]

    # 「先看这些」（2026-10-19 R8）：40 条待办对律师没有优先级等于没有待办。
    # 只按**可解释的两条规则**挑最多 3 条：①你标了星的最新条目；②时限类里挂得最久的。
    # 不引入日期解析与主观紧迫度打分——面板给不出理由的优先级不该出现在这里。
    def _pick_focus() -> list:
        """挑出「今天最要紧的几件」，最多 5 条。

        旧版只挑「时限类挂最久 + 其余最紧的一条」，第 2、3 条是凑数的，等于没有重点。
        现在按时效排：已过期 → 今天到期 → 3 天内 → 你标星 → 等你拍板且已挂 ≥3 天。
        """
        out: list = []
        picked: set = set()
        seen_matter: set = set()      # 同一案件同一事项在重点区只出现一次

        def add(it, why):
            if len(out) >= 5 or it is None or it["id"] in picked:
                return
            key = (str(it.get("subject") or ""), str(it.get("topic") or ""))
            if key[0] and key[1]:
                if key in seen_matter:
                    return
                seen_matter.add(key)
            picked.add(it["id"])
            out.append({"id": it["id"], "text": str(it.get("text") or ""),
                        "title": str(it.get("title") or ""), "why": why,
                        "days_left": it.get("days_left")})

        expired = sorted([i for i in pending if isinstance(i.get("days_left"), int) and i["days_left"] < 0],
                         key=lambda x: x["days_left"])
        for it in expired:
            add(it, f"已过期 {-it['days_left']} 天")
        for it in [i for i in pending if i.get("days_left") == 0]:
            add(it, "今天到期")
        for it in sorted([i for i in pending if isinstance(i.get("days_left"), int) and 0 < i["days_left"] <= 3],
                         key=lambda x: x["days_left"]):
            add(it, f"剩 {it['days_left']} 天")
        starred = sorted([i for i in pending if i.get("important")],
                         key=lambda x: str(x.get("date") or ""), reverse=True)
        if starred:
            add(starred[0], "你标了星")
        stuck = sorted([i for i in pending
                        if i.get("category") == "待决策" and int(i.get("seen_days") or 1) >= 3],
                       key=lambda x: -int(x.get("seen_days") or 1))
        if stuck:
            add(stuck[0], f"已挂 {int(stuck[0].get('seen_days') or 1)} 天未决")

        return out

    return {
        "pending": pending,
        "focus": _pick_focus(),
        "done": _state_list("done"),
        "deleted": _state_list("deleted"),
        "days": [d["date"] for d in days[:MAX_DAYS]],
        # 数据新鲜度（2026-10-19 R6）：面板要能说出「数据停在哪天」，而不是让用户以为
        # 看到的就是今天的待办。措辞由前端按 stale_days 决定。
        "latest_date": days[0]["date"] if days else "",
        "stale_days": _stale_days(days[0]["date"], today) if days else None,
        "window_days": MAX_DAYS,
        "today": today.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # 操作记录读不出时如实告知（面板可据此提示），不把坏状态当成"没有记录"
        "state_error": state_err,
        # 主体分组（第二次优化）：同案多条折叠，前端按 ids 归组；未命中主体的条目各自平铺
        "groups": groups,
        # 被挡在列表外的残片/过程陈述条数（面板显示「另有 N 条过程记录」）
        "noise_count": noise,
    }


def _stale_days(latest_date: str, today) -> int | None:
    """最新一份提要距今天数；日期不可解析时返回 None（不臆造天数）。"""
    try:
        return (today - datetime.strptime(latest_date, "%Y-%m-%d").date()).days
    except (ValueError, TypeError):
        return None


def cached_payload(force: bool = False) -> dict:
    """TTL 缓存版 build_payload（R7）；force=True 时强制重建。"""
    now = time.time()
    if force or _PAYLOAD_CACHE["data"] is None or now - float(_PAYLOAD_CACHE["at"]) > _PAYLOAD_TTL:
        data = build_payload()
        _PAYLOAD_CACHE["data"] = data
        _PAYLOAD_CACHE["at"] = now
    return _PAYLOAD_CACHE["data"]


class ActionBody(BaseModel):
    text: str
    action: str
    category: str = ""
    date: str = ""
    id: str = ""          # 面板读到的稳定标识（sha1(归一化文本)[:10]），用于精确定位


def set_action(body) -> dict:
    text = str(body.text or "").strip()
    action = str(body.action or "").strip()
    if not text or action not in ("done", "later", "delete", "open", "important", "normal"):
        return {"ok": False, "error": "bad request"}
    nk = _normalize(text)
    rid = str(getattr(body, "id", "") or "").strip()
    records, state_err = _load_state()
    if state_err:
        # 状态读不出时不得当空集合继续写：否则会把既有操作记录整体覆盖掉
        return {"ok": False, "error": f"操作记录不可读（{state_err}），本次未写入"}
    rec, level = _find_record_full(nk, text, records, rid)

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
async def items(refresh: bool = False) -> dict:
    try:
        return cached_payload(force=bool(refresh))
    except Exception as exc:  # never 500 the pane
        return {"pending": [], "done": [], "deleted": [], "days": [], "error": str(exc)}


@router.post("/action")
async def action(body: ActionBody) -> dict:
    try:
        result = set_action(body)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if isinstance(result, dict) and result.get("ok"):
        _PAYLOAD_CACHE["data"] = None     # 写成功：让下一次读取重建（R7）
    return result


@router.get("/digests")
async def digests() -> dict:
    try:
        days = _load_days()
        return {"items": [{"date": d["date"], "markdown": d["body"]} for d in days[:MAX_DAYS]],
                "generated_at": datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        return {"items": [], "error": str(exc)}
