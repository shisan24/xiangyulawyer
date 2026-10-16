# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Provider limits / balance plugin API — runs inside the Hermes gateway.

作用：把"模型供应商还剩多少额度"集中显示——
  · 订阅制（含 5 小时 / 每周 / 每月 窗口）：CommandCode、ChatGPT(Codex)、OpenCode Go、GLM 编程套餐
  · 余额制（账户剩余金额）：DeepSeek、Kimi/Moonshot、OpenRouter、Nous Portal
  · 本机真实消耗（state.db 的 session_model_usage，按今日 / 7 日 / 30 日）
  · 凭据池健康（auth.json 中的失败原因、耗尽状态）

只读：仅发起用量/余额查询（GET），不写配置、不改凭据、不发起推理请求。
凭据通过 hermes_cli.runtime_provider 解析（config / .env / credential pool 同源），
不落盘、不回传、不打印。

Mounted at /api/plugins/provider-limits/ by the gateway plugin loader.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter

router = APIRouter()

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / "AppData" / "Local" / "hermes"))
STATE_DB = HERMES_HOME / "state.db"
AUTH_JSON = HERMES_HOME / "auth.json"

HTTP_TIMEOUT = 12.0
CACHE_TTL = 300.0        # 成功结果 5 分钟
CACHE_TTL_ERROR = 60.0   # 失败结果 1 分钟

# CommandCode 各套餐每月额度（美元；取自官方 CLI 的 planId→credits 映射）
COMMANDCODE_PLAN_CREDITS = {
    "individual-go": 10.0,
    "individual-goat": 70.0,
    "individual-pro": 30.0,
    "individual-pro-v1": 80.0,
    "individual-provider": 15.0,
    "individual-max": 150.0,
    "individual-ultra": 300.0,
    "teams-pro": 40.0,
}
COMMANDCODE_PLAN_NAMES = {
    "individual-go": "Go",
    "individual-goat": "GOAT",
    "individual-pro": "Pro",
    "individual-pro-v1": "Pro",
    "individual-provider": "Provider",
    "individual-max": "Max",
    "individual-ultra": "Ultra",
    "teams-pro": "Teams Pro",
}

# ────────────────────────── 配置（可覆盖：state/config.json） ──────────────────────────
PLUGIN_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = PLUGIN_DIR / "state"
CONFIG_FILE = STATE_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "window_pct": 90.0,                        # 订阅窗口用量达到该百分比即告警
    "low_balance": {"USD": 1.0, "CNY": 5.0},   # 余额不高于该值即告警（按币种）
    "days_left": 3.0,                          # 按当前速度预计可用天数低于该值即告警
    "fx_to_usd": {"CNY": 0.1408, "USD": 1.0},  # 余额折美元（仅用于「预计可用天数」）
    "cooldown_hours": 12.0,                    # 同一条告警的重复提醒间隔（看门狗脚本用）
    "health_alert_max_age_hours": 48.0,        # 凭据失败超过该时长不再告警
    "mute": [],                                # 静默：告警 id（deepseek:balance）或供应商 id（deepseek）
}

_CONFIG_CACHE: dict[str, Any] = {"mtime": None, "value": None}


def _config() -> dict[str, Any]:
    """读取 state/config.json（缺省 = DEFAULT_CONFIG；按 mtime 缓存，坏文件回落默认值）。"""
    try:
        mtime = CONFIG_FILE.stat().st_mtime
    except OSError:
        mtime = None
    if _CONFIG_CACHE["value"] is not None and _CONFIG_CACHE["mtime"] == mtime:
        return _CONFIG_CACHE["value"]
    merged = {key: (dict(val) if isinstance(val, dict) else list(val) if isinstance(val, list) else val)
              for key, val in DEFAULT_CONFIG.items()}
    if mtime is not None:
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) or {}
            for key, value in raw.items():
                if key not in merged or value is None:
                    continue
                if isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key].update(value)
                elif isinstance(merged[key], list) and isinstance(value, list):
                    merged[key] = list(value)
                elif isinstance(merged[key], (int, float)) and isinstance(value, (int, float)) \
                        and not isinstance(value, bool):
                    merged[key] = float(value)
        except Exception:
            pass
    _CONFIG_CACHE.update({"mtime": mtime, "value": merged})
    return merged


def _is_muted(config: dict, alert_id: str, provider_id: str) -> bool:
    for item in config.get("mute") or []:
        token = str(item).strip()
        if token and (token == alert_id or token == provider_id or alert_id.startswith(token + ":")):
            return True
    return False


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


# 无公开额度接口的供应商：只提示去控制台看
CONSOLE_ONLY = (
    ("alibaba-coding-plan-cn", "阿里云百炼（编程套餐）", "https://bailian.console.aliyun.com/"),
    ("custom:ark.cn-beijing.volces.com", "火山方舟 Ark", "https://console.volcengine.com/ark/"),
)

_CACHE: dict[str, Any] = {"at": 0.0, "data": None, "ok": False}
_RESOLVE_CACHE: dict[str, tuple[float, Optional[dict]]] = {}
_PROXY_CACHE: dict[str, Any] = {"checked": False, "value": None}


# ────────────────────────── 小工具 ──────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso_from_ms(value: Any) -> Optional[str]:
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    if ms < 1e12:  # 秒级
        ms *= 1000.0
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat(timespec="seconds")


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            value = float(str(value))
        except (TypeError, ValueError):
            return None
    f = float(value)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _bar(label: str, used: Any, cap: Any, *, reset_at: Any = None, exceeded: Any = None,
         unit: str = "$", note: Optional[str] = None) -> Optional[dict]:
    u, c = _num(used), _num(cap)
    if u is None or c is None or c <= 0:
        return None
    pct = max(0.0, min(100.0, u / c * 100.0))
    return {
        "label": label, "used": round(u, 2), "cap": round(c, 2), "pct": round(pct, 1),
        "remaining": round(max(0.0, c - u), 2), "unit": unit,
        "reset_at": _iso_from_ms(reset_at) if isinstance(reset_at, (int, float)) else (reset_at or None),
        "exceeded": bool(exceeded) if exceeded is not None else None,
        "note": note,
    }


def _get_json(client: httpx.Client, url: str, headers: dict, *, params: dict | None = None) -> Any:
    resp = client.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def _resolve(provider: str) -> tuple[Optional[str], Optional[str]]:
    """→ (api_key, base_url)。带 5 分钟缓存；失败返回 (None, None)。

    运行时解析不出密钥时，退回 PROVIDER_ENV_FALLBACK 里登记的变量名直读
    .env / 进程环境（不经 secret scope）——被池标记失败的条目会被
    resolve_runtime_provider 跳过，否则面板只报「未解析到 API Key」。
    """
    hit = _RESOLVE_CACHE.get(provider)
    if hit and time.time() - hit[0] < CACHE_TTL:
        resolved = hit[1]
    else:
        resolved = None
        try:
            from hermes_cli.runtime_provider import resolve_runtime_provider
            data = resolve_runtime_provider(requested=provider) or {}
            resolved = {
                "api_key": str(data.get("api_key") or "").strip(),
                "base_url": str(data.get("base_url") or "").strip(),
            }
        except Exception:
            resolved = None
        _RESOLVE_CACHE[provider] = (time.time(), resolved)
    key = str((resolved or {}).get("api_key") or "").strip()
    if not key:
        key = _env_fallback_for(provider)
    if not key:
        return None, None
    return key, (resolved or {}).get("base_url") or None


