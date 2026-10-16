#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""辅助模型端点连通性探针（scope-recall 网络失败观察用）。

背景：2026-09-30 排查发现记忆流水线存在间歇性 network_error（当日按小时 19/6/61 次，
而 09-25、09-26 为零）；实测端点当下健康（TLS1.3、GET /models 200、0.8s），
说明不是 DNS/TLS/代理/封禁的恒定断裂。要定位只能按时间采样。

本探针**不调用模型**：只做 TCP+TLS 握手与 GET {base_url}/models（不产生 token 消耗）。

输出约定（供 no_agent 任务使用）：
- 端点健康：不打印任何内容（静默，避免噪声）。
- 从健康变为失败：打印一行（首次异常通知）。
- 持续失败：静默（不重复告警）。
- 恢复：打印一行（恢复通知，只通知一次）。

每次采样都追加到 <HERMES_HOME>/cron/lawyer-status/endpoint-probe.jsonl，便于事后与
work_error_details 的失败时间对齐。
"""

import json
import os
import socket
import ssl
import sys
import time
import urllib.request
from pathlib import Path

HERMES_HOME = Path(
    os.environ.get("HERMES_HOME")
    or (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "hermes")
)
STATUS_DIR = HERMES_HOME / "cron" / "lawyer-status"
LOG_PATH = STATUS_DIR / "endpoint-probe.jsonl"
STATE_PATH = STATUS_DIR / "endpoint-probe.json"
TIMEOUT = int(os.environ.get("ENDPOINT_PROBE_TIMEOUT", "15"))


def base_url() -> str:
    """主配置 model.base_url（辅助模型与主模型同路由）。"""
    try:
        import yaml

        cfg = yaml.safe_load((HERMES_HOME / "config.yaml").read_text(encoding="utf-8")) or {}
        url = (cfg.get("model") or {}).get("base_url")
        if isinstance(url, str) and url.startswith("http"):
            return url.rstrip("/")
    except Exception:
        pass
    return os.environ.get("ENDPOINT_PROBE_URL", "").rstrip("/")


def probe(url: str) -> dict:
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "url": url}
    if not url:
        out.update(ok=False, reason="no_base_url")
        return out
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    t0 = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=TIMEOUT)
        tcp_ms = int((time.time() - t0) * 1000)
        if parsed.scheme == "https":
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(sock, server_hostname=host) as ss:
                out["tls"] = ss.version()
        else:
            sock.close()
        out["tcp_ms"] = tcp_ms
    except Exception as exc:
        out.update(ok=False, reason=f"{type(exc).__name__}: {exc}"[:160], tcp_ms=int((time.time() - t0) * 1000))
        return out
    try:
        req = urllib.request.Request(url + "/models", headers={"User-Agent": "hermes-endpoint-probe"})
        t1 = time.time()
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            out.update(ok=True, http=resp.status, http_ms=int((time.time() - t1) * 1000))
    except Exception as exc:
        code = getattr(exc, "code", None)
        out.update(ok=False, reason=f"http {code or type(exc).__name__}: {str(exc)[:120]}",
                   http_ms=int((time.time() - t1) * 1000))
    return out


def main() -> int:
    url = base_url()
    result = probe(url)
    try:
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(result, ensure_ascii=False) + "\n")
        prev = {}
        if STATE_PATH.exists():
            try:
                loaded = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                prev = loaded if isinstance(loaded, dict) else {}
            except json.JSONDecodeError:
                prev = {}
        prev_ok = prev.get("ok")
        # 原子替换：避免进程中断或半写留下坏 JSON，使下一轮丢失前态（影响异常/恢复通知的去重）
        # 唯一临时名：避免并发进程互相覆盖对方的临时文件（固定名会被另一进程替换掉）
        tmp = STATE_PATH.with_name(f"{STATE_PATH.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, STATE_PATH)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
    except OSError as exc:
        # 采样状态写不进去是真故障：不能返回 0 让调度器记成一次成功探针。
        print(f"[probe] 状态写入失败：{exc}", file=sys.stderr)
        print(f"[probe] 状态写入失败：{exc}")
        return 3

    if not result.get("ok") and prev_ok is not False:
        print(f"[probe] 辅助模型端点不可用（{result.get('reason')}）——{url}")
    elif result.get("ok") and prev_ok is False:
        print(f"[probe] 辅助模型端点已恢复（HTTP {result.get('http')}，{result.get('http_ms')}ms）——{url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
