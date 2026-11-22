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

## 2026-11-22 互动完成机制自测记录

- 测试时间：2026-11-22 14:38-14:44（Asia/Shanghai）
- 代码基线：`main` / `a9f5601e787ddc55641b74695b0f747c702e9100`
- 测试对象：工作区内尚未提交的阶段三互动完成机制改动

本次确认正式学生和体验账户均可通过以下任一条件完成阶段三引导学习：

- 覆盖 3 个关键知识点；
- 累计 4 次由服务端判定为有效的提问；
- 在消息间隔不超过 3 分钟的前提下持续有效交流 10 分钟，间隔超过 3 分钟后重新计算连续交流时长。

自动化回归测试使用项目 `.venv`、Python 3.14.4、Node.js v24.12.0、隔离的临时 SQLite 数据库及 `instance/runtime-temp`，没有写入正式学生数据库，也没有修改现有提交成绩。执行范围为全部 `test_stage3*.py`，以及体验账户引导学习、数据隔离、资料页和会话生命周期测试：

```powershell
$env:TEMP='C:\Users\1\Desktop\dachuang\CodeSense\instance\runtime-temp'
$env:TMP=$env:TEMP
$env:PYTHONIOENCODING='utf-8'
$stage3Tests = Get-ChildItem -LiteralPath tests -Filter 'test_stage3*.py' | ForEach-Object { $_.FullName }
$extraTests = @(
  'tests\test_demo_guided_learning.py',
  'tests\test_demo_database_isolation.py',
  'tests\test_demo_profile_views.py',
  'tests\test_session_lifecycle.py',
  'tests\test_session_lifecycle_routes.py'
)
& .venv\Scripts\python.exe -m pytest $stage3Tests $extraTests -q
```

测试结果：`321 passed, 7263 warnings in 308.64s (0:05:08)`，退出码为 0。警告主要来自 Flask-WTF、Flask-Session、Python 3.14 日期时间弃用提示、SQLAlchemy 旧接口和 pytest 测试类收集提示；没有测试因此失败。

通过的行为包括：4 次有效提问触发完成；无意义、重复和寒暄消息不计数；10 分钟连续有效交流触发完成；3 分钟中断后重新计时；知识点覆盖规则仍然生效；完成状态、完成时间和阶段通过记录同步更新；正式学生与体验账户均启用；作业列表显示“引导学习已完成”，但不伪造代码提交成绩；前端显示完成进度并关闭已完成会话的输入。

同时执行以下静态检查，均以退出码 0 通过：

```powershell
.venv\Scripts\python.exe -m py_compile services\stage3_engagement.py routes\thinking.py routes\assignments.py utils\agents\goal.py tests\test_stage3_engagement.py tests\test_stage3_forum_routes.py tests\test_stage3_forum_ui.py tests\test_stage3_goal.py
node --check static\js\thinking.js
git diff --check
```

本次执行的是相关功能回归测试，不是整个仓库的全量测试。当前 5000 端口服务需要重启后才会加载改动，因此尚未在用户当前浏览器会话中进行人工点击验收。本次没有提交或推送 Git 变更。

## 互动完成机制安全边界

### 保护对象

本机制保护的是阶段三完成状态、经过验证的 `stage_pass` 记录和作业列表中的“引导学习已完成”标记。代码提交成绩是独立数据，不会因为互动完成而被正式账户伪造或提高。

### 不可信输入

以下内容均由浏览器或学生控制，服务端不得直接据此完成阶段三：

- `session_id`、`request_id`、目标 Agent 和回复目标；
- 消息正文、消息长度、重复请求和发送频率；
- 客户端声明的提问次数、活跃时长、知识点覆盖数、完成状态或判定元数据；
- 页面显示的进度、按钮状态和浏览器本地时间。

客户端额外提交 `effective_question_count`、`active_seconds`、`stage3_completed` 或 `engagement_assessment` 等字段时，路由不会读取这些字段作为完成依据。

### 服务端可信依据

只有以下证据可以推进完成状态：

- 登录态、学生角色、会话所有权和作业访问权均通过后，由服务端写入的阶段三学生消息事件；
- 服务端生成的事件时间，用于计算 3 分钟消息间隔和 10 分钟连续交流；
- 服务端覆盖度工具产生的 3 个关键知识点覆盖结果；
- 来源为 `server_stage3_engagement`、版本匹配的服务端有效性判定；无来源、旧版本或浏览器伪造的判定会根据已持久化消息重新计算；
- 带 `validated: true` 的服务端 `stage_pass` 记录。

### 强制执行规则

- 阶段三接口要求已登录学生，先检查会话所有权、作业访问权和当前活动阶段，再构建 Agent 运行时。
- 正式账户只有处于阶段三、阶段二已完成且状态为 `in_progress` 的会话可以触发互动完成。
- 有效消息必须与编程任务或服务端作业上下文相关。随机字符串、低信息重复字符、无关问题、简单寒暄、重复内容和超过 2000 字符的消息不计入完成进度。
- 判定基于服务端已保存的消息正文。相同 `request_id` 被重放时，新请求正文不能改写原事件的有效性。
- 10 分钟路径只使用有效消息的服务端时间；相邻有效消息间隔超过 3 分钟即重置当前连续时段。
- 完成操作在数据库会话行锁内重新读取状态，并检查是否已有经过验证的通过记录；重复调用不会创建第二条 `stage_pass`。
- 前端只展示服务端返回的进度，不拥有完成权限。隐藏按钮、修改 JavaScript 或伪造 JSON 都不能直接改变服务端完成状态。
- 体验账户使用临时数据隔离。公开体验可使用专用快进入口，但该入口只允许当前体验会话；正式账户在非调试环境不能使用它绕过学习条件。
- CSRF 由应用全局保护，测试环境才关闭。公开响应继续过滤内部工具参数、标准答案和私有 Agent 信号。

### 明确不承诺的范围

- 规则判定是可解释的启发式判断，不等同于教师对学习质量的最终评价，也不应用作正式成绩。
- 本机制降低简单刷次数和伪造客户端状态的风险，但不声称能够识别所有语义改写、多人代答或自动生成的相关问题。
- 数据库管理员权限、服务器代码被篡改、账号凭据被盗等属于更高层安全事件，不由本完成机制单独防护。
- 单机 SQLite 自测不能证明生产环境的多进程并发效果；生产数据库需要支持事务和行锁，并保持数据库、会话、缓存及体验账户运行数据隔离。
- 接口级限流、WAF、异常账号检测和审计告警属于部署层防滥用措施，不以互动完成计数替代。

### 安全回归要求

后续修改至少要保留以下测试：未登录拒绝、跨账户会话拒绝、客户端完成字段无效、无关和低信息消息不计数、超长消息不计数、重复请求不能重分类、非活动阶段不能完成、重复完成只有一条验证记录、体验账户数据隔离及公开响应不泄露私有字段。

### 2026-11-22 安全加固复测

- 测试时间：2026-11-22 14:55-15:01（Asia/Shanghai）
- 定向安全测试：`22 passed, 250 warnings in 57.41s`
- 阶段三、体验账户隔离和会话生命周期整组测试：`327 passed, 7251 warnings in 301.32s (0:05:01)`
- Python 编译检查、JavaScript 语法检查和 `git diff --check`：全部通过，退出码均为 0

本次新增回归覆盖客户端伪造完成字段、任务相关性、低信息和超长内容、服务端判定来源、非活动阶段完成拦截、重复请求正文替换以及完成记录幂等。警告类型与前次自测一致，没有新增测试失败。本次仍未代替生产数据库并发压测、部署层限流验证或浏览器人工验收。
