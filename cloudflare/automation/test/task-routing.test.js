import test from "node:test";
import assert from "node:assert/strict";
import {
  nextStageForCompletedRecord,
  nextStageEligibility,
  memberTaskPlan,
  parseStageNumber,
  parsePullRequestStage,
  pullRequestStageMatchesTask,
  projectForChat,
  projectForRepository,
  stageTaskContent,
  selectTaskForGithubIdentity,
  ensureNextStageTask,
  taskRecordSnapshot,
} from "../src/task-board.js";

test("stage parsing supports Arabic and Chinese stage names", () => {
  assert.equal(parseStageNumber("阶段 8：真实问题"), 8);
  assert.equal(parseStageNumber("阶段八：真实问题"), 8);
  assert.equal(parseStageNumber("阶段十一：真实问题"), 11);
  assert.equal(parseStageNumber("阶段十五：真实链路"), 15);
  assert.equal(parsePullRequestStage("codex/stage12-evaluation-followup"), 12);
});

test("repository and chat routing remain project-specific", () => {
  const env = {
    FEISHU_CODESENSE_CHAT_IDS: "oc_codesense, oc_total",
    FEISHU_CAIFUSI_CHAT_IDS: "oc_caifusi",
  };
  assert.equal(projectForRepository(env, "XiaoCow666/CodeSense").key, "codesense");
  assert.equal(projectForRepository(env, "XiaoCow666/Caifusi").key, "caifusi");
  assert.equal(projectForChat(env, "oc_codesense").key, "codesense");
  assert.equal(projectForChat(env, "oc_caifusi").key, "caifusi");
  assert.equal(projectForChat(env, "oc_unknown"), null);
});

test("completed member work exposes the next stage without creating an automation row", () => {
  const record = {
    record_id: "rec_1",
    fields: {
      "任务名称": "阶段二：真实问题改进（张三）",
      "状态": ["已完成"],
      "负责人": [{ id: "ou_member", name: "张三" }],
      "GitHub PR / Issue": "https://github.com/XiaoCow666/CodeSense/pull/22",
    },
  };
  const snapshot = taskRecordSnapshot(record);
  assert.deepEqual(snapshot, {
    recordId: "rec_1",
    taskName: "阶段二：真实问题改进（张三）",
    status: "已完成",
    assigneeOpenId: "ou_member",
    assigneeName: "张三",
    prUrl: "https://github.com/XiaoCow666/CodeSense/pull/22",
    stage: 2,
  });
  assert.deepEqual(nextStageForCompletedRecord([snapshot], snapshot), {
    assigneeOpenId: "ou_member",
    assigneeName: "张三",
    nextStage: 3,
  });
});

test("online task reconciliation does not create a duplicate active next stage", async () => {
  const snapshot = {
    recordId: "rec_1",
    taskName: "阶段二：真实问题改进（张三）",
    status: "已完成",
    assigneeOpenId: "ou_member",
    assigneeName: "张三",
    prUrl: "",
    stage: 2,
  };
  const activeNext = { ...snapshot, recordId: "rec_2", taskName: "阶段三：验证（张三）", status: "进行中", stage: 3 };
  assert.deepEqual(await ensureNextStageTask({}, {}, snapshot, [snapshot, activeNext]), {
    created: false,
    record_id: null,
    next_stage: null,
    reason: "next_stage_exists",
  });
});

test("an existing next-stage record prevents another next-stage record", () => {
  const completed = { taskName: "阶段十一：维护整理", status: "已完成", assigneeOpenId: "ou_member", assigneeName: "张三", stage: 11 };
  const existingNext = { taskName: "阶段十二：经验方法", status: "已完成", assigneeOpenId: "ou_member", assigneeName: "张三", stage: 12 };
  assert.deepEqual(nextStageEligibility([completed, existingNext], completed), {
    eligible: false,
    reason: "next_stage_exists",
  });
});

test("completed task recovery reports missing metadata instead of silently skipping", () => {
  assert.deepEqual(
    nextStageEligibility([], { taskName: "历史任务", status: "已完成", assigneeOpenId: null, stage: 2 }),
    { eligible: false, reason: "assignee_missing" },
  );
  assert.deepEqual(
    nextStageEligibility([], { taskName: "历史任务", status: "已完成", assigneeOpenId: "ou_member", stage: null }),
    { eligible: false, reason: "stage_missing" },
  );
});

