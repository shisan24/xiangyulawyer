# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Cron：额度日报（每早 08:00）——以 --daily 模式调用看门狗脚本。

脚本本体与阈值配置：
  scripts/provider_limits_watchdog.py
  plugins/provider-limits/state/config.json
"""
import runpy
import sys
from pathlib import Path

sys.argv = [sys.argv[0], "--daily"]
runpy.run_path(str(Path(__file__).with_name("provider_limits_watchdog.py")), run_name="__main__")
