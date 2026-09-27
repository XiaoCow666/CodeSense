const GITHUB_API_BASE = "https://api.github.com";
const GITHUB_DIFF_BASE = "https://github.com";
const SAFE_CHECK_CONCLUSIONS = new Set(["success", "neutral", "skipped"]);
const SAFE_REPOSITORY = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

function encodeSegment(value) {
  return encodeURIComponent(String(value));
}

function reviewArray(value) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

export function repositoryName(value) {
  const repository = String(value || "").trim();
  if (!SAFE_REPOSITORY.test(repository)) throw new Error("github repository is invalid");
  return repository;
}

export function pullRequestReference(event) {
  const payload = event?.payload || {};
  const repository = payload.repository?.full_name || payload.repository || null;
  const pullRequest = payload.pull_request || payload.issue || payload.check_suite?.pull_requests?.[0] || payload.check_run?.pull_requests?.[0] || {};
  const number = pullRequest.number || payload.number || null;
  if (!repository || !number) return null;
  return { repository: repositoryName(repository), number: Number(number) };
}

export function pullRequestUrl(repository, number) {
  return `https://github.com/${repositoryName(repository)}/pull/${Number(number)}`;
}

function apiError(method, path, status) {
  const category = path.split("?")[0].replace(/^\/repos\//, "repos/");
  return new Error(`github api ${method} ${category} returned ${status}`);
}

export function latestCheckRuns(runs) {
  const latest = new Map();
  for (const run of runs) {
    const key = String(run.name || run.id || "unknown");
    const previous = latest.get(key);
    const runTime = String(run.completed_at || run.started_at || "");
    const previousTime = String(previous?.completed_at || previous?.started_at || "");
    if (!previous || runTime > previousTime || (runTime === previousTime && Number(run.id || 0) > Number(previous.id || 0))) latest.set(key, run);
  }
  return [...latest.values()];
}

export async function githubApi(env, method, path, body) {
  if (!env.GITHUB_API_TOKEN) throw new Error("github api token is not configured");
  const headers = {
    accept: "application/vnd.github+json",
    authorization: `Bearer ${env.GITHUB_API_TOKEN}`,
    "user-agent": "codesense-project-automation",
    "x-github-api-version": "2022-11-28",
  };
  const options = { method, headers };
  if (body !== undefined) {
    headers["content-type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(`${GITHUB_API_BASE}${path}`, options);
  if (!response.ok) throw apiError(method, path, response.status);
  if (response.status === 204) return {};
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`github api ${method} returned invalid json`);
  }
}

export async function githubDiff(env, event) {
  const reference = pullRequestReference(event);
  if (!reference) return { available: false, text: "(pull request reference is unavailable)" };
  const url = `${GITHUB_DIFF_BASE}/${reference.repository}/pull/${reference.number}.diff`;
  const headers = {
    accept: "application/vnd.github.v3.diff",
    "user-agent": "codesense-project-automation",
  };
  if (env.GITHUB_API_TOKEN) headers.authorization = `Bearer ${env.GITHUB_API_TOKEN}`;
  const response = await fetch(url, { headers });
  if (!response.ok) return { available: false, text: `(diff unavailable: GitHub returned ${response.status})` };
  const value = await response.text();
  return { available: value.length > 0, text: value };
}

export async function freshPullRequest(env, reference) {
  const repository = repositoryName(reference.repository);
  const [owner, repo] = repository.split("/");
  return githubApi(env, "GET", `/repos/${encodeSegment(owner)}/${encodeSegment(repo)}/pulls/${Number(reference.number)}`);
}

export async function pullRequestsForHeadSha(env, repository, sha) {
  const normalizedRepository = repositoryName(repository);
  const [owner, repo] = normalizedRepository.split("/");
  const value = await githubApi(env, "GET", `/repos/${encodeSegment(owner)}/${encodeSegment(repo)}/pulls?state=open&per_page=100`);
  if (!Array.isArray(value)) return [];
  return value.filter((pullRequest) => pullRequest?.head?.sha === sha);
}

export function normalizeOpenPullRequests(value) {
  return (Array.isArray(value) ? value : []).filter((pullRequest) => pullRequest?.state === "open"
    && pullRequest.number != null
    && Number.isInteger(Number(pullRequest.number))
    && typeof pullRequest.head?.sha === "string"
    && pullRequest.head.sha.length > 0);
}

export async function listOpenPullRequests(env, repository) {
  const normalizedRepository = repositoryName(repository);
  const [owner, repo] = normalizedRepository.split("/");
  const value = await githubApi(env, "GET", `/repos/${encodeSegment(owner)}/${encodeSegment(repo)}/pulls?state=open&per_page=100&sort=updated&direction=desc`);
  return normalizeOpenPullRequests(value);
}

export function isMergedPullRequest(pullRequest) {
  return pullRequest?.merged === true || Boolean(pullRequest?.merged_at);
}

export async function listMergedPullRequests(env, repository, since) {
  const normalizedRepository = repositoryName(repository);
  const [owner, repo] = normalizedRepository.split("/");
  const pullRequests = [];
  for (let page = 1; ; page += 1) {
    const value = await githubApi(env, "GET", `/repos/${encodeSegment(owner)}/${encodeSegment(repo)}/pulls?state=closed&per_page=100&sort=updated&direction=desc&page=${page}`);
    if (!Array.isArray(value)) throw new Error("GitHub 已关闭 PR 列表格式无效");
    pullRequests.push(...value);
    if (value.length < 100) break;
  }
  const sinceTime = Date.parse(String(since || ""));
  return pullRequests.filter((pullRequest) => isMergedPullRequest(pullRequest)
    && (!Number.isFinite(sinceTime) || Date.parse(String(pullRequest.merged_at || "")) >= sinceTime));
}

export async function commitChecks(env, reference, sha) {
  const repository = repositoryName(reference.repository);
  const [owner, repo] = repository.split("/");
  const [checkRuns, status] = await Promise.all([
    githubApi(env, "GET", `/repos/${encodeSegment(owner)}/${encodeSegment(repo)}/commits/${encodeSegment(sha)}/check-runs?per_page=100`),
    githubApi(env, "GET", `/repos/${encodeSegment(owner)}/${encodeSegment(repo)}/commits/${encodeSegment(sha)}/status?per_page=100`),
  ]);
  const runs = Array.isArray(checkRuns.check_runs) ? checkRuns.check_runs : [];
  const statuses = Array.isArray(status.statuses) ? status.statuses : [];
  const currentRuns = latestCheckRuns(runs);
  const pendingRuns = currentRuns.filter((run) => run.status !== "completed");
  const failedRuns = currentRuns.filter((run) => run.status === "completed" && !SAFE_CHECK_CONCLUSIONS.has(run.conclusion));
  const pendingStatuses = statuses.filter((item) => item.state === "pending");
  const failedStatuses = statuses.filter((item) => item.state !== "success");
  return {
    has_checks: runs.length > 0 || statuses.length > 0,
    pending: pendingRuns.length > 0 || pendingStatuses.length > 0,
    failed: failedRuns.length > 0 || failedStatuses.length > 0,
    check_runs: currentRuns.length,
    statuses: statuses.length,
  };
}

export function normalizeReviewResult(result) {
  const normalized = {
    provider: result?.provider || "",
    model: result?.model || "",
    diff_available: result?.diff_available === true,
    decision: ["approve", "changes_requested", "comment"].includes(result?.decision) ? result.decision : "comment",
    summary: typeof result?.summary === "string" ? result.summary.trim() : "",
    blocking_findings: reviewArray(result?.blocking_findings),
    non_blocking_findings: reviewArray(result?.non_blocking_findings),
    requested_changes: reviewArray(result?.requested_changes),
    test_evidence: reviewArray(result?.test_evidence),
  };
  if (normalized.blocking_findings.length > 0 && normalized.decision === "approve") normalized.decision = "changes_requested";
  if (!normalized.diff_available && normalized.decision === "approve") normalized.decision = "comment";
  return normalized;
}

export function evaluateMergeGate(pr, checks, reviewResult, eventHeadSha) {
  const reasons = [];
  if (!pr || pr.state !== "open") reasons.push("pull_request_not_open");
  if (pr?.draft) reasons.push("pull_request_is_draft");
  if (eventHeadSha && pr?.head?.sha !== eventHeadSha) reasons.push("head_sha_changed");
  if (pr?.mergeable !== true) reasons.push("pull_request_not_mergeable");
  if (!["clean", "unstable"].includes(pr?.mergeable_state)) reasons.push("mergeable_state_not_ready");
  if (checks?.pending) reasons.push("checks_pending");
  if (checks?.failed) reasons.push("checks_failed");
  if (!checks?.has_checks) reasons.push("checks_missing");
  if (!reviewResult || reviewResult.decision !== "approve") reasons.push("review_not_approved");
  if (reviewResult?.diff_available !== true) reasons.push("diff_unavailable");
  if (reviewResult?.blocking_findings?.length > 0) reasons.push("blocking_findings_present");
  return { allowed: reasons.length === 0, reasons };
}

export function reviewMarker(headSha, attemptId = "") {
  const attempt = String(attemptId || "").replace(/[^A-Za-z0-9:_-]/g, "_").slice(0, 80);
  return attempt
    ? `<!-- codesense-head:${String(headSha)}:attempt:${attempt} -->`
    : `<!-- codesense-head:${String(headSha)} -->`;
}

export function formatGithubReview(result, eventId, headSha, attemptId = "") {
  const normalized = normalizeReviewResult(result);
  const lines = ["### CodeSense 自动评审", "", normalized.summary || "已完成必要项检查。"];
  if (normalized.blocking_findings.length > 0) {
    lines.push("", "**需要先处理的问题**", ...normalized.blocking_findings.map((item) => `- ${item}`));
  }
  if (normalized.requested_changes.length > 0) {
    lines.push("", "**请按下面的步骤修改**", ...normalized.requested_changes.map((item) => `- ${item}`));
  }
  if (normalized.non_blocking_findings.length > 0) {
    lines.push("", "**合并后可以继续改进的地方**", ...normalized.non_blocking_findings.map((item) => `- ${item}`));
  }
  if (normalized.test_evidence.length > 0) {
    lines.push("", "**已有验证信息**", ...normalized.test_evidence.map((item) => `- ${item}`));
  }
  lines.push("", `评审事件：${eventId}`, reviewMarker(headSha, attemptId));
  return lines.join("\n").slice(0, 60000);
}

export async function postGithubReview(env, reference, headSha, result, eventId, attemptId = "") {
  const repository = repositoryName(reference.repository);
  const [owner, repo] = repository.split("/");
  const marker = reviewMarker(headSha, attemptId);
  const reviews = await githubApi(env, "GET", `/repos/${encodeSegment(owner)}/${encodeSegment(repo)}/pulls/${Number(reference.number)}/reviews?per_page=100`);
  const existing = (Array.isArray(reviews) ? reviews : []).find((item) => String(item.body || "").includes(marker));
  if (existing) return { posted: false, review_id: existing.id, event: existing.state };
  const normalized = normalizeReviewResult(result);
  const reviewEvent = normalized.decision === "approve" ? "APPROVE" : normalized.decision === "changes_requested" ? "REQUEST_CHANGES" : "COMMENT";
  const response = await githubApi(env, "POST", `/repos/${encodeSegment(owner)}/${encodeSegment(repo)}/pulls/${Number(reference.number)}/reviews`, {
    body: formatGithubReview(normalized, eventId, headSha, attemptId),
    event: reviewEvent,
    commit_id: headSha,
  });
  return { posted: true, review_id: response.id || null, event: reviewEvent };
}

export async function mergeGithubPullRequest(env, reference, headSha) {
  const repository = repositoryName(reference.repository);
  const [owner, repo] = repository.split("/");
  const response = await githubApi(env, "PUT", `/repos/${encodeSegment(owner)}/${encodeSegment(repo)}/pulls/${Number(reference.number)}/merge`, { merge_method: "squash", sha: headSha });
  return { merged: response.merged === true, sha: response.sha || null, message: typeof response.message === "string" ? response.message : "" };
}