test("stage fourteen completion creates stage fifteen and stage fifteen is final", () => {
  const completedStageFourteen = { taskName: "阶段十四：独立完成一个小闭环", status: "已完成", assigneeOpenId: "ou_member", assigneeName: "张三", stage: 14 };
  assert.deepEqual(nextStageEligibility([], completedStageFourteen), {
    eligible: true,
    assigneeOpenId: "ou_member",
    assigneeName: "张三",
    nextStage: 15,
  });
  assert.deepEqual(nextStageEligibility([], { ...completedStageFourteen, taskName: "阶段十五：把改进接进真实链路", stage: 15 }), {
    eligible: false,
    reason: "final_stage",
  });
  assert.notEqual(stageTaskContent("CodeSense", 14, "张三").description, stageTaskContent("CodeSense", 15, "张三").description);
});

test("automatic PR linking refuses a clearly different stage", () => {
  assert.equal(pullRequestStageMatchesTask("阶段十五：把改进接进真实链路", { headRefName: "codex/stage12-evaluation-followup", title: "fix: correct stage12 evaluation evidence" }), false);
  assert.equal(pullRequestStageMatchesTask("阶段十五：把改进接进真实链路", { headRefName: "codex/stage15-real-path", title: "feat: integrate the verified change" }), true);
  assert.equal(pullRequestStageMatchesTask("阶段十五：把改进接进真实链路", { headRefName: "codex/knowledge-rag", title: "feat: improve retrieval" }), true);
});

test("github identity links only one active stage task", () => {
  const task = {
    record_id: "rec_stage_7",
    fields: {
      "任务名称": "阶段七：验证（张三）",
      "状态": ["进行中"],
      "负责人": [{ id: "ou_member", name: "张三" }],
      "任务模式": ["阶段任务"],
      "GitHub PR / Issue": null,
    },
  };
  assert.equal(selectTaskForGithubIdentity([task], "ou_member"), task);
  assert.equal(selectTaskForGithubIdentity([task, { ...task, record_id: "rec_other" }], "ou_member"), null);
});

test("github identity follows the next stage after the highest completed stage", () => {
  const staleEarlier = {
    record_id: "rec_stage_9_old",
    fields: {
      "任务名称": "阶段九：旧记录（张三）",
      "状态": ["待评审"],
      "负责人": [{ id: "ou_member", name: "张三" }],
      "任务模式": ["阶段任务"],
      "GitHub PR / Issue": null,
    },
  };
  const completed = {
    record_id: "rec_stage_10",
    fields: {
      "任务名称": "阶段十：已完成（张三）",
      "状态": ["已完成"],
      "负责人": [{ id: "ou_member", name: "张三" }],
      "任务模式": ["阶段任务"],
      "GitHub PR / Issue": "https://github.com/XiaoCow666/CodeSense/pull/64",
    },
  };
  const expected = {
    record_id: "rec_stage_11",
    fields: {
      "任务名称": "阶段十一：当前任务（张三）",
      "状态": ["待开始"],
      "负责人": [{ id: "ou_member", name: "张三" }],
      "任务模式": ["阶段任务"],
      "GitHub PR / Issue": null,
    },
  };
  assert.equal(selectTaskForGithubIdentity([staleEarlier, completed, expected], "ou_member"), expected);
  assert.deepEqual(memberTaskPlan([staleEarlier, completed, expected], "ou_member"), { action: "keep", record_id: "rec_stage_11" });
});

test("member reconciliation keeps an active later stage and recovers the missing next stage", () => {
  const completed = {
    record_id: "rec_stage_6",
    fields: {
      "任务名称": "阶段六：接管演练（张三）",
      "状态": ["已完成"],
      "负责人": [{ id: "ou_member", name: "张三" }],
    },
  };
  const active = {
    record_id: "rec_stage_7",
    fields: {
      "任务名称": "阶段七：真实问题改进（张三）",
      "状态": ["进行中"],
      "负责人": [{ id: "ou_member", name: "张三" }],
    },
  };
  assert.deepEqual(memberTaskPlan([completed, active], "ou_member"), { action: "keep", record_id: "rec_stage_7" });
  assert.deepEqual(memberTaskPlan([completed], "ou_member"), { action: "create_next", record: completed, next_stage: 7 });
});

test("stage tasks use a short STAR story and change the mission by stage", () => {
  const stageTwo = stageTaskContent("CodeSense", 2, "张三");
  const stageThree = stageTaskContent("CodeSense", 3, "张三");

  for (const label of ["S：", "T：", "A：", "R："]) assert.match(stageTwo.description, new RegExp(label));
  assert.ok(stageTwo.description.length < 600);
  assert.notEqual(stageTwo.description, stageThree.description);
  assert.match(stageTwo.target, /真实问题/);
  assert.match(stageTwo.acceptance, /PR/);
});
