# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Cron 入口：月度快照备份（no_agent 模式，本脚本 stdout 即任务输出）。

实际备份逻辑在 system-maintenance 技能的脚本里，此处仅作 cron 挂载点：
- 技能脚本: skills/devops/system-maintenance/scripts/backup_hermes_snapshot.py
- 输出位置: [本地路径]
- 手动入口: 桌面 Hermes-月度备份.cmd
"""
import runpy

TARGET = r'[本地路径]'

if __name__ == '__main__':
    runpy.run_path(TARGET, run_name='__main__')
