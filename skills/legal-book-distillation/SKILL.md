---
name: legal-book-distillation
description: 拆法律实务书/实务档案→升级现有技能（不新建技能）。触发：拆法律书、拆档案/原档、继续拆（法律）、书→技能映射。
version: 1.0.0
author: xiangyulawyer
source: https://github.com/shisan24/xiangyulawyer
---

> © 2026 xiangyulawyer（github.com/shisan24/xiangyulawyer）· 本技能由作者从执业实务中提炼，公开版本仅保留方法框架与通用清单，不含任何个案信息。转载或引用请署名。

# legal-book-distillation

**适用场景**：拆法律实务书/实务档案→升级现有技能（不新建技能）。触发：拆法律书、拆档案/原档、继续拆（法律）、书→技能映射。

### 0. 侦察（每本新书）
1. 检查 `ocr结果/` 是否已有拆分（`_split_` 前缀目录 = 百页一册的 PDF 分块 c_0000-0099.pdf，可直接用作分块源）。

### 2. 阶段 1 — 5 提取器并行
framework / principle / case / counter-example / glossary 五个提取器（prompt 在 cangjie-skill 的 `extractors/`）。本环境 delegate_task 并行上限 3，分两批（3+2）或串行降级。**大书（>20 个 part 文件）必须分组**：每任务 13-14 个 part 文件（600s 硬上限内稳定值，见 Pitfalls 超时治理条），全书按 part 数 ÷ 14 分组，5 提取器 × 组数 = 总任务数，3 个并行交错分批部署（如 3 组 × 5 类 = 15 任务分 5 批）。任务描述写死文件范围 + 每文件最多 2 次调用。

### 4. 映射阶段（替代 cangjie 阶段 2-4）
- 直接可用清单 → contract-review 系技能（methodology / delivery）
- 风险维度新增 → 甲方利益审查技能
- 决策框架 → legal-opinion-delivery（"给建议而非只提示风险"）
- 语言规则 → 合同语言审查
- 流程方法 → 审查流程标准化

## Verification
- 映射方案交付前：逐技能核对"该技能现在有什么、缺什么、加什么"，不写空泛建议
