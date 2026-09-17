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

可选：

```text
REVIEW_ENGINE_URL
REVIEW_ENGINE_TOKEN
```

`REVIEW_ENGINE_URL` 没有配置时，Worker 仍会可靠地接收并记录事件，但不会假装已经完成 PR 评审或飞书跟进。真正接入 CodeX/ChatGPT 评审引擎后，再配置该地址。

## 部署

首次部署需要先执行：

```bash
npx wrangler d1 migrations apply codesense-automation-state --remote
npx wrangler deploy
```

仓库中的 `.github/workflows/deploy-cloudflare-automation.yml` 会在后续变更时自动部署。GitHub Actions 需要 `CLOUDFLARE_API_TOKEN` 与 `CLOUDFLARE_ACCOUNT_ID` 两个仓库 Secret。
