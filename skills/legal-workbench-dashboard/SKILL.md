---
name: legal-workbench-dashboard
description: building lawyer dashboards. Apply legal workflow.
version: 1.0.0
author: xiangyulawyer
source: https://github.com/shisan24/xiangyulawyer
---

> © 2026 xiangyulawyer（github.com/shisan24/xiangyulawyer）· 本技能由作者从执业实务中提炼，公开版本仅保留方法框架与通用清单，不含任何个案信息。转载或引用请署名。

# legal-workbench-dashboard

**适用场景**：building lawyer dashboards. Apply legal workflow.

## 适用范围
- 不用于替代案件分析、法律意见或正式诉讼文书；看板展示的是办理状态和来源边界，不是法律结论。

## 现行形态与设计取舍（2026-09 重新设计）
- **首屏要能回答“今天先动哪个案子”**：只给清单与计数不够。用面板已有数据合成判断（期限倒计时／记录停滞天数／未办件数），每条判断都要写明理由，不做无依据的高亮。

### 5. 使用法律工作语境的界面文案
文案应说明依据和状态，不制造结论。例如使用“期限待核实”“来源文件待绑定”“材料阅核范围未建立”，不要写“已逾期”“已完成核查”或“可以继续”，除非相应事实和核验记录已经绑定。

### 6. 交互必须服务于办理流程
交互状态要与文案一致。新增的本地示例事项不得冒充已经写入案件台账；真实数据写入必须另有明确的来源和回读验证。

### 7. 视觉和代码验收
- 先检查首屏信息层级，再检查响应式布局、焦点状态、对比度、点击区域和长中文文案换行。
- 指标卡必须保持同一层级。计数与状态文本不能混用同一视觉规则；状态文字应使用独立的字号和类名。
- 不用渐变、图标和虚构 KPI 填充空白；每个模块都必须对应一个办理判断或下一项实际工作。

### 8. 交付前必须做真实验证
按以下顺序验收，不以“文件已经写入”替代验证：
1. 确认目标 HTML 或项目文件存在，读取最终版本而不是只看编辑器内存。
2. 用浏览器打开页面，检查标题、首屏标题、关键控件和控制台错误；至少截图检查一个主要视口。
3. 实际点击主入口，验证登记弹窗可以打开和关闭；实际切换一个工作模式，验证筛选结果数量和显示状态符合预期。
4. 界面上算出来的信号（决策条、排序、标签、倒计时）交付前用**真实数据复演**一遍：在 Python 里按同一阈值跑真实 payload，确认既不为空也不泛滥（例如“记录停滞”在 14 个事项上应命中 2–3 条）。日期只认 `YYYY-MM-DD`；`约 2027-03 上旬` 这类文本一律返回空值、不折算天数、不推定逾期——宁可少显示一条判断，不可给错天数。阈值集中成一个具名常量（如 `STALE_DAYS`），便于一句话调档；调档必须基于真实数据的复演结果，不凭手感。
最终报告分开写：已交付成果、已验证项目、尚未接入或未解决事项、下一步建议。没有真实数据接入时，明确写明原型边界。

