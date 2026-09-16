# 作业知识证据工作区设计规格

## 目标

把现有的作业范围知识检索结果变成学生、教师和 AI 都能理解的“证据工作区”：用户能知道回答参考了什么、没有找到证据时该怎么继续，教师能看到覆盖与降级诊断；所有结果仍严格限制在当前作业、当前用户可访问的范围内。

这是一项表现层与交互层优化，不改变已有评分、提交、权限判定和知识检索算法的语义。第一版只消费 `services/knowledge_rag.py` 已提供的检索结果，不新增数据库表、迁移、外部 embedding、LLM 请求或跨作业索引。

## 已确认的系统边界

- `retrieve_assignment_knowledge()` 已经提供 assignment-scoped、最多 64 个索引文档和最多 8 条最终证据的安全检索结果。
- `KnowledgePointScore` 中的私有评分不属于用户可见证据，任何新的服务、API、模板和日志都不得读取或暴露它。
- `/api/ask_question` 已有知识收据；本次补齐作业详情、提交详情和 Code Studio `/api/code_advice` 的一致投影。
- 分析/检索失败必须保持 answer-only 降级，不能阻断代码提交或 AI 对话。
- 新增响应字段只做 additive change；现有 `answer`、`content`、`advice`、SSE 事件顺序和权限契约保持兼容。
- 新 API 必须使用 `Cache-Control: no-store`；未授权和不存在的作业返回同一个 403 形态，避免资源枚举。
- 查询文本只用于本次请求，最长 2000 字符；证据条数只能是 1–8 的正整数。
- 日志只记录角色、作业 ID、状态、模式、候选/命中数量和耗时，不记录问题、代码、姓名、证据正文或私有评分。

## 交互设计

### 视觉方向

证据面板是页面中唯一需要被快速识别的“解释性对象”，采用深色墨蓝标题、蓝色证据标记、纸白内容底和青绿色成功状态；警告/无结果使用克制的琥珀色。沿用项目现有字体与图标，不引入字体、UI 框架或图标依赖，不使用渐变和大面积营销卡片。

- 墨蓝：`#14213D`
- 证据蓝：`#2F80ED`
- 纸白：`#F7FAFC`
- 成功青：`#0F766E`
- 恢复提示琥珀：`#B45309`

面板内容左对齐，正文行宽控制在约 80 个字符内；边框、焦点环和对比度满足 WCAG 2.2。动态状态使用 `role="status"` 和 `aria-live="polite"`，动画在 `prefers-reduced-motion: reduce` 下关闭。

### 三类受众

- 学生：标题为“作业知识焦点”，展示知识点、证据标题/摘要、当前状态和一个具体的下一步；失败时明确“回答仍可继续，但没有可引用证据”。
- 教师/管理员：同一证据内容加上候选数、命中数、索引块数、检索模式和耗时等诊断；不显示学生私有评分。
- 提交详情：标题为“这道作业使用的知识焦点”，加注“这是 AI/知识检索参考，不是本次评分依据”，避免把知识证据误解为评分理由。

### 状态模型

安全投影服务只允许以下面向用户的状态：

| 原始结果 | 用户状态 | 学生下一步 | 教师提示 |
| --- | --- | --- | --- |
| `grounded` | 已找到作业知识证据 | 点击证据详情，把问题与对应概念联系起来 | 检查命中/覆盖与检索模式 |
| `no_result` | 暂无匹配证据 | 缩小问题、查看作业知识焦点或继续普通提问 | 检查作业是否绑定知识点 |
| `unavailable` | 证据暂时不可用 | 继续查看 AI 指导，稍后重试 | 查看降级模式与耗时 |
| 缺失/未知 | 证据状态不可用 | 继续使用基础指导 | 只显示安全的未知状态 |

原始 `fallback.code` 仅作为稳定机器字段返回；模板和前端使用白名单标签、摘要和下一步，不直接把异常消息呈现给用户。

## 数据流与接口

### 安全显示投影

新增 `services/knowledge_evidence.py`：

