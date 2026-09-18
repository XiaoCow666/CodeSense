import { listChatMembers, sendFeishuText, formatMemberOnboarding } from "./feishu.js";
import { listOpenPullRequests, listRecentlyMergedPullRequests } from "./github.js";
import {
  ensureNextStageTask,
  ensureStageOneTask,
  listProjectRecords,
  projectForRepository,
  taskRecordSnapshot,
} from "./task-board.js";
import { formatDailyReport } from "./online.js";

const PROJECT_REPOSITORIES = ["XiaoCow666/CodeSense", "XiaoCow666/Caifusi"];
const SKIPPED_MEMBER_IDS = new Set();

function projectChats(env, project) {
  return [...new Set(String(env[project.chatIds] || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean))];
}

function taskUrl(env, project) {
  const token = env[project.baseToken];
  return token ? `https://hcnohkzwsogo.feishu.cn/base/${token}` : "";
}

function skipMember(env, openId) {
  return !openId || openId === env.FEISHU_BOT_OPEN_ID || openId === env.FEISHU_OWNER_OPEN_ID || SKIPPED_MEMBER_IDS.has(openId);
}

function eventForCron(eventId) {
  return { event_id: eventId, source: "internal", event_type: "cron" };
}

function reconciliationBucket() {
  return Math.floor(Date.now() / (10 * 60 * 1000));
}

async function enqueueReviewForOpenPullRequest({ env, project, pullRequest, enqueueEvent, runAction, eventId }) {
  const number = Number(pullRequest.number);
  const headSha = String(pullRequest.head?.sha || "");
  if (!Number.isInteger(number) || !headSha) return { queued: false, reason: "pull_request_identity_missing" };
  const actionKey = `online-review:${project.repository}#${number}:${headSha}:${reconciliationBucket()}`;
  return runAction(
    env,
    eventForCron(eventId),
    "online_review_enqueue",
    actionKey,
    () => enqueueEvent({
      event_id: `online-review:${project.repository}#${number}:${headSha}:${reconciliationBucket()}`,
      source: "internal",
      event_type: "reconcile",
      delivery_id: `online-review:${project.repository}#${number}:${headSha}`,
      payload: { repository: project.repository, number },
    }).then(() => ({ queued: true, repository: project.repository, number, head_sha: headSha })),
  );
}

async function onboardMembers({ env, project, members, records, runAction, eventId }) {
  let created = 0;
  let messages = 0;
  for (const member of members) {
    if (skipMember(env, member.openId)) continue;
    const task = await runAction(
      env,
      eventForCron(eventId),
      "task_stage_one",
      `task-stage1:${project.key}:${member.openId}`,
      () => ensureStageOneTask(env, project, member.openId, member.name),
    );
    if (task.created && task.idempotent_replay !== true) {
      created += 1;
      await runAction(
        env,
        eventForCron(eventId),
        "feishu_member_message",
        `feishu-member:${project.key}:${member.openId}`,
        () => sendFeishuText(
          env,
          "open_id",
          member.openId,
          formatMemberOnboarding(project.name, member.name, taskUrl(env, project)),
          `member_${project.key}_${member.openId}`,
        ),
      );
      messages += 1;
    }
  }
  return { created, messages, records: records.length };
}

async function continueCompletedTasks({ env, project, records, runAction, eventId }) {
  let created = 0;
  let messages = 0;
  const skipped = {};
  for (const record of records) {
    const snapshot = taskRecordSnapshot(record);
    if (snapshot.status !== "已完成") continue;
    const result = await runAction(
      env,
      eventForCron(eventId),
      "task_next_stage",
      `task-next-stage:${project.key}:${snapshot.recordId}:${snapshot.stage || "unknown"}`,
      () => ensureNextStageTask(env, project, record, records),
    );
    if (result.reason) skipped[result.reason] = (skipped[result.reason] || 0) + 1;
    if (!result.created || result.idempotent_replay === true) continue;
    created += 1;
    await runAction(
      env,
      eventForCron(eventId),
      "feishu_next_stage_message",
      `feishu-next-stage:${project.key}:${snapshot.assigneeOpenId}:${result.next_stage}`,
      () => sendFeishuText(
        env,
        "open_id",
        result.assignee_open_id,
        `上一阶段已经完成，新的阶段${result.next_stage}任务已经创建。请打开任务台按新任务继续，完成后提交新的 PR。${taskUrl(env, project) ? `\n任务台：${taskUrl(env, project)}` : ""}`,
        `next_${project.key}_${result.assignee_open_id}_${result.next_stage}`,
      ),
    );
    messages += 1;
  }
  return { created, messages, skipped };
}