def _proxy_url() -> Optional[str]:
    """境外接口（chatgpt.com / api.anthropic.com）用的代理：环境变量 → Windows 注册表。
    国内供应商直连，不走代理。"""
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = (os.environ.get(var) or "").strip()
        if value:
            return value
    cached = _PROXY_CACHE.get("value")
    if cached is not None or _PROXY_CACHE.get("checked"):
        return cached or None
    _PROXY_CACHE["checked"] = True
    try:  # Windows：Internet 选项里的系统代理（Clash 等随机端口）
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "").strip()
        if enabled and server:
            if "=" in server:  # "http=host:port;https=host:port"
                parts = dict(part.split("=", 1) for part in server.split(";") if "=" in part)
                server = parts.get("https") or parts.get("http") or server
            if not server.lower().startswith("http"):
                server = "http://" + server
            _PROXY_CACHE["value"] = server
            return server
    except Exception:
        pass
    return None


def _bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Accept": "application/json",
            "User-Agent": "HermesAgent/1.0 (provider-limits plugin)"}


def _entry(pid: str, name: str, kind: str, **kw: Any) -> dict:
    out = {"id": pid, "name": name, "kind": kind, "status": "ok", "windows": [],
           "balance": None, "details": [], "links": [], "error": None, "plan": None}
    out.update(kw)
    return out


# ────────────────────────── 订阅制：CommandCode（多账户） ──────────────────────────

def _mask_email(value: str) -> str:
    text = (value or "").strip()
    if "@" not in text:
        return text
    local, domain = text.split("@", 1)
    head = local[:4] if len(local) > 4 else local[:1]
    return f"{head}…@{domain}"


def _env_fallback_key(env_var: str) -> str:
    """不经 secret scope 的密钥兜底：直读 <HERMES_HOME>/.env，再退到进程环境。

    0.21.4 起多路复用（multiplex）强制开启：进程内没有 profile secret scope 时，
    get_env_prefer_dotenv → agent.secret_scope.get_secret 会抛 UnscopedSecretError
    （"Hermes could not read this profile's KEY"）。本插件后端由桌面 App / serve 挂载，
    请求上下文里没有 scope，于是凭证池每个账户都解析不到密钥。只读文件与进程环境，
    与 Hermes 同一来源；仅用于查询，不落盘、不入日志、不回传前端。
    """
    value = ""
    try:
        from hermes_cli.config import load_env
        value = str((load_env() or {}).get(env_var) or "").strip()
    except Exception:
        value = ""
    if not value:
        value = str(os.environ.get(env_var) or "").strip()
    return "" if value.startswith("op://") else value  # 未解析的 1Password 引用不是密钥


# 运行时解析不出密钥时兜底直读的变量名（供应商 id → 候选变量，按序取第一个非空）。
# 适用场景：池内条目被标记 auth/耗尽后 resolve_runtime_provider 直接跳过，
# 面板就成了「未解析到 API Key」；这里只补读，不改池状态。
PROVIDER_ENV_FALLBACK = {
    "commandcode": ("COMMANDCODE_API_KEY", "COMMANDCODE_API_KEY_2"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "kimi-coding-cn": ("KIMI_CN_API_KEY", "MOONSHOT_API_KEY"),
    "zai": ("GLM_API_KEY", "ZHIPUAI_API_KEY", "ZAI_API_KEY"),
    "nous": ("NOUS_API_KEY",),
    "openai-codex": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "opencode-go": ("OPENCODE_GO_API_KEY", "OPENCODE_GO_API_KEY_2"),
}


def _env_fallback_for(provider: str) -> str:
    for var in PROVIDER_ENV_FALLBACK.get(provider, ()):
        value = _env_fallback_key(var)
        if value:
            return value
    return ""


def _pool_accounts(provider: str) -> list[dict]:
    """凭证池里该 provider 的各账户（只读）。

    label/source/priority/base_url 取自 auth.json；密钥本体由 Hermes 的
    get_env_prefer_dotenv 从 .env / os.environ 解析（与运行时同一来源），
    仅用于查询，不落盘、不入日志、不回传前端。
    密钥取不到时**仍保留该账户条目**（标错误），避免面板把「主/备」静默塌成一个账户。
    """
    entries: list = []
    try:
        store = json.loads(AUTH_JSON.read_text(encoding="utf-8"))
        raw = (store.get("credential_pool") or {}).get(provider) or []
        if isinstance(raw, list):
            entries = raw
    except Exception:
        entries = []
    try:
        from agent.credential_pool import get_env_prefer_dotenv
    except Exception:
        get_env_prefer_dotenv = None
    accounts: list[dict] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "")
        env_var = source.split(":", 1)[1].strip() if source.startswith("env:") else ""
        key = ""
        key_error = ""
        if env_var:
            if get_env_prefer_dotenv is not None:
                try:
                    key = (get_env_prefer_dotenv(env_var) or "").strip()
                except Exception:
                    key = ""
            if not key:
                key = _env_fallback_key(env_var)
            if not key:
                key_error = f"未解析到 API Key（{env_var}）"
        if not env_var and not key:
            continue
        accounts.append({"label": str(item.get("label") or env_var or "账户"), "env_var": env_var,
                         "priority": item.get("priority"), "base_url": str(item.get("base_url") or ""),
                         "last_status": str(item.get("last_status") or ""),
                         "last_status_at": item.get("last_status_at"),
                         "last_error_code": item.get("last_error_code"),
                         "last_error_reset_at": item.get("last_error_reset_at"),
                         "key_error": key_error,
                         "key": key})
    accounts.sort(key=lambda acc: (acc.get("priority") is None, acc.get("priority"), acc.get("label") or ""))
    return accounts


def _commandcode_pool_accounts() -> list[dict]:
    """CommandCode 各账户（保留旧调用名）。"""
    return _pool_accounts("commandcode")


def _pool_active_key(provider: str) -> str:
    """凭据池实际会选中的那条凭证的密钥——「运行时正在使用」的判据。

    不能用 ``_resolve()``：桌面后端是 multiplex 进程，那里
    ``resolve_runtime_provider`` 不走凭据池，直接落到 .env 的主变量，
    会把额度已耗尽的账户标成「正在使用」（2026-10-15 实测：普通进程 →
    池选 ``..._KEY_2``；multiplex → 直读 ``..._KEY``）。

    multiplex 进程里 ``load_pool()`` 自己也会抛 UnscopedSecretError
    （读 ``<PROVIDER>_BASE_URL`` 时没有 profile secret scope），所以池读不到时
    按池行自算：auth.json 里按 priority 排序，跳过仍在冷却的条目。
    """
    try:
        from agent.credential_pool import load_pool
        pool = load_pool(provider)
        entry = pool.current()
        if entry is None:
            entry = pool.select()
        key = str(getattr(entry, "runtime_api_key", "") or "") if entry is not None else ""
        if key:
            return key
    except Exception:
        pass
    for account in _pool_accounts(provider):
        if _account_in_cooldown(account):
            continue
        if account.get("key"):
            return str(account["key"])
    return ""


def _account_in_cooldown(account: dict) -> bool:
    """池内冷却判定（与 credential_pool._exhausted_until 同一口径）。

    供应商给了窗口重置时刻（``last_error_reset_at``）就认它——Go 的月度额度
    要到重置日才恢复，按 429 的 1 小时 TTL 判会把「额度用尽」当成「稍后就好」。
    """
    if str(account.get("last_status") or "") != "exhausted":
        return False
    reset_at = _num(account.get("last_error_reset_at"))
    if reset_at and reset_at > time.time():
        return True
    stamp = _num(account.get("last_status_at"))
    if stamp is None or stamp <= 0:
        return True
    code = int(_num(account.get("last_error_code")) or 0)
    return (stamp + POOL_EXHAUSTED_TTL.get(code, POOL_EXHAUSTED_TTL_DEFAULT)) > time.time()


