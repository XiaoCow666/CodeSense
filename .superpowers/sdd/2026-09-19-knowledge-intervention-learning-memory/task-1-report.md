# Task 1 report

日期：2026-09-19

## 变更文件

- `services/student_vector_store.py`
  - 新增 `list_student_learning_sources(student_id)`。
  - 通过 `_student_id` 校验学生身份，只查询 `student_private` 来源。
  - 返回有界摘要字段：来源类型、来源编号、作业编号、标题、作用域、状态、短版本号、时间戳和撤回原因。
  - 使用稳定排序和数量上限，未返回 `content` 或 `embedding`。
- `routes/main.py`
  - 首页传入 `student_learning_sources`。
  - 新增登录学生专用的 `POST /student/learning-memory/revoke`。
  - 缺少表单字段时返回首页并提示；其他学生来源与未知编号使用相同响应；本人来源调用现有 `revoke_student_vector_source`。
- `templates/components/student_learning_memory.html`
  - 在学生首页展示来源版本摘要和当前状态。
  - 为仍处于 active 状态的本人来源提供撤回表单。

## 测试

- `E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_student_vector_store.py -q`
  - 结果：`13 passed, 44 warnings`。
- `E:\anaconda\envs\student-eval\python.exe -m compileall -q services/student_vector_store.py routes/main.py`
  - 结果：通过。
- `git diff --check`
  - 结果：通过。
## 关注事项

- 未新增数据库字段或迁移。
- 候选工作区已有改动均保留；来源投影、撤回隐私和陈旧索引均有对应测试。
- 陈旧索引、失败重建和来源生命周期均已纳入同一候选的向量服务回归；来源投影、自身撤回、跨学生隐私和首页入口均通过验收。
