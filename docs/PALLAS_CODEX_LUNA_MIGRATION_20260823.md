# Pallas：DSA Codex / ChatGPT OAuth / Luna Max 迁移记录

状态：`READY_FOR_INDEPENDENT_REVIEW`

日期：2026-08-23（Asia/Shanghai）

本文件是本次 Pallas 迁移的实现与运行态记录。普通 provider 配置仍可参考
[`LLM_CONFIG_GUIDE.md`](./LLM_CONFIG_GUIDE.md)；本文件中的 Pallas production profile
优先于其中面向历史兼容路径的通用示例。

## 范围与冻结边界

- 实际 Git 仓库：`/Users/m5air/WorkBuddy/Li'ang/daily_stock_analysis`
- 实现分支：`pallas/codex-luna-migration-20260823`
- 基线：`2f03f4db5710cc808228e7ec856cc9b7246e2eee`
- 远端：`soccomp/daily_stock_analysis`
- 本任务只迁移 DSA 的生产推理层；没有删除 Qwen/oMLX 模型、文件或安装。
- 没有启用真实交易、没有 resume Scheduler、没有 merge `main/upstream`，也没有 push。
- 原有 DSA → Portfolio → Risk → Athena 数据与安全边界保持不变；运行态继续
  `LIVE_TRADING=false`、simulation-only，未知订单不被自动补单或重试。
- Pallas benchmark 的结论是 `SUPERSEDED_BY_ARCHITECTURE_DECISION`：Codex/Luna
  已由独立 PoC 和生产任务证明可用，benchmark 不再作为迁移前置条件。

## 目标架构

```text
DSA 数据/确定性计算/证据组织
        │
        ├─ codex_cli（普通生成）
        └─ codex_app_server（Agent + Tool Surface）
                │
                ▼
        ChatGPT OAuth → gpt-5.6-luna → reasoning=max
                │
                ▼
        strict Structured JSON → DSA parser / integrity / persistence
                │
                ▼
        Research Result → Portfolio / Risk / Athena
```

DSA 不读取或保存 OAuth token，也不把 OAuth 凭据转换为 OpenAI API key。Codex
子进程仅接收允许的环境变量；API key、provider token、webhook secret 等被拒绝
继承。模型、reasoning effort、web-search 开关和 provider identity 都进入可审计
诊断，但原始 prompt、OAuth token 和完整 stdout 不进入诊断或 usage 表。

## 生产调用矩阵

| 调用面 | 实际 backend | provider / model | effort | web | 输出契约 | fallback 语义 |
|---|---|---|---|---|---|---|
| 个股普通分析 `GeminiAnalyzer.analyze` | `codex_cli` | `codex_chatgpt_oauth` / `gpt-5.6-luna` | `max` | closed | strict DSA dashboard JSON；解析后做完整性校验 | 禁止模型/provider/local fallback |
| 大盘复盘 `MarketAnalyzer` | `codex_cli` | 同上 | `max` | closed | strict `{report: string}` | 仅允许明确的业务模板降级，不切换模型/provider |
| Screening ranker | `codex_cli` | 同上 | `max` | closed | strict ranking JSON | 仅 deterministic factor degradation，不切换模型/provider |
| 问股 Chat dashboard | `codex_app_server` | `codex_chatgpt_oauth` / `gpt-5.6-luna` | `max` | DSA controlled tools；不启用 Codex native web | strict DSA dashboard schema | 不回退 LiteLLM、Qwen/oMLX 或 API provider |
| Research Agent | `codex_app_server` | 同上 | `max` | DSA controlled evidence tools | strict research response schema | 工具失败显式报告，不切换模型/provider |
| Vision / 图片识别 | Codex 不支持 | 无 | — | — | 显式 `CODEX_VISION_UNSUPPORTED` | 禁止暗中回到 LiteLLM/API key 路径 |

Codex App Server 的生产动态工具面固定为三个具备有界取消契约的只读工具：
`get_analysis_context`、`get_skill_backtest_summary`、`get_strategy_backtest_summary`。
实时行情、新闻和联网搜索不通过 Codex native web 或未验证的工具面暗中启用。

所有传给 Codex 的 object schema 都显式设置 `additionalProperties=false`，并让
`required` 覆盖该对象的全部 properties；这满足 Codex strict structured-output
校验。DSA parser 对历史数据仍保持兼容，但不再依赖“模型随意增加字段”来完成
生产契约。

## 配置迁移

`.env.example` 已提供目标 profile；本机 `.env` 已在受控备份后切换为：