# 凭证池给「耗尽」条目的冷却时长（与 agent/credential_pool.py 的 _exhausted_ttl 同步）
POOL_EXHAUSTED_TTL = {401: 5 * 60, 429: 60 * 60}
POOL_EXHAUSTED_TTL_DEFAULT = 60 * 60


def _pool_bench_note(account: dict) -> Optional[str]:
    """凭证池对该账户的冷却说明——池内状态，不是供应商账单口径。

    池子把失败归到哪个账户，和该账户在供应商侧的真实用量可能不一致
    （例如辅助调用重试时未带失败密钥指纹，池子按 current() 记账），
    两边并列显示才能发现这种误判。
    """
    if str(account.get("last_status") or "") != "exhausted":
        return None
    stamp = _num(account.get("last_status_at"))
    if stamp is None or stamp <= 0:
        return "池内标记：耗尽"
    code = int(_num(account.get("last_error_code")) or 0)
    remaining = stamp + POOL_EXHAUSTED_TTL.get(code, POOL_EXHAUSTED_TTL_DEFAULT) - time.time()
    if remaining <= 0:
        return None
    minutes = max(1, int(remaining // 60))
    span = f"{minutes} 分钟" if minutes < 90 else f"{minutes / 60:.1f} 小时"
    return f"池内冷却：{span}后解禁（池标记，非账单口径）"


def _fetch_commandcode_accounts() -> list[dict]:
    """CommandCode 全部账户各出一条记录（单账户时与旧行为一致）。"""
    accounts = _commandcode_pool_accounts()
    if not accounts:
        key, base = _resolve("commandcode")
        if not key:
            entry = _entry("commandcode", "CommandCode", "subscription")
            entry.update(status="unavailable", error="未解析到 API Key")
            return [entry]
        accounts = [{"label": "默认", "env_var": "", "priority": 0, "base_url": base or "", "key": key}]
    active_key = _pool_active_key("commandcode")
    total = len(accounts)
    return [_fetch_commandcode_one(acc, index=idx, total=total, active=(acc["key"] == active_key))
            for idx, acc in enumerate(accounts)]


def _fetch_commandcode_one(account: dict, *, index: int = 0, total: int = 1, active: bool = False) -> dict:
    """单个 CommandCode 账户：月额度 + 5 小时/每周窗口 + 本周期用量。"""
    key = str(account.get("key") or "")
    tag = "" if total <= 1 else ("主" if index == 0 else "备" if index == 1 else f"#{index + 1}")
    entry = _entry("commandcode" if index == 0 else f"commandcode-{index + 1}",
                   "CommandCode" + (f"（{tag}）" if tag else ""), "subscription")
    entry["meta"] = {"account_index": index, "account_total": total, "active": active,
                     "env_var": str(account.get("env_var") or "")}
    if not key:
        entry.update(status="unavailable", error=str(account.get("key_error") or "未解析到 API Key"))
        return entry
    base = str(account.get("base_url") or "")
    root = "https://api.commandcode.ai"
    if base and "//" in base:
        root = base.split("//", 1)[0] + "//" + base.split("//", 1)[1].split("/", 1)[0]
    headers = _bearer(key)
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            who = _get_json(client, f"{root}/alpha/whoami", headers, params={"limits": 1}) or {}
            org_id = ((who.get("org") or {}).get("id")) if isinstance(who.get("org"), dict) else None
            params = {"orgId": org_id} if org_id else None
            sub = (_get_json(client, f"{root}/alpha/billing/subscriptions", headers, params=params) or {}).get("data") or {}
            cred = _get_json(client, f"{root}/alpha/billing/credits", headers, params=params) or {}
            credits = cred.get("credits") or {}
            windows_raw = cred.get("windowLimits") or {}
            period_start = sub.get("currentPeriodStart")
            summary: dict = {}
            try:
                s_params = {"orgId": org_id} if org_id else {}
                if period_start:
                    s_params["since"] = period_start
                summary = _get_json(client, f"{root}/alpha/usage/summary", headers, params=s_params or None) or {}
            except Exception:
                summary = {}

        user = who.get("user") if isinstance(who.get("user"), dict) else {}
        account_email = _mask_email(str(user.get("email") or ""))
        plan_id = str(sub.get("planId") or credits.get("planId") or "").strip()
        plan_name = COMMANDCODE_PLAN_NAMES.get(plan_id, plan_id or None)
        monthly_remaining = sum(v for v in (_num(credits.get("monthlyCredits")),
                                            _num(credits.get("purchasedCredits")),
                                            _num(credits.get("freeCredits"))) if v is not None)
        plan_total = COMMANDCODE_PLAN_CREDITS.get(plan_id)
        spent = _num(summary.get("totalCost"))
        pool = None
        if plan_total:
            pool = max(plan_total, monthly_remaining)
        elif spent is not None:
            pool = monthly_remaining + spent
        month_bar = None
        if pool and pool > 0:
            month_bar = _bar("本月额度", max(0.0, pool - monthly_remaining), pool, reset_at=sub.get("currentPeriodEnd"),
                             unit="$", note="含赠送/加购 credits" if (credits.get("purchasedCredits") or credits.get("freeCredits")) else None)

        five = windows_raw.get("fiveHour") or {}
        week = windows_raw.get("weekly") or {}
        bars = [b for b in (
            month_bar,
            _bar("5 小时", five.get("used"), five.get("cap"), reset_at=five.get("resetAt"), exceeded=five.get("exceeded")),
            _bar("每周", week.get("used"), week.get("cap"), reset_at=week.get("resetAt"), exceeded=week.get("exceeded")),
        ) if b]

        details = []
        if account_email:
            details.append(f"账户 {account_email}")
        if total > 1 and active:
            details.append("运行时正在使用")
        pool_note = _pool_bench_note(account)
        if pool_note:
            details.append(pool_note)
        if spent is not None:
            details.append(f"本期已用 ${spent:,.2f}")
        if _num(summary.get("totalCount")):
            details.append(f"请求 {int(summary['totalCount']):,} 次")
        tok = _num(summary.get("totalTokens"))
        if tok:
            details.append(f"tokens {(tok / 1e6):,.1f}M")
        if sub.get("currentPeriodEnd"):
            details.append(f"周期至 {str(sub['currentPeriodEnd'])[:10]}")
        if credits.get("belowThreshold"):
            details.append("⚠ 余量已低于计费阈值")

        # 本计费周期日均消耗 → 预计可用天数（用供应商自己的账单口径，比本机估算准）
        rate = None
        period_start = sub.get("currentPeriodStart")
        if spent is not None and period_start:
            try:
                started = datetime.fromisoformat(str(period_start).replace("Z", "+00:00"))
                elapsed_days = max(0.5, (datetime.now(timezone.utc) - started).total_seconds() / 86400)
                daily = spent / elapsed_days
                if daily > 0.01:
                    rate = {"daily_usd": round(daily, 2), "basis": "本计费周期",
                            "days_left": round(max(0.0, monthly_remaining) / daily, 1)}
            except Exception:
                rate = None

        entry.update(plan=plan_name, windows=bars, details=details, status="ok", rate=rate,
                     balance={"amount": round(monthly_remaining, 2), "currency": "USD", "label": "剩余额度"},
                     links=[{"label": "Studio 用量页", "url": "https://commandcode.ai/usage"}])
        entry["meta"] = dict(entry.get("meta") or {}, plan_id=plan_id, period_end=sub.get("currentPeriodEnd"),
                             env_var=account.get("env_var") or "", plan_name=plan_name)
        return entry
    except Exception as exc:
        entry.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:160]}")
        return entry


