import test from "node:test";
import assert from "node:assert/strict";
import {
  nextStageForCompletedRecord,
  nextStageEligibility,
  parseStageNumber,
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

test("stage tasks use a short STAR story and change the mission by stage", () => {
  const stageTwo = stageTaskContent("CodeSense", 2, "张三");
  const stageThree = stageTaskContent("CodeSense", 3, "张三");

  for (const label of ["S：", "T：", "A：", "R："]) assert.match(stageTwo.description, new RegExp(label));
  assert.ok(stageTwo.description.length < 600);
  assert.notEqual(stageTwo.description, stageThree.description);
  assert.match(stageTwo.target, /真实问题/);
  assert.match(stageTwo.acceptance, /PR/);
});
