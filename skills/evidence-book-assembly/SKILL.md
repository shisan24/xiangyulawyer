---
name: evidence-book-assembly
description: 证据册/成册PDF组装与重组——抽页、打印页码、宽表重导、页码顺延、终验。触发：证据册、成册、补页、重组证据。
version: 1.0.0
author: xiangyulawyer
source: https://github.com/shisan24/xiangyulawyer
---

> © 2026 xiangyulawyer（github.com/shisan24/xiangyulawyer）· 本技能由作者从执业实务中提炼，公开版本仅保留方法框架与通用清单，不含任何个案信息。转载或引用请署名。

# evidence-book-assembly

**适用场景**：证据册/成册PDF组装与重组——抽页、打印页码、宽表重导、页码顺延、终验。触发：证据册、成册、补页、重组证据。

### 从源文件组装（首次/全量重排）
1. 收集证据源文件（PDF/JPG，按证据顺序）

### 从混合源件成册（报送用：docx/xls/PDF → 全册连续页码 + 目录页码区段）
1. **一遍合并、同步记区间**：按目录项顺序合并，合并前取 `part.page_count`，`start = out.page_count + 1`，`insert_pdf(part)` 后 `end = out.page_count`——合并完成即得全部项的页码区间，不必事后翻册数页。

### 步骤
1. **按档案结构选页**：
   - 监理月报标准结构：卷皮 → 卷内目录 → **01表（完成任务对比/工程进度）→ 02表（工程质量）→ 03表（计量支付）→ 04表（指令）**，A/B 标段各 1 页——同格式各卷页序一致，第一卷确认后直接套用

## 终验清单（每版必跑）
1. **页码 1-N 连续**：`re.findall(r'第\s*(\d+)\s*页', page_text)` 取最后一个匹配（页面可能带原件自带的档案编页"第172页"，须用我们打印的页码；SimHei 字体可作区分）
2. 残留检查：旧页码字符串清零、破折号/ASCII 引号（对外文书）
3. 验证脚本的说明表位置**不能猜**——从"无打印页码"或内容关键词判断，猜位置会导致页码连续性误报（V8 验证两次猜错 desc_pos，实际页码是对的）
