from datetime import datetime, timedelta

from services.stage3_engagement import (
    ASSESSMENT_SOURCE,
    ASSESSMENT_VERSION,
    MAX_ENGAGEMENT_MESSAGE_CHARS,
    assess_stage3_message,
    summarize_stage3_engagement,
)


def _event(index, content, created_at, assessment=None):
    metadata = {}
    if assessment is not None:
        metadata["engagement_assessment"] = assessment.to_metadata()
    return {
        "id": index,
        "content": content,
        "created_at": created_at,
        "metadata": metadata,
    }


def test_effective_question_rejects_filler_small_talk_and_duplicates():
    filler = assess_stage3_message("好的")
    small_talk = assess_stage3_message("你今天的天气怎么样？")
    first = assess_stage3_message("为什么循环条件要写成 i 小于 n？")
    request = assess_stage3_message("请解释一下循环边界的作用")
    duplicate = assess_stage3_message(
        "为什么循环条件要写成 i 小于 n？",
        previous_messages=["为什么循环条件要写成 i 小于 n？"],
    )

    assert filler.valid_message is False
    assert small_talk.valid_question is False
    assert first.valid_message is True
    assert first.valid_question is True
    assert request.valid_question is True
    assert duplicate.valid_message is False


def test_effective_question_requires_task_relevance_and_rejects_low_information():
    random_text = assess_stage3_message("abcdefghijk?")
    irrelevant = assess_stage3_message("为什么电影结局会是这样？")
    repeated_noise = assess_stage3_message("哈哈哈哈哈哈哈哈？")
    assignment_term = assess_stage3_message(
        "斐波那契为什么从零开始？",
        task_context=["斐波那契"],
    )

    assert random_text.valid_message is False
    assert irrelevant.valid_question is False
    assert repeated_noise.reason == "low_information"
    assert assignment_term.valid_question is True


def test_ambiguous_everyday_terms_do_not_count_without_programming_context():
    messages = [
        "为什么最后一个图标是灰色的？",
        "院子里的树为什么秋天会落叶？",
        "报名条件为什么这么严格？",
        "手机返回键为什么没有反应？",
    ]

    assessments = [assess_stage3_message(message) for message in messages]

    assert all(item.valid_message is False for item in assessments)
    assert all(item.valid_question is False for item in assessments)
    assert all(item.reason == "no_learning_signal" for item in assessments)


def test_english_assignment_title_words_do_not_independently_prove_relevance():
    assessment = assess_stage3_message(
        "Why is the weather nice at the beach?",
        task_context=["Find the Maximum Value"],
    )

    assert assessment.valid_message is False
    assert assessment.valid_question is False
    assert assessment.reason == "no_learning_signal"


def test_ambiguous_loop_term_counts_with_explicit_programming_context():
    assessment = assess_stage3_message("为什么循环会多执行一次？")

    assert assessment.valid_message is True
    assert assessment.valid_question is True
    assert assessment.reason == "meaningful"


def test_programming_cue_pairs_require_whole_words_and_local_context():
    english_substrings = assess_stage3_message(
        "Why are the photograph and anode gray?",
    )
    distant_chinese_cues = assess_stage3_message(
        "为什么手机输入法总失败？聊完这个以后，我还想知道城市边界怎么划分？",
    )
    cross_sentence_cues = assess_stage3_message(
        "为什么手机输入法总失败？城市边界怎么划分？",
    )
    punctuation_separated_cues = assess_stage3_message(
        "为什么输入，，，，，，，，，，，，，边界会这样？",
    )
    lf_separated_cues = assess_stage3_message(
        "为什么手机输入法总失败\n边界怎么划分？",
    )
    crlf_separated_cues = assess_stage3_message(
        "为什么手机输入法总失败\r\n边界怎么划分？",
    )

    assert english_substrings.valid_message is False
    assert english_substrings.valid_question is False
    assert distant_chinese_cues.valid_message is False
    assert distant_chinese_cues.valid_question is False
    assert cross_sentence_cues.valid_message is False
    assert cross_sentence_cues.valid_question is False
    assert punctuation_separated_cues.valid_message is False
    assert punctuation_separated_cues.valid_question is False
    assert lf_separated_cues.valid_message is False
    assert lf_separated_cues.valid_question is False
    assert crlf_separated_cues.valid_message is False
    assert crlf_separated_cues.valid_question is False


def test_code_shape_rejects_natural_language_parenthetical_but_accepts_function_call():
    parenthetical = assess_stage3_message(
        "Why was the train (the late one) cancelled?",
    )
    function_call = assess_stage3_message(
        "为什么 sort(values) 没有按预期排序？",
    )

    assert parenthetical.valid_message is False
    assert parenthetical.valid_question is False
    assert function_call.valid_message is True
    assert function_call.valid_question is True


def test_code_shape_requires_an_expression_around_operator_symbols():
    separators = [
        "Why is Beijing--Shanghai train travel expensive?",
        "Why is Beijing -- Shanghai train travel expensive?",
        "Why is Beijing-- Shanghai train travel expensive?",
        "Why is Boston -> Chicago so expensive?",
        "Why is Monday :: Tuesday so confusing?",
        "Why is apples && bananas so unpopular?",
        "Why is coffee || tea the only choice?",
        "为什么客厅->卧室的路线这么绕？",
        "为什么周一::周二的安排很奇怪？",
        "为什么苹果 && 香蕉不能一起吃？",
    ]
    assessments = [assess_stage3_message(message) for message in separators]
    postfix_expression = assess_stage3_message("为什么 count-- 会改变结果？")
    prefix_expression = assess_stage3_message("为什么 --count 会改变结果？")
    contextual_arrow = assess_stage3_message("为什么指针 pointer -> next 会越界？")

    assert all(item.valid_message is False for item in assessments)
    assert all(item.valid_question is False for item in assessments)
    assert postfix_expression.valid_message is True
    assert postfix_expression.valid_question is True
    assert prefix_expression.valid_message is True
    assert prefix_expression.valid_question is True
    assert contextual_arrow.valid_message is True
    assert contextual_arrow.valid_question is True


