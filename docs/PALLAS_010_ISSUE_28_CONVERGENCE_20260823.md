# PALLAS-010 / Athena Issue #28 convergence evidence

状态：`READY_FOR_INDEPENDENT_REVIEW`

本文件记录 independent review comment `5384474698` 与 corrective comment `5384738675` 要求的候选分支收敛证据。范围严格限于 Athena Issue #28 与 PALLAS-010 corrective DSA/Athena 依赖适配；不包含 PALLAS-011、proof order、scheduler catch-up 或生产变更。

## 候选基座

| 项目 | 值 |
| --- | --- |
| DSA candidate branch | `pallas-010/codex-luna-convergence-dsa` |
| Codex/Luna base | `f5dde6309f655176cd45abc114ee917c2e58c07e` |
| corrective DSA parent | `0ab622b782c2b58adb4c59cdf853aaa3044fd059` |
| Athena candidate branch | `pallas-010/codex-luna-convergence-athena` |
| corrective Athena parent | `03b462c935dbe9b2f701c704d39e7aaa16a7b081` |
| review boundary | `https://github.com/soccomp/athena/issues/28#issuecomment-5384474698` |
| corrective review boundary | `https://github.com/soccomp/athena/issues/28#issuecomment-5384738675` |

## Codex/Luna identity and health

- 主依赖唯一标识为 `codex-luna`，category 为 `LLM_RESEARCH`，provider 为 `codex_chatgpt_oauth`，effective model 为 `gpt-5.6-luna`，auth mode 为 Codex-managed ChatGPT OAuth。
- `codex --version`：`codex-cli 0.149.0-alpha.4.1`。
- `codex login status`：`Logged in using ChatGPT`。
- identity probe 为 `HEALTHY` 只表示 executable/version/login/model identity；没有 generation layer 时，`LLM_RESEARCH` 仍为 `UNKNOWN` 并 fail closed。
- canonical `LLM_RESEARCH` generation 只有在真实 Pallas structured/research contract 已实际通过、model/provider 与 backend identity 匹配时才可恢复 `HEALTHY`；普通 Chat、Agent text、ranking 或 backend smoke success 仅保留 telemetry，不得覆盖 generation failure。schema/source-grounding/timeout/login/quota failure 仍 fail closed；generation freshness TTL 为 900 秒。
- 本轮 7 次新鲜真实 generation 均返回 `returncode=0`、strict schema 成功、usage 可用，未观察到 timeout、login 或 quota/rate-limit failure。这里不把“本轮未耗尽”扩展解释为账户剩余额度；quota failure 仍由 gate 显式阻断。

## 真实 600519 workload benchmark

命令使用候选工具 `tools/pallas010_codex_luna_benchmark.py`，复用真实 DSA prompt/schema，临时 cwd、sandbox read-only、ephemeral、web search off、串行并发 1，单样本上限 300 秒。各 setting 的 contract-quality proxy 为 strict structured-output success；它不是投资质量评分。

| reasoning effort | 样本 | success / structured | p50 | p95 | max | timeout rate | 300s hard-timeout margin | 75% health-budget margin |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `max` | 1 新鲜 + 1 同 workload baseline | 2/2 | 177,898.5 ms | 221,087 ms | 221,087 ms | 0% | 78,913 ms | 3,913 ms |
| `xhigh` | 2 | 2/2 | 110,354 ms | 119,690 ms | 119,690 ms | 0% | 180,310 ms | 105,310 ms |
| `high` | 2 | 2/2 | 78,338 ms | 79,715 ms | 79,715 ms | 0% | 220,285 ms | 145,285 ms |
| `medium` | 2 | 2/2 | 23,058 ms | 24,406 ms | 24,406 ms | 0% | 275,594 ms | 200,594 ms |