# ────────────────────────── 订阅制：Hermes 内置（Codex / Anthropic） ──────────────────────────

def _from_snapshot(pid: str, name: str, provider_key: str) -> dict:
    """借用 Hermes 自己的 account_usage 抓取（Codex / Claude 的 5h+周窗口）。"""
    entry = _entry(pid, name, "subscription")
    try:
        from agent import account_usage as au  # 同进程内可用
    except Exception as exc:
        entry.update(status="unavailable", error=f"无法加载 Hermes account_usage：{exc}")
        return entry
    snapshot = None
    err = None
    fetcher = getattr(au, "_USAGE_FETCHERS", {}).get(provider_key)
    if fetcher is not None:
        try:
            snapshot = fetcher(None, None)
        except Exception as exc:
            err = f"{type(exc).__name__}: {str(exc)[:140]}"
    if snapshot is None and err is None:
        try:
            snapshot = au.fetch_account_usage(provider_key)
        except Exception as exc:
            err = f"{type(exc).__name__}: {str(exc)[:140]}"
    if snapshot is None:
        entry.update(status="unavailable" if err else "no_api",
                     error=err or "无可用凭据或接口不可达（如 chatgpt.com 需代理）")
        return entry
    windows = []
    for w in snapshot.windows:
        cap = 100.0
        used = w.used_percent if w.used_percent is not None else 0.0
        bars = _bar(w.label, used, cap, unit="%")
        if bars:
            bars["reset_at"] = w.reset_at.isoformat(timespec="seconds") if w.reset_at else None
            if w.detail:
                bars["note"] = w.detail
            windows.append(bars)
    entry.update(status="ok" if not snapshot.unavailable_reason else "unavailable",
                 plan=snapshot.plan, windows=windows, details=list(snapshot.details),
                 error=snapshot.unavailable_reason)
    return entry


def _fetch_codex() -> dict:
    """ChatGPT（Codex）订阅窗口：5 小时 + 每周。境外接口，走系统代理。"""
    entry = _entry("openai-codex", "ChatGPT（Codex）", "subscription")
    try:
        from agent.account_usage import _codex_backend_urls, _codex_headers, _resolve_codex_usage_credentials
    except Exception as exc:
        entry.update(status="unavailable", error=f"无法加载 Hermes 凭据模块：{str(exc)[:100]}")
        return entry
    proxy = _proxy_url()

    def _usage(token: str, base: str, acct: Optional[str]) -> dict:
        url = _codex_backend_urls(base)[0]
        with httpx.Client(timeout=HTTP_TIMEOUT, proxy=proxy) as client:
            resp = client.get(url, headers=_codex_headers(token, acct))
            resp.raise_for_status()
            return resp.json() or {}

    try:
        token, base, acct = _resolve_codex_usage_credentials(None, None)
    except Exception as exc:
        entry.update(status="unavailable", error=f"未登录或凭据不可用：{str(exc)[:110]}")
        return entry
    try:
        try:
            payload = _usage(token, base, acct)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401:
                raise
            token, base, acct = _resolve_codex_usage_credentials(None, None, force_refresh=True)
            payload = _usage(token, base, acct)
    except Exception as exc:
        fallback = _from_snapshot("openai-codex", "ChatGPT（Codex）", "openai-codex")
        if fallback.get("status") == "ok":
            return fallback
        entry.update(status="unavailable",
                     error=f"{type(exc).__name__}: {str(exc)[:110]}" + ("（已走代理）" if proxy else "（未发现代理）"))
        return entry
    rate = payload.get("rate_limit") or {}
    windows = []
    for key, label in (("primary_window", "5 小时"), ("secondary_window", "每周")):
        win = rate.get(key) or {}
        pct = _num(win.get("used_percent"))
        if pct is None:
            continue
        bar = _bar(label, pct, 100.0, unit="%", reset_at=win.get("reset_at"))
        if bar:
            windows.append(bar)
    details = []
    plan = str(payload.get("plan_type") or "").strip()
    if plan:
        details.append(f"{plan.upper()} 订阅")
    credits = payload.get("credits") or {}
    if credits.get("has_credits"):
        balance = _num(credits.get("balance"))
        details.append("附加额度不限量" if credits.get("unlimited") else
                       (f"附加额度 ${balance:,.2f}" if balance is not None else "有附加额度"))
    banked = _num((payload.get("rate_limit_reset_credits") or {}).get("available_count")) or 0
    if banked:
        details.append(f"重置券 {int(banked)} 张")
    if rate.get("limit_reached"):
        details.append("⚠ 已达上限")
    entry.update(status="ok" if windows else "no_api", plan=plan or None, windows=windows, details=details,
                 error=None if windows else "接口未返回窗口数据",
                 links=[{"label": "用量页", "url": "https://chatgpt.com/codex/settings/usage"}],
                 meta={"proxied": bool(proxy), "source": "usage_api"})
    return entry


def _fetch_anthropic_direct() -> dict:
    """Claude 订阅窗口（OAuth 账户才有）：5 小时 / 每周 / 分模型周窗口。

    当前未启用：本机没有 Claude 凭据，用户要求不显示。需要时在 _collect 的
    subscription 列表里加回 results["anthropic"]，并把 "anthropic": _fetch_anthropic_direct
    放回 tasks。
    """
    entry = _entry("anthropic", "Claude（订阅）", "subscription")
    try:
        from agent.anthropic_credentials import _is_oauth_token, resolve_anthropic_token

        token = (resolve_anthropic_token() or "").strip()
    except Exception as exc:
        entry.update(status="unavailable", error=f"无法加载 Claude 凭据：{str(exc)[:100]}")
        return entry
    if not token:
        entry.update(status="unavailable", error="无 Claude 凭据")
        return entry
    if not _is_oauth_token(token):
        entry.update(status="no_api", error="该 Claude 密钥非订阅（OAuth）账户，无窗口额度")
        return entry
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json",
               "anthropic-beta": "oauth-2025-04-20", "User-Agent": "claude-code/2.1.0"}
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, proxy=_proxy_url()) as client:
            payload = client.get("https://api.anthropic.com/api/oauth/usage", headers=headers).json() or {}
    except Exception as exc:
        entry.update(status="unavailable", error=f"{type(exc).__name__}: {str(exc)[:110]}")
        return entry
    windows = []
    for key, label in (("five_hour", "5 小时"), ("seven_day", "每周"),
                       ("seven_day_opus", "Opus 周"), ("seven_day_sonnet", "Sonnet 周")):
        win = payload.get(key) or {}
        pct = _num(win.get("utilization"))
        if pct is None:
            continue
        if pct <= 1:
            pct *= 100
        bar = _bar(label, pct, 100.0, unit="%", reset_at=win.get("resets_at"))
        if bar:
            windows.append(bar)
    details = []
    extra = payload.get("extra_usage") or {}
    if extra.get("is_enabled") and _num(extra.get("used_credits")) is not None and _num(extra.get("monthly_limit")) is not None:
        details.append(f"额外用量 {extra['used_credits']:.2f}/{extra['monthly_limit']:.2f} {extra.get('currency') or 'USD'}")
    entry.update(status="ok" if windows else "no_api", windows=windows, details=details,
                 error=None if windows else "接口未返回窗口数据")
    return entry


