import test from "node:test";
import assert from "node:assert/strict";
import {
  extractPullRequestReference,
  actionCanBeReclaimed,
  isKnowledgeCandidate,
  isReviewRequest,
  formatDailyReport,
  scheduledActionKey,
  scheduledMode,
} from "../src/online.js";

test("Cloudflare cron keeps reconciliation and the daily report separate", () => {
  assert.equal(scheduledMode("*/10 * * * *"), "reconcile");
  assert.equal(scheduledMode("0 10 * * *"), "daily-report");
  assert.equal(scheduledMode("unknown"), "reconcile");
});

test("scheduled jobs use distinct idempotent action keys", () => {
  const now = new Date("2026-09-19T01:20:00+08:00");
  assert.equal(scheduledActionKey("*/10 * * * *", now), `scheduler:reconcile:${Math.floor(now.getTime() / 600000)}`);
  assert.equal(scheduledActionKey("0 10 * * *", now), "scheduler:daily-report:2026-09-19");
});

test("online message routing extracts only an explicit supported PR", () => {
  assert.deepEqual(
    extractPullRequestReference(
      "请复审 https://github.com/XiaoCow666/CodeSense/pull/17",
      "XiaoCow666/CodeSense",
    ),
    { repository: "XiaoCow666/CodeSense", number: 17 },
  );
  assert.deepEqual(
    extractPullRequestReference("请看 PR #8", "XiaoCow666/Caifusi"),
    { repository: "XiaoCow666/Caifusi", number: 8 },
  );
  assert.equal(extractPullRequestReference("请看别的项目 PR #8", "XiaoCow666/CodeSense"), null);
});

test("online assistant recognizes review and high-value knowledge requests", () => {
  assert.equal(isReviewRequest("请审一下这个 PR"), true);
  assert.equal(isReviewRequest("收到，谢谢"), false);
  assert.equal(isKnowledgeCandidate("经验：这个版本的 webhook 重试要保留事件编号"), true);
  assert.equal(isKnowledgeCandidate("今天辛苦了"), false);
});

test("daily report stays short while retaining actionable counts", () => {
  const report = formatDailyReport({
    date: "2026-09-18",
    projects: [
      { name: "CodeSense", tasks: { "待开始": 2, "进行中": 1 }, openPrs: 1 },
      { name: "Caifusi", tasks: { "已完成": 3 }, openPrs: 0 },
    ],
    githubReviews: 2,
    merged: 1,
    completedTasks: 3,
    nextTasks: 2,
    errors: 0,
  });
  assert.match(report, /2026-09-18/);
  assert.match(report, /PR 评审：2 次，合并：1 个/);
  assert.match(report, /CodeSense：待开始 2，进行中 1；开放 PR 1 个/);
  assert.match(report, /失败重试：0/);
});

test("stale running actions can be reclaimed after a worker interruption", () => {
  const now = Date.parse("2026-09-18T04:00:00Z");
  assert.equal(actionCanBeReclaimed({ status: "failed" }, now), true);
  assert.equal(actionCanBeReclaimed({ status: "running", updated_at: "2026-09-18T03:00:00Z" }, now), true);
  assert.equal(actionCanBeReclaimed({ status: "running", updated_at: "2026-09-18T03:59:00Z" }, now), false);
  assert.equal(actionCanBeReclaimed({ status: "completed" }, now), false);
});
