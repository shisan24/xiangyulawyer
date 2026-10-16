#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""cron 包装：运行技能内的磁盘清理 sweeper（单源，逻辑不复制到本目录）。

为什么用包装：调度器要求 script 位于 HERMES_HOME/scripts/，而 sweeper 的实现与
sweep-config.json 是 windows-disk-space-cleanup 技能的资产（判据与脚本同源，避免双份漂移）。
本文件只负责转调，改动请改技能内脚本与其配置。

行为：cron 缺省强制预演，即使配置 mode=apply 也不自动搬。
交互调用显式 --apply 才允许真搬；--dry-run/--preview 的优先级最高。
预演只写 D 盘报告，不搬源文件。跨盘真搬会在校验后删源，不清空待删除区。
"""

import os
import runpy
import sys

HOME = os.environ.get("HERMES_HOME") or os.path.join(
    os.environ.get("LOCALAPPDATA", r"[本地路径]"), "hermes")
TARGET = os.path.join(HOME, "skills", "devops", "windows-disk-space-cleanup", "scripts", "disk_sweep.py")

if not os.path.exists(TARGET):
    print("磁盘清理 sweeper 不存在，任务未执行：%s" % TARGET)
    raise SystemExit(2)

forwarded = sys.argv[1:]
if "--apply" not in forwarded:
    forwarded = forwarded + ["--dry-run"]
sys.argv = [TARGET] + forwarded
runpy.run_path(TARGET, run_name="__main__")
