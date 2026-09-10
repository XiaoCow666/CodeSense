from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARENA_TEMPLATE = (PROJECT_ROOT / "templates" / "thinking" / "arena.html").read_text(encoding="utf-8")
THINKING_JS = (PROJECT_ROOT / "static" / "js" / "thinking.js").read_text(encoding="utf-8")
THINKING_CSS = (PROJECT_ROOT / "static" / "css" / "thinking.css").read_text(encoding="utf-8")


def _slice(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def test_stage3_template_exposes_forum_dom_contract():
    required_ids = (
        'id="stage3-forum"',
        'id="forum-sticky-head"',
        'id="forum-goal-card"',
        'id="forum-goal-progress-bar"',
        'id="forum-goal-steps"',
        'id="forum-feed"',
        'id="forum-target-teacher"',
        'id="forum-target-student"',
        'id="forum-target-auto"',
        'id="forum-input"',
        'id="forum-send"',
        'id="forum-reply-context"',
    )

    for marker in required_ids:
        assert marker in ARENA_TEMPLATE

    assert 'class="forum-feed"' in ARENA_TEMPLATE
    assert 'class="forum-reply-context"' in ARENA_TEMPLATE
    assert "position: sticky" in THINKING_CSS
    assert "top: 0" in THINKING_CSS
    assert "translate3d(0, -2px, 0)" in THINKING_CSS
    assert "backdrop-filter: blur(10px)" in THINKING_CSS


def test_stage3_target_controls_remain_in_the_sticky_header():
    sticky_block = _slice(
        ARENA_TEMPLATE,
        '<div class="forum-sticky-head"',
        '<div class="forum-feed"',
    )

    assert 'class="forum-toolbar"' in sticky_block
    assert 'class="forum-goal-card"' not in sticky_block
    assert ".forum-sticky-head" in THINKING_CSS
    assert "bindForumStickyHead" in THINKING_JS
    assert "const scrollTargets = [feed, panelBody].filter" in THINKING_JS
    assert "requestAnimationFrame(updateStickyState)" in THINKING_JS
    assert "classList.toggle('is-scrolled', isScrolled)" in THINKING_JS


def test_stage3_uses_the_right_rail_for_dynamic_goal_and_moves_guide_below_forum():
    goal_panel_block = _slice(
        ARENA_TEMPLATE,
        'id="stage3-goal-panel"',
        'id="student-agent-panel"',
    )
    forum_block = _slice(
        ARENA_TEMPLATE,
        'id="stage3-forum"',
        '<div class="forum-feed"',
    )

    assert 'id="forum-goal-card"' in goal_panel_block
    assert 'id="forum-goal-card"' not in forum_block
    assert 'stage3-guide-drawer' in ARENA_TEMPLATE
    assert ARENA_TEMPLATE.index('id="student-agent-panel"') > ARENA_TEMPLATE.index('</div><!-- .arena-body -->')
    assert "grid-template-columns: minmax(0, 1fr) minmax(320px, 420px)" in THINKING_CSS
    assert "#stage3-goal-panel" in THINKING_CSS
    assert "#stage3-goal-panel .forum-goal-steps" in THINKING_CSS
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in THINKING_CSS
    assert "stage3-guide-drawer" in THINKING_CSS
    assert "goalPanel.classList.add('active')" in ARENA_TEMPLATE
    assert "tabRightBtn.textContent = '学习任务'" in ARENA_TEMPLATE


def test_stage3_target_controls_default_to_auto_with_visible_and_aria_state():
    teacher_button = _slice(
        ARENA_TEMPLATE,
        '<button type="button" class="forum-target-btn" id="forum-target-teacher"',
        '</button>',
    )
    student_button = _slice(
        ARENA_TEMPLATE,
        '<button type="button" class="forum-target-btn" id="forum-target-student"',
        '</button>',
    )
    auto_button = _slice(
        ARENA_TEMPLATE,
        '<button type="button" class="forum-target-btn is-selected" id="forum-target-auto"',
        '</button>',
    )

    assert 'data-target-role="teacher_agent"' in teacher_button
    assert 'aria-pressed="false"' in teacher_button
    assert 'data-target-role="student_agent"' in student_button
    assert 'aria-pressed="false"' in student_button
    assert 'data-target-role="auto"' in auto_button
    assert 'aria-pressed="true"' in auto_button
    assert ".forum-target-btn.is-selected" in THINKING_CSS
    assert '.forum-target-btn[aria-pressed="true"]' in THINKING_CSS


def test_send_forum_message_posts_only_the_public_routing_payload():
    request_block = _slice(
        THINKING_JS,
        "const requestPayload = {",
        "const userEvent = sanitizeForumEvent({",
    )

    assert "session_id: state.sessionId" in request_block
    assert "message: message" in request_block
    assert "target_role: targetRole" in request_block
    assert "reply_to_event_id: replyToEventId" in request_block
    assert "request_id: requestId" in request_block
    assert "history" not in request_block
    assert "messages" not in request_block
    assert "JSON.stringify(requestPayload)" in THINKING_JS


def test_stage3_forum_renders_one_primary_reply_with_reply_context_and_action():
    assert "payload.primary" in THINKING_JS
    assert "payload.interventions" not in THINKING_JS
    assert "forum-role" in THINKING_JS
    assert "forumRelationLabel" in THINKING_JS
    assert "forum-reply-action" in THINKING_JS
    assert "reply_to_event_id" in THINKING_JS
    assert "message_kind" in THINKING_JS
    assert "payload.user_goal" in THINKING_JS
    assert "renderForumUserGoal" in THINKING_JS


def test_stage3_forum_keeps_model_failures_visible_instead_of_dropping_empty_replies():
    assert "function forumFallbackText(payload)" in THINKING_JS
    assert "safeForumText(payload.primary, forumFallbackText(payload.primary))" in THINKING_JS
    assert "当前暂时无法生成回复，请稍后重试。" in THINKING_JS


def test_student_probe_switches_the_selected_target_to_student_agent():
    assert "primaryEvent.message_kind === 'student_probe'" in THINKING_JS
    assert THINKING_JS.count("setForumTarget('student_agent')") >= 1
    assert "forum_state.target_role === 'student_agent'" in THINKING_JS


def test_forum_uses_one_current_turn_and_exposes_auto_arbitration():
    assert "function requestStudentProbe()" not in THINKING_JS
    assert "'/thinking/api/stage3/forum/student-probe'" not in THINKING_JS
    assert "target_role: targetRole" in THINKING_JS
    assert "id=\"forum-target-auto\"" in ARENA_TEMPLATE
    assert "按当前内容决定谁先回应" in ARENA_TEMPLATE
    assert "interventions.forEach" not in THINKING_JS


def test_buggy_code_and_ui_action_open_the_existing_repair_area():
    assert "payload.ui_action === 'show_code_review'" in THINKING_JS
    assert "payload.user_goal.status === 'ready_for_code'" in THINKING_JS
    assert "state.forumUserGoal.status === 'ready_for_code'" in THINKING_JS
    assert "triggerCodeWritingPhase();" in THINKING_JS
    assert "showCodeReviewPanel(payload.buggy_code)" in THINKING_JS
    assert "triggerCodeWritingPhase()" in THINKING_JS
    assert "id=\"code-review-section\"" in ARENA_TEMPLATE


def test_browser_state_and_forum_rendering_stay_on_public_fields_only():
    sanitize_block = _slice(
        THINKING_JS,
        "function sanitizeForumEvent(rawEvent, options = {}) {",
        "function normalizeForumTargetRole(role) {",
    )

    assert "state.forumHistory = sanitizePublicForumHistory(data.forum_history || [], { persisted: true });" in THINKING_JS
    assert "state.forumHistory = [...state.forumHistory, sanitized].slice(-MAX_PUBLIC_FORUM_EVENTS);" in THINKING_JS

    for forbidden in (
        "tool_call",
        "tool_arguments",
        "internal_signals",
        "artifact",
        "decision",
        "reference_code",
        "hidden_code",
        "full_history",
    ):
        assert forbidden not in sanitize_block


def test_successful_forum_send_reconciles_with_public_history_only():
    send_block = _slice(
        THINKING_JS,
        "function sendForumMessage(options = {}) {",
        "function sendTeacherChat() {",
    )
    reconcile_block = _slice(
        THINKING_JS,
        "function reconcileForumHistory(localRequestId) {",
        "function mergeReconciledForumHistory(",
    )

    assert "return reconcileForumHistory(requestId).catch(() =>" in send_block
    assert "fetchJSON('/thinking/api/start_session'" in reconcile_block
    assert "assignment_id: state.assignmentId" in reconcile_block
    assert "String(data.session_id) !== String(state.sessionId)" in reconcile_block
    assert "data.forum_history" in reconcile_block
    assert "sanitizePublicForumHistory(\n                data.forum_history,\n                { persisted: true }\n            )" in reconcile_block
    assert "state.teacherHistory" not in reconcile_block
    assert "state.studentHistory" not in reconcile_block
    assert "mergeReconciledForumHistory(\n                persistedHistory,\n                localHistory,\n                localRequestId\n            )" in reconcile_block


def test_reply_actions_and_reply_payload_require_persisted_event_ids():
    node_block = _slice(
        THINKING_JS,
        "function createForumEventNode(event) {",
        "function applyForumTurnPayload(",
    )
    reply_block = _slice(
        THINKING_JS,
        "function setForumReplyContext(event) {",
        "function clearForumReplyContext() {",
    )

    assert "if (isPersistedForumEvent(sanitized))" in node_block
    assert "function isSyntheticForumEventId(eventId)" in THINKING_JS
    assert "forum-welcome-" in THINKING_JS
    assert "local-" in THINKING_JS
    assert "const replyToEventId = getPersistedForumReplyEventId();" in THINKING_JS
    assert "if (!sanitized || !isPersistedForumEvent(sanitized)" in reply_block
    assert "return isPersistedForumEvent(currentEvent) ? currentEvent.event_id : null;" in THINKING_JS
