# CodeSense 纯色界面改版实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 CodeSense 的自有页面改为统一的纯色、轻量、适应窄屏的界面，并修复 AI 编程助手的拥挤排版。

**Architecture:** 继续使用 Flask/Jinja、Bootstrap 和现有 JavaScript。通过共享语义色变量及现有模板宏实现可复用组件；页面局部 CSS 只承担布局和具体内容展示。保持原有路由与数据接口不变。

**Tech Stack:** Flask、Jinja2、CSS、原生 JavaScript、pytest、浏览器视觉检查。

**Spec:** `docs/superpowers/specs/2026-10-01-flat-ui-refresh-design.md`

## Global Constraints

- 自有产品 CSS/模板不得保留 `linear-gradient(` 或 `radial-gradient(`；不修改第三方 vendor 文件。
- 设计色：页面 `#F5F7F8`、表面 `#FFFFFF`、主文字 `#23343D`、次文字 `#64757D`、线条 `#DDE5E6`、操作 `#237B75`、强调浅底 `#EAF4F2`、输入浅底 `#F0F3F3`。
- 不新增 React 构建或运行时；保持现有服务端渲染及 AI 聊天功能。
- 重点检查 1440、768、390、320 CSS 像素宽度。

## Review Focus

1. 知识证据为空或检索失败时，紧凑面板仍显示下一步与重试入口。
2. 长代码、表格、URL 和中文段落在 AI 回复中不撑破侧栏。
3. 展开证据后来源与引用均可读，键盘可操作。
4. 流式输出、快捷问题、发送与清空按钮保持可用。
5. 对比度、焦点样式和减少动画偏好在浅色界面仍清晰。

---

### Task 1: 共享视觉基础

**Files:**
- Modify: `static/modern.css`
- Modify: `templates/layout.html`
- Test: `tests/test_flat_ui_contract.py`

**Interfaces:**
- Produces CSS variables `--cs-bg`, `--cs-surface`, `--cs-ink`, `--cs-muted`, `--cs-line`, `--cs-accent`, `--cs-accent-soft`, `--cs-input` for subsequent page CSS.

- [ ] **Step 1: Write a failing static contract test** in `tests/test_flat_ui_contract.py` that reads `static/modern.css` and asserts the exact semantic variable/value pairs below. Check shared button, focus, surface and body rules reference these variables.

```python
EXPECTED = {
    "--cs-bg": "#F5F7F8", "--cs-surface": "#FFFFFF",
    "--cs-ink": "#23343D", "--cs-muted": "#64757D",
    "--cs-line": "#DDE5E6", "--cs-accent": "#237B75",
    "--cs-accent-soft": "#EAF4F2", "--cs-input": "#F0F3F3",
}
```
- [ ] **Step 2: Run** `python -m pytest tests/test_flat_ui_contract.py -q`; expect failure from missing variables.
- [ ] **Step 3: Implement** the variables in `:root` and replace general navigation, button, card, form and focus colors with semantic variables. Preserve existing layout and semantic error/success states.
- [ ] **Step 4: Run** the contract test and `python -m pytest tests/test_app.py -q`; inspect failures before proceeding.
- [ ] **Step 5: Commit** `static/modern.css`, `templates/layout.html`, and the test.

### Task 2: AI 助手和知识证据

**Files:**
- Modify: `templates/submit_code.html`
- Modify: `templates/components/knowledge_evidence.html`
- Modify: `static/css/knowledge-evidence.css`
- Modify: `static/css/codesense-markdown.css`
- Test: `tests/test_knowledge_evidence_ui.py`
- Test: `tests/test_flat_ui_contract.py`

**Interfaces:**
- Consumes Task 1 CSS variables.
- Keeps `knowledge_evidence_panel(...)` macro signature and existing chat element IDs used by JavaScript.

- [ ] **Step 1: Add a failing UI contract test** asserting the compact knowledge panel contains `<details` and `<summary`, retains `knowledge-evidence-retry`, `knowledge-evidence-citation`, and `knowledge-evidence-detail__source`, and that the submit page retains `id="ai-chat-messages"`, `id="ai-chat-input"`, `id="ai-send-button"`, and `id="clear-chat"`.
- [ ] **Step 2: Run** `python -m pytest tests/test_knowledge_evidence_ui.py tests/test_flat_ui_contract.py -q`; expect new assertions to fail.
- [ ] **Step 3: Implement** the flat assistant header, compact evidence summary, full-width assistant messages, restrained prompt buttons, flexible code/editor columns and mobile stacking. Use `min-width: 0`, wrapping and local overflow for code and tables. Leave full evidence mode unchanged.
- [ ] **Step 4: Run** the two contract suites plus `python -m pytest tests/test_submission_knowledge_views.py -q`.
- [ ] **Step 5: Check** the page at 1440, 768, 390 and 320 widths in a browser, with evidence expanded and a long AI answer. Repair observed overflow or clipped controls.
- [ ] **Step 6: Commit** the scoped changes.

### Task 3: 全站纯色迁移

**Files:**
- Modify: `static/css/action-center.css`, `static/css/thinking.css`, `static/modern.css`
- Modify: all first-party templates currently containing gradients, as enumerated by `git grep -l -i -E 'linear-gradient\\(|radial-gradient\\(' -- 'static/*.css' 'static/**/*.css' 'templates/*.html'` excluding `static/vendor/`
- Test: `tests/test_flat_ui_contract.py`

**Interfaces:**
- Consumes Task 1 CSS variables. No route or JavaScript API changes.

- [ ] **Step 1: Extend the failing contract test** to scan first-party CSS and templates for `linear-gradient(` and `radial-gradient(`, excluding `static/vendor/`; print offending file paths and line numbers. Use `Path.rglob` rooted at `static` and `templates`, and `re.compile(r"(?:linear|radial)-gradient\\(", re.I)`.
- [ ] **Step 2: Run** `python -m pytest tests/test_flat_ui_contract.py -q`; expect the gradient scan to fail.
- [ ] **Step 3: Replace** each gradient by a solid semantic color: page sections use `var(--cs-bg)`, cards `var(--cs-surface)`, primary buttons `var(--cs-accent)`, selected or informational sections `var(--cs-accent-soft)`, and input areas `var(--cs-input)`. Handle hover states, overlays, inline styles and pseudo elements. Preserve semantic warning/danger colors. Remove decorative gradient-only pseudo elements instead of substituting an opaque block.
- [ ] **Step 4: Run** the gradient scan to zero findings, then inspect at least login, student home, teacher home, class detail, feedback and admin profile at desktop and narrow widths.
- [ ] **Step 5: Commit** first-party CSS/templates and the test.

### Task 4: Final behavior and visual verification

**Files:**
- Modify only files where verification finds defects.

**Interfaces:**
- Validates all prior tasks.

- [ ] **Step 1: Run** `git diff --check` and targeted UI suites (`tests/test_flat_ui_contract.py`, `tests/test_knowledge_evidence_ui.py`, `tests/test_submission_knowledge_views.py`, `tests/test_status_recovery_ui.py`).
- [ ] **Step 2: Inspect** key pages and controls at 1440, 768, 390 and 320 widths. Verify no horizontal overflow, readable text, visible keyboard focus, working evidence expansion and chat interactions.
- [ ] **Step 3: Compare** the code submission page with the approved Figma desktop and mobile frames; record any deliberate deviations.
- [ ] **Step 4: Repair concrete defects, rerun only the checks affected by those repairs, and commit the final verified state.

## Handoff

The implementation stays on `codex/flat-ui-refresh` in the isolated worktree. Do not merge, deploy, or overwrite the user's dirty main checkout during this plan.
