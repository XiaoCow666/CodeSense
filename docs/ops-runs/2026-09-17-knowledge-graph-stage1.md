# CodeSense 2026-09-17 第一阶段运行报告：知识图谱学习路径投影

## 阶段边界

本阶段目标是把现有作业知识点和学生知识点评分投影为权限受控的学习路径，接入学生首页和教师仪表盘。今天不新增生产数据库表、不接外部向量服务、不把共同出现关系包装成前置依赖；学生向量库留到下一阶段。

候选工作树：`E:\CodeSense\源代码\.worktrees\knowledge-graph-stage1-20260917`
候选分支：`codex/knowledge-graph-stage1-20260917`
基线：`origin/main=52acab2`
融合基线提交：`019b77c`
计划提交：`eba9147`

## 主工作区改动融合清单

主工作区在开始时落后远端 30 个提交，并有 48 个 tracked 文件修改和 2 个未跟踪文件。所有改动均保留在主工作区原位，并复制到候选工作树进行融合；没有执行 reset、checkout、clean 或未经授权的 stash。

| disposition | paths | 处理 |
| --- | --- | --- |
| fused | `models.py`; `routes/main.py`; `routes/thinking.py`; `routes/users.py`; `services/course_grading.py`; `services/demo_experience.py`; `services/teacher_analytics.py`; `static/modern.css`; `tasks/submission_tasks.py`; `utils/ability_scorer.py`; `utils/code_evaluator.py`; `utils/maturity_calculator.py`; `utils/scoring.py` | 评分规范化、统计和演示数据改动进入候选，保留为后续图谱基础 |
| fused | `templates/admin_dashboard.html`; `templates/admin_profile.html`; `templates/all_submissions.html`; `templates/api_docs.html`; `templates/assign_form.html`; `templates/assignment_detail.html`; `templates/assignments.html`; `templates/classes/class_assignment_stats.html`; `templates/classes/class_comparison.html`; `templates/classes/class_detail.html`; `templates/classes/class_list.html`; `templates/grades.html`; `templates/profile.html`; `templates/s_assignments.html`; `templates/sprofile.html`; `templates/student_details.html`; `templates/student_home.html`; `templates/submission_detail.html`; `templates/submission_history.html`; `templates/submissions.html`; `templates/teacher_assignments.html`; `templates/teacher_home.html`; `templates/users.html` | 0–100 展示、学生快照、题库批量入口和相关页面改动进入候选 |
| fused | `tests/test_course_grading.py`; `tests/test_demo_database_isolation.py`; `tests/test_demo_experience.py`; `tests/test_demo_guided_learning.py`; `tests/test_demo_profile_views.py`; `tests/test_demo_submission_isolation.py`; `tests/test_student_home_history.py`; `tests/test_submission_review_collaboration.py`; `tests/test_submission_worker.py`; `tests/test_teacher_ai_suggestions.py`; `tests/test_teacher_analytics.py`; `tests/test_question_bank_features.py` | 测试和新增题库覆盖进入候选 |
| conflict-resolved | `routes/api.py`; `routes/assignments.py` | 最新 RAG/证据导入与用户评分规范化/题库导入合并；未丢弃任一侧的有效功能 |

## 基线验证

```text
pytest tests/test_question_bank_features.py tests/test_teacher_analytics.py tests/test_demo_experience.py tests/test_student_home_history.py -q --disable-warnings
13 passed, 70 warnings in 16.14s

compileall: exit 0
git diff --check: exit 0
```

警告尚未作为失败处理；后续若影响图谱流程会单独分类。评分规范化与题库改动在图谱阶段不得回归。

## 图谱交付记录

待完成：图谱服务、学生/教师路由入口、共享模板、真实角色走查、完整回归、必要性结论和回滚判断。

## 回滚方式

本阶段新增内容只应是服务、路由上下文、模板、样式和测试；回滚时移除对应候选提交即可，不需要生产 schema 回滚。主工作区不属于候选回滚范围。
