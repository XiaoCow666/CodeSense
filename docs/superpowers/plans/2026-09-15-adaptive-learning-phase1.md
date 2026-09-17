# 自适应掌握度学习闭环：Phase 1 只读建议基础

## 目标与变更范围

本阶段在学生首页增加一张“自适应下一步”卡片。它从当前账号已经可见的、当前未截止作业、最近三阶段学习会话、知识点掌握度和最近提交摘要中，按固定规则给出一个可解释的下一步入口。

- 新增 `services/adaptive_learning.py`：纯函数、无 Flask/数据库/网络/AI 依赖。
- `routes/main.py` 在既有学生与班级范围查询之后调用该函数；操作 URL 仅由服务端按已有 endpoint 生成。
- `templates/student_home.html` 显示建议、证据和边界说明。
- `tests/test_adaptive_learning.py` 覆盖优先级、无证据回退、隐私输出边界和首页集成。

本阶段不增加 API、角色、表、字段、索引、迁移、后台任务、模型调用、生产配置或外部通知。

## 规则与事实边界

推荐优先级是确定性的：

1. 继续当前有效作业上可恢复的三阶段会话。
2. 在至少一次已有练习、掌握度低于 70 分的知识点中，匹配带有该知识点标签的当前作业。
3. 复练当前有效作业中最近一条失败、部分通过或得分低于 60 分的提交。
4. 开始一份尚无提交记录的当前有效作业。
5. 没有当前证据时转到作业列表，并明确不对真实掌握情况作推断。

事实：作业有效性、会话可恢复状态、知识点得分/次数、提交状态与得分均为已有持久数据的只读投影。建议内容不读取或输出提交代码、评语、AI 输出、会话对话内容或学生标识。

推断：低于 70 分且已有练习记录被标记为“优先巩固”，只是可复核的排序规则，不是对学习能力、成绩或教学效果的判断。没有记录时不把 0 分解释为薄弱。

## 安全与权限边界

- 输入仍由 `/home` 既有 `login_required`、当前学生 ID、权威班级与 `assignment_target_class_filter` 限定；服务层不扩大查询范围。
- 只对 `active_assignment_ids` 中的作业生成操作建议；会话和提交再次按该集合过滤。
- 跳转 URL 不由数据库文本或推荐服务提供：`thinking.arena`、`assignments.submit_code` 和 `assignments.student_assignments` 三种既有服务端路由按动作类型生成。
- 没有新写入，因此不存在计划持久化、跨学生读取、教师覆盖、权限提升或可回滚数据清理问题。
- 未读取 `.env`、未接触凭据、未执行真实 AI、沙箱、Redis、生产部署或数据库结构操作。

## 验证命令与预期证据

本机没有仓库运行指南中提到的 `student-eval` Conda 环境，因此验证使用工作区内、Git 忽略的 Python 3.13 `.venv`。该环境只安装仓库声明的运行/测试依赖；为运行仓库既有 `template_rendered` 测试而额外安装的 `blinker` 仅存在于该隔离环境，未修改依赖清单。

实际执行：

```powershell
\.venv\Scripts\python.exe -m pytest tests/test_adaptive_learning.py -q --disable-warnings
\.venv\Scripts\python.exe -m pytest tests/test_student_home_history.py -q --disable-warnings
\.venv\Scripts\python.exe -m pytest tests/test_session_lifecycle_routes.py -q --disable-warnings
\.venv\Scripts\python.exe -m compileall -q services/adaptive_learning.py routes/main.py tests/test_adaptive_learning.py
git diff --check
```

结果：新增自适应测试 `6 passed`；既有学生首页历史统计 `1 passed`；既有会话连续性路由 `7 passed`；`compileall` 与 `git diff --check` 均以 0 退出。pytest 同时报告了仓库既有依赖/`datetime.utcnow` 等大量 warning；本阶段未通过忽略或改写警告来掩盖它们。

全量 `pytest -q --disable-warnings` 的事实边界：

- 第一次：`686 passed, 1 failed`，失败在未改动的 AI/SSE 测试导入 OpenAI 前；根因是 `.venv` 中 CPython 3.11 的 `pydantic_core` 扩展与 Python 3.13 不兼容。
- 修复隔离环境中已声明的二进制依赖后，AI/SSE 原测试单独为 `1 passed`。
- 第二次：`686 passed, 1 failed`，失败为未改动的 RQ 提交 worker 集成测试。该次全量运行中该测试意外尝试真实 LLM provider 并遇到鉴权失败，随后同一测试单独重跑为 `1 passed`。

因此可以复核的结论是：本阶段新增与相邻回归共 `14 passed`，全量其余 `686` 项在第二次运行通过，唯一失败项单独复核通过；但尚未获得一次单进程、无波动的 `687 passed` 全量输出。这个 worker/真实 provider 耦合是现有测试隔离风险，不是本阶段改动；仍应由 CI 或人工评审复跑全量门禁。

验收证据包括：纯函数优先级测试、首页模板中建议与服务器生成 URL 的断言、既有学生首页历史统计与会话连续性回归、Python 编译和 diff 空白检查。测试使用临时 SQLite 文件；不连接主开发数据库或生产数据库。

## 回滚与下一阶段门槛

回滚仅需撤销本阶段提交；没有迁移、后台状态或已保存学习计划需要恢复。

下一阶段若要保存推荐历史、让教师覆盖推荐、写入掌握度规则版本，或根据推荐闭环统计效果，将触及数据模型和权限语义。届时必须先提交：数据最小化方案、迁移/回滚方案、角色授权矩阵、历史数据兼容策略、隔离测试数据库验证和人工审批；在批准前不得直接写入这些状态。
