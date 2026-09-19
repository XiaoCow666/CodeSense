# Task 1 brief

Work in the current candidate worktree `E:\CodeSense\源代码\.worktrees\weak-point-guidance-20260919`. Read this file first; it is the exact requirement for this task.

Implement the student learning-source projection and self-revocation route from the 2026-09-19 plan.

Required files:

- `services/student_vector_store.py`
- `routes/main.py`
- `tests/test_student_vector_store.py` already contains the red tests.

Required behavior:

- Add `list_student_learning_sources(student_id)`.
- Validate the student scope through the existing `_student_id` boundary.
- Return bounded metadata only: `source_type`, `source_id`, `assignment_id`, `title`, `scope`, `status`, a short `source_version`, timestamps, and revoke reason. Do not return `content` or `embedding`.
- Keep results scoped to the requested student and deterministically ordered.
- Add a logged-in student-only POST route at `/student/learning-memory/revoke`.
- Read `source_type` and `source_id` from form data, reject missing input, reject non-student actors with the existing home redirect pattern, and keep another student's source indistinguishable from an unknown source.
- Use the existing `revoke_student_vector_source` service so `user_revoked` survives future rebuilds.
- The home route must pass `student_learning_sources` to the student template context.
- Preserve the existing rebuild route and old response fields.

Constraints:

- Use `apply_patch` for edits.
- Do not add database fields or migrations.
- Do not add mocks or fake data.
- Run the focused vector tests after implementation.
- Write a report to `.superpowers/sdd/2026-09-19-knowledge-intervention-learning-memory/task-1-report.md` with changed files, test command/output, and concerns.
