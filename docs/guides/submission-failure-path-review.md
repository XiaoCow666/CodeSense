# 提交失败路径的维护复盘检查法

这份检查法用于评审提交入口、后台评测和失败状态处理的连续改动。重点不是判断某个函数名是否"看起来重复"，而是从调用者入口追到状态写入，再用同一条用户可见路径验证结果。

## 规则来源：PR #65

历史记录：[PR #65](https://github.com/XiaoCow666/CodeSense/pull/65)，合并提交 `b8e4072`。

### 触发

提交评测有一个失败状态转换函数。路由入口调用公开的 `mark_submission_failed`，这个函数又转调 `_mark_submission_failed`；评测内部的队列不可用路径和异常路径直接调用私有函数。两个名称指向同一份数据库更新逻辑，调用者却需要记住两条入口。

### 处理

合并改动把数据库更新实现保留在 `mark_submission_failed`，删除只负责转发的 `_mark_submission_failed`，并让评测内部的两条路径也调用公开函数。路由层的导入和调用方式不变。

代码事实可以用下面的命令复核：

```powershell
git show --stat --oneline b8e4072
git show b8e4072 -- tasks/submission_tasks.py
```

### 验证

这类整理的验收点不是"函数数量变少"本身，而是两件事同时成立：

* 所有调用者仍能到达同一个失败状态转换；
* 失败状态、提示文本、数据库提交时机和状态查询结果保持不变。

因此，复盘时要把静态调用者检查和一条真实入口测试放在一起。只跑导入检查，不能证明路由异常路径仍然写回失败状态。

## 可复用的五步检查

1. 先写调用者契约。记录谁触发路径、输入是什么、用户最终读取哪个状态或提示。
2. 列出定义、导入和调用者。用 `rg` 搜索函数名和旧函数名，不凭文件名推断调用范围。
3. 画出状态变化。至少写清入口、服务或任务、数据库字段、状态接口四个位置；标出异常分支和提交点。
4. 选一条兼容约束。对本类改动，约束是原有失败状态和错误提示不变，且状态接口仍返回同一个终态。
5. 用两类证据验收。先用搜索命令确认调用图符合意图，再运行一条会穿过入口、状态写回和反馈读取的回归测试。

这条规则的判断顺序是：先确认调用契约，再决定是否能合并重复层；不能因为两个函数名字相似，就直接删除其中一个。

## 新例子：评测无法启动

这是对上述方法的独立演练，不是 PR #65 的重复说明。

### 触发和处理

`routes/assignments.py` 的学生提交入口调用 `evaluate_submission_async`。当评测无法启动时，入口捕获异常并调用 `mark_submission_failed`。该函数把提交状态写为 `failed`，保存"后台评测启动失败，请稍后重试。"，并提交数据库会话。

### 按检查法核对调用图

在主线提交 `5b8ac14` 上执行：

```powershell
rg -n "^def mark_submission_failed\(" tasks/submission_tasks.py
rg -n "_mark_submission_failed" tasks routes tests
```

判定：第一条只找到一个公开定义；第二条无输出，说明私有转发层没有残留引用。

### 真实入口验证

测试命令：

```powershell
$taskPython = 'C:\Users\1\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$taskPyPath = 'C:\Users\1\Desktop\新建文件夹\CodeSense-latest-analysis\.venv-codesense\Lib\site-packages'
$env:PYTHONPATH = $taskPyPath
& $taskPython -c "import pytest; raise SystemExit(pytest.main(['-q', 'tests/test_submission_api_queue.py::test_regular_form_marks_submission_failed_when_evaluation_cannot_start']))"
```

实测结果：`1 passed, 15 warnings in 11.23s`。

这个测试同时检查：

* 提交入口在评测启动异常后仍然重定向回提交页；
* 数据库中的提交状态是 `failed`；
* 反馈是"后台评测启动失败，请稍后重试。"；
* 提交状态接口也返回 `failed`。

因此，静态搜索验证了调用者只有一条失败状态入口，真实入口测试验证了用户可见的终态没有改变。

## 事实、推断和边界

事实：PR #65 的合并提交删除了私有转发函数，主线保留 `mark_submission_failed` 作为失败状态更新入口；新例子的目标测试在上述隔离 Python 环境中通过。

复盘推断：统一函数入口降低了维护者追踪失败状态路径的成本，但它不等于证明所有异步执行环境都可用。

本检查法没有验证真实 Redis 服务、生产数据库并发、跨进程异常、部署配置或权限策略。涉及这些边界的改动仍需要对应环境的专项验证。

## 提交前清单

* 是否能指出用户入口和最终读取状态的代码位置？
* 是否搜索过定义、导入和全部调用者？
* 是否记录了异常分支、状态字段和数据库提交点？
* 是否写明不能改变的兼容行为？
* 是否有一条穿过真实入口和状态反馈的自动化测试？
* 是否把环境缺失、弃用警告和未验证的生产边界单独记录？
