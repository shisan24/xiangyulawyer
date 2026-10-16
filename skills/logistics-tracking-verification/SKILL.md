---
name: logistics-tracking-verification
description: 快递/EMS面单核验与轨迹查询。触发：核验快递面单、查EMS签收记录、送达证据核验。
version: 1.0.0
author: xiangyulawyer
source: https://github.com/shisan24/xiangyulawyer
---

> © 2026 xiangyulawyer（github.com/shisan24/xiangyulawyer）· 本技能由作者从执业实务中提炼，公开版本仅保留方法框架与通用清单，不含任何个案信息。转载或引用请署名。

# logistics-tracking-verification

**适用场景**：快递/EMS面单核验与轨迹查询。触发：核验快递面单、查EMS签收记录、送达证据核验。

## 一、面单图像读取（已验证）
1. **cv2 中文路径必失败**：`cv2.imread('中文路径.jpg')` 报 can't open/read。必须 `np.fromfile(path, dtype=np.uint8)` + `cv2.imdecode(buf, cv2.IMREAD_COLOR)`。

### 执照/证件扫描件的形近字 OCR 误读（送达地址核实的直接坑）
1. 手写签名识别（池→沈、任→伍）一律标"疑为X误读，需人工核对"，不写死进文书
