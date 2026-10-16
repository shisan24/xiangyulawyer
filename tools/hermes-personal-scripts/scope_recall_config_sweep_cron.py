#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""cron 包装：按保留策略隔离 scope-recall worker 临时配置（等价于 --apply）。

单独一个包装文件，是因为 cron 任务的 script 字段只接受脚本路径、不传参数。
真正逻辑在 scope_recall_config_sweep.py；无残留或无需隔离时保持安静（空输出＝不通知）。
"""

import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).with_name("scope_recall_config_sweep.py")
sys.argv = [str(TARGET), "--apply"]
runpy.run_path(str(TARGET), run_name="__main__")