# ────────────────────────── 订阅制：GLM 编程套餐（智谱 / z.ai） ──────────────────────────

def _fetch_glm_balance() -> dict:
    """GLM（智谱 open.bigmodel.cn）：按量计费密钥的余额条目。

    智谱开放平台没有公开的余额查询接口 —— 2026-09-23 用本机密钥实测
    /api/paas/v4/account/balance、/api/biz/finance/account/getAccount、
    /api/biz/finance/account/getCustomerAccount、/api/biz/finance/account/queryAccount、
    /api/biz/finance/balance、/api/biz/account/balance、/api/biz/account/getAccount、
    /api/biz/resourcepack/usages 全部 404「接口不存在」。所以只给控制台入口，不编造数字；
    日后拿到 paas 余额接口，在这里补 URL 与解析即可。
    （编码套餐 Coding Plan 密钥走 _fetch_glm_quota，本机不是套餐，故不启用。）
    """
    entry = _entry("zai", "GLM（智谱）", "balance")
    key, base = _resolve("zai")
    if not key:
        entry.update(status="unavailable", error="未解析到 API Key")
        return entry
    host = (base or "").split("//", 1)[-1].split("/", 1)[0].lower()
    url = "https://open.bigmodel.cn/usercenter/resourcepack" if "bigmodel" in host else "https://z.ai/manage-apikey/account"
    entry.update(status="no_api", error="余额制密钥：智谱未提供公开余额查询接口，请在控制台查看",
                 links=[{"label": "控制台", "url": url}])
    return entry


def _fetch_glm_quota() -> dict:
    """编码套餐（Coding Plan）的额度窗口 —— 当前未启用：本机 GLM 密钥是按量计费余额制。"""
    entry = _entry("zai", "GLM（智谱 / z.ai）", "subscription")
    key, base = _resolve("zai")
    if not key:
        entry.update(status="unavailable", error="未解析到 API Key")
        return entry
    host = (base or "").split("//", 1)[-1].split("/", 1)[0].lower()
    url = "https://open.bigmodel.cn/api/monitor/usage/quota/limit" if "bigmodel" in host else "https://api.z.ai/api/monitor/usage/quota/limit"
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            data = _get_json(client, url, _bearer(key))
    except Exception as exc:
        entry.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:140]}")
        return entry
    if not isinstance(data, dict) or data.get("success") is False or (isinstance(data.get("code"), int) and data.get("code") not in (0, 200)):
        msg = str(data.get("msg") or data.get("message") or "该密钥不是编程套餐（Coding Plan）密钥")
        entry.update(status="no_plan", error=msg, kind="subscription")
        return entry
    payload = data.get("data") or {}
    limits = payload.get("limits") or payload.get("quotaLimits") or []
    windows = []
    if isinstance(limits, list):
        for item in limits:
            if not isinstance(item, dict):
                continue
            used = _num(item.get("usage") if item.get("usage") is not None else item.get("currentValue")) or 0.0
            cap = _num(item.get("cap") or item.get("limit") or item.get("total")) or 0.0
            pct = _num(item.get("percentage"))
            label = str(item.get("type") or item.get("name") or "额度")
            bar = _bar(label, used, cap, reset_at=item.get("nextResetTime"), unit="$") if cap > 0 else None
            if bar is None and pct is not None:
                bar = _bar(label, pct, 100.0, reset_at=item.get("nextResetTime"), unit="%")
            if bar:
                windows.append(bar)
    entry.update(status="ok" if windows else "no_plan", windows=windows,
                 plan=str(payload.get("level") or "") or None,
                 error=None if windows else "接口未返回可解析的窗口数据",
                 links=[{"label": "用量页", "url": "https://open.bigmodel.cn/usercenter/resourcepack"}])
    return entry


# ────────────────────────── 订阅制：OpenCode Go ──────────────────────────

# 字面量端点：运行时的 base_url 在 anthropic 协议模式下会丢 /v1 后缀，而 /usage 只在 /v1 路径下存在
# （与 Hermes 内置 opencode-go provider profile 同一来源，2026-09-29 直连实测可用）。
OPENCODE_GO_USAGE_URL = "https://opencode.ai/zen/go/v1/usage"


def _fetch_opencode_go_accounts() -> list[dict]:
    """OpenCode Go 全部账户各出一条（单账户时与旧行为一致）。

    账户清单取自 auth.json 的凭证池（与 CommandCode 同一做法）：主账户额度用尽
    被池标记后，面板仍要能看出「哪个账户、剩多少、运行时正在用哪个」。
    """
    accounts = _pool_accounts("opencode-go")
    if not accounts:
        return [_fetch_opencode_go_one(None)]
    active_key = _pool_active_key("opencode-go")
    total = len(accounts)
    return [_fetch_opencode_go_one(acc, index=idx, total=total, active=(acc.get("key") == active_key))
            for idx, acc in enumerate(accounts)]


def _fetch_opencode_go() -> dict:
    """单账户回退：池里读不到账户时使用。"""
    return _fetch_opencode_go_one(None)


def _fetch_opencode_go_one(account: Optional[dict], *,
                           index: int = 0, total: int = 1, active: bool = False) -> dict:
    """单个 OpenCode Go 账户：滚动 / 每周 / 每月（百分比制）。

    接口返回 {"usage": {"rolling"|"weekly"|"monthly": {"status", "percent", "resetsAt"}}}，
    percent 为已用百分比、resetsAt 为窗口重置时间。境外接口：先直连（本机实测可达），
    仅当直连网络错误时才回退环境变量 / 注册表代理。
    """
    tag = "" if total <= 1 else ("主" if index == 0 else "备" if index == 1 else f"#{index + 1}")
    entry = _entry("opencode-go" if index == 0 else f"opencode-go-{index + 1}",
                   "OpenCode Go" + (f"（{tag}）" if tag else ""), "subscription")
    entry["meta"] = {"account_index": index, "account_total": total, "active": active,
                     "env_var": str((account or {}).get("env_var") or "")}
    if account is None:
        key, _base = _resolve("opencode-go")
        key_error = "未解析到 API Key"
    else:
        key = str(account.get("key") or "")
        key_error = str(account.get("key_error") or "未解析到 API Key")
    if not key:
        entry.update(status="unavailable", error=key_error)
        return entry
    headers = _bearer(key)

    def _fetch_once(proxy: Optional[str]) -> dict:
        kwargs: dict[str, Any] = {"timeout": HTTP_TIMEOUT, "follow_redirects": True}
        if proxy:
            kwargs["proxy"] = proxy
        else:
            kwargs["trust_env"] = False  # 直连：绕开环境变量里的历史代理残留
        with httpx.Client(**kwargs) as client:
            return _get_json(client, OPENCODE_GO_USAGE_URL, headers)

    try:
        try:
            data = _fetch_once(None)
        except (httpx.TransportError, httpx.TimeoutException):
            proxy = _proxy_url()
            if not proxy:
                raise
            data = _fetch_once(proxy)
    except Exception as exc:
        entry.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:140]}")
        return entry

    usage = (data or {}).get("usage") or {}
    windows = []
    for window_key, label in (("rolling", "滚动窗口"), ("weekly", "每周"), ("monthly", "每月")):
        window = usage.get(window_key) or {}
        pct = _num(window.get("percent"))
        if pct is None:
            continue
        bar = _bar(label, pct, 100.0, unit="%", reset_at=window.get("resetsAt"))
        if bar:
            win_status = str(window.get("status") or "").strip()
            if win_status and win_status != "ok":
                bar["note"] = win_status
            windows.append(bar)
    details: list[str] = []
    if total > 1:
        details.append("运行时正在使用" if active else "运行时未选中")
    if account is not None:
        if str(account.get("last_status") or "") == "exhausted":
            reset_at = _num(account.get("last_error_reset_at"))
            if reset_at and reset_at > time.time():
                when = datetime.fromtimestamp(reset_at).strftime("%m-%d %H:%M")
                details.append(f"池内标记：额度用尽（供应商窗口 {when} 恢复，期间重试仍会被拒）")
            else:
                pool_note = _pool_bench_note(account)
                details.append(pool_note or "池内标记：耗尽")
        else:
            pool_note = _pool_bench_note(account)
            if pool_note:
                details.append(pool_note)
    entry.update(status="ok" if windows else "no_api", windows=windows,
                 error=None if windows else "接口未返回窗口数据",
                 details=details,
                 links=[{"label": "控制台", "url": "https://opencode.ai/auth"}],
                 meta=dict(entry.get("meta") or {}, source="zen_go_usage_api"))
    return entry


