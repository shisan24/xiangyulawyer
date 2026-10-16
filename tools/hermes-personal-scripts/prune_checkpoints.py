# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Cron: prune Hermes checkpoints to enforce max_total_size_mb."""
import logging
import sys, os
import threading
sys.path.insert(0, r"[本地路径]")

from tools.checkpoint_maintenance import prune_checkpoints

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


_section = _checkpoints_config()
retention_days = _positive_int(_section.get("retention_days"), 7)
max_total_size_mb = _positive_int(_section.get("max_total_size_mb"), 500)

# The shared store has an intentional non-blocking lock. A concurrent owner is
# a clean defer: capture only the precise busy-lock warning and avoid classifying
# that zero-work result as a failed maintenance run. Other errors still fail.
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


_capture = _MaintenanceLogCapture()
_maintenance_logger = logging.getLogger("tools.checkpoint_maintenance")
_maintenance_logger.addHandler(_capture)
try:
    result = prune_checkpoints(
        retention_days=retention_days,
        delete_orphans=True,
        max_total_size_mb=max_total_size_mb,
    )
finally:
    _maintenance_logger.removeHandler(_capture)

print(f"Scanned: {result['scanned']}, Orphan: {result['deleted_orphan']}, "
      f"Stale: {result['deleted_stale']}, Errors: {result['errors']}, "
      f"Freed: {result['bytes_freed']/1024/1024:.1f} MB "
      f"(cap {max_total_size_mb} MB / retention {retention_days} 天，取自 config.yaml)")

_busy_only_result = (
    result.get("errors") == 1
    and result.get("scanned") == 0
    and result.get("deleted_orphan") == 0
    and result.get("deleted_stale") == 0
    and result.get("bytes_freed") == 0
)
if _busy_only_result and any(message.startswith(_busy_warning) for message in _capture.messages):
    print("[prune_checkpoints] 本轮跳过：共享存储正在被其他进程使用；下次周期重试。")
    sys.exit(0)

# 清理过程中出现其他错误＝本次清理不完整：不得以 0 退出冒充成功。
if result.get("errors"):
    print(f"[prune_checkpoints] 清理不完整：{result['errors']} 处错误，未处理项仍留在磁盘", file=sys.stderr)
    sys.exit(3)
