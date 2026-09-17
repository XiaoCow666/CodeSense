import test from "node:test";
import assert from "node:assert/strict";
import { evaluateMergeGate, latestCheckRuns, normalizeReviewResult } from "../src/github.js";
import { callLuoxin, shouldInvokeLuoxin } from "../src/index.js";

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
