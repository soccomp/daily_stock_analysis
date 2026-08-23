# Pallas Codex/Luna 运行态证据摘要

本文件只保存可复核的脱敏摘要，不保存 OAuth token、API key、完整 prompt、完整
新闻上下文或完整模型输出。

## 运行环境

| 项目 | 证据 |
|---|---|
| DSA repo | `/Users/m5air/WorkBuddy/Li'ang/daily_stock_analysis` |
| branch | `pallas/codex-luna-migration-20260823` |
| generation | `codex_cli` |
| provider | `codex_chatgpt_oauth` |
| model | `gpt-5.6-luna` |
| reasoning | `max` |
| web | `false`（closed） |
| fallback | `null`；Codex primary 非空 fallback 被拒绝 |
| Agent | `codex_app_server` / single / timeout 300s |
| trading | `LIVE_TRADING=false`；simulation-only |

## PoC

证据目录：`/Users/m5air/Workbuddy/dsa-athena-p0/luna-oauth-poc-20260823/`

结果：`POC_PASS`。PoC 使用真实 DSA prompt，通过 ChatGPT OAuth 调用 Luna Max，
返回 structured JSON，并确认没有 Qwen/oMLX 或模型 fallback。PoC 本身不提供
API billing 证据。

## 真实任务

```json
{
  "task_id": "8ac50a4da98f41bca15a1a40dbf50a0d",
  "stock_code": "600519",
  "status": "completed",
  "progress": 100,
  "stage": "COMPLETED",
  "model_used": "gpt-5.6-luna",
  "llm_status": "ok",
  "history_status": "ok",
  "analysis_history_id": 399,
  "action": "watch",
  "sentiment_score": 47,
  "error": null
}
```

LLM 运行耗时约 239,782ms。报告保留了 `non_trading` 阶段和数据质量限制；没有
将该结果解释成当日盘中或真实交易信号。

## Usage telemetry

修复 provider duplicate-key 后的真实 Codex usage probe：

```json
{
  "model": "gpt-5.6-luna",
  "provider": "codex_chatgpt_oauth",
  "prompt_tokens": 18479,
  "completion_tokens": 24,
  "total_tokens": 18503,
  "provider_usage_schema_name": "codex_cli_turn_usage",
  "provider_usage_schema_version": "1",
  "stock_code": "600519"
}
```

该条记录证明 Codex JSONL `turn.completed.usage` 可以进入本地 `llm_usage`，不
等于付费账单、额度批准或长期可用性证明。

## Research Agent smoke

最新服务重启后，`POST /api/v1/agent/research` 返回 `success=true`、`error=null`。
请求明确要求不调用外部网络；Agent 通过受限的 DSA evidence tool 返回：当前没有
可用的整体策略回测汇总，因此不能编造收益率、胜率、样本数或风险指标。该响应的
`sources` 数为 `1`，`token_usage` 为 `12310`；这只证明 Agent 门禁、结构化响应和
只读证据路径已贯通，不代表已有回测结果或交易可用性。

## 失败与修复记录

1. 第一次真实任务：当前 Codex CLI 不再接受旧的 `--ask-for-approval` 参数；已从
   preset 移除，并保留 `--sandbox read-only`、ephemeral、JSONL 和输出文件边界。
2. 第二次真实任务：DSA schema 的 object 使用 `additionalProperties=true`，被
   Codex strict response schema 拒绝；已将所有 Codex object schema 收紧，并令
   `required` 覆盖 properties。
3. 生产任务成功后发现 usage persistence 的 provider 重复 keyword；已修复并由
   `tests/test_llm_usage.py` 回归覆盖。

## 不在本证据范围内

- 真实成交、实盘交易、API billing、额度购买；
- 全市场筛选质量或长期收益；
- Athena scheduler resume；
- Qwen/oMLX 删除或卸载（本任务明确没有做）；
- Codex 在所有未来 CLI 版本上的兼容性。
