# RAG Evidence Recovery and Quality Loop

## Status

Approved for this autonomous run by the standing CodeSense daily iteration brief.

## Goal

Make assignment-scoped knowledge retrieval understandable and recoverable across the student Code Studio, teacher/admin assignment views, API consumers, and the admin quality surface, without changing the answer-generation model, permission boundaries, or database schema.

## Evidence and design constraints

- [WCAG 2.2](https://www.w3.org/TR/WCAG22/) requires status messages to be programmatically exposed, keyboard focus to remain visible, and pointer targets to remain usable. The UI therefore uses live regions, explicit buttons/links, visible focus, and user-triggered retry only.
- [OpenTelemetry semantic-convention guidance](https://opentelemetry.io/docs/specs/semconv/how-to-write-conventions/) warns against unbounded attribute values. Quality data will use a fixed status/mode vocabulary and bounded counters/latency samples; no query, student identifier, answer, prompt, or exception text crosses the quality endpoint.
- [Lewis et al. RAG](https://arxiv.org/abs/2005.11401) motivates explicit non-parametric evidence and provenance. [Self-RAG](https://arxiv.org/abs/2310.11511) supports retrieving when useful and abstaining when evidence is unavailable; CodeSense will expose an explicit answer-only state rather than inventing citations.
- [GitHub Copilot research/plan/review workflow](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/research-plan-iterate) and [Replit checkpoint previews](https://docs.replit.com/updates/2025/05/16/changelog) are product references for visible state, reviewable output, and recovery. CodeSense adapts the state/retry pattern only; it does not add code mutation, checkpoints, or autonomous student completion.

## Current facts

The current remote baseline is `origin/main=7dccdfd`, which adds Stage 13 in-memory RAG reliability controls. Its raw retrieval layer already emits `timeout` and `rate_limited`, but the public evidence projection still accepts only `grounded`, `no_result`, and `unavailable`; this turns the two new safe fallbacks into `unknown` for API consumers. The student ask-question SSE envelope also lacks the structured `knowledge_evidence` view that the Code Studio renderer expects, while the assignment panel has no explicit retry affordance.

## Design

### 1. Stable evidence state boundary

The public projection accepts exactly six states: `grounded`, `no_result`, `unavailable`, `timeout`, `rate_limited`, and `unknown`. The last state is reserved for malformed or missing input. Each state has bounded, plain-language status copy and a safe fallback code. The existing answer-only fallback remains intact.

The public retrieval envelope gains only bounded fields already produced by the reliability layer: `retrieval_timeout_fallback`, `rate_limit_fallback`, `index_revision`, `privacy_filtered_count`, and `citation_completeness`. Teacher/admin evidence views may show bounded diagnostics; student views receive status and evidence only.

### 2. Cross-surface response contract

`/api/ask_question` returns the same `knowledge_evidence` view in JSON and in the `done` SSE event, at both `data.knowledge_evidence` and the legacy top-level position. Existing `knowledge_retrieval` and rendered receipt text remain for compatibility. Code advice keeps its current shape.

### 3. Recovery interaction

The server-rendered assignment and submission panels receive a GET retry link to the existing non-cacheable evidence endpoint. The Code Studio dynamic receipt receives a user-triggered “重新检索证据” button when the status is retryable. The button is disabled while fetching, reports progress in a live region, updates the receipt in place, and never includes query text, student data, or HTML from the response. `no_result` keeps a learning-oriented next step rather than promising a retry will create evidence.

### 4. Teacher/admin visibility

Teacher/admin diagnostics show candidate/hit counts, index chunks, revision, privacy-filtered count, latency, citation completeness, and retrieval mode. These fields are capped by the existing projection and are explicitly labeled as retrieval diagnostics, never grading evidence.

Admins receive a no-store `GET /api/admin/knowledge-quality` endpoint and a dashboard card with loading, available, empty, and unavailable states. The endpoint exposes only the in-process bounded quality snapshot and static configured limits, not raw content or user identity.

### 5. Observability and failure handling

RAG request logs include the fixed status/fallback/mode fields and the new bounded revision/privacy flags, while continuing to omit query, code, answer, prompt, and exception text. Dashboard/API failures remain non-blocking and render a truthful unavailable state. No database, Redis, queue, provider, permission, or deployment configuration changes are part of this slice.

## Independent acceptance items

1. Timeout/rate-limited states survive public projection.
2. Fallback copy clearly distinguishes timeout, rate limiting, unavailable, and no-result states.
3. New reliability metrics survive the safe response projection.
4. JSON ask-question responses include the evidence view.
5. SSE ask-question done events include the evidence view.
6. Server-rendered evidence panels expose explicit retry links.
7. Code Studio receipts expose accessible, safe retry controls.
8. Teacher/admin diagnostics expose bounded quality details.
9. Admin quality endpoint enforces role/no-store/privacy boundaries.
10. Admin dashboard renders live quality states and refreshes explicitly.
11. RAG logs include stable low-cardinality outcome fields without sensitive content.
12. Help content explains evidence boundaries and answer-only recovery.

## Error, privacy, and rollback boundaries

- Retry is a GET read and does not mutate application data; it can be rolled back by removing the UI control and projection additions.
- Missing/forbidden assignment behavior stays 403 and non-enumerating.
- Student pages never receive diagnostics or process-wide counters.
- Admin metrics are process-local observations, not production SLA claims.
- No migration or external service is required; rollback is a code-only revert to `7dccdfd`.

## Verification strategy

- Write failing projection/API/SSE/UI contract tests before production edits.
- Run focused knowledge tests, route/access tests, JavaScript syntax checks, `compileall`, and `git diff --check`.
- Run the tracked full regression suite from the isolated worktree.
- Run an authenticated local browser smoke for student, teacher, and admin surfaces when the local browser harness is available; otherwise record the exact environment limitation.
