---
name: legal-party-relationship-diagram
description: 诉讼当事人关系图制作（SVG/HTML）。触发：做关系图、当事人关系图。
version: 1.0.0
author: xiangyulawyer
source: https://github.com/shisan24/xiangyulawyer
---

> © 2026 xiangyulawyer（github.com/shisan24/xiangyulawyer）· 本技能由作者从执业实务中提炼，公开版本仅保留方法框架与通用清单，不含任何个案信息。转载或引用请署名。

# legal-party-relationship-diagram

**适用场景**：诉讼当事人关系图制作（SVG/HTML）。触发：做关系图、当事人关系图。

### 忠实性（照既有材料重绘时）
- **不乱序**：按源语义顺序（日期→箭头→阅读顺序→阶段）；源顺序与时间顺序冲突时不静默选一个，图注记录两种读法。
- **不越权论证**：节点与连线只放事实与状态，不放论证性判断（不用“本院认为”“构成违约”这类表述）。

### 视觉纪律
- 单一强调色（建议深红系）；全图强调不超过 2 处；不得再添第二强调色（如蓝色），否则语义失效。

## Pitfalls
- 被告序号必须标全（被告一/二/三/四），法院文书惯例
