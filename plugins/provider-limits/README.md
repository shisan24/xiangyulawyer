<!-- © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名 -->

# provider-limits · 额度与余额看板

桌面 App 右侧面板「额度与余额」+ 状态栏常显 chip + 无 token 的 cron 告警看门狗。

## 文件

| 文件 | 作用 |
| --- | --- |
| `dashboard/plugin_api.py` | 后端：并发抓取各供应商额度/余额、本机消耗、凭据健康、告警；挂载在 `/api/plugins/provider-limits/` |
| `dashboard/manifest.json` | 后端清单（`{"name": "provider-limits", "api": "plugin_api.py"}`） |
| `state/config.json` | 阈值 / 静默名单 / 冷却时长（见下） |
| `state/alert_state.json` | 看门狗已提醒记录（自动生成，可删） |
| `../../desktop-plugins/provider-limits/plugin.js` | 前端：面板 + 状态栏 chip（保存即热更新） |
| `../../scripts/provider_limits_watchdog.py` | cron 看门狗（`--daily` = 日报模式） |
| `../../scripts/provider_limits_daily.py` | 日报包装脚本 |

## 生效条件

- 前端：`plugin.js` 保存即热更新（兜底：⌘K → Reload desktop plugins）。
- 后端：**只在桌面 App / serve 启动时挂载一次**。改完 `plugin_api.py`、或首次启用后，必须重启 App，
  否则面板报「尚未取到数据」。
- 后端导入受 `config.yaml → plugins.enabled` 门控（已含 `provider-limits`）。

## 数据源

| 供应商 | 类型 | 来源 |
| --- | --- | --- |
| CommandCode | 订阅（月 / 5 小时 / 每周）× 池里全部账户 | `api.commandcode.ai/alpha/{whoami,billing/credits,billing/subscriptions,usage/summary}` |
| ChatGPT（Codex） | 订阅（5 小时 / 每周） | `chatgpt.com/backend-api/wham/usage`（经系统代理；代理取自环境变量或 Windows 注册表） |
| OpenCode Go | 订阅（滚动 / 每周 / 每月，百分比制）× 池里全部账户 | `opencode.ai/zen/go/v1/usage`（先直连；失败回退环境变量 / 注册表代理） |
| ~~Claude（订阅）~~ | 未启用 | 本机没有 Claude 凭据，面板不显示；`_fetch_anthropic_direct` 保留未调用 |
| GLM（智谱 / z.ai） | 余额（本机为按量计费，非编程套餐） | 智谱**没有公开的余额查询接口**（2026-09-23 实测 8 个候选路径全部 404），只给控制台入口；`_fetch_glm_quota`（`/api/monitor/usage/quota/limit`）保留未启用 |
| DeepSeek / Kimi / OpenRouter / Nous | 余额 | 各自 `/user/balance`、`/v1/users/me/balance`、`/api/v1/credits`、Nous 门户 |
| 阿里云百炼 / 火山方舟 | — | 无公开接口，只给控制台入口 |

本机消耗来自 `state.db`（`session_model_usage`，按会话归属今日 / 7 日 / 30 日），
是 Hermes 侧估算，不等于供应商账单。

## 多账户供应商（CommandCode / OpenCode Go）

CommandCode 在凭证池里有两个账户（`auth.json → credential_pool.commandcode`，主 = `COMMANDCODE_API_KEY`、
备 = `COMMANDCODE_API_KEY_2`，两者都是 GOAT）。插件按池内 `priority` 顺序**逐账户各出一条**，名称标 主/备：

- 密钥解析走 Hermes 的 `agent.credential_pool.get_env_prefer_dotenv`（与运行时同源；只读，不落盘、不回传前端、不入日志）；
  该调用在多路复用（multiplex）进程里、请求上下文没有 profile secret scope 时会抛
  `UnscopedSecretError`（0.21.4 起 multiplex 强制开启）。此时按 `load_env()`（`<HERMES_HOME>/.env`）→
  `os.environ` 兜底解析；**仍取不到密钥的账户不会被丢弃**，而是照常出一条标「未解析到 API Key（变量名）」的卡片，
  避免面板把「主/备」静默塌成一个无标签账户。
- 同一套兜底（`PROVIDER_ENV_FALLBACK`）也接在 `_resolve()` 后面：池内条目被标 auth/耗尽后
  `resolve_runtime_provider` 会直接跳过，退回按变量名直读 .env，OpenRouter 这类行才不会只剩「未解析到 API Key」；
  只补读，不改池状态。新增供应商时在 `PROVIDER_ENV_FALLBACK` 里登记变量名即可。
- 邮箱做掩码（`【邮箱】`）；**凭据池当前选中的**那个标「运行时正在使用」（判据见下条）——注意池子是
  **限流后自动切换**，该标记不等于"此刻每一次请求都在服务"。
