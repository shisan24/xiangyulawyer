---
name: contract-transfer-agreement
description: 三方合同转让协议起草：权利义务/债权/租金债权转让、合同地位变更。触发：三方转让协议、合同地位变更。
version: 1.0.0
author: xiangyulawyer
source: https://github.com/shisan24/xiangyulawyer
---

> © 2026 xiangyulawyer（github.com/shisan24/xiangyulawyer）· 本技能由作者从执业实务中提炼，公开版本仅保留方法框架与通用清单，不含任何个案信息。转载或引用请署名。

# contract-transfer-agreement

**适用场景**：三方合同转让协议起草：权利义务/债权/租金债权转让、合同地位变更。触发：三方转让协议、合同地位变更。

## 第一步：确认转让结构（最关键，勿预设）
| 结构 | 法律依据 | 效果 |

## 第三步：条款设计要点
1. **通知效力**：三方签署即构成546条债权转让通知，避免"未通知对债务人不生效"风险。
2. **争议解决**：默认跟主合同（如租赁标的所在地法院），交付时提示可改（如集团内部归集可改受让方所在地）。

## 第五步：格式与交付
- 生成后 python-docx 读回逐段验证 + 格式检查（空段/引号/破折号/字体四元/纸型）
