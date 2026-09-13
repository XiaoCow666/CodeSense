# 提交复核协作 v1 设计

## 目标

把学生的代码提交、AI 评估、教师复核、学生追问和再次行动连接在同一个提交详情页中。首版只使用已有 `SystemLog` 与站内通知能力，不新增表、不迁移数据、不调用模型、不接外部邮件或短信 provider。

## 证据与设计约束

- [WCAG 2.2](https://www.w3.org/TR/WCAG22/) 要求键盘可操作、焦点顺序保持含义、标题/标签清晰，并把状态消息作为可感知但不打断的反馈；因此复核表单使用原生控件、可见标签和 `role="status"`，移动端不依赖悬停。
- [GitHub notifications inbox filters](https://docs.github.com/en/subscriptions-and-notifications/reference/inbox-filters) 与 [about notifications](https://docs.github.com/en/subscriptions-and-notifications/concepts/about-notifications) 将“被分派、评论、状态变化”作为通知原因，并允许未读/已读分拣。CodeSense 只借鉴原因和状态的心智模型，通知仍是本地站内通知，不复制订阅、邮件和 mention。
- [Exploring the Potential of Large Language Models to Generate Formative Programming Feedback](https://arxiv.org/abs/2309.00029) 提醒教育者：LLM 对初学者的反馈可能有帮助，也可能误导，因此 UI 把 AI 反馈标为起点，提供“有帮助/需要澄清”和教师复核入口，不把模型结论直接变成教师评价。

以上是证据；针对 CodeSense 的推断是：现有提交详情已经是学生和教师共同可见的最稳定交汇点，故用一个受权限保护的事件线程承载协作，比新建业务表或分散到普通通知正文更容易回退和审计。

## 数据与权限边界

复核事件写入 `SystemLog`，`log_type="提交复核"`，JSON `schema_version=1`，字段包括 `event`、`review_id`、`submission_id`、`actor_id`、`actor_role`、`body`、`status`、`created_at`。正文是用户主动提交的业务内容，不写入观测日志；长度限制 2,000 字符。AI 反馈信号使用独立的 `log_type="AI反馈信号"`，每个学生和提交只保留一条最新信号。

参与者只有提交学生、其所属班级教师和管理员。教师必须通过学生的 `class_id` 命中自己管理的班级；不能只凭提交 ID 或作业创建者放行。页面和消息不会增加邮箱、学号、班级或代码快照的展示范围。

复核状态为 `requested → in_review → waiting_student → resolved`。教师/管理员可以把 `requested` 置为 `in_review`，把 `in_review` 置为 `waiting_student` 或 `resolved`，把 `waiting_student` 置为 `in_review`；学生回复会把 `waiting_student` 或 `resolved` 重新置为 `in_review`。跳级、重复状态和学生直接改状态都被拒绝。每次状态变化写审计事件。

## 端到端流程

1. 学生在提交详情点击“申请教师复核”，填写具体困惑；同一提交再次点击返回同一 `review_id`，不重复创建请求。
2. 受管班级教师在“复核队列”按状态查看请求，打开提交详情后可回复、推进状态或解决；管理员可查看全部。
3. 教师回复后学生收到带提交详情链接的站内通知；学生回复/申请复核后受管教师收到通知。通知使用 `review_id + event_id` 幂等键。
4. 提交详情展示按时间排序的事件摘要和当前状态；只向有权限的参与者显示正文。
5. 学生可对 AI 评估选择“有帮助/需要澄清”，信号仅供后续教学评估，不修改分数或触发新的模型调用。

## 路由与回退

- `POST /submission/<id>/review/request`：提交人创建或复用复核请求。
- `POST /submission/<id>/review/message`：参与者追加一条消息，自动按角色更新状态。
- `POST /submission/<id>/review/status`：教师/管理员执行有限状态转换。
- `GET /teacher/reviews`：教师看自己班级、管理员看全部的复核队列。
- `POST /submission/<id>/ai-feedback-signal`：提交学生更新 AI 反馈信号。

所有新写入失败时回滚并给出可恢复提示；旧提交没有复核事件时仍按原页面渲染。删除候选提交即可回到 parent，历史 `SystemLog` 保留且旧版本忽略新类型。

## 验收

- 单元/路由测试覆盖状态机、幂等、权限、通知归属、开放重定向、旧提交兼容和 AI 信号 upsert。
- 浏览器验收覆盖学生申请、教师队列、教师回复、学生回复/重开、标记已解决、通知收件箱和移动焦点/标签。
- 运行候选全量 pytest、compileall、Node `--check`、`git diff --check`；不修改线上数据库、Redis、服务、凭据或服务器未提交改动。