- ⚠ 「正在使用」的判据必须取**池的选择**（`load_pool()` → `current()`/`select()`），不能用 `_resolve()`：
  桌面后端是 multiplex 进程，`resolve_runtime_provider` 在那里不走凭据池、直接落到 `.env` 主变量，
  会把额度已耗尽的账户标成「正在使用」（2026-10-15 实测：普通进程 → 池选 `..._API_KEY_2`；multiplex →
  直读 `..._API_KEY`，两张卡片的标记正好互换）。multiplex 里 `load_pool()` 自身也会抛 `UnscopedSecretError`
  （读 `<PROVIDER>_BASE_URL` 时没有 profile secret scope），故 `_pool_active_key()` 读不到池时按 auth.json
  池行自算：priority 升序、跳过仍在冷却的条目；冷却口径同 `credential_pool._exhausted_until`
  ——供应商给了窗口重置时刻（`last_error_reset_at`）就认它，不用 429 的 1 小时 TTL。
- 池内冷却会一并显示（`池内冷却：xx 分钟后解禁（池标记，非账单口径）`）。**池标记与供应商账单口径不一致 = 误判**：
  2026-09-17 就出现过辅助调用重试未带失败密钥指纹、把 429 记到健康备用账户头上，导致一部分会话无从轮换；
  处置与排查见技能 `model-provider-management` → `references/credential-pool-multi-account.md`。
- 切换优先级：`hermes auth priority commandcode <label> 0`；查看：`hermes auth list commandcode`；清冷却：`hermes auth reset commandcode`。
- Claude 系模型走独立池（`commandcode-anthropic` / `commandcode-claude`），两个账户需各自在该池里才生效。
- **OpenCode Go** 同样按池内账户逐条出（`opencode-go` / `opencode-go-2`，名称标 主/备；
  `PROVIDER_ENV_FALLBACK` 已登记 `OPENCODE_GO_API_KEY`、`OPENCODE_GO_API_KEY_2`），额度取
  `opencode.ai/zen/go/v1/usage` 的滚动 / 每周 / 每月三个百分比窗口。
- 账户被池标 `exhausted` 且供应商侧给出窗口重置时刻时，卡片直接写「池内标记：额度用尽（供应商窗口 MM-DD HH:MM 恢复，期间重试仍会被拒）」：
  429 的池内冷却 TTL 只有 1 小时，而 Go 的月度额度要到重置日才恢复，两者不是同一件事，按 TTL 写成「x 分钟后解禁」会误导。

## 配置（`state/config.json`，改完无需重启：后端按 mtime 缓存）

```json
{
  "window_pct": 90.0,                        // 窗口用量达该百分比即告警
  "low_balance": { "USD": 1.0, "CNY": 5.0 }, // 余额不高于该值即告警
  "days_left": 3.0,                          // 预计可用天数低于该值即告警
  "fx_to_usd": { "CNY": 0.1408, "USD": 1.0 },// 折算汇率（仅用于「预计可用天数」）
  "cooldown_hours": 12.0,                    // 同一条告警的重复提醒间隔
  "health_alert_max_age_hours": 48.0,        // 凭据失败超过此时长不再告警
  "mute": []                                 // 静默：告警 id（"deepseek:balance"）或供应商 id（"deepseek"）
}
```

## cron 看门狗

| 任务 | 排程 | 脚本 | 行为 |
| --- | --- | --- | --- |
| 额度看门狗（整点） | `0 * * * *` | `provider_limits_watchdog.py` | 有新告警/升级/冷却期满才输出；无输出 = 静默 |
| 额度日报（08:00） | `0 8 * * *` | `provider_limits_daily.py` | 每天一份额度日报 |

手动跑：

```bash
PY=[本地路径]
"$PY" [本地路径]           # 告警模式
"$PY" [本地路径] --daily   # 日报
"$PY" [本地路径] --force   # 忽略冷却重发
```

## 已核验行为（2026-09-17）

- CommandCode / Codex（走代理 【本机端口】）/ DeepSeek / Kimi / OpenRouter 均取到真实数据。
- 首次运行输出 3 条提醒（DeepSeek 余额耗尽、Kimi 余额偏低、nous 凭据异常），二次运行静默，
  日报正常；`--force` 可重发。
- 凭据告警做了去噪：供应商本次查询正常、或失败时间超过 48 小时（池子里的历史 429/401）不再提醒。
- 2026-09-29 新增 OpenCode Go：`/zen/go/v1/usage` 直连实测 200（滚动 / 每周 / 每月 百分比 + 重置时间），已入「订阅额度」区；密钥变量 `OPENCODE_GO_API_KEY` 已登记进 `PROVIDER_ENV_FALLBACK`。
