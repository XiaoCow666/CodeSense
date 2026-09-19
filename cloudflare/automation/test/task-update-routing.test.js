import test from "node:test";
import assert from "node:assert/strict";
import { taskCompletionState, taskUpdateActionKey } from "../src/index.js";

test("an approved review completes the task before GitHub merge conditions are ready", () => {
  assert.equal(
    taskCompletionState({ review: { decision: "approve" }, merge: { merged: false } }),
    "已完成",
  );
  assert.equal(
    taskCompletionState({ review: { decision: "changes_requested" }, merge: { merged: false } }),
    "进行中",
  );
});

test("an earlier unlinked task update gets a bounded retry key", () => {
  const outcome = {
    repository: "XiaoCow666/CodeSense",
    number: 61,
    headSha: "abc123",
    review: { decision: "approve" },
    merge: { merged: false },
    gate: { reasons: ["pull_request_not_mergeable"] },
  };
  assert.equal(
    taskUpdateActionKey(outcome, null, 100),
    "task-pr:XiaoCow666/CodeSense#61:abc123:approve:pull_request_not_mergeable",
  );
  assert.equal(
    taskUpdateActionKey(outcome, { matched: false, reason: "task_not_linked" }, 100),
    "task-pr:XiaoCow666/CodeSense#61:abc123:approve:pull_request_not_mergeable:link-retry:100",
  );
});
