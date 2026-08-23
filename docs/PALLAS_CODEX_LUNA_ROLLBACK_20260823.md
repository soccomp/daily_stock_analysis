# Pallas Codex / Luna 回滚手册

适用版本：2026-08-23 Codex/Luna 迁移

回滚是 owner review 后的显式操作。本手册不自动执行交易、不恢复 Scheduler
立即运行，也不删除 Qwen/oMLX 模型。

## 触发条件

出现以下任一情况时可回滚：Codex 登录或 quota 长期不可用、模型延迟超出业务
窗口、strict schema 与 DSA 版本不兼容、ChatGPT OAuth policy 变化，或需要恢复
原有 LiteLLM/本地模型路径。

## 代码回滚

先确认目标仓库、当前分支和待回滚提交：

```bash
cd "/Users/m5air/WorkBuddy/Li'ang/daily_stock_analysis"
git status --short
git log --oneline -5
```

对已合并的迁移提交使用 `git revert <migration-commit>`，保留可审计历史；不要
使用 `git reset --hard` 覆盖 owner 变更。若迁移仍在 review 分支，优先在 review
后由 owner 决定是否 revert，不要直接改写远端历史。

## 配置回滚

当前迁移前 `.env` 备份在：

`/Users/m5air/.codex/pallas-backups/dsa-env-pre-codex-luna-20260823`

确认文件权限和目标路径后，再由 owner 执行可恢复的备份还原：

```bash
install -m 600 \
  "/Users/m5air/.codex/pallas-backups/dsa-env-pre-codex-luna-20260823" \
  "/Users/m5air/WorkBuddy/Li'ang/daily_stock_analysis/.env"
```

如果只回退 provider 而保留其他设置，应至少恢复为经 owner 确认的旧值：

```env
GENERATION_BACKEND=litellm
GENERATION_FALLBACK_BACKEND=<旧值或空值>
AGENT_BACKEND=auto
AGENT_ARCH=single
LITELLM_MODEL=<旧值>
```

不要把 `CODEX_HOME`、Codex OAuth 文件或 Qwen/oMLX 模型目录当作回滚垃圾删除。

## LaunchAgent 回滚与重载

若需要恢复 WebUI 启动文件，备份在：

`/Users/m5air/.codex/pallas-backups/com.dsa.webui-pre-codex-luna-20260823.plist`

还原后重新加载：

```bash
install -m 600 \
  "/Users/m5air/.codex/pallas-backups/com.dsa.webui-pre-codex-luna-20260823.plist" \
  "$HOME/Library/LaunchAgents/com.dsa.webui.plist"
launchctl bootout "gui/$(id -u)/com.dsa.webui" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.dsa.webui.plist"
launchctl kickstart -k "gui/$(id -u)/com.dsa.webui"
```

只在确认没有其他服务占用端口后执行重载；启动失败时保留 `/tmp/dsa_launchd.log`
和服务日志，不要通过反复重试制造任务重复。

## oMLX / Qwen 处理

本次迁移没有卸载或删除 oMLX/Qwen。若 owner 要恢复旧本地推理，先确认旧
LaunchAgent、端口、模型目录和 `.env` 备份，再单独恢复 `LLM_CHANNELS` /
`LITELLM_MODEL` 或旧 oMLX service。恢复后必须确认 DSA 的实际 provider identity，
不能仅凭 UI 颜色或进程存在就宣称切换成功。

## 回滚后验收

```bash
curl -fsS http://127.0.0.1:8080/api/v1/health
curl -fsS http://127.0.0.1:8080/api/v1/system/config/generation-backends/status
launchctl print "gui/$(id -u)/com.dsa.webui" | rg "state|program|environment"
```

然后检查：

- primary backend/provider/model 与目标旧配置一致；
- `LIVE_TRADING=false`、simulation-only 仍成立；
- Scheduler 没有被意外 resume 或立即执行；
- 无 pending/unknown order 被自动 retry、补单或撤单；
- 以一条 simulation-only、无交易副作用的 smoke/历史查询证明下游读取仍正常；
- Git 状态、运行态和最终报告明确区分已验证与未验证内容。