## 桌面插件交付（在 Hermes 面板内显示）
- 生效方式分两种：只改 plugin.js 内容可热加载（Ctrl+K → **Reload desktop plugins**，不用重启）；但**新增带 Python 后端的插件或改 `plugins.enabled` 后必须完全退出并重开桌面 app**——gateway 只在启动时挂载 `/api/plugins/<id>` 并读取 enabled 白名单，热加载不会注册新后端，不重启就会“调不出来”。
- **桌面半身只认一个路径：`$HERMES_HOME/desktop-plugins/<id>/plugin.js`**（Hermes 桌面端的加载根，见 `hermes-agent/apps/desktop/src/plugins/README.md` 与 `website/docs/user-guide/desktop.md` 的 desktop-plugins 根与迁移说明）。仓里另有 `plugins/<id>/desktop/plugin.js` 同名副本，多为早期形态遗留、长期停在旧版——**判断“某功能到底有没有实现”之前，先 `ls --time-style=full-iso` 与 `sha256sum` 比这两处，以 mtime 新且被真正加载的那一份为准**。曾按旧副本读代码，误判“决策条与推荐逻辑根本不存在”。改错文件的表现是“改了不生效”，且不报任何错。
- **外部代理交来的核查报告先核时间点与哈希再动手**（完整方法见 `external-plan-verification`）：本页只记工作台特有的两处——报告自带的 `第二轮现场结构核查.json` 一类文件里有逐文件 sha256，是判定“它看的是哪一版”最快的一手证据；报告里的合成场景回放不能换算成真实错误率。
- ESM/JSX 语法自检：纯 JS 逻辑块写入临时 `.mjs` 再 `node --check`（裸 import 不解析也能过；不要当 CommonJS 检查）；**含 JSX 的 plugin.js 别用 `node --check`**（JSX 不是合法 JS，会在标签处报语法错），改用 esbuild 打包校验：`hermes-agent/node_modules/.bin/esbuild --loader:.js=jsx --format=esm --bundle --external:@hermes/plugin-sdk --external:react --external:react/jsx-runtime <plugin.js> --outfile=<scratch>/check.js`（十几毫秒出结果，改完即跑，比渲染测试更早暴露语法错）。
- 手写 jsx 陷阱：`jsx()`/`jsxs()` 只收 3 参（type, props, children?）——多子元素必须写成 `children: [...]`，禁止 `jsx('div', {...}, null, [...])` 这类 4 参调用；这种调用 node --check 能过，但渲染时静默丢失子元素。写完用正则扫 `jsx\('[^']+',\s*\{[^}]*\},\s*null,` 排查。
- **验证改过的前端逻辑要“抽线上代码实跑”，不要另写一份等价逻辑**（另写只能证明你的重写是对的）：node 读取 `plugin.js`，把依赖常量/函数（`DAY_MS`、`dateParts`、`daysUntil`、`daysSince`、`STALE_DAYS`）与目标逻辑块（如 `const focus = (() => {…})()`）按“起始正则＋结束正则”切出，拼成临时 `.cjs`（`module.exports = function(matters, deadlines){ …; return focus }`）后 `require`，喂**真实 payload**——用 hermes venv 的 python 调适配层 `build_payload()` 导成 JSON。三个必踩的坑：① 文件是 **CRLF**，切之前先把 `\r\n` 归一为 `\n`，否则 `\n}\n` 切不到函数尾、拼出的模块少一个花括号（报 `Unexpected end of input`）；② 结束正则以换行打头时匹配位置指向 `\n` 本身，收尾的 `}`／`})()` 必须**显式补回**；③ 依赖链要切全，漏一个常量就 `ReferenceError`。同一套 harness 直接喂**合成边界件**（构造出一个“只有等待类待办”的事项、一个“已办结且记录陈旧”的事项、一个“同名两个事项”），一次验证四条推荐规则，比读代码可靠。
- **改 plugin.js 后做真实渲染冒烟测试**（强于 node --check：能抓 undefined 变量、区块漏渲、字段名拼错）：临时目录配好 node 环境——`node_modules/@hermes/plugin-sdk/index.mjs` mock（导出 cn/host/Tip/useQuery；useQuery 按 queryKey 返回桩数据）＋ `cmd /c mklink /J` 链入 hermes-agent 的 react、react-dom ＋ `package.json {"type":"module"}`；`test.mjs` 里 `plugin.register(mockCtx)` 收集 `ctx.register` 注册项，`renderToString(regs.find(r=>r.id==='pane').render())`，对每个区块文案做 `html.includes(...)` 断言。**清理必须先用 `os.rmdir()` 删 junction、再删目录**——`rm -rf` 会沿 junction 递归删除 react 源包。React dev 模式对 key 经 props 传入 jsx 的警告是 jsx-runtime 的正常写法提示，可忽略。
  - mock 用**环境变量选场景**（正常／请求失败／字段缺失／空清单／异常元素／无效元素），一次 bundle 跑完全部场景；夹具（导出的真实 payload）在改动后**重新导出**——用修复前的快照跑修复后的渲染，新字段必然缺失，只会得到假失败。