# ────────────────────────── 余额制 ──────────────────────────

def _fetch_deepseek() -> dict:
    entry = _entry("deepseek", "DeepSeek", "balance")
    key, base = _resolve("deepseek")
    if not key:
        entry.update(status="unavailable", error="未解析到 API Key")
        return entry
    root = (base or "https://api.deepseek.com/v1").rstrip("/")
    for suffix in ("/v1", "/beta"):
        if root.endswith(suffix):
            root = root[: -len(suffix)]
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            data = _get_json(client, f"{root}/user/balance", _bearer(key))
        infos = data.get("balance_infos") or []
        info = infos[0] if infos else {}
        amount = _num(info.get("total_balance"))
        entry.update(
            status="ok",
            balance={"amount": amount, "currency": info.get("currency") or "CNY", "label": "账户余额"},
            details=[f"充值余额 {info.get('topped_up_balance')}", f"赠送余额 {info.get('granted_balance')}"]
                    if info.get("topped_up_balance") else [],
            warn=None if data.get("is_available") else "余额不足，接口可能已停用",
            links=[{"label": "充值", "url": "https://platform.deepseek.com/top_up"}],
        )
        return entry
    except Exception as exc:
        entry.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:140]}")
        return entry


def _fetch_moonshot(pid: str, name: str, provider_key: str) -> dict:
    entry = _entry(pid, name, "balance")
    key, base = _resolve(provider_key)
    if not key:
        entry.update(status="unavailable", error="未解析到 API Key")
        return entry
    root = (base or "https://api.moonshot.cn/v1").rstrip("/")
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            data = _get_json(client, f"{root}/users/me/balance", _bearer(key))
        payload = data.get("data") or {}
        amount = _num(payload.get("available_balance"))
        entry.update(status="ok", balance={"amount": amount, "currency": "CNY", "label": "账户余额"},
                     details=[f"现金 {payload.get('cash_balance')}", f"代金券 {payload.get('voucher_balance')}"],
                     links=[{"label": "充值", "url": "https://platform.moonshot.cn/console/pay" if "moonshot.cn" in root else "https://platform.moonshot.ai/console/pay"}])
        return entry
    except Exception as exc:
        entry.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:140]}")
        return entry


def _fetch_openrouter() -> dict:
    entry = _entry("openrouter", "OpenRouter", "balance")
    key, base = _resolve("openrouter")
    if not key:
        entry.update(status="unavailable", error="未解析到 API Key")
        return entry
    root = (base or "https://openrouter.ai/api/v1").rstrip("/")
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            credits = (_get_json(client, f"{root}/credits", _bearer(key)) or {}).get("data") or {}
            try:
                keyinfo = (_get_json(client, f"{root}/key", _bearer(key)) or {}).get("data") or {}
            except Exception:
                keyinfo = {}
        total, usage = _num(credits.get("total_credits")) or 0.0, _num(credits.get("total_usage")) or 0.0
        balance = max(0.0, total - usage)
        details = [f"累计充值 ${total:,.2f}", f"累计消耗 ${usage:,.2f}"]
        for field, label in (("usage_daily", "今日"), ("usage_weekly", "本周"), ("usage_monthly", "本月")):
            v = _num(keyinfo.get(field))
            if v:
                details.append(f"{label} ${v:,.2f}")
        entry.update(status="ok", balance={"amount": round(balance, 2), "currency": "USD", "label": "剩余额度"},
                     details=details, links=[{"label": "充值", "url": "https://openrouter.ai/settings/credits"}])
        if balance <= 1.0:
            entry["warn"] = "余额偏低"
        return entry
    except Exception as exc:
        entry.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:140]}")
        return entry


def _fetch_nous() -> dict:
    entry = _entry("nous", "Nous Portal", "balance")
    try:
        from agent.account_usage import nous_credits_lines, build_nous_credits_snapshot, _fetch_portal_account, _nous_logged_in
    except Exception as exc:
        entry.update(status="unavailable", error=f"无法加载 Hermes 模块：{exc}")
        return entry
    try:
        if not _nous_logged_in():
            entry.update(status="unavailable", error="未登录（hermes auth 登录后可见）")
            return entry
        snapshot = build_nous_credits_snapshot(_fetch_portal_account(8.0))
        if snapshot is None:
            entry.update(status="unavailable", error="门户未返回账户信息")
            return entry
        windows = []
        for w in snapshot.windows:
            bar = _bar(w.label, w.used_percent or 0.0, 100.0, unit="%")
            if bar:
                if w.detail:
                    bar["note"] = w.detail
                windows.append(bar)
        entry.update(status="ok", plan=snapshot.plan, windows=windows, details=list(snapshot.details))
        if snapshot.unavailable_reason:
            entry.update(status="unavailable", error=snapshot.unavailable_reason)
        return entry
    except Exception as exc:
        entry.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:140]}")
        return entry


def _console_only_entries() -> list[dict]:
    out = []
    for pid, name, url in CONSOLE_ONLY:
        key, base = _resolve(pid)
        entry = _entry(pid, name, "unsupported", status="no_api",
                       error="供应商未提供额度/余额查询接口，需在控制台查看" if key else "未配置密钥")
        entry["links"] = [{"label": "控制台", "url": url}]
        out.append(entry)
    return out


# ────────────────────────── 本机消耗（state.db） ──────────────────────────

