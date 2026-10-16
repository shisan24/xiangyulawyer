---
name: legal-workbench-kanban-integration
description: integrating a legal workbench with Hermes Kanban.
version: 1.0.0
author: xiangyulawyer
source: https://github.com/shisan24/xiangyulawyer
---

> © 2026 xiangyulawyer（github.com/shisan24/xiangyulawyer）· 本技能由作者从执业实务中提炼，公开版本仅保留方法框架与通用清单，不含任何个案信息。转载或引用请署名。

# legal-workbench-kanban-integration

**适用场景**：integrating a legal workbench with Hermes Kanban.

## 永久规则
1. **真实案件使用独立 Kanban 板**：先核对当前板，再建立专用板；不得把法律案件写入 `demo`、测试板或其他业务板。适配层应显式指定板 slug，不依赖当前活动板。
2. **先只读、后受控写入**：第一阶段只读取案件索引和 `hermes kanban list --json`；确认主体、路径、版本和任务关联稳定后，才设计建立任务、评论或状态变更。任何写入都必须有明确授权和可回读验证。
3. **任务负责人必须来自实际 Profile**：先运行 `hermes profile list` 或等价查询，再分配任务；不猜测 Profile 名称，不把没有法律授权或未经确认的 Profile 作为默认负责人。
4. **交付必须验证实际效果**：至少通过源代码语法检查、索引格式检查、API 健康检查、浏览器 DOM/控制台检查、关键交互检查和首屏截图检查。报告实际登记数量、Kanban 板、未解决项和服务持久化状态，不把“文件已写入”当成“接入成功”。

## 标准流程
   - 明确哪些案件目录可以接入、哪些目录明确排除。
1. **核对 Hermes 状态**
   - 通过 Hermes CLI JSON 接口读取指定 board，优先使用公开 CLI/JSON，不直接依赖内部 SQLite 表结构。
   - 只读阶段的建立事项、完成任务等按钮必须提示尚未写入，不能形成假成功。
2. **执行交付验收**
   - Python 适配层和登记脚本编译通过；JSON 索引格式通过；HTML 内嵌 JavaScript 用 Node 语法检查。
   - 请求 `/api/health` 和聚合端点，核对 board、案件数、任务数、状态计数及错误数组。
   - 浏览器检查连接提示、空状态、模式筛选、登记弹窗、只读提交行为和控制台错误。
