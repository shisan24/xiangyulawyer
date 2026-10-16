#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""OpenViking 健康检查 — 检查 ov-server 存活 + 子系统就绪。

用法:
    python ov-healthcheck.py              # 标准输出
    python ov-healthcheck.py --json       # JSON 输出 (供 cron)
"""

import json
import sys
import urllib.request
import urllib.error

OV_BASE = "http://【本机端口】"
TIMEOUT = 10


def http_get(url: str) -> dict:
    """GET 请求."""
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        body = json.loads(resp.read().decode("utf-8"))
        return {"ok": True, "status_code": resp.status, "data": body, "error": None}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = str(e)
        return {"ok": e.code < 500, "status_code": e.code, "data": body, "error": str(e)}
    except Exception as e:
        return {"ok": False, "status_code": None, "data": None, "error": str(e)}


def check_health() -> dict:
    """基础健康检查."""
    r = http_get(f"{OV_BASE}/health")
    if r["ok"] and r["data"]:
        return {
            "healthy": r["data"].get("healthy", False),
            "version": r["data"].get("version", "?"),
            "auth_mode": r["data"].get("auth_mode", "?"),
            "ok": r["data"].get("healthy", False),
            "error": None,
        }
    return {"ok": False, "healthy": False, "version": None, "auth_mode": None, "error": r["error"]}


def check_ready() -> dict:
    """就绪检查 — 子系统状态."""
    r = http_get(f"{OV_BASE}/ready")
    data = r.get("data", {}) or {}
    checks = data.get("checks", {})

    subsystems = {}
    warnings = []

    for name, state in checks.items():
        if isinstance(state, str):
            subsystems[name] = state
            if state != "ok" and state != "not_configured":
                warnings.append(f"{name}={state}")
        elif isinstance(state, dict):
            st = state.get("status", "?")
            subsystems[name] = st
            if st != "ok" and st != "not_supported":
                warnings.append(f"{name}={st}")

    ok = data.get("status") == "ok"
    return {
        "ok": ok or r.get("status_code") == 200,
        "status": data.get("status", "not_ready"),
        "subsystems": subsystems,
        "warnings": warnings,
        "error": r["error"] if not r["ok"] else None,
    }


def main():
    json_mode = "--json" in sys.argv

    health = check_health()
    if health["ok"]:
        ready = check_ready()
    else:
        ready = {"ok": False, "status": "skipped", "subsystems": {}, "warnings": [], "error": "health check failed"}

    all_ok = health["ok"]
    exit_code = 0 if all_ok else 1

    if json_mode:
        output = {
            "health": health,
            "ready": ready,
            "overall_ok": all_ok,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        sys.exit(exit_code)

    print("=== OpenViking Health Check ===")
    print(f"  Liveness: {'OK' if health['ok'] else 'FAIL'}  "
          f"v{health.get('version','?')}  auth={health.get('auth_mode','?')}")
    if health.get("error"):
        print(f"  ERROR: {health['error']}")

    subs = ready.get("subsystems", {})
    if subs:
        print("  Subsystems:")
        for name in sorted(subs):
            state = subs[name]
            icon = "OK" if state in ("ok", "not_supported", "not_configured") else "XX"
            print(f"    {icon} {name}: {state}")
    warnings = ready.get("warnings", [])
    if warnings:
        print(f"  Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"    WARN: {w}")

    print(f"  Result: {'HEALTHY' if all_ok else 'UNHEALTHY'}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