def _local_usage() -> dict:
    """按会话归属统计今日 / 7 日 / 30 日的 tokens 与估算费用（只读）。"""
    empty = {"available": False, "periods": [], "by_provider": [], "error": None}
    if not STATE_DB.exists():
        empty["error"] = f"未找到 {STATE_DB}"
        return empty
    now = datetime.now().astimezone()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    periods = (
        ("今日", midnight.timestamp()),
        ("近 7 日", (now - timedelta(days=7)).timestamp()),
        ("近 30 日", (now - timedelta(days=30)).timestamp()),
    )
    sql = (
        "SELECT u.billing_provider AS prov,"
        " SUM(u.input_tokens), SUM(u.output_tokens), SUM(u.cache_read_tokens), SUM(u.cache_write_tokens),"
        " SUM(u.estimated_cost_usd), SUM(u.api_call_count), COUNT(DISTINCT u.session_id) "
        "FROM session_model_usage u JOIN sessions s ON s.id = u.session_id "
        "WHERE s.started_at >= ? GROUP BY u.billing_provider ORDER BY SUM(u.estimated_cost_usd) DESC"
    )
    try:
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=4.0)
        try:
            rows_out = []
            by_provider: dict[str, dict] = {}
            for label, since in periods:
                rows = con.execute(sql, (since,)).fetchall()
                total = {"label": label, "cost_usd": 0.0, "tokens": 0, "calls": 0, "sessions": 0}
                for prov, tin, tout, tcr, tcw, cost, calls, sessions in rows:
                    tin, tout = tin or 0, tout or 0
                    tokens = tin + tout + (tcr or 0) + (tcw or 0)
                    cost = cost or 0.0
                    total["cost_usd"] += cost
                    total["tokens"] += tokens
                    total["calls"] += calls or 0
                    total["sessions"] += sessions or 0
                    if label == "近 30 日":
                        slot = by_provider.setdefault(str(prov or "未知"), {"provider": str(prov or "未知"), "cost_usd": 0.0, "tokens": 0})
                        slot["cost_usd"] += cost
                        slot["tokens"] += tokens
                total["cost_usd"] = round(total["cost_usd"], 4)
                rows_out.append(total)
        finally:
            con.close()
    except Exception as exc:
        empty["error"] = f"{type(exc).__name__}: {str(exc)[:140]}"
        return empty
    ranked = sorted(by_provider.values(), key=lambda r: -r["cost_usd"])[:5]
    for item in ranked:
        item["cost_usd"] = round(item["cost_usd"], 4)
    return {"available": True, "periods": rows_out, "by_provider": ranked, "error": None,
            "note": "按会话开始时间归属；费用为 Hermes 侧估算，不是供应商账单"}


# ────────────────────────── 凭据健康（auth.json） ──────────────────────────

