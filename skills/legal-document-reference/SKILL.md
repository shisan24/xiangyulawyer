---
name: legal-document-reference
description: 法律文书参考知识——API参数、格式规范、工作流校正。触发：文书格式疑问。
version: 1.0.0
author: xiangyulawyer
source: https://github.com/shisan24/xiangyulawyer
---

> © 2026 xiangyulawyer（github.com/shisan24/xiangyulawyer）· 本技能由作者从执业实务中提炼，公开版本仅保留方法框架与通用清单，不含任何个案信息。转载或引用请署名。

# legal-document-reference

**适用场景**：法律文书参考知识——API参数、格式规范、工作流校正。触发：文书格式疑问。

### 批量候选扫描与归属核验方法
- .doc 老格式 python-docx 读不了（`Package not found`），假 .doc（实为 OOXML）报 `themeManager` 错误；损坏 docx 报 Bad CRC——这些直接跳过，不阻塞入库流程
- 表格内容 paragraphs 抓不到（法审意见单正文在表格里），判断归属/内容时须查 tables

### Qwen 3.7-max
- `enable_thinking`：可选（非 OpenAI 标准参数）

### 写作矫正记录
| 6 | 986条善意得利人 | DS | 不改 | 边缘风险，不影响本金 |
**核心原则——什么不该改：**
- 时效论证框架不动（法庭上的可信度重于措辞精度）

### 地方文件检索路径（关键）
- **语义检索（law_vector_search）对地方文件覆盖差**：查"当地 七通一平 土地出让"返回的全是中央文件。地方文件必须走 **fg_search 关键词+地域过滤**：`dy` 传省名短词（"当地"），`keyword` 用实务术语原词（"七通一平"/"基础设施配套费"），`sxx="现行有效"`
