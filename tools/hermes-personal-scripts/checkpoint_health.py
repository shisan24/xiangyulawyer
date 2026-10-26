# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Cron: checkpoint 存储体检（越线报警）——2026-10-18 新增。

为什么需要它：2026-10-18 之前，checkpoint 存储从 2G 上限涨到 9.1G、C 盘被吃掉，
全过程没有任何提醒；等发现时已经堆积了 1.8 万个文件版本却只有一个半残的还原点。
本脚本每次只看四个硬指标，全部正常就静默；任一越线就输出明细并 exit 3（触发通知）。

指标与判据：
1. 体积：objects（打包 + 散件）+ indexes 的实占 > 上限 × 1.25 ⇒ 越线
   （「每个项目至少保留一个快照」是设计，所以允许 25% 余量）
2. 残渣：objects/pack 下存在 tmp_pack_*，或 count-objects 报 garbage > 0 ⇒ 越线
   （都是被掐断的 git 操作留下的垃圾）
3. 快照是否真的在成功：某项目的 workdir 近 24 小时内有改动，但它的 ref 上最近提交
   早于 48 小时 ⇒ 该项目的快照一直没提交成功（正是本机 [本地路径] 曾出现的退化形态）
4. add 超时频率：当天 errors.log 里 "git timed out" 超过 20 次 ⇒ 越线
   （单次超时是常态，成规模才说明遍历成本失控）

上限取 config.yaml 的 checkpoints.max_total_size_mb；读不到时按 2000 计。
退出码：0＝健康（静默）；3＝越线或有内容要报；2＝无法完成体检（必须报，不静默）。
"""

import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME") or r"[本地路径]")
BASE = HOME / "checkpoints"
STORE = BASE / "store"
GIT = HOME / "tools" / "git-2.53.0+3-win32-x64" / "cmd" / "git.exe"
ERRORS_LOG = HOME / "logs" / "errors.log"

TIMEOUT_LIMIT_PER_DAY = 20
SIZE_SLACK = 1.25
WORKDIR_ACTIVE_HOURS = 24
SNAPSHOT_STALE_HOURS = 48


def _cap_mb() -> int:
    try:
        import yaml
        text = (HOME / "config.yaml").read_text(encoding="utf-8")
        section = (yaml.safe_load(text) or {}).get("checkpoints") or {}
        value = int(section.get("max_total_size_mb") or 0)
        return value if value > 0 else 2000
    except Exception:
        return 2000


def _builtin_git() -> str:
    if GIT.exists():
        return str(GIT)
    for cand in glob.glob(str(HOME / "tools" / "git-*" / "cmd" / "git.exe")):
        return cand
    return "git"


def _run_git(args: list[str]) -> str:
    proc = subprocess.run([_builtin_git(), "--git-dir", str(STORE)] + args,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=180)
    return (proc.stdout or "") + (proc.stderr or "")


def _dir_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _count_timeouts_today() -> int:
    today = time.strftime("%Y-%m-%d")
    count = 0
    try:
        with ERRORS_LOG.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith(today) and "git timed out" in line:
                    count += 1
    except OSError:
        return -1
    return count


def main() -> int:
    if not STORE.exists():
        print("[checkpoint 体检] 存储目录不存在：%s（若已关闭 checkpoints 属正常）" % STORE)
        return 0

    findings = []
    cap_bytes = _cap_mb() * 1024 * 1024

    size = _dir_bytes(STORE / "objects") + _dir_bytes(STORE / "indexes")
    if size > cap_bytes * SIZE_SLACK:
        findings.append("体积 %.2f GB 已超上限 %d MB 的 %.0f%%（设计上允许 25%% 余量）"
                        % (size / 1024 ** 3, cap_bytes / 1024 ** 2, size / cap_bytes * 100))

    pack_dir = STORE / "objects" / "pack"
    tmp_packs = sorted(glob.glob(str(pack_dir / "tmp_pack_*")))
    if tmp_packs:
        findings.append("残留 %d 个 tmp_pack 垃圾：%s"
                        % (len(tmp_packs), ", ".join(os.path.basename(p) for p in tmp_packs[:4])))

    stats = _run_git(["count-objects", "-v"]) if STORE.exists() else ""
    garbage = re.search(r"^garbage:\s*(\d+)", stats, re.M)
    loose = re.search(r"^count:\s*(\d+)", stats, re.M)
    if garbage and int(garbage.group(1)) > 0:
        findings.append("git 报 garbage 对象 %s 个" % garbage.group(1))

    now = time.time()
    projects = sorted(glob.glob(str(STORE / "projects" / "*.json")))
    for meta_path in projects:
        try:
            meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        workdir = meta.get("workdir") or ""
        if not workdir or not os.path.isdir(workdir):
            continue
        try:
            active = now - os.path.getmtime(workdir) < WORKDIR_ACTIVE_HOURS * 3600
        except OSError:
            active = False
        if not active:
            continue
        digest = os.path.basename(meta_path)[:-5]
        head = _run_git(["log", "-1", "--format=%ct", "refs/hermes/%s" % digest]).strip().splitlines()
        last = int(head[0]) if head and head[0].isdigit() else 0
        age_hours = (now - last) / 3600 if last else None
        if age_hours is None:
            findings.append("工作目录 %s 近 24 小时有改动，但该项目在存储里没有任何提交（快照从未成功）" % workdir)
        elif age_hours > SNAPSHOT_STALE_HOURS:
            findings.append("工作目录 %s 近 24 小时有改动，但最近一次可用快照是 %.0f 小时前（快照可能一直超时失败）"
                            % (workdir, age_hours))

    timeouts = _count_timeouts_today()
    if timeouts < 0:
        findings.append("读不到 %s，当日超时次数未核验" % ERRORS_LOG)
    elif timeouts > TIMEOUT_LIMIT_PER_DAY:
        findings.append("当日 git add 超时 %d 次（阈值 %d 次）" % (timeouts, TIMEOUT_LIMIT_PER_DAY))

    if findings:
        print("[checkpoint 体检] %s" % time.strftime("%Y-%m-%d %H:%M"))
        print("  体积 %.2f GB / 上限 %d MB；散件 %s"
              % (size / 1024 ** 3, cap_bytes / 1024 ** 2, loose.group(1) if loose else "?"))
        for item in findings:
            print("  - %s" % item)
        return 3

    if size > cap_bytes:
        print("[checkpoint 体检] 体积 %.2f GB，略高于上限 %d MB 但在允许余量内，其余指标正常。"
              % (size / 1024 ** 3, cap_bytes / 1024 ** 2))
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