def _credential_health() -> list[dict]:
    if not AUTH_JSON.exists():
        return []
    try:
        data = json.loads(AUTH_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[dict] = []
    pool = data.get("credential_pool") or {}
    for provider, entries in pool.items():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            reason = e.get("failure_reason") or e.get("last_error_reason")
            status = e.get("last_status")
            if not reason and status in (None, "ok"):
                continue
            if provider in ("commandcode-chat", "commandcode-anthropic", "commandcode-claude",
                            "alibaba-cn", "alibaba-cloud-cn", "dashscope-cn", "alibaba-coding-cn",
                            "alibaba-coding-plan-cn", "dashscope-coding-cn", "openai-codex"):
                # 同一密钥的别名条目 / codex 已在订阅区显示，避免重复噪声
                if provider != "openai-codex":
                    continue
            out.append({
                "provider": provider,
                "label": str(e.get("label") or "")[:24],
                "status": str(status or ""),
                "reason": str(reason or "")[:60],
                "message": str(e.get("last_error_message") or "")[:120],
                "code": e.get("last_error_code"),
                "at": _iso_from_ms(e.get("last_status_at")),
                "reset_at": _iso_from_ms(e.get("last_error_reset_at")),
            })
    for provider, state in (data.get("providers") or {}).items():
        err = (state or {}).get("last_auth_error") if isinstance(state, dict) else None
        if isinstance(err, dict):
            out.append({"provider": provider, "label": "登录态", "status": "auth_error",
                        "reason": str(err.get("reason") or "")[:60], "message": str(err.get("message") or "")[:120],
                        "code": err.get("code"), "at": str(err.get("at") or "")[:19], "reset_at": None})
    seen, uniq = set(), []
    for item in out:
        k = (item["provider"], item["reason"], item["code"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(item)
    return uniq[:8]


# ────────────────────────── 汇总 ──────────────────────────

def _local_rates(days: int = 7) -> dict:
    """近 N 日各供应商的日均花费（Hermes 侧估算），用于「预计可用天数」。"""
    if not STATE_DB.exists():
        return {}
    since = (datetime.now().astimezone() - timedelta(days=days)).timestamp()
    sql = ("SELECT u.billing_provider, SUM(u.estimated_cost_usd) "
           "FROM session_model_usage u JOIN sessions s ON s.id = u.session_id "
           "WHERE s.started_at >= ? GROUP BY u.billing_provider")
    try:
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=4.0)
        try:
            rows = con.execute(sql, (since,)).fetchall()
        finally:
            con.close()
    except Exception:
        return {}
    out: dict = {}
    for provider, cost in rows:
        value = _num(cost)
        if value and value > 0:
            out[str(provider or "未知")] = value / float(days)
    return out


def _attach_rates(entries: list, rates: dict, days: int) -> None:
    """给余额类供应商补上「日均花费 / 预计可用天数」；非美元余额按 fx_to_usd 折算成美元。"""
    config = _config()
    fx = config.get("fx_to_usd") or {}
    for entry in entries:
        if entry.get("rate") or entry.get("kind") != "balance":
            continue
        balance = entry.get("balance") or {}
        amount = balance.get("amount")
        if amount is None:
            continue
        daily = rates.get(str(entry.get("id")))
        if not daily or daily <= 0.005:
            continue
        currency = str(balance.get("currency") or "USD").upper()
        factor = _num(fx.get(currency))
        base = {"daily_usd": round(daily, 2), "basis": f"近 {days} 日"}
        if factor is None:
            entry["rate"] = dict(base, days_left=None, note=f"{currency} 余额未配置折算汇率")
            continue
        usd = float(amount) * factor
        entry["rate"] = dict(base, days_left=round(max(0.0, usd) / daily, 1),
                             converted=currency != "USD", currency=currency)


def _collect() -> dict:
    """并发抓取全部供应商（同步实现，由端点丢进线程池）。"""
    tasks = {
        "commandcode": _fetch_commandcode_accounts,
        "openai-codex": _fetch_codex,
        "opencode-go": _fetch_opencode_go_accounts,
        "zai": _fetch_glm_balance,
        "deepseek": _fetch_deepseek,
        "kimi-cn": lambda: _fetch_moonshot("kimi-coding-cn", "Kimi（Moonshot CN）", "kimi-coding-cn"),
        "openrouter": _fetch_openrouter,
        "nous": _fetch_nous,
    }
    results: dict[str, dict] = {}
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {name: pool.submit(fn) for name, fn in tasks.items()}
        for name, fut in futures.items():
            try:
                results[name] = fut.result(timeout=HTTP_TIMEOUT + 25)
            except Exception as exc:
                results[name] = {"id": name, "name": name, "kind": "subscription", "status": "error",
                                 "error": f"{type(exc).__name__}: {str(exc)[:140]}", "windows": [], "details": []}
    commandcode = results.get("commandcode")
    if isinstance(commandcode, dict):
        commandcode = [commandcode]
    # Claude（订阅）不列入：本机没有 Claude 凭据，用户要求不显示 —— 需要时把
    # _fetch_anthropic_direct 加回这里即可（该函数保留未删）。
    opencode = results.get("opencode-go")
    if isinstance(opencode, dict):
        opencode = [opencode]
    subscription = list(commandcode or []) + [results["openai-codex"]] + list(opencode or [])
    balance = [results["zai"], results["deepseek"], results["kimi-cn"], results["openrouter"], results["nous"]]
    usage = _local_usage()
    try:
        _attach_rates(balance, _local_rates(7), 7)
    except Exception:
        pass
    payload = {
        "ok": True,
        "fetched_at": _now_iso(),
        "subscription": subscription,
        "balance": balance,
        "unsupported": _console_only_entries(),
        "local_usage": usage,
        "health": _credential_health(),
        "thresholds": {"window_pct": _config().get("window_pct"), "low_balance": _config().get("low_balance"),
                       "days_left": _config().get("days_left"), "cooldown_hours": _config().get("cooldown_hours"),
                       "health_alert_max_age_hours": _config().get("health_alert_max_age_hours"),
                       "mute": _config().get("mute")},
    }
    payload["alerts"] = _build_alerts(payload)
    return payload


# ────────────────────────── 告警 ──────────────────────────

# 兼容别名——实际生效值见 DEFAULT_CONFIG / state/config.json（_config()）
ALERT_WINDOW_PCT = float(DEFAULT_CONFIG["window_pct"])
ALERT_LOW_BALANCE = dict(DEFAULT_CONFIG["low_balance"])
ALERT_DAYS_LEFT = float(DEFAULT_CONFIG["days_left"])


def _build_alerts(data: dict) -> list:
    """按阈值挑出需要提醒的条目（面板、桌面通知、cron 看门狗共用）。

    阈值与静默清单来自 _config()（state/config.json）。凭据类告警只在
    ①该供应商本次查询不正常、②失败时间在 health_alert_max_age_hours 内时才产生，
    避免翻出池子里早已过期的一次性 429/401。
    """
    config = _config()
    window_pct = float(config.get("window_pct") or ALERT_WINDOW_PCT)
    low_balance = config.get("low_balance") or ALERT_LOW_BALANCE
    days_limit = float(config.get("days_left") or ALERT_DAYS_LEFT)
    health_max_age = float(config.get("health_alert_max_age_hours") or 48.0)
    live_ok = {str(e.get("id")) for e in (data.get("subscription") or []) + (data.get("balance") or [])
               if e.get("status") == "ok"}
    now = datetime.now(timezone.utc)
    alerts: list = []
    for entry in data.get("subscription", []):
        if entry.get("status") != "ok":
            continue
        for win in entry.get("windows", []):
            pct = float(win.get("pct") or 0)
            if not (win.get("exceeded") or pct >= window_pct):
                continue
            alert_id = f"{entry.get('id')}:{win.get('label')}"
            if _is_muted(config, alert_id, str(entry.get("id") or "")):
                continue
            parts = []
            if win.get("unit") != "%" and win.get("remaining") is not None:
                remaining = _num(win.get("remaining"))
                if remaining is not None:
                    parts.append("额度已用尽" if remaining <= 0 else f"剩 {win.get('unit')}{remaining:,.2f}")
            reset_text = _rel_reset(win.get("reset_at"))
            if reset_text:
                parts.append(reset_text)
            alerts.append({
                "id": alert_id,
                "level": "critical" if (win.get("exceeded") or pct >= 95) else "warn",
                "provider": entry.get("name"),
                "title": f"{win.get('label')}已用 {round(pct)}%",
                "detail": "｜".join(parts),
                "reset_at": win.get("reset_at"),
            })
    for entry in data.get("balance", []):
        balance = entry.get("balance") or {}
        amount = balance.get("amount")
        currency = str(balance.get("currency") or "").upper()
        balance_flagged = False
        alert_id = f"{entry.get('id')}:balance"
        muted = _is_muted(config, alert_id, str(entry.get("id") or ""))
        if amount is not None and entry.get("status") == "ok" and not muted:
            if amount <= 0:
                balance_flagged = True
                alerts.append({"id": alert_id, "level": "critical", "provider": entry.get("name"),
                               "title": "余额已耗尽", "detail": f"{amount} {currency}", "reset_at": None})
            elif amount <= (_num(low_balance.get(currency)) or 0):
                balance_flagged = True
                alerts.append({"id": alert_id, "level": "warn", "provider": entry.get("name"),
                               "title": "余额偏低", "detail": f"{amount} {currency}", "reset_at": None})
        rate = entry.get("rate") or {}
        days_left = rate.get("days_left")
        rate_id = f"{entry.get('id')}:rate"
        if not balance_flagged and days_left is not None and days_left <= days_limit \
                and not _is_muted(config, rate_id, str(entry.get("id") or "")):
            alerts.append({"id": rate_id, "level": "warn", "provider": entry.get("name"),
                           "title": f"按当前速度约 {days_left} 天用完",
                           "detail": f"日均 ${rate.get('daily_usd')}", "reset_at": None})
    for item in data.get("health", []):
        provider_id = str(item.get("provider") or "")
        status = str(item.get("status") or "")
        reason = str(item.get("reason") or "")
        if status == "ok" or provider_id in live_ok:
            continue  # 该供应商本次查询正常 → 池子里的历史失败不再提醒
        if not (status in ("exhausted", "auth_error") or reason in ("auth", "exhausted", "rate_limit")):
            continue
        at = _parse_iso(item.get("at"))
        if at is not None and (now - at).total_seconds() > health_max_age * 3600:
            continue
        if at is None and not provider_id:
            continue
        if _is_muted(config, f"{provider_id}:health", provider_id):
            continue
        alerts.append({"id": f"{provider_id}:health", "level": "warn", "provider": provider_id,
                       "title": "凭据异常",
                       "detail": f"{status} {reason} {item.get('code') or ''}".strip(),
                       "reset_at": item.get("reset_at")})
    seen, uniq = set(), []
    for alert in alerts:
        if alert["id"] in seen:
            continue
        seen.add(alert["id"])
        uniq.append(alert)
    order = {"critical": 0, "warn": 1}
    uniq.sort(key=lambda a: order.get(a["level"], 2))
    return uniq


def _rel_reset(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        target = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    seconds = (target - datetime.now(timezone.utc)).total_seconds()
    if seconds <= 0:
        return "已重置"
    hours = int(seconds // 3600)
    if hours < 24:
        return f"{hours}h 后重置"
    return f"{hours // 24} 天后重置"


def collect_alerts(force: bool = False) -> list:
    """对外入口（cron 看门狗脚本也用这个）。"""
    return _cached_overview(force=force).get("alerts") or []


def _cached_overview(force: bool = False) -> dict:
    now = time.time()
    age = now - float(_CACHE.get("at") or 0.0)
    ttl = CACHE_TTL if _CACHE.get("ok") else CACHE_TTL_ERROR
    if not force and _CACHE.get("data") is not None and age < ttl:
        data = dict(_CACHE["data"])
        data["cache_age"] = round(age, 1)
        data["cached"] = True
        return data
    data = _collect()
    ok = any(e.get("status") == "ok" for e in data.get("subscription", []) + data.get("balance", []))
    _CACHE.update({"at": now, "data": data, "ok": ok})
    out = dict(data)
    out["cache_age"] = 0.0
    out["cached"] = False
    return out


# ────────────────────────── 路由 ──────────────────────────

@router.get("/overview")
async def overview(refresh: int = 0) -> dict:
    # 同步 HTTP 抓取全部丢线程池，避免阻塞 serve 事件循环
    return await asyncio.to_thread(_cached_overview, bool(refresh))


@router.get("/alerts")
async def alerts(refresh: int = 0) -> dict:
    data = await asyncio.to_thread(_cached_overview, bool(refresh))
    return {"ok": True, "fetched_at": data.get("fetched_at"), "alerts": data.get("alerts") or [],
            "thresholds": data.get("thresholds")}


@router.get("/health")
async def health() -> dict:
    return {"ok": True, "read_only": True, "plugin": "provider-limits", "generated_at": _now_iso(),
            "state_db": str(STATE_DB), "ttl_seconds": CACHE_TTL}
