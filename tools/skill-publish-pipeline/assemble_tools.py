# -*- coding: utf-8 -*-
"""组装「自建工具与插件」公开产物：布局 tools/<组>/、plugins/<名>/ + README + 注水印。
用法: python assemble_tools.py <framed_dir> <out_dir> <units.json> <log.md>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_repo import watermark  # noqa: E402

TOOLS_README = """# 自建工具

作者本人在 Windows + Hermes 桌面端环境中长期使用的自建工具脚本。

| 目录 | 用途 |
|---|---|
| `skill-publish-pipeline/` | 技能/资产对外发布管线：来源核验 → 标识符清洗 → 实体清洗 → 框架化 → 注水印 → 逐单元提交 → 回读复扫 |
| `hermes-personal-scripts/` | Hermes 本机运维脚本：健康检查、看门狗、探针、待办与期限扫描、会话清理等 |
| `tang-assistant/` | 法律助手配置包的安装与运维脚本（体检、备份、更新检查、诊断） |
| `cangjie-pipeline/` | 拆书流水线脚本（OCR 分窗、章节切分、候选提取、合并与校验） |
| `mineru/` | MinerU 文档解析工具链的安装与批量调用 |

## 版权与使用条件

- **许可：CC BY-NC 4.0**（署名—非商业性使用 4.0 国际），全文见仓库根目录 [LICENSE](../LICENSE)。
- 转载、引用、二次分发请**保留署名与来源链接**；商业使用需另行取得作者授权。
- 脚本按现状提供，**不含任何保证**；其中与本机路径、账户、私有服务相关的部分需自行改造后使用。
- 部分脚本的名单类数据（主体/当事人/律所/本机标识）已外置为模板，公开版不含实际名单。

> 本目录不含当事人、客户或本机的识别信息；方法描述中保留必要的裁判规则、地域与机构示例。如你认为某处仍涉及你的信息，请提出，我们会立即处理。
"""

PLUGINS_README = """# 自建插件

作者为本机 Hermes 桌面端开发的插件。均为**自用工具**，依赖本机环境与本人配置，公开仅作参考。

| 插件 | 用途 |
|---|---|
| `lawyer-workbench/` | 律师工作台：右侧面板 + 桌面入口，案件接续、文书与台账操作的界面层 |
| `digest-board/` | 摘要看板：把巡检/日报类产出归集到面板查看 |
| `memory-dashboard/` | 记忆看板：MEMORY.md / USER.md 占用与记忆运行时健康 |
| `provider-limits/` | 额度与余额看板：多账户额度、状态栏常显与无 token 告警看门狗 |

## 版权与使用条件

- **许可：CC BY-NC 4.0**（署名—非商业性使用 4.0 国际），全文见仓库根目录 [LICENSE](../LICENSE)。
- 转载、引用、二次分发请**保留署名与来源链接**；商业使用需另行取得作者授权。
- 插件依赖本机路径与个人账户配置，直接使用需先改造；作者不对适用性作任何保证。

> 本目录不含当事人、客户或本机的识别信息；方法描述中保留必要的机构与地域示例。
"""


def main():
    framed, out, units_file, logp = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    units = json.load(open(units_file, encoding="utf-8"))
    log = ["| 单元 | 文件数 | 落盘路径 |", "|---|---|---|"]
    total = 0
    for u in units:
        name = u["name"]
        src = os.path.join(framed, name.replace("/", "__"))
        if not os.path.isdir(src):
            log.append(f"| {name} | 0 | 缺产物，跳过 |")
            continue
        dst = os.path.join(out, *name.split("/"))
        n = 0
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                sp = os.path.join(root, f)
                rel = os.path.relpath(sp, src)
                dp = os.path.join(dst, rel)
                os.makedirs(os.path.dirname(dp), exist_ok=True)
                with open(sp, "rb") as fh:
                    data = fh.read()
                open(dp, "wb").write(data)
                n += 1
        total += n
        log.append(f"| {name} | {n} | `{name}/` |")
    os.makedirs(os.path.join(out, "tools"), exist_ok=True)
    os.makedirs(os.path.join(out, "plugins"), exist_ok=True)
    open(os.path.join(out, "tools", "README.md"), "w", encoding="utf-8",
         newline="\n").write(TOOLS_README)
    open(os.path.join(out, "plugins", "README.md"), "w", encoding="utf-8",
         newline="\n").write(PLUGINS_README)
    w = 0
    for root, dirs, files in os.walk(out):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in files:
            if watermark(os.path.join(root, f), "xiangyulawyer"):
                w += 1
    open(logp, "w", encoding="utf-8").write("\n".join(log) + "\n")
    print(f"共 {total} 个文件落盘到 {out}；注水印 {w} 个")
    print("\n".join(log[2:]))


if __name__ == "__main__":
    main()
