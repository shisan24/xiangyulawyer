---
name: court-eservice-intake
description: 收到法院送达短信/链接、起诉状、传票时：浏览器直读、签收红线、取回清单、关联检索。
version: 1.0.0
author: xiangyulawyer
source: https://github.com/shisan24/xiangyulawyer
---

> © 2026 xiangyulawyer（github.com/shisan24/xiangyulawyer）· 本技能由作者从执业实务中提炼，公开版本仅保留方法框架与通用清单，不含任何个案信息。转载或引用请署名。

# court-eservice-intake

**适用场景**：收到法院送达短信/链接、起诉状、传票时：浏览器直读、签收红线、取回清单、关联检索。

## 一、送达链接可以直接看——不要报告“打不开”
- 用真实浏览器加载（playwright 工具）：`init_browser(url)` → `get_text_snapshot` / `get_screenshot`（结构复杂时用 `get_full_snapshot`）；

## 四、材料到手先做关联检索，再问人
**数字先复算**：诉请金额、利息（基数×利率×天数，核对 360/365 天基数口径与起止日实际天数）、受理费、保全费先用代码复算再进结论，不心算；同案材料出现多个版本/重发件时先比对是否同一文本（哈希或文本对比），避免把重发件当新版本、把不同版本当一致。
