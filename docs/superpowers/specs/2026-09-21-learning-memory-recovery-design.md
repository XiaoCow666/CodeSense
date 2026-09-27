# 学生学习记忆索引恢复与来源治理设计

## 目标与必要性

学生在完成作业后会进入个人学习记忆索引。当前索引已经具备学生范围、作业范围、来源版本、撤回和上一版行数据保留能力，仍有四个会直接影响使用的问题：重复点击更新会重复生成 revision，失败更新后的状态没有完整传递到 AI 回执，撤回历史会持续占用来源列表，教师无法判断班级知识图谱使用的学生数据覆盖情况。

本轮服务学生作业问答、Code Studio AI 辅导和教师知识点教学建议。成功指标如下：

- 来源没有变化时，更新操作保持现有 revision，不重复计算 embedding。
- 单次索引更新遇到可重试的构建异常时最多进行两次尝试；两次都失败时，上一版 active 行继续可检索。
- 经过保留期限的 revoked 行变成 `expired`，仍保留审计元数据，继续排除检索，并能在学生页面区分撤回与过期。
- AI JSON/SSE 证据回执带有 `index_status` 与 `freshness_status`，失败后使用上一版时明确告知学生可以重试。
- 教师只看到其管理班级的聚合覆盖数量，不会读取学生私有来源、正文、向量或学生编号。

## 设计

### 数据与事务

继续使用 `StudentLearningVector` 和 `StudentVectorIndexState` 现有字段，不增加数据库迁移。新增 `expired` 状态作为可逆的软治理状态，保留 `revoked_at`、`revoke_reason`、来源版本和索引 revision。用户撤回在重建和过期之后仍然有效，`expired + user_revoked` 依旧阻止同一来源重新进入 active。

重建先读取当前学生来源并建立来源键集合，再在单个 SQLAlchemy 事务中更新来源行和索引状态。来源没有变化、索引状态可用且索引未陈旧时直接返回当前快照。构建异常执行显式 rollback，写入 `failed` 状态；上一版 active 行不受影响。外层重试只捕获 `StudentVectorRebuildError`，最多两次，不引入无界等待。

### 三条用户流程

1. 学生提交评测后，现有 submission worker 调用有界重试入口刷新本人的学习索引；失败时不影响提交结果。
2. 学生在首页点击更新或重试，页面展示索引状态、当前版本、active 来源数、过期来源数和来源治理状态。学生问答与 Code Studio 继续使用上一版可用数据，并在回执中说明状态。
3. 教师打开仪表盘时获得其管理班级的学习记忆覆盖汇总，入口连接到班级知识覆盖和知识点教学建议；汇总只包含人数和状态数量。

### 状态与权限

- `active` 行才允许进入查询候选；`revoked` 与 `expired` 都排除查询。
- 学生接口只使用当前登录学生的 `student_id`，教师汇总先按管理班级过滤学生，再只读取 `StudentVectorIndexState`。
- 学生来源页面不返回正文和 embedding；教师投影不返回来源 ID、正文、版本和个人状态。
- AI 证据仍然只用于反思引导，不参与分数计算。

### 研究依据与推断边界

- 公开证据：[Qdrant Filtering](https://qdrant.tech/documentation/search/filtering/) 和 [Qdrant Indexing](https://qdrant.tech/documentation/manage-data/indexing/) 说明过滤条件应在向量候选范围中生效，过滤字段需要索引。针对 CodeSense 的推断是继续把学生、作业和 active 状态条件放入 SQL 查询，暂不引入 Qdrant。
- 公开证据：[SQLAlchemy Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html) 说明 flush 失败后必须显式 rollback，rollback 会恢复未提交的对象状态。针对 CodeSense 的推断是把重建行更新保持在一个事务中，失败时继续使用上一版 active 行。
- 公开证据：[WCAG 2.2 Status Messages](https://www.w3.org/TR/WCAG22/#status-messages) 要求状态消息可被辅助技术识别。针对 CodeSense 的推断是将失败、过期和可重试状态放在 `role=status` 或 `role=alert` 区域，并保留键盘可访问的表单按钮。

## 错误处理、恢复与回滚

来源更新失败时，学生提交流程继续完成；索引服务记录失败类型并保留上一版查询能力。学生手动更新最多重试两次，最终失败后显示可再次触发的动作。过期治理只改变状态，不删除数据库行，候选可以通过重新部署父提交恢复代码行为；本轮没有新增迁移和生产数据删除。

回滚方式：恢复本轮代码提交的父提交，在生产目录执行现有 `bash /var/www/codesense/update.sh`，然后复查应用、worker、`/healthz`、`/readyz`、登录入口与学生问答入口。

## 验收

- 单元与服务测试覆盖来源未变化、来源变化、撤回、过期、空索引、失败重试和上一版查询。
- AI API 测试覆盖 JSON 与 SSE 回执字段和失败状态说明。
- 学生页面测试覆盖未建立、已建立、失败重试、过期来源和作用域拒绝。
- 教师测试覆盖管理班级聚合、无管理班级、私有数据不出现在 HTML/JSON。
- 运行完整跟踪测试、compileall、前端脚本语法检查和 `git diff --check`，并完成学生、教师、管理员测试客户端走查。
