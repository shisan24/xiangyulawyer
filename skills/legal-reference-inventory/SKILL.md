---
name: legal-reference-inventory
description: Catalog legal reference libraries with OCR status tracking.
version: 1.0.0
author: xiangyulawyer
source: https://github.com/shisan24/xiangyulawyer
---

> © 2026 xiangyulawyer（github.com/shisan24/xiangyulawyer）· 本技能由作者从执业实务中提炼，公开版本仅保留方法框架与通用清单，不含任何个案信息。转载或引用请署名。

# legal-reference-inventory

**适用场景**：Catalog legal reference libraries with OCR status tracking.

# 法律参考资料目录盘点
盘点法律参考资料目录：对照原始 PDF 与 OCR 产物，输出结构化清单（已完成 / 中间产物 / 待处理），识别重复文件和 OCR 缺口。不处理 OCR 质量评估、不启动新 OCR 任务。

## Prerequisites
- 目录结构约定：原始 PDF 在根目录或子目录，OCR 结果在 `ocr结果/` 下
- `search_files` 可访问目标路径

## How to Run
通过 `search_files` 工具探索目录结构，然后通过 `terminal` 工具用 `ls` 获取精确子目录列表。分三步：粗扫 → 精列 → 结构化输出。

### 第一步：粗扫顶层
search_files(path="目标目录", target="files", pattern="*", limit=100)

### 第二步：精列 OCR 结果
terminal(command='ls -la "目标目录/ocr结果/"')
获取 OCR 产物子目录完整列表，区分已完成 OCR（有 markdown 的目录）和中间产物（`_split_` 前缀目录）。

## Pitfalls
- OCR 结果目录命名与原始 PDF 不完全一致（如 `合同起草审查_公司卷` vs `合同起草审查指南公司卷第二版2023.pdf`），需要人工对应
- **外部来源（分享链接/转卖资料包）入库先核版本年代再核内容**：规则类文本出现“发审委”“创业板首批试点”一类表述即属核准制时代的旧版，只能作框架参考、不得作为现行依据；同时标注来源渠道与授权状态不明（转卖扫描件多为二次搬运），正式项目引用前先核出处

## Verification
确认输出的清单中：每个原始 PDF 都有对应的 OCR 状态（已完成/中间产物/待处理），无遗漏。盘点报告末尾必须附核验回执（source_sha256 + OCR 状态映射表）。