`max` 的 baseline 是同一 600519 prompt、同一模型/provider、同一 strict schema 的既有 OAuth PoC 成功样本（`luna-oauth-poc-20260823/poc_report.md`，221.087 秒）；它被单独标为 baseline，不冒充本轮新鲜样本。当前新鲜 `max` 样本为 134,710 ms，usage 为 input 20,515 / output 7,157 / reasoning 5,428。lower settings 的 6 次新鲜样本均 usage 可用。

本轮 Owner observation period 保持 production/default reasoning effort 为 `max`。`xhigh`/`high`/`medium` 仅保留为后续优化证据，不切换默认值；本表每个 setting 只有 n=2 bounded preliminary workload samples（`max` 含一条既有 baseline），不构成长周期 p95/SLA，也不证明 investment quality 相同。后续如要改变默认值，须由 Owner 基于真实 `llm_usage` quota/latency/quality 观察另行授权 benchmark 与配置变更。

## Routing / gate convergence

- Bocha 为 `PRIMARY/priority=1`；已配置 SearXNG 为 `FALLBACK/priority=2`；public SearXNG discovery 默认关闭；其他 providers 均为 `AUXILIARY/priority=99`。
- topic、stock-news、stock-events 与 comprehensive-intel 都按 Bocha → SearXNG → auxiliary chain；Bocha 有可用结果时不会调用 SearXNG，Bocha 失败或过滤为空时才进入 SearXNG。
- research endpoint 的 sources 不再接受模型文本作为独立权威：每个 source 必须匹配成功的实际 DSA tool call，返回值重建为 `tool:<name>`；无成功 tool evidence 或存在未匹配 source 时 fail closed。
- `record_llm_run()` 与普通 Codex App Server Chat success 不再写入 canonical generation；只有显式 Pallas structured contract success 才能调用 qualifying recovery path。
- Athena read-only client 对 `codex-luna` 的 model/provider、identity status、generation status 与 row status 做防御性校验；缺失、错误身份、过期/未知/失败 generation 或 `LLM_RESEARCH=DEGRADED` 均阻断 autonomous readiness。pre-trade gate 只消费这一 fail-closed readiness，不触发补偿执行。

## 回归与安全边界

- PALLAS-010 DSA regression：33 passed；其中新增覆盖 non-qualifying Chat/diagnostic success 不得 healing、qualifying structured Pallas recovery、schema-invalid response 不得 healing、identity/login failure、generation recovery/expiry、legacy Qwen 不得提升 ready、Bocha/SearXNG ordering、research source grounding、Agent API/backend 与 local CLI。
- Athena candidate P010 + pre-trade gate regression：17 passed。
- DSA candidate full regression（在最后两项 endpoint grounding tests 加入前）：`6057 passed, 6 skipped, 4 failed`。4 个 failure 均为范围外环境边界：1 个 intelligence test 依赖当前不可达 Eastmoney 网络，3 个 proposal-handoff E2E 依赖缺失的其他 Athena recovery/impl worktree；没有本轮受影响 convergence test failure。最后两项 grounding tests 已在 PALLAS-010 focused 31 passed 中单独通过。
- Athena candidate full regression 在 collection 阶段有 7 个既有 cross-test import/worktree errors（缺失 `tests.test_market_intelligence`、`tests.pallas_003_helpers` 及其依赖链）；因此以可执行的 P010 + pre-trade focused 17 passed 作为本候选的 gate 证据，不修复无关 checkout 缺口。
- `compileall`/`py_compile` 与 `git diff --check` 通过。
- 本 corrective pass 未启动新的 quota-consuming Luna benchmark；既有 benchmark 未启动 DSA/Athena 服务。未修改生产目录、数据库、scheduler、proposal/order state、main 或 upstream；没有 proof order、scheduler catch-up、merge 或 PALLAS-011。

本 corrective implementation commit 为 `8578bc9`；独立 reviewer 应以候选分支 handoff 时的 exact `HEAD` 与 GitHub 远端提交为审计对象。
