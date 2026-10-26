#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""scope-recall worker 临时配置的保留策略（2026-09-30 起）。

背景：worker 每次启动会写一个 `runtime-config-worker-<8位>.json`，并声明
`cleanup_config: True` 由子进程退出时自删。worker 异常退出时删不掉，于是累积：
2026-09-30 实测 金额 个 / 46.6 MiB，且每小时新增约 180–250 个。

已核实（做清理前的前置事实）：
- 文件内容**不含凭据值**，只有环境变量名（如 `credential_env: DEEPSEEK_API_KEY`）；
- 没有活进程引用（进程命令行里不含该文件名）；
- 包里没有按 `runtime-config-worker*` 模式扫描/读取这些文件的代码——它们是按显式路径
  传给子进程的，进程退出后即无用。

策略：**只移动、不删除**。保留规则（两条取并集，满足其一即保留）：
- 修改时间在 KEEP_HOURS 小时以内（可能仍是刚启动、尚在运行的 worker）；
- 最新的 KEEP_NEWEST 个。
其余移入 `<scope-recall>/_swept-worker-configs-<日期>/`，可原样移回。

用法：
  python scope_recall_config_sweep.py            # 只报告（dry-run，不动文件）
  python scope_recall_config_sweep.py --apply    # 执行隔离
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERMES_HOME = Path(
    os.environ.get("HERMES_HOME")
    or (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "hermes")
)
STORE_DIR = HERMES_HOME / "scope-recall"
KEEP_HOURS = 2
KEEP_NEWEST = 300
NOTIFY_MIN = 50  # cron 执行分支：隔离数低于此值且无失败时不通知，避免每周噪声


def collect() -> list[Path]:
    return [p for p in STORE_DIR.glob("runtime-config-worker-*.json") if p.is_file()]


def plan(files: list[Path]) -> tuple[list[Path], list[Path]]:
    now = time.time()
    by_mtime = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
    keep = set(by_mtime[:KEEP_NEWEST])
    keep |= {p for p in files if (now - p.stat().st_mtime) / 3600 < KEEP_HOURS}
    swept = [p for p in sorted(files, key=lambda p: str(p)) if p not in keep]
    return sorted(keep, key=lambda p: str(p)), swept


def main() -> int:
    ap = argparse.ArgumentParser(description="scope-recall worker 临时配置保留策略（只隔离不删除）")
    ap.add_argument("--apply", action="store_true", help="执行隔离；不带则只报告")
    args = ap.parse_args()

    files = collect()
    if not files:
        print("[OK] 没有 runtime-config-worker-*.json 残留")
        return 0
    keep, swept = plan(files)
    total_mib = sum(p.stat().st_size for p in files) / 1048576
    swept_mib = sum(p.stat().st_size for p in swept) / 1048576
    if not swept:
        return 0
    if not args.apply:
        print(f"残留 {len(files)} 个 / {total_mib:.1f} MiB；保留 {len(keep)} 个，待隔离 {len(swept)} 个 / {swept_mib:.1f} MiB")
        print(f"保留规则：{KEEP_HOURS} 小时内 + 最新 {KEEP_NEWEST} 个")
        print("[DRY-RUN] 未改动任何文件；加 --apply 执行隔离")
        for p in swept[:5]:
            print(f"  将隔离：{p.name}")
        if len(swept) > 5:
            print(f"  …另 {len(swept) - 5} 个")
        return 0

    dest = STORE_DIR / f"_swept-worker-configs-{time.strftime('%Y%m%d')}"
    dest.mkdir(parents=True, exist_ok=True)
    moved, failed = 0, []
    for p in swept:
        target = dest / p.name
        try:
            if target.exists():
                target.unlink()
            shutil.move(str(p), str(target))
            moved += 1
        except OSError as exc:
            failed.append(f"{p.name}: {exc}")
    manifest = {
        "swept_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rule": {"keep_hours": KEEP_HOURS, "keep_newest": KEEP_NEWEST},
        "moved": moved,
        "failed": failed[:20],
        "dest": str(dest),
        "restore": f"把 {dest} 下的文件移回 {STORE_DIR} 即可还原",
    }
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if failed:
        print(f"[WARN] 隔离 {moved} 个，{len(failed)} 个失败（前 3）：{failed[:3]}；目录 {dest}")
    elif moved >= NOTIFY_MIN:
        print(f"[OK] 已隔离 {moved} 个到 {dest}")
    # 例行小量隔离不通知（cron 场景下空输出＝不通知）
    return 0


if __name__ == "__main__":
    sys.exit(main())
