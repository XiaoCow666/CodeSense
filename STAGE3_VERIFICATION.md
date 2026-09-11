# 阶段三验证说明

本文记录当前 `main` 中阶段三学习闭环的可复现验证入口。本文只描述现有实现和测试覆盖，不引入数据库结构、权限策略或生产部署变更。

## 变更范围

- 对话与教学入口：`POST /thinking/api/stage3/chat`、`/teach`；
- 覆盖度评估与代码准备门禁：`/write_code`；
- 修复提交与评估：`/fix_code`；
- 会话归属、活动阶段、请求去重、事件恢复，以及公开响应不泄露内部工具结果。

阶段三要求学习会话属于当前登录用户且处于活动阶段；代码生成还要求覆盖度达到门槛。本文不改变这些规则。

## 本地验证

在项目根目录执行：

```powershell
python -m pytest tests/test_stage3_coverage.py tests/test_stage3_agent_contracts.py tests/test_stage3_agent_memory.py tests/test_stage3_agent_loop.py tests/test_stage3_agent_routes.py tests/test_stage3_agent_tools.py tests/test_stage3_goal.py tests/test_stage3_forum_contracts.py tests/test_stage3_forum_intent.py tests/test_stage3_forum_memory.py tests/test_stage3_forum_orchestrator.py tests/test_stage3_forum_restore.py tests/test_stage3_forum_routes.py tests/test_stage3_forum_trace.py tests/test_stage3_forum_ui.py -q
```

这组测试覆盖阶段三的核心状态机、代理契约、记忆与事件恢复、路由门禁、论坛编排及前端契约。测试使用替身模型和临时数据库，不需要真实 AI provider 或生产数据库。

## 验证边界

已由源码和测试直接证实：

- 非所有者不能访问阶段三会话，且运行时不会在归属检查前创建；
- 客户端不能通过提交历史或学生状态覆盖服务端状态；
- 未达到覆盖门禁时不会生成待修复代码；
- 重放相同请求不会重复执行生成器或追加重复事件；
- 隐藏的工具参数、内部信号和修复答案不会进入公开响应；
- 修复结果会持久化，并按评估结果更新阶段三完成状态。

本验证不声称已经证实真实 AI provider 的网络、限流、计费或返回质量，也不覆盖数据库迁移、生产部署和真实浏览器端到端流程。这些属于后续集成验证或安全边界事项。

## 环境备注

全量测试还需要 `requirements-test.txt` 中声明的依赖可从当前包源安装；若包源无法提供 `rq==2.11.0`，应先恢复依赖安装，再执行全量测试。该环境问题不影响上述阶段三定向测试。