def test_oversized_message_can_be_answered_but_cannot_advance_completion():
    assessment = assess_stage3_message(
        "循环" + ("边界" * MAX_ENGAGEMENT_MESSAGE_CHARS),
    )

    assert assessment.valid_message is False
    assert assessment.valid_question is False
    assert assessment.reason == "too_long"


def test_raw_message_length_rejects_internal_whitespace_before_normalization():
    message = (
        "为什么循环"
        + (" " * MAX_ENGAGEMENT_MESSAGE_CHARS)
        + "边界会越界？"
    )

    assessment = assess_stage3_message(message)

    assert assessment.reason == "too_long"
    assert assessment.valid_message is False
    assert assessment.valid_question is False


def test_oversized_previous_message_does_not_make_valid_question_duplicate():
    question = "为什么循环条件要写成 i 小于 n？"
    oversized = (" " * MAX_ENGAGEMENT_MESSAGE_CHARS) + question

    rejected = assess_stage3_message(oversized)
    valid = assess_stage3_message(question, previous_messages=[oversized])

    assert rejected.reason == "too_long"
    assert valid.valid_message is True
    assert valid.valid_question is True


def test_summary_rejects_legacy_message_with_oversized_outer_whitespace():
    started = datetime(2026, 11, 22, 8, 0, 0)
    message = (
        (" " * MAX_ENGAGEMENT_MESSAGE_CHARS)
        + "为什么循环边界会越界？"
        + (" " * MAX_ENGAGEMENT_MESSAGE_CHARS)
    )

    summary = summarize_stage3_engagement([
        _event(1, message, started),
    ])

    assert summary["effective_message_count"] == 0
    assert summary["effective_question_count"] == 0
    assert summary["active_seconds"] == 0


def test_summary_does_not_trust_browser_claimed_assessment_metadata():
    started = datetime(2026, 11, 22, 8, 0, 0)
    events = [{
        "id": 1,
        "content": "abcdefghijk?",
        "created_at": started,
        "metadata": {
            "engagement_assessment": {
                "source": "browser",
                "version": ASSESSMENT_VERSION,
                "valid_message": True,
                "valid_question": True,
                "reason": "forged",
                "intent": "ask_teacher",
            },
        },
    }]

    summary = summarize_stage3_engagement(events)

    assert ASSESSMENT_SOURCE != "browser"
    assert summary["effective_message_count"] == 0
    assert summary["effective_question_count"] == 0
    assert summary["questions_complete"] is False


def test_four_effective_questions_complete_the_question_path():
    started = datetime(2026, 11, 22, 8, 0, 0)
    questions = [
        "为什么循环条件要写成 i 小于 n？",
        "输入为零时应该怎么处理这个边界？",
        "如何保证每轮循环都更新当前结果？",
        "输出最后一个值时为什么不能再循环一次？",
    ]
    events = []
    previous = []
    for index, question in enumerate(questions, start=1):
        assessment = assess_stage3_message(question, previous_messages=previous)
        previous.append(question)
        events.append(_event(index, question, started + timedelta(minutes=index), assessment))

    summary = summarize_stage3_engagement(events)

    assert summary["effective_question_count"] == 4
    assert summary["questions_complete"] is True


def test_active_conversation_resets_after_a_gap_over_three_minutes():
    started = datetime(2026, 11, 22, 8, 0, 0)
    messages = [
        ("我先从输入和初始值开始分析这段程序。", 0),
        ("接着检查循环边界是否会多执行一次。", 2),
        ("然后考虑每轮循环如何更新前两个变量。", 4),
        ("最后再核对输出的是不是目标位置。", 11),
        ("这里还要考虑输入为零时的特殊情况。", 13),
    ]
    events = []
    previous = []
    for index, (message, minute) in enumerate(messages, start=1):
        assessment = assess_stage3_message(message, previous_messages=previous)
        previous.append(message)
        events.append(_event(index, message, started + timedelta(minutes=minute), assessment))

    summary = summarize_stage3_engagement(events)

    assert summary["active_message_count"] == 2
    assert summary["active_seconds"] == 0
    assert summary["active_conversation_complete"] is False


def test_active_conversation_completes_after_ten_minutes_without_long_gap():
    started = datetime(2026, 11, 22, 8, 0, 0)
    messages = [
        "我先说明输入值与初始变量之间的关系。",
        "接着分析循环条件为什么不能包含最后一个下标。",
        "每轮循环都要同步更新前一项和当前项。",
        "输入为零或一时应该直接走边界分支。",
        "最后输出目标变量并检查是否多循环一次。",
    ]
    events = []
    previous = []
    for index, message in enumerate(messages, start=1):
        assessment = assess_stage3_message(message, previous_messages=previous)
        previous.append(message)
        events.append(_event(index, message, started + timedelta(seconds=(index - 1) * 150), assessment))

    summary = summarize_stage3_engagement(events)

    assert summary["active_message_count"] == 5
    assert summary["active_seconds"] == 600
    assert summary["active_conversation_complete"] is True
