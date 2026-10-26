# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""期限台账的共享判定核心（唯一真源）。

被 `scripts/lawyer_ops.py`（命令行/每日提要）与
`plugins/lawyer-workbench/dashboard/plugin_api.py`（工作台面板）共同导入，
避免两处各写一份状态集合而悄悄漂移（第 5 轮外部复核判为「须共享纯函数」）。

两条**独立维度**并列，不再用一个覆盖另一个：
  status_class : done(已办结) / event(事件已发生≠办结) / open(待办) / unknown(未标状态)
  date_quality : date(确定为 YYYY-MM-DD) / tentative(约期·待核实) / invalid(不可解析)

分桶规则只依赖这两维 + 窗口值，五个桶互斥且完备（每次调用都会归入且只归入一个桶）。
"""
from __future__ import annotations

import datetime
import re

DEFAULT_SOON_DAYS = 30
# 两个**有意不同**的窗口设定：工作台面板看得宽（30 天），每日提要只提醒最紧的（15 天）。
# 这是两个不同的用途设定，不是漂移；两个值都可配置，且都经同一个解析函数。
DEFAULT_BRIEF_DAYS = 15
CONFIG_KEY_SOON = 'deadline_soon_days'
CONFIG_KEY_BRIEF = 'deadline_brief_days'


def resolve_window(cfg, key, default):
    """从配置快照解析窗口天数。**任何异常一律回落默认值**。

    复核 F01：裸 int() 在 `1e309`（json 解析为正无穷）上会抛 OverflowError、顶层为
    null/[] 时 cfg.get 抛 AttributeError，两者都不在原先的 except 里，配置一点小错
    就能让期限服务整体失败。这里逐类显式处理：
      - 非 dict（None/[]/字符串）→ 默认
      - bool（true 不是 1）→ 默认
      - 浮点：仅接受整值（45.0→45），45.9 / inf / nan → 默认
      - 字符串：允许 "45"；其余 → 默认
      - 整数：须在 1–365 内，越界 → 默认
    """
    try:
        if not isinstance(cfg, dict):
            return default
        v = cfg.get(key, default)
        if isinstance(v, bool):
            return default
        if isinstance(v, float):
            if not v.is_integer():
                return default
            v = int(v)
        elif isinstance(v, str):
            v = int(v.strip())
        elif not isinstance(v, int):
            return default
        return v if 1 <= v <= 365 else default
    except (OverflowError, ValueError, TypeError, AttributeError):
        return default

TERMINAL_STATUS = {'已完成', '已办结', '已处理', '已取消', '取消', '已撤销', '办结', '完成'}
MILESTONE_STATUS = {'已开庭', '已提交', '已缴费', '已续冻', '已解除'}

# 备注里出现这些词 = 明确表示不需要回证凭据，不提示补记（用户约定的豁免标记）
RECEIPT_EXEMPT = ('无须回证', '无需回证', '免回证', '不需回证', '无回证')

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_DATE_FRAG_RE = re.compile(r'\d{4}-\d{2}-\d{2}|\d{1,2}-\d{1,2}')   # 区间/复合表述里的日期片段
_MD_STRIP = '*`_ \t'
_TENTATIVE_HINTS = ('约', '待核实', '待核', '待定', '暂定', '月底', '上旬', '中旬', '下旬',
                    '季度', '待送达', '待判决', '待生效', '生效后', '为准', '未定', '待')


def clean_due(value) -> str:
    """剥掉 markdown 包裹与首尾空白。

    台账里日期常被写成 `**2026-10-28**`（实测第 15/16/23 行三条客户单位期限即如此）：
    不剥的话既解析不出日期（被当成"既非日期也非约期表述"而从清单里消失），
    显示出来还会带一串星号。
    """
    return str(value or '').strip().strip(_MD_STRIP).strip()


def status_class(status) -> str:
    s = str(status or '').strip()
    if s in TERMINAL_STATUS:
        return 'done'
    if s in MILESTONE_STATUS:
        return 'event'
    if not s:
        return 'unknown'
    return 'open'


def date_quality(due) -> str:
    d = clean_due(due)
    if not d:
        return 'tentative'
    if _DATE_RE.match(d):
        try:
            datetime.datetime.strptime(d, '%Y-%m-%d')
            return 'date'
        except ValueError:
            return 'invalid'
    if any(h in d for h in _TENTATIVE_HINTS):
        return 'tentative'
    # 区间/复合日期（如「2026-10-19 起至 11-18」）：不是解析错误，只是给不出单点倒计时，
    # 归 tentative 让人工判断——此前只有"含约/待"才放行，这类被当成 bad 数据报出来。
    if _DATE_FRAG_RE.search(d):
        return 'tentative'
    return 'invalid'


def parse_date(due):
    d = clean_due(due)
    if not _DATE_RE.match(d):
        return None
    try:
        return datetime.datetime.strptime(d, '%Y-%m-%d').date()
    except ValueError:
        return None


def needs_receipt(note) -> bool:
    """已办结条目是否缺登记凭据：**仅当备注为空时**算缺。

    备注有任意内容即视为已登记凭据；确实不需要凭据的条目，按约定写法在备注注明
    「无须回证」这类词（见 RECEIPT_EXEMPT）——提示语里就是这么引导用户的。
    """
    return not str(note or '').strip()


def bucket(item, today, soon_days: int = DEFAULT_SOON_DAYS):
    """返回 (桶, 理由)。桶 ∈ decide / soon / unverified / far / excluded，互斥且完备。

    复核 F06：非 dict 元素不得抛异常绕过分桶——归入 unverified 并说明，由调用方计入
    结构问题计数，这样"完备"对任意输入都成立，而不是只在"已验证 dict 输入"下成立。
    """
    if not isinstance(item, dict):
        return 'unverified', f'条目结构异常（{type(item).__name__}），已保留待人工核对'
    st = status_class(item.get('status', ''))
    dq = date_quality(item.get('due', ''))
    if st == 'done':
        if needs_receipt(item.get('note', '')):
            return 'decide', '已办结但缺登记凭据（凭据在附件或工作记录里的，可在备注注明「无须回证」）'
        return 'excluded', '已办结且有登记凭据，不再催办'
    if st == 'event':
        return 'decide', '事件已发生，不等于事项办结；需确认是否仍需后续动作'
    if st == 'unknown':
        return 'unverified', '台账未标状态，无法判断是否仍需办理'
    if dq == 'tentative':
        return 'unverified', '登记为约期/待核实，需待送达或裁判结果核后方可判断'
    if dq == 'invalid':
        return 'unverified', '日期不可解析（该行已保留，需人工核对）'
    d = parse_date(item.get('due', ''))
    days = (d - today).days
    if days <= soon_days:
        return 'soon', f'距登记日期 {days} 天' + ('（已过期）' if days < 0 else '')
    return 'far', f'距登记日期 {days} 天（超出 {soon_days} 天窗口，不催办）'