```env
GENERATION_BACKEND=codex_cli
GENERATION_FALLBACK_BACKEND=
CODEX_CLI_MODEL=gpt-5.6-luna
CODEX_CLI_REASONING_EFFORT=max
CODEX_CLI_WEB_SEARCH_ENABLED=false

AGENT_BACKEND=codex_app_server
AGENT_ARCH=single
AGENT_ORCHESTRATOR_TIMEOUT_S=300

LITELLM_MODEL=
LLM_CHANNELS=
LLM_OMLX_ENABLED=false
```

Qwen/oMLX 的历史 URL、模型名和 key 仍保留为 dormant 配置，避免破坏回滚和既有
安装；它们不在本次正常 DSA 调用链上。`resolve_generation_fallback_backend_id`
和配置校验会对 `codex_cli` primary 的任何非空 fallback fail-closed。

本机配置备份：

`/Users/m5air/.codex/pallas-backups/dsa-env-pre-codex-luna-20260823`

LaunchAgent 备份：

`/Users/m5air/.codex/pallas-backups/com.dsa.webui-pre-codex-luna-20260823.plist`

## 运行态证据

### 独立 PoC（迁移前已完成）

`/Users/m5air/Workbuddy/dsa-athena-p0/luna-oauth-poc-20260823/` 已记录：

- `POC_PASS`
- ChatGPT OAuth、非 OpenAI API key、`gpt-5.6-luna`、`reasoning=max`
- 真实 DSA prompt、strict JSON、无 Qwen/oMLX、无模型 fallback
- input 72,632；cached input 41,472；output 11,443；reasoning 8,996；
  wall time 221.087s

### 生产 DSA 任务

任务 `8ac50a4da98f41bca15a1a40dbf50a0d`（600519，异步、强制刷新、通知关闭）
已完成：

- status `completed`，progress `100`，stage `COMPLETED`
- `model_used=gpt-5.6-luna`
- `llm=ok`，耗时约 239,782ms
- DSA 返回 structured dashboard，最终 action 为 `watch`，sentiment score 为 47
- history id `399`，`history=ok`
- 原有两次失败任务分别暴露旧 CLI approval 参数和 strict schema 问题；它们没有
  被伪造为成功，也没有触发 fallback 或交易动作。

### Usage telemetry

Codex JSONL `turn.completed.usage` 已映射为 input/output/reasoning/total token
字段，并写入本地 `llm_usage`。迁移后发现并修复了 provider telemetry 的重复
keyword bug；短 production-path probe 的实际记录为：

- model `gpt-5.6-luna`
- provider `codex_chatgpt_oauth`
- `prompt_tokens=18479`，`completion_tokens=24`，`total_tokens=18503`
- `provider_usage_schema_name=codex_cli_turn_usage`，version `1`
- stock code `600519`

该 probe 只验证 telemetry 写入，不代表真实成本或付费 API 计费；当前没有 API
billing 证据。

### 服务与安全状态

- `GET /api/v1/health`：`status=ok`
- generation backend status：primary `codex_cli`，fallback `null`，provider
  `codex_chatgpt_oauth`，available `true`，usage available `true`
- Agent status：`codex_app_server`，可执行版本 `codex-cli 0.149.0-alpha.4.1`
- Agent models：唯一 primary deployment 为
  `codex_chatgpt_oauth/gpt-5.6-luna`
- WebUI LaunchAgent 使用显式 ChatGPT/Codex PATH 和 `CODEX_HOME`；scheduler
  仍受生产冻结变量抑制，未自动运行。

## 验证边界

已验证的是一次真实个股任务的完整 DSA 路径、structured JSON、历史保存、Codex
usage 提取/写入，以及 Agent/market/screening 的代码契约与回归测试。没有把这次
个股任务扩大解释为：实际成交、live trading、全市场筛选完成、Athena 下单可用、
API 配额已购买或模型长期 SLA 已成立。非交易日结果也只基于可用的上一完整日线
和已标注数据质量限制。

## 回滚

按 [`PALLAS_CODEX_LUNA_ROLLBACK_20260823.md`](./PALLAS_CODEX_LUNA_ROLLBACK_20260823.md)
执行。回滚边界是恢复配置和代码，不删除 Qwen/oMLX 模型；回滚后仍需重新验证
`LIVE_TRADING=false`、Scheduler 状态、generation backend identity、health 和
simulation-only 边界。

## Git 交付

本分支只保留本次迁移代码、配置模板、文档和测试变更；提交 hash 以最终
`git log` 为准。未 push、未 merge，停止状态为 `READY_FOR_INDEPENDENT_REVIEW`。