```python
def build_knowledge_evidence_view(
    retrieval: Mapping[str, Any] | None,
    *,
    audience: str = "student",
) -> dict[str, Any]: ...
```

返回稳定结构：`status`、`status_label`、`summary`、`next_step`、`has_evidence`、`fallback_code`、`retrieval_mode`、`evidence`；每条证据只保留 `evidence_id`、`citation`、`title`、`content`、`source_label`、`created_at`。`teacher`/`admin` 才增加 `diagnostics`，其中只有整数计数、有限检索模式和非负耗时。任何未列入白名单的原始键都被丢弃。

### 证据 API

新增受保护接口：

```text
GET /api/assignments/<assignment_id>/knowledge-evidence
  ?q=<optional question>&limit=<1..8>
```

成功响应同时提供兼容所需的原始 `knowledge_retrieval` 和模板/前端使用的 `knowledge_evidence`。请求会按当前用户角色生成投影。未登录返回现有认证错误；不存在或无权作业统一 403；参数错误 400；成功和参数错误都不能缓存。

### Code Studio

当 `/api/code_advice` 收到作业 ID 时，使用用户问题（分析模式为空查询）调用同一个 assignment-scoped 检索器。聊天模式把有限的 `build_knowledge_prompt_context()` 追加到现有用户提示，明确“只使用给定证据，不得编造引用”；不额外调用模型。SSE `done` 和非流式 JSON 添加 `knowledge_retrieval`、`knowledge_evidence`，局部 `delta` 事件不携带证据，确保浏览器只在回答完成后渲染收据。

## 页面落点

- `assignment_detail.html`：学生看到知识焦点与证据；教师/管理员看到同一面板的覆盖诊断。
- `submit_code.html`：AI 助手顶部显示当前作业知识焦点，并根据前 3 条证据生成可点击的引导式快速提问；动态回答完成后在该回答下渲染证据收据。
- `submission_detail.html`：显示作业知识焦点和“不是评分依据”边界说明。
- 新增 `templates/components/knowledge_evidence.html`、`static/css/knowledge-evidence.css`、`static/js/knowledge-evidence.js`。Jinja 和 JavaScript 都必须使用转义/`textContent`，不把知识正文当 HTML。

## 失败恢复与隐私

无结果和不可用都保留 AI 基础回答能力，并提供不同的解释和下一步；前端处理空 payload、未知状态、SSE 缺字段和非 200 响应，不显示堆栈或后端异常。证据 API 使用 no-store，动态视图不写入 localStorage。作业访问检查必须在检索前完成；没有 assignment ID 时不创建跨作业检索。

## 验收与验证

每项实现先增加失败测试，再写最小代码；至少运行对应测试文件、相关现有知识/AI 测试、编译/语法检查和 `git diff --check`。完成前运行固定离线知识评估，确认原有 Recall@1、Recall@k 和模式分布没有回归，并记录全量测试中已知的正式 worker 会话缓存失败，不把它误报为本次功能回归。

固定质量依据：

- [WCAG 2.2](https://www.w3.org/TR/WCAG22/)，尤其是错误识别、标签/说明、错误建议和状态消息相关成功标准。
- [Understanding SC 3.3.3: Error Suggestion](https://www.w3.org/WAI/WCAG22/Understanding/error-suggestion.html)，用于无结果/不可用状态的下一步提示。
- [GitHub Copilot code review](https://docs.github.com/en/copilot/concepts/agents/code-review)，用于“回答之外还要让用户看见审查结果与下一步”的交互参照。
- [GitHub Copilot code referencing](https://docs.github.com/en/copilot/concepts/completions/code-referencing)，用于证据来源可见性与引用完整性参照。
- [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)，用于“生成回答与非参数证据分离、并向用户暴露来源”的数据流依据。

## 不在本次范围

不增加 schema/migration，不改评分或评测结论，不接外部 embedding/provider，不修改生产服务器配置，不展示私有知识点分数，不实现跨作业个人知识画像，不把检索证据宣称为评分依据。