export async function runOnlineReconciliation({ env, enqueueEvent, runAction } = {}) {
  if (typeof enqueueEvent !== "function" || typeof runAction !== "function") throw new Error("online reconciliation dependencies are missing");
  const eventId = `cron-reconcile:${reconciliationBucket()}`;
  const summary = { projects: 0, members: 0, stageOneTasks: 0, nextStageTasks: 0, nextStageSkipped: {}, messages: 0, reviewsQueued: 0, openPullRequests: 0, mergedPullRequests: 0 };
  for (const repository of PROJECT_REPOSITORIES) {
    const project = projectForRepository(env, repository);
    if (!project) throw new Error(`project is not configured: ${repository}`);
    const records = await listProjectRecords(env, project);
    let members = [];
    for (const chatId of projectChats(env, project)) {
      const chatMembers = await listChatMembers(env, chatId);
      members.push(...chatMembers);
    }
    members = [...new Map(members.map((member) => [member.openId, member])).values()];
    summary.members += members.length;
    const onboarding = await onboardMembers({ env, project, members, records, runAction, eventId });
    summary.stageOneTasks += onboarding.created;
    summary.messages += onboarding.messages;
    const next = await continueCompletedTasks({ env, project, records, runAction, eventId });
    summary.nextStageTasks += next.created;
    for (const [reason, count] of Object.entries(next.skipped)) summary.nextStageSkipped[reason] = (summary.nextStageSkipped[reason] || 0) + count;
    summary.messages += next.messages;
    const pullRequests = await listOpenPullRequests(env, project.repository);
    summary.openPullRequests += pullRequests.length;
    for (const pullRequest of pullRequests) {
      const result = await enqueueReviewForOpenPullRequest({ env, project, pullRequest, enqueueEvent, runAction, eventId });
      if (result.queued) summary.reviewsQueued += 1;
    }
    const recentMerges = await listRecentlyMergedPullRequests(env, project.repository, new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString());
    summary.mergedPullRequests += recentMerges.length;
    for (const pullRequest of recentMerges) {
      const result = await enqueueReviewForOpenPullRequest({ env, project, pullRequest: { ...pullRequest, head: { sha: pullRequest.head?.sha || pullRequest.merge_commit_sha || pullRequest.merged_at } }, enqueueEvent, runAction, eventId });
      if (result.queued) summary.reviewsQueued += 1;
    }
    summary.projects += 1;
  }
  return summary;
}

async function actionCounts(env, since) {
  const rows = await env.STATE_DB.prepare(
    "SELECT action_type, status, response_json FROM action_log WHERE created_at >= ?",
  ).bind(since).all();
  const counts = { githubReviews: 0, merged: 0, completedTasks: 0, nextTasks: 0, errors: 0 };
  for (const row of rows.results || []) {
    if (row.status !== "completed") {
      counts.errors += 1;
      continue;
    }
    if (row.action_type === "github_review") counts.githubReviews += 1;
    if (row.action_type === "github_merge") {
      const response = row.response_json ? JSON.parse(row.response_json) : {};
      if (response.merged === true) {
        counts.merged += 1;
        counts.completedTasks += 1;
      }
    }
    if (row.action_type === "task_next_stage") {
      const response = row.response_json ? JSON.parse(row.response_json) : {};
      if (response.created === true) counts.nextTasks += 1;
    }
  }
  return counts;
}

async function eventErrorCount(env, since) {
  const result = await env.STATE_DB.prepare(
    "SELECT COUNT(*) AS count FROM event_inbox WHERE first_seen_at >= ? AND (status != 'processed' OR (action_status IS NOT NULL AND action_status != 'completed'))",
  ).bind(since).first();
  return Number(result?.count || 0);
}

export async function buildOnlineDailyReport(env) {
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const counts = await actionCounts(env, since);
  counts.errors += await eventErrorCount(env, since);
  const projects = [];
  for (const repository of PROJECT_REPOSITORIES) {
    const project = projectForRepository(env, repository);
    if (!project) throw new Error(`project is not configured: ${repository}`);
    const records = await listProjectRecords(env, project);
    const tasks = {};
    for (const record of records) {
      const status = taskRecordSnapshot(record).status || "未设置";
      tasks[status] = (tasks[status] || 0) + 1;
    }
    const openPrs = await listOpenPullRequests(env, project.repository);
    projects.push({ name: project.name, tasks, openPrs: openPrs.length });
  }
  return formatDailyReport({
    date: new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date()).replaceAll("/", "-"),
    projects,
    ...counts,
  });
}

export async function runOnlineDailyReport({ env, runAction } = {}) {
  if (typeof runAction !== "function") throw new Error("daily report dependencies are missing");
  if (!env.FEISHU_OWNER_OPEN_ID) throw new Error("FEISHU_OWNER_OPEN_ID is not configured");
  const date = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai" }).format(new Date());
  const eventId = `cron-daily-report:${date}`;
  const report = await buildOnlineDailyReport(env);
  return runAction(
    env,
    eventForCron(eventId),
    "feishu_daily_report",
    eventId,
    () => sendFeishuText(env, "open_id", env.FEISHU_OWNER_OPEN_ID, report, eventId),
  );
}

export async function buildMessageContext(env, event, project, records = [], pullRequest = null) {
  const details = event?.payload ? event.payload : event;
  const senderOpenId = details?.event?.sender?.sender_id?.open_id
    || details?.event?.sender?.sender_id?.user_id
    || details?.sender_open_id
    || null;
  const snapshots = records.map(taskRecordSnapshot)
    .filter((record) => !senderOpenId || record.assigneeOpenId === senderOpenId)
    .slice(0, 8)
    .map((record) => ({ task: record.taskName, status: record.status, stage: record.stage, pr: record.prUrl }));
  return {
    project: project ? { name: project.name, repository: project.repository } : null,
    member_tasks: snapshots,
    pull_request: pullRequest ? {
      number: pullRequest.number,
      state: pullRequest.state,
      draft: pullRequest.draft,
      head_sha: pullRequest.head?.sha || null,
      mergeable: pullRequest.mergeable,
      mergeable_state: pullRequest.mergeable_state,
      title: pullRequest.title,
    } : null,
  };
}
