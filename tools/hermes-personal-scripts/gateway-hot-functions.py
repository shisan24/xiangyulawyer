#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""把 py-spy 的 raw 折叠栈汇总成「函数级热点 + 调用者回溯」。

配合 hermes-gateway-diagnostics 技能：网关常驻 CPU 偏高时先做函数级归因，不猜队列。

采集（对网关进程采样 10 秒、50Hz）::

    uv tool run py-spy record -p <pid> -d 10 -r 50 -f raw --nonblocking -o "[本地路径]"

判读（本机实测）::

    python scripts/gateway-hot-functions.py "[本地路径]"
    python scripts/gateway-hot-functions.py prof.txt -n 15 --chains 3

输出三段：
1) 叶帧榜——CPU 实际停在哪个函数，带文件:行号与占比；
2) 帧榜（含父帧累计）——哪些函数出现在调用栈里最多；
3) 头名叶帧的调用链——回溯认出是谁在调用它（判断是变更监视扫树还是别的组件）。

判读要点见技能正文：目录遍历类（_dir_tree_signature / walk / realpath）占头名＝变更监视在扫树；
trim_memory、*_content_sig、local_lineage_index 属次要项。重启只治标，改间隔才治本。
"""

from __future__ import annotations

import argparse
import collections
import re
import sys

FRAME_RE = re.compile(r"^(.*?)\s*\((.*?)(?::(\d+))?\)\s*$")


def parse_frame(raw: str) -> tuple[str, str, str]:
    """把 'module.func (path/file.py:123)' 拆成 (函数, 文件, 行)。"""
    raw = raw.strip()
    m = FRAME_RE.match(raw)
    if m:
        func, path, line = m.group(1), m.group(2), m.group(3) or ""
        return func, path, line
    return raw, "", ""


def read_folded(path: str) -> tuple[list[tuple[list[str], int]], int, int]:
    """读折叠栈，返回 ([(frames, count)], 行数, 坏行数)。"""
    rows: list[tuple[list[str], int]] = []
    bad = 0
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            total += 1
            head, sep, tail = line.rpartition(" ")
            if not sep or not tail.isdigit():
                bad += 1
                continue
            rows.append((head.split(";"), int(tail)))
    return rows, total, bad


def short(path: str, func: str) -> str:
    if not path:
        return ""
    tail = path.replace("\\", "/").split("/")[-2:]
    return "/".join(tail)


def main() -> int:
    ap = argparse.ArgumentParser(description="py-spy raw 折叠栈 → 函数级热点")
    ap.add_argument("profile", help="py-spy record -f raw 的输出文件")
    ap.add_argument("-n", "--top", type=int, default=12, help="每榜显示条数（默认 12）")
    ap.add_argument("--chains", type=int, default=2, help="每个头部叶帧展示的调用链条数（默认 2）")
    ap.add_argument("--min-share", type=float, default=0.0, help="低于该占比（0-1）不显示，默认不过滤")
    args = ap.parse_args()

    rows, total, bad = read_folded(args.profile)
    if not rows:
        print(f"没有可用折叠栈：{args.profile}（行数 {total}，无法解析 {bad}）", file=sys.stderr)
        return 1

    samples = sum(c for _, c in rows)
    leaf_count: collections.Counter[tuple[str, str, str]] = collections.Counter()
    frame_count: collections.Counter[tuple[str, str, str]] = collections.Counter()
    chains: dict[tuple[str, str, str], collections.Counter[str]] = collections.defaultdict(collections.Counter)

    for frames, count in rows:
        parsed = [parse_frame(f) for f in frames]
        leaf = parsed[-1]
        leaf_count[leaf] += count
        for fr in parsed:
            frame_count[fr] += count
        chain_sig = " ← ".join(
            f"{f[0]} [{short(f[1], f[0])}]" if f[1] else f[0] for f in reversed(parsed[-5:])
        )
        chains[leaf][chain_sig] += count

    print(f"样本 {samples} 个（栈 {len(rows)} 条，跳过错行 {bad}）← {args.profile}")
    print("\n== 1. 叶帧榜（CPU 停在哪）==")
    print(f"{'占比':>7}  {'样本':>7}  函数 (文件:行)")
    for (func, path, line), cnt in leaf_count.most_common(args.top):
        share = cnt / samples
        if share < args.min_share:
            continue
        loc = f" ({short(path, func)}:{line})" if path else ""
        print(f"{share*100:6.1f}%  {cnt:7d}  {func}{loc}")

    print("\n== 2. 帧榜（含父帧累计）==")
    print(f"{'占比':>7}  {'样本':>7}  函数 (文件:行)")
    for (func, path, line), cnt in frame_count.most_common(args.top):
        share = cnt / samples
        if share < args.min_share:
            continue
        loc = f" ({short(path, func)}:{line})" if path else ""
        print(f"{share*100:6.1f}%  {cnt:7d}  {func}{loc}")

    print("\n== 3. 头名叶帧调用链（回溯调用者）==")
    for (func, path, line), cnt in leaf_count.most_common(min(3, args.top)):
        share = cnt / samples
        if share < args.min_share:
            continue
        loc = f" ({short(path, func)}:{line})" if path else ""
        print(f"\n-- {func}{loc}  占 {share*100:.1f}%（{cnt} 样本）")
        for sig, c in chains[(func, path, line)].most_common(args.chains):
            print(f"   {c:6d}×  {sig}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
