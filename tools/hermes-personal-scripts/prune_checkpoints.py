# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Cron: 定期回收 Hermes checkpoint 存储（2026-10-18 改造）。

改造原因（本机 2026-10-18 实测）：
1. ``tools.checkpoint_pruning.store_lock`` 是**非阻塞**文件锁，agent 每完成一轮文件
   改动都会持锁做快照。原实现撞上锁就写一条 busy 警告并以 0 退出，看起来「正常」，
   实际是「一直忙 → 永远不清理 → 存储从 2G 上限涨到 9.1G 无人知晓」。现在改为轮询
   等待空闲（最多 WAIT_ROUNDS 轮），等不到就告警退出。
2. ``git gc`` 的预算是 ``HERMES_CHECKPOINT_TIMEOUT × 3``（默认 30×3＝90 秒），对 GB
   级库不够。本脚本在导入前把该变量提到 60（→ 180 秒预算）。
3. 退出码语义：0＝健康且无事可报（静默）；3＝有内容要通知（回收汇总、跳过、未完成）。
   不再用 0 冒充成功。
"""
import logging
import sys, os
import threading
import time

sys.path.insert(0, r"[本地路径]")

# 必须在导入前设置：_GIT_TIMEOUT 在 import 时求值（clamp 10..60）。
os.environ["HERMES_CHECKPOINT_TIMEOUT"] = "60"

from tools.checkpoint_maintenance import prune_checkpoints

WAIT_ROUNDS = 8        # 最多等 8 轮
WAIT_SECONDS = 60      # 每轮间隔 60 秒 ⇒ 最长等 8 分钟

# 上限与保留天数一律取 config.yaml 的 checkpoints.*，不再写死：
# 写死会与 CLI（hermes checkpoints prune）分歧——用户在配置里抬高上限后本任务仍按旧值判定，
# 于是永远报「超过上限」并以 3 退出，把真实结果掩盖成一个永不消失的告警。
def _checkpoints_config() -> dict:
    try:
        from hermes_cli.config import load_config
        section = (load_config() or {}).get("checkpoints") or {}
        return section if isinstance(section, dict) else {}
    except Exception:
        return {}


def _positive_int(value, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


# 共享存储的锁是有意的非阻塞锁，撞上并发持有者属「本轮没轮上」。现在改为等待重试，
# 只有等满 WAIT_ROUNDS 轮仍被占用才告警 —— 原实现直接静默跳过，正是 9.1G 无人知晓的成因。
_busy_warning = "Checkpoint maintenance stopped: checkpoint store is busy:"


class _MaintenanceLogCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.thread_id = threading.get_ident()
        self.messages = []

    def emit(self, record):
        if record.thread == self.thread_id:
            message = record.getMessage()
            if message.startswith(_busy_warning):
                self.messages.append(message)


def _prune_once(retention_days: int, max_total_size_mb: int):
    capture = _MaintenanceLogCapture()
    logger = logging.getLogger("tools.checkpoint_maintenance")
    logger.addHandler(capture)
    try:
        result = prune_checkpoints(
            retention_days=retention_days,
            delete_orphans=True,
            max_total_size_mb=max_total_size_mb,
        )
    finally:
        logger.removeHandler(capture)
    return result, capture.messages


def _busy_only(result: dict, messages: list) -> bool:
    return bool(
        result.get("errors") == 1
        and result.get("scanned") == 0
        and result.get("deleted_orphan") == 0
        and result.get("deleted_stale") == 0
        and result.get("bytes_freed") == 0
        and messages
    )


def main() -> int:
    section = _checkpoints_config()
    retention_days = _positive_int(section.get("retention_days"), 7)
    max_total_size_mb = _positive_int(section.get("max_total_size_mb"), 500)

    result: dict = {}
    for attempt in range(1, WAIT_ROUNDS + 1):
        result, messages = _prune_once(retention_days, max_total_size_mb)
        if _busy_only(result, messages):
            if attempt < WAIT_ROUNDS:
                time.sleep(WAIT_SECONDS)   # agent 快照通常在几十秒内结束，等下一轮
                continue
            print("[prune_checkpoints] 连续 %d 轮（约 %d 分钟）存储都被占用，本轮未执行；"
                  "若持续出现说明快照一直没停过，需要人工看一眼。"
                  % (WAIT_ROUNDS, WAIT_ROUNDS * WAIT_SECONDS // 60))
            return 3
        break

    freed_mb = (result.get("bytes_freed") or 0) / 1024 / 1024
    summary = ("Scanned: %s, Orphan: %s, Stale: %s, Freed: %.1f MB "
               "(cap %d MB / retention %d 天，取自 config.yaml)"
               % (result.get("scanned"), result.get("deleted_orphan"),
                  result.get("deleted_stale"), freed_mb, max_total_size_mb, retention_days))

    # 清理过程中出现其他错误＝本次清理不完整：不得以 0 退出冒充成功。
    if result.get("errors"):
        print("[prune_checkpoints] 清理不完整：%s 处错误，未处理项仍留在磁盘 —— %s"
              % (result["errors"], summary))
        return 3

    # 真回收了才报一句；无事可报保持静默（no_agent 任务的健康态）。
    if freed_mb >= 500 or result.get("deleted_stale") or result.get("deleted_orphan"):
        print("[prune_checkpoints] 已回收：%s" % summary)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
