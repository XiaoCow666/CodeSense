# 全站状态与恢复体验 v1 设计

## 目标

让 CodeSense 在公共页、登录/反馈表单、教师 AI 流式建议和学生评测等待页中都能明确表达“正在做什么、出了什么问题、下一步怎么恢复”，同时保留可追踪但不泄露隐私的请求编号。

## 事实与范围

- 基线：`origin/main=6cb03299f1f30200c78dc35ef28baf15ca84c828`，隔离基线全量测试 `470 passed`。
- 现有应用已经在 access log 中生成服务端 UUID，但响应没有统一回传；`layout.html` 的移动导航没有 Escape/焦点恢复；反馈错误摘要没有把字段错误标到控件；教师 AI 页面通过动态 HTML 拼接模型内容；学生评测页只有自动轮询失败后的重新提交入口。
- 本轮只修改应用层、模板、静态资源和测试；不改变 schema、迁移、权限、provider、模型调用、队列或生产数据。

## 设计决策

### 1. 稳定错误边界

在 Flask 应用层注册 404、405、500 处理器。HTML 请求渲染品牌化恢复页，显示通用说明、返回首页/帮助/反馈入口和当前请求编号；`/api/` 或明确要求 JSON 的请求返回稳定 JSON，包含 `error`、`message` 和 `request_id`。不把异常文本、请求正文或服务端路径发给用户。每个非静态响应通过 `X-Request-ID` 暴露同一个服务端生成的 opaque UUID，拒绝采用客户端自带 ID。

### 2. 共享壳层与可访问状态

两个现存模板壳都声明 SVG favicon。全局提示继续使用 `status`/`alert` 与 `aria-live`，补充 reduced-motion CSS。移动导航关闭时恢复打开前焦点，Escape 和外部点击都使用同一关闭函数。反馈表单为每个失败字段提供 `aria-invalid`、`aria-describedby` 和可聚焦错误摘要。

### 3. AI 与评测恢复语义

教师 AI 建议的状态容器使用 `role=status`、`aria-live=polite`、`aria-busy`；流式失败消息可聚焦、能保留已生成内容并再次触发同一刷新操作，不使用阻断式 `alert()`。动态模型文本统一经过既有 DOMPurify；来自结构化建议的数据先转义为文本。学生评测页用 `progressbar` 反映阶段进度，失败时同时提供“重新检查状态”和“查看提交记录”，不强迫学生重复提交。

## 研究约束

| 来源 | 直接链接与复查日期 | 采用的约束 | CodeSense 差异 |
|---|---|---|---|
| WCAG 2.2 | <https://www.w3.org/TR/WCAG22/>；2026-09-12 | 采用 3.3.1 错误识别、3.3.2 标签/说明、4.1.3 状态消息和可见焦点的验收方向。 | 本轮是局部行为测试，不宣称整站 WCAG 合规。 |
| WAI 对 3.3.1 的解释 | <https://www.w3.org/WAI/WCAG22/Understanding/error-identification>；2026-09-12 | 错误须被具体指认并以文本说明；错误出现时把焦点带到可见的摘要/字段。 | 仅对反馈表单实施，不重写所有历史表单。 |
| Flask 3.1.x 错误处理 | <https://flask.palletsprojects.com/en/stable/errorhandling/>；2026-09-12 | handler 必须显式返回正确 HTTP 状态码；HTML 与 API 错误表示分开。 | 不引入 Sentry 或外部服务。 |
| MDN `aria-live` / `aria-invalid` | <https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Attributes/aria-live>、<https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Attributes/aria-invalid>；2026-09-12 | 非打断状态使用 polite live region；字段格式错误使用 `aria-invalid` 并关联说明。 | 仅使用现有模板/脚本，不引入 ARIA widget 库。 |
| GitHub 通知收件箱 | <https://docs.github.com/en/subscriptions-and-notifications/how-tos/viewing-and-triaging-notifications/managing-notifications-from-your-inbox>；2026-09-12 | 借鉴“状态明确、可预览、可继续处理”的恢复心智模型。 | CodeSense 只做本地提示/恢复，不复制外部通知订阅。 |

## 验收与回滚

- 新增行为先以失败测试证明缺失，再写最小实现；目标测试覆盖 HTML/JSON 错误、请求编号、favicon、导航脚本、反馈字段语义、教师 AI 状态/XSS 防护、学生评测重试。
- 运行目标测试、相关回归、全量 `py -3.13 -m pytest -q`、`py -3.13 -m compileall -q app.py forms.py models.py services routes tasks`、相关 `node --check` 和 `git diff --check`。
- 任何测试不稳定、出现数据库/Redis写入边界或需要线上凭据时停止候选，不修改主工作区。代码可通过逆序 revert 本轮提交回退；没有 schema 变更，不需要数据回滚。
