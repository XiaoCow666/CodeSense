# CodeSense 持久化自动化入口

这个 Worker 负责接收 GitHub PR 与飞书事件，把事件先写入 Cloudflare Queue，再由队列消费者以幂等方式写入 D1。它不依赖本机 CodeX 在线，适合作为后续 PR 复审、任务推进和知识库同步的稳定入口。

## 资源

- Worker：`codesense-project-automation`
- D1：`codesense-automation-state`
- Queue：`codesense-automation-events`
- 健康检查：`/healthz`
- GitHub Webhook：`/webhooks/github`
- 飞书事件入口：`/webhooks/feishu`
- 内部补偿入口：`/internal/reconcile`

## 必须配置的 Worker Secrets

```text
GITHUB_WEBHOOK_SECRET
FEISHU_VERIFICATION_TOKEN
INTERNAL_RECONCILE_SECRET
```

评审引擎配置：

```text
LUOXIN_API_KEY
```

`LUOXIN_BASE_URL` 和 `LUOXIN_MODEL` 已在 `wrangler.toml` 中配置为非敏感变量；API Key 只能作为 Worker Secret 写入。当前 Worker 会对符合条件的 GitHub PR 事件调用 OpenAI 兼容的 `/chat/completions`，并把结构化评审结果写入 D1。它不会把模型返回的文字直接当成“已合并”，也不会在没有 GitHub/飞书执行凭据时伪造后续动作。

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
