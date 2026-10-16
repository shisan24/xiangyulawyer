---
name: government-filing-review
description: 审查修订当事人起草的对外公文与商务函件（请示/报告/函/催告·整改·解除通知）。触发：客户发来对外函件要审查或修订。
version: 1.0.0
author: xiangyulawyer
source: https://github.com/shisan24/xiangyulawyer
---

> © 2026 xiangyulawyer（github.com/shisan24/xiangyulawyer）· 本技能由作者从执业实务中提炼，公开版本仅保留方法框架与通用清单，不含任何个案信息。转载或引用请署名。

# government-filing-review

**适用场景**：审查修订当事人起草的对外公文与商务函件（请示/报告/函/催告·整改·解除通知）。触发：客户发来对外函件要审查或修订。

## 二、铁律：引用原文逐字核对
- 扫描件流程：pymupdf 转 PNG（dpi 140-160）→ vision_analyze 逐页读全文；关键字段（备注原文、批准文号、注册分类、持有人、有效期）逐项记录并与文书核对

## 三、法条核实（引用前必做）
- 元典 `yuandian_rh_ft_search`：fgmc（法规名）+ keyword（法条关键词）+ sxx=现行有效，逐条核对引用内容与条文号
- 大部头 PDF（如《专利审查指南》613页）：pymupdf 全文检索关键词（"上市许可之日"），确认有无相关定义/条款

## 六、python-docx run 级修改陷阱（在原文件上修订时）
1. **Run 包装对象比较陷阱**：`p.runs` 每次访问生成新的 Run 对象，`r is not carrier` 恒为 True，会把载体 run 也删掉（段落变空且难发现）。**必须比较 `r._element is not carrier._element`**
2. **多 run 段落逐 run 赋值会文本叠加**：用 set_text 模式——新文本写入载体 run（优先选 eastAsia=目标字体如方正仿宋_GB2312 的 run），删除其余 run 的 `_element`

### 双模式判定
| formal-draft（正式发文草稿）| 通用正式党政机关公文草稿/排版稿 | 只生成草稿或排版稿，不表示已签发；文号由机关流程分配、印章由正式用印流程加盖，不伪造 |

### 校验三态输出
生成/修改后结构校验（python-docx 读回，见第六节），结果区分三态：
- `fail`：有失败项——**不得声称版式通过**
- `unverified`：无法确认项——**必须逐项披露**
正式交付前仍需在 Microsoft Word 中核对分页、字体替换和域更新（LibreOffice/WPS 只作兼容性参考，替换字体度量不同连页数都会变）。
