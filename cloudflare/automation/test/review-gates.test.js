import test from "node:test";
import assert from "node:assert/strict";
import { evaluateMergeGate, normalizeReviewResult } from "../src/github.js";

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
