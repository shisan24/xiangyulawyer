<!-- © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名 -->

# memory-dashboard（记忆看板）

Hermes 桌面插件：右侧栏「记忆看板」页签 + 状态栏「MEM n%」芯片。
显示 MEMORY.md / USER.md 占用与 scope-recall 运行时健康。

## 两件套与生效方式

| 半边 | 文件 | 生效方式 |
|---|---|---|
| 前端 | `desktop-plugins/memory-dashboard/plugin.js` | 保存即热载（Ctrl+K → Reload desktop plugins 可强制） |
| 后端 | `plugins/memory-dashboard/dashboard/plugin_api.py` | 挂载于 `/api/plugins/memory-dashboard`；**改动需重启 App/后端进程**（启动时导入一次） |

## 显示内容（2026-09-29 v2）

- MEMORY.md / USER.md：字符数/配额、条数（§ 块数）、修改时间。**配额读 `HERMES_HOME/config.yaml` 的 `memory.memory_char_limit` / `user_char_limit`**（与 `scripts/memory_preflight.py` 的 `load_limits()` 同源；config 读不到才回落到 `LIMITS_DEFAULT`）——脚本内不得写死，否则配置改过之后看板仍显示旧配额。
- scope-recall（3.2.0 / schema 1110，v3.x 库）：
  - **worker**：最后成功时间（读 `scope-recall/runtime-worker-status.json`；绿 <24h，橙 <72h，红 更久/缺失）
  - **记忆** = `claims` 活跃条数（新库的"记忆条目"）
  - **待处理** = `work_items.state='pending'`；**失败** = `state='failed'`
  - **来源** = `source_events` 总数；**24h** = 近 24 小时新增（UTC 截断比较）
  - **最近捕获** = `MAX(recorded_at)`；**epoch** = `instance_meta.memory_epoch`；**DB** = 库文件大小
- 旧版（≤2026-08）读取的 `memories` / `journal_entries` / `journal_digest_runs` 表在 v3 已不存在——v2 已全部替换；读不到时显示"读取失败"与恢复提示。

## 接口

- `GET /stats` → `{ memory, scope_recall, generated_at }`
- `GET /memories?limit=20` → 最近 claims（claim_id / subject / predicate / kind）

## 变更记录

- 2026-10-14：配额改为读 `config.yaml` 的 `memory.memory_char_limit` / `user_char_limit`（此前写死 6000/3000，配置 10-11 提到 10000/6000 后看板仍显示旧配额）。改前备份：`plugin_api.py.bak-limits-20261014`。
- 2026-09-29：scope-recall 段按 v3.x 库结构重写（此前读旧表报 `no such table: memories`，界面显示 undefined）。改前备份：`plugin_api.py.bak-scope3x-20260929-1203`、`plugin.js.bak-scope3x-20260929-1203`。
