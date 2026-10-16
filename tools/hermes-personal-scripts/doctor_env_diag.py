#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""诊断 v2：在 cron 环境里二分定位「哪个环境变量让 scope-recall doctor 崩掉」（2026-09-30）。

v1 已确认的现场事实（cron 环境，14:40:41 采样）：
- 继承 cron 环境调用 venv 里的 scope-recall.exe → rc=1、stdout=0、stderr 2289 字节 Python traceback；
- 换成 9 个变量的最小环境（SYSTEMROOT/PATH/TEMP/TMP/LOCALAPPDATA/APPDATA/USERPROFILE/HERMES_HOME/COMSPEC）→ 正常输出 【金额】 字节；
- 桌面 shell 里各种组合都正常 → 故障只在 cron 那套环境里出现。

本脚本在 cron 里做二分查找：以最小环境为能跑的基线，把其余变量对半分批塞回，
每轮只看"塞回后是否仍能输出"，收敛到能单独复现故障的变量，并落盘失败那次的完整 stderr。
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERMES_HOME = Path(
    os.environ.get("HERMES_HOME")
    or (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "hermes")
)
OUT = HERMES_HOME / "cron" / "lawyer-status" / "doctor-env-diag2.json"
EXE = str(HERMES_HOME / "hermes-agent" / "venv" / "Scripts" / "scope-recall.exe")
CMD = [EXE, "doctor", "--host", "hermes", "--instance-root", str(HERMES_HOME)]
BASE_KEYS = ("SYSTEMROOT", "PATH", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE",
             "HERMES_HOME", "COMSPEC")
full = dict(os.environ)


def probe(env: dict) -> dict:
    try:
        r = subprocess.run(CMD, capture_output=True, text=True, timeout=120, cwd=str(HERMES_HOME), env=env)
        return {"rc": r.returncode, "out": len(r.stdout or ""), "err": r.stderr or ""}
    except Exception as exc:
        return {"rc": None, "out": 0, "err": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    report = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "exe": EXE}
    base = {k: v for k, v in full.items() if k.upper() in BASE_KEYS}
    base_run = probe(base)
    report["baseline_minimal"] = {"out": base_run["out"], "rc": base_run["rc"]}
    inherited = probe(full)
    report["inherited"] = {"out": inherited["out"], "rc": inherited["rc"], "stderr": inherited["err"][-3000:]}

    if base_run["out"] == 0:
        report["verdict"] = "基线最小环境也拿不到输出——不是单个变量的问题（可能涉及 spawn/控制台因素）"
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[diag2] 基线异常：最小环境也无输出")
        return 0
    if inherited["out"] > 0:
        report["verdict"] = "本次未复现（间歇性）——本脚本每 5 分钟重跑，等下一次采样"
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[diag2] 本次未复现，已记录")
        return 0

    extra = sorted(k for k in full if k.upper() not in BASE_KEYS)
    suspect = list(extra)
    trail = []
    while len(suspect) > 1:
        half = len(suspect) // 2
        left, right = suspect[:half], suspect[half:]
        env_left = dict(base)
        env_left.update({k: full[k] for k in left})
        run_left = probe(env_left)
        trail.append({"tried": left, "out": run_left["out"]})
        if run_left["out"] == 0:
            suspect = left
            continue
        env_right = dict(base)
        env_right.update({k: full[k] for k in right})
        run_right = probe(env_right)
        trail.append({"tried": right, "out": run_right["out"]})
        if run_right["out"] == 0:
            suspect = right
        else:
            report.update(verdict="左右两半单独都不复现——需组合（可能两三个变量共同作用）", trail=trail)
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print("[diag2] 单一变量不足以复现")
            return 0

    culprit = suspect[0]
    env_one = dict(base)
    env_one[culprit] = full[culprit]
    one = probe(env_one)
    report.update(verdict=f"单一变量即可复现：{culprit}", culprit=culprit,
                  culprit_value=str(full.get(culprit))[:200],
                  single_run={"out": one["out"], "rc": one["rc"], "stderr": one["err"][-3000:]},
                  trail=trail)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[diag2] 定位到：{culprit}（单独塞回后 stdout={one['out']}B）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
