import test from "node:test";
import assert from "node:assert/strict";
import { evaluateMergeGate, latestCheckRuns, normalizeReviewResult } from "../src/github.js";
import { callLuoxin, claimAction, shouldInvokeLuoxin } from "../src/index.js";

function actionLogDb(
  existing,
  { insertChanges = 0, updateChanges = 1, stateful = false } = {},
) {
  let row = existing ? { ...existing } : null;
  const statements = [];
  return {
    statements,
    getRow() {
      return row;
    },
    prepare(sql) {
      statements.push(sql);
      return {
        bind(...args) {
          return {
            async run() {
              if (sql.startsWith("INSERT")) return { meta: { changes: insertChanges } };
              if (sql.startsWith("UPDATE")) {
                if (!stateful) return { meta: { changes: updateChanges } };
                const [timestamp, , staleBefore] = args;
                const reclaimable = row && (
                  row.status === "failed" ||
                  (row.status === "running" && row.updated_at <= staleBefore)
                );
                if (!reclaimable) return { meta: { changes: 0 } };
                row = { ...row, status: "running", updated_at: timestamp };
                return { meta: { changes: 1 } };
              }
              throw new Error(`unexpected run: ${sql}`);
            },
            async first() {
              return row;
            },
          };
        },
      };
    },
  };
}

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

test("a stale running action can be reclaimed after a worker interruption", async () => {
  const db = actionLogDb({
    status: "running",
    updated_at: new Date(Date.now() - 16 * 60 * 1000).toISOString(),
  }, { stateful: true });

  assert.equal(
    await claimAction(
      { STATE_DB: db },
      "event-stale",
      "review_engine",
      "review:repo#1:sha-stale",
    ),
    true,
  );
  assert.match(db.statements[2], /status = 'running'/);
  assert.match(db.statements[2], /updated_at <= \?/);
});

test("only the first retry can reclaim the same stale action", async () => {
  const db = actionLogDb({
    status: "running",
    updated_at: new Date(Date.now() - 16 * 60 * 1000).toISOString(),
  }, { stateful: true });

  const firstClaim = await claimAction(
    { STATE_DB: db },
    "event-race",
    "review_engine",
    "review:repo#1:sha-race",
  );
  const secondClaim = await claimAction(
    { STATE_DB: db },
    "event-race-retry",
    "review_engine",
    "review:repo#1:sha-race",
  );

  assert.equal(firstClaim, true);
  assert.equal(secondClaim, false);
  assert.equal(db.getRow().status, "running");
});

test("a recent running action is still owned by the active worker", async () => {
  const db = actionLogDb({
    status: "running",
    updated_at: new Date(Date.now() - 14 * 60 * 1000).toISOString(),
  });

  assert.equal(
    await claimAction(
      { STATE_DB: db },
      "event-recent",
      "review_engine",
      "review:repo#1:sha-recent",
    ),
    false,
  );
  assert.equal(db.statements.length, 2);
});

test("completed actions remain idempotent and are not reclaimed", async () => {
  const db = actionLogDb({ status: "completed", updated_at: new Date().toISOString() });

  assert.equal(
    await claimAction(
      { STATE_DB: db },
      "event-completed",
      "review_engine",
      "review:repo#1:sha-completed",
    ),
    false,
  );
  assert.equal(db.statements.length, 2);
});

test("failed actions keep the existing retry path", async () => {
  const db = actionLogDb({ status: "failed", updated_at: new Date().toISOString() });

  assert.equal(
    await claimAction(
      { STATE_DB: db },
      "event-failed",
      "review_engine",
      "review:repo#1:sha-failed",
    ),
    true,
  );
  assert.match(db.statements[2], /status = 'failed'/);
});
