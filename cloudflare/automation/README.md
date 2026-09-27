# CodeSense 持久化自动化入口

这个 Worker 负责接收 GitHub PR 与飞书事件，把事件先写入 Cloudflare Queue，再由队列消费者以幂等方式写入 D1。它不依赖本机 CodeX 在线，适合作为后续 PR 复审、任务推进和知识库同步的稳定入口。

当前链路如下：GitHub/飞书事件 → Worker 验签 → Queue → D1 事件记录 → Luoxin 评审或消息回复 → GitHub Review/合并、飞书私聊、任务台更新、知识库记录。Cloudflare Cron 每十分钟执行成员、任务和 PR 对账，每天中国时间 18:00 发送线上日报。每个外部动作都有独立的 action key，重复投递不会重复发 Review、重复建任务或重复发私信；连续失败的消息会进入 `codesense-automation-dead-letter`，方便人工排查。

## 资源

- Worker：`codesense-project-automation`
- D1：`codesense-automation-state`
- Queue：`codesense-automation-events`
- 失败消息队列：`codesense-automation-dead-letter`
- 健康检查：`/healthz`
- GitHub Webhook：`/webhooks/github`
- 飞书事件入口：`/webhooks/feishu`
- 内部补偿入口：`/internal/reconcile`
- 事件重放入口：`/internal/replay`

## 线上定时流程

- `*/10 * * * *`：读取两个项目群成员，补齐阶段一任务；检查已完成阶段是否缺少下一阶段任务；读取开放 PR 并把当前提交送入幂等复审队列；读取最近一天已经合并的 PR，补写任务完成状态。
- `0 10 * * *`：按照中国时间 18:00 读取 D1、两个任务台和两个仓库，向负责人私聊当天 PR 评审、合并、完成任务、续派任务和失败重试数量。
- 自动跟进属于线上动作记录，不创建成员任务台行；成员任务行只表示成员需要完成的阶段任务。

## 复审与阶段任务规则

- 同一 PR、同一 head SHA 的普通 GitHub 事件只处理一次，保证重复投递不会重复调用评审或重复发布 Review。
- 成员在飞书明确要求复审，或在 GitHub 评论中使用 `@codex`、`@牛顿`、`/review`，当前提交会开启新的复审轮次。新的轮次使用独立事件标记，模型会重新读取当前 diff、Checks 和 PR 状态。
- Review 只把安全风险、数据损坏、明显回归、无法运行、明确失败的检查和目标未完成列为阻塞。可选重构、文字格式、补充测试和后续优化写入合并后的建议。
- 阶段任务使用简短的 STAR 内容：`S` 写当前情境，`T` 写本阶段结果，`A` 写可执行动作，`R` 写提交结果。每个阶段都有独立主题，从项目认识逐步进入问题发现、根因定位、回归验证、运行观察、经验整理和独立交付。

## 必须配置的 Worker Secrets

```text
GITHUB_WEBHOOK_SECRET
GITHUB_API_TOKEN
FEISHU_VERIFICATION_TOKEN
FEISHU_APP_SECRET
INTERNAL_RECONCILE_SECRET
INTERNAL_REPLAY_SECRET
```

评审引擎配置：

```text
LUOXIN_API_KEY
```

`LUOXIN_BASE_URL` 和 `LUOXIN_MODEL` 已在 `wrangler.toml` 中配置为非敏感变量；API Key 只能作为 Worker Secret 写入。当前 Worker 会对两个仓库符合条件的 GitHub PR 事件调用 OpenAI 兼容的 `/chat/completions`，读取最新 diff 和 Checks，再按门禁判断是否能合并。门禁要求 PR 可合并、head SHA 未变化、至少有一项检查且全部通过、评审结果为 approve、diff 可读取并且没有阻塞问题。只有 GitHub 明确返回合并成功，任务才会进入已完成并创建下一阶段；评审不通过时会把具体的文件/位置、当前问题、目标改法和可交给 AI 的操作提示写进 Review、任务台和知识库。

飞书消息默认保持安静：普通群聊不响应；直接 @机器人，或出现冲突、无法提交、重复提交、权限等严重任务问题时才处理。自动跟进通过私聊发送；仅在有人直接 @机器人或出现严重问题时才在群消息线程回复。新成员事件按群 ID 路由到对应项目并创建阶段一任务。

知识库同步会为 GitHub push 和 PR 评审生成文字记录。没有当前事件对应的图片证据时不会复用历史图片，也不会为了凑内容生成图片；需要图示时应把本次事件的具体截图或链接作为独立附件接入。

如果改用独立评审网关，可配置：

```text
REVIEW_ENGINE_URL
REVIEW_ENGINE_TOKEN
```

此时网关需要接受 Worker 发送的事件 JSON；它不是 Luoxin 的 Base URL。

## 部署

首次部署需要先执行：

```bash
npx wrangler d1 migrations apply codesense-automation-state --remote
npx wrangler deploy
```

仓库中的 `.github/workflows/deploy-cloudflare-automation.yml` 会在后续变更时自动部署。GitHub Actions 需要 `CLOUDFLARE_API_TOKEN` 与 `CLOUDFLARE_ACCOUNT_ID` 两个仓库 Secret。

## Webhook 事件

两个仓库的 GitHub Webhook 都指向：

```text
https://codesense-project-automation.daiyupeng5.workers.dev/webhooks/github
```

事件至少需要包含 `pull_request`、`pull_request_review`、`pull_request_review_comment`、`issue_comment`、`push`、`check_suite` 和 `check_run`。`check_suite`/`check_run` 用于在代码检查从等待变为完成后再次评估合并条件。

飞书应用的事件订阅地址为：

```text
https://codesense-project-automation.daiyupeng5.workers.dev/webhooks/feishu
```

需要订阅 `im.message.receive_v1` 和 `im.chat.member.user.added_v1`。Worker 会保留飞书事件到 D1；普通群消息不回复，直接 @机器人、私聊消息和严重任务问题才触发回复。消息中包含明确的 PR 复审请求时，Worker 会把该 PR 当前提交送入 GitHub 复审队列。

内部补偿入口只接受带 `Authorization: Bearer <INTERNAL_RECONCILE_SECRET>` 的请求，并且正文需要是：

```json
{"repository":"XiaoCow666/CodeSense","number":12}
```

事件重放入口只接受带 `Authorization: Bearer <INTERNAL_REPLAY_SECRET>` 的请求，并且正文需要包含已有失败事件的 ID：

```json
{"event_id":"event-inbox-id"}
```

不要把任何 Secret 写进仓库、任务台、知识库或 PR description。
