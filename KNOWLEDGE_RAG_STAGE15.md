# 阶段十五：真实学生入口集成与失败可恢复路径

能力主题键：`CodeSense:knowledge-rag:stage15`

## 真实入口

本次选择学生代码工作台的聊天入口：

```text
学生打开 /submit/<assignment_id>
  -> submit_code.html 的 sendToAI()
  -> POST /api/code_advice（SSE）
  -> assignment-scoped knowledge retrieval
  -> AI done/error 事件
  -> 页面显示回答和知识证据回执
```

阶段十四已经让 `/api/code_advice` 使用可预算的 RAG provider，并在成功的 `done` 事件中返回安全的 `knowledge_evidence`。本阶段关注真实使用中的失败边界：流式 AI 在已经输出部分内容后中断时，旧前端会吞掉 `error` 事件，只留下空白状态，且用户看不到本次检索是否成功。

## 改动

- `routes/api.py`：代码建议 SSE 的空回答、LLM 流中断和未知异常都通过同一失败事件构造器返回；如果本次请求有作业知识证据，则以现有安全投影同时放在事件顶层和 `data` 中。没有作业上下文时不新增跨作业检索数据。
- `templates/submit_code.html`：不再吞掉 SSE 错误。前端停止继续消费失败流，将错误交给统一失败处理，向学生显示可理解的错误信息，并保留已经得到的知识证据回执。正常 `done` 和旧的非流式响应路径保持不变。
- `tests/test_code_advice_knowledge.py`：补充真实 `/api/code_advice` SSE 中断集成测试，验证回答失败时证据状态仍可见。
- `tests/test_knowledge_evidence_integration.py`：验证学生提交页包含证据回执挂载点、流中断提示和错误状态传递钩子。

## 事实与边界

已验证：真实 Flask 登录会话、作业权限、作业级知识检索、`/api/code_advice` SSE 成功路径和中断路径；中断时不会把私有评分或 prompt 放入公开事件。

未验证：真实外部 AI provider、浏览器端真实网络断线、生产 Redis、生产数据库和部署环境。浏览器仍可能在 TCP 断开时无法取得服务端错误事件，此时由页面已有的网络异常提示兜底。

## 回滚与复现

回滚本次提交即可恢复原前端和 SSE 事件行为；不涉及数据库结构、权限、部署和核心成功响应字段。

在隔离 worktree 中运行：

```powershell
python -m pytest tests/test_code_advice_knowledge.py tests/test_knowledge_evidence_integration.py -q --disable-warnings
python -m pytest -q --disable-warnings
```

实际结果：集成测试 `7 passed`；全量测试 `749 passed`，退出码 0，耗时约 17 分 17 秒。Python 静态编译、`git diff --check` 和 10 个不含 Jinja 占位符的页面脚本块语法校验均通过；含 Jinja 变量的 1 个脚本块需在 Flask 渲染后校验。

测试结果和 commit SHA 也会写入 PR 描述及任务台验证结果。

## 后续风险

1. 真实浏览器断网和代理中断仍需补端到端演练。
2. 生产 provider 的成本、超时和全局配额仍属于阶段十四未决边界。
3. 任务完成仍需 PR 评审和隔离验证通过。
