import test from "node:test";
import assert from "node:assert/strict";
import { evaluateMergeGate, formatGithubReview, isMergedPullRequest, latestCheckRuns, normalizeOpenPullRequests, normalizeReviewResult, reviewMarker } from "../src/github.js";
import { callLuoxin, reviewActionKey, shouldInvokeLuoxin } from "../src/index.js";

test("an approved clean PR with passing checks can pass the merge gate", () => {
  const result = evaluateMergeGate(
    { state: "open", draft: false, head: { sha: "abc" }, mergeable: true, mergeable_state: "clean" },
    { has_checks: true, pending: false, failed: false },
    { decision: "approve", diff_available: true, blocking_findings: [] },
    "abc",
  );
  assert.deepEqual(result, { allowed: true, reasons: [] });
});

test("a conflict or failed check blocks merging", () => {
  const result = evaluateMergeGate(
    { state: "open", draft: false, head: { sha: "abc" }, mergeable: false, mergeable_state: "dirty" },
    { has_checks: true, pending: false, failed: true },
    { decision: "approve", diff_available: true, blocking_findings: [] },
    "abc",
  );
  assert.equal(result.allowed, false);
  assert.deepEqual(result.reasons, ["pull_request_not_mergeable", "mergeable_state_not_ready", "checks_failed"]);
});

test("blocking findings override an accidental approval", () => {
  const result = normalizeReviewResult({ decision: "approve", diff_available: true, blocking_findings: ["请修复 config.js:12 的凭据泄露"] });
  assert.equal(result.decision, "changes_requested");
});

test("an unavailable diff cannot produce an automatic approval", () => {
  const result = normalizeReviewResult({ decision: "approve", diff_available: false });
  assert.equal(result.decision, "comment");
});

test("an explicit review request opens a new review attempt for the same commit", () => {
  const reference = { repository: "XiaoCow666/CodeSense", number: 12 };
  const normalEvent = {
    event_id: "cron-1",
    payload: { repository: reference.repository, number: reference.number },
  };
  const manualEvent = {
    event_id: "feishu-review-1",
    payload: { repository: reference.repository, number: reference.number, force_review: true },
  };

  assert.equal(reviewActionKey(normalEvent, reference, "abc"), "review-engine:XiaoCow666/CodeSense#12:abc");
  assert.equal(reviewActionKey(manualEvent, reference, "abc"), "review-engine:XiaoCow666/CodeSense#12:abc:manual:feishu-review-1");
  assert.notEqual(reviewActionKey(normalEvent, reference, "abc"), reviewActionKey(manualEvent, reference, "abc"));
  assert.equal(reviewMarker("abc"), "<!-- codesense-head:abc -->");
  assert.equal(reviewMarker("abc", "feishu-review-1"), "<!-- codesense-head:abc:attempt:feishu-review-1 -->");
});

test("github review output keeps fixes separate from optional improvements", () => {
  const body = formatGithubReview(
    {
      decision: "changes_requested",
      diff_available: true,
      summary: "需要先修复一个会影响运行结果的问题。",
      blocking_findings: ["配置读取失败时程序会继续使用空值。"],
      requested_changes: ["位置：src/config.js 的 loadConfig；现在：读取失败后继续执行；改成：返回明确错误并停止启动；交给 AI：请执行上述修改并运行 npm test。"],
      non_blocking_findings: ["合并后可以补充一条边界测试。"],
      test_evidence: [],
    },
    "event-1",
    "abc",
  );

  assert.match(body, /需要先处理的问题/);
  assert.match(body, /请按下面的步骤修改/);
  assert.match(body, /合并后可以继续改进的地方/);
  assert.match(body, /codesense-head:abc/);
});

test("a PR without any check result cannot be merged automatically", () => {
  const result = evaluateMergeGate(
    { state: "open", draft: false, head: { sha: "abc" }, mergeable: true, mergeable_state: "clean" },
    { has_checks: false, pending: false, failed: false },
    { decision: "approve", diff_available: true, blocking_findings: [] },
    "abc",
  );
  assert.equal(result.allowed, false);
  assert.deepEqual(result.reasons, ["checks_missing"]);
});

test("completed check-run events can trigger a fresh PR review", () => {
  const event = {
    source: "github",
    event_type: "check_run",
    payload: {
      action: "completed",
      repository: { full_name: "XiaoCow666/CodeSense" },
      check_run: { head_sha: "abc", pull_requests: [{ number: 12 }] },
    },
  };
  assert.equal(shouldInvokeLuoxin({}, event), true);
});

test("hydrated check-run events can trigger a fresh PR review when GitHub omits pull_requests", () => {
  const event = {
    source: "github",
    event_type: "check_run",
    payload: {
      action: "completed",
      repository: { full_name: "XiaoCow666/CodeSense" },
      check_run: { head_sha: "abc", pull_requests: [] },
      pull_request: { number: 12, head: { sha: "abc" } },
    },
  };
  assert.equal(shouldInvokeLuoxin({}, event), true);
});

test("a readable diff keeps an approve decision eligible for the merge gate", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    if (String(url).endsWith(".diff")) return new Response("diff --git a/app.js b/app.js\n", { status: 200 });
    return new Response(JSON.stringify({
      model: "test-model",
      choices: [{ message: { content: JSON.stringify({ decision: "approve", summary: "通过", blocking_findings: [], non_blocking_findings: [], requested_changes: [], test_evidence: [] }) } }],
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const result = await callLuoxin(
      { LUOXIN_API_KEY: "test-key", LUOXIN_BASE_URL: "https://example.test/v1", LUOXIN_MODEL: "test-model" },
      { source: "github", event_type: "pull_request", payload: { repository: { full_name: "XiaoCow666/CodeSense" }, pull_request: { number: 12, head: { sha: "abc" } } } },
    );
    assert.equal(result.diff_available, true);
    assert.equal(result.decision, "approve");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("old failed reruns do not keep a newer successful check red", () => {
  const current = latestCheckRuns([
    { id: 1, name: "build", status: "completed", conclusion: "failure", completed_at: "2026-09-17T01:00:00Z" },
    { id: 2, name: "build", status: "completed", conclusion: "success", completed_at: "2026-09-17T02:00:00Z" },
  ]);
  assert.deepEqual(current, [{ id: 2, name: "build", status: "completed", conclusion: "success", completed_at: "2026-09-17T02:00:00Z" }]);
});

test("online recovery keeps only usable open pull requests", () => {
  assert.deepEqual(
    normalizeOpenPullRequests([
      { number: 12, state: "open", head: { sha: "abc" } },
      { number: null, state: "open", head: { sha: "missing-number" } },
      { number: 13, state: "closed", head: { sha: "closed" } },
    ]),
    [{ number: 12, state: "open", head: { sha: "abc" } }],
  );
});

test("online recovery recognizes a recently merged pull request", () => {
  assert.equal(isMergedPullRequest({ merged_at: "2026-09-18T03:00:00Z" }), true);
  assert.equal(isMergedPullRequest({ merged_at: null, state: "closed" }), false);
});
