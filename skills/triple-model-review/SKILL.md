---
name: triple-model-review
description: 三方交叉复核——DeepSeek+Kimi+Qwen终稿前并行审查。触发：文书终稿复核。
version: 1.0.0
author: xiangyulawyer
source: https://github.com/shisan24/xiangyulawyer
---

> © 2026 xiangyulawyer（github.com/shisan24/xiangyulawyer）· 本技能由作者从执业实务中提炼，公开版本仅保留方法框架与通用清单，不含任何个案信息。转载或引用请署名。

# triple-model-review

**适用场景**：三方交叉复核——DeepSeek+Kimi+Qwen终稿前并行审查。触发：文书终稿复核。

适用范围：三方交叉复核——DeepSeek+Kimi+Qwen终稿前并行审查。触发：文书终稿复核。
开始时按请求定位一个具体操作。先读下方章节索引，打开包含该操作的完整章节，再使用现有脚本、参考文件和资源；不能仅凭本短入口猜测参数或跳过原方法中的必要校验。

## 详细方法
任一模型腿无法完成（余额不足、账户停用、超时）时，按 part-005 备用通道补位（GLM／OpenRouter／Codex CLI），如实标注实际完成的腿与替代模型；不得以单腿或补位结果冒称原计划三方通过。
