"""教师 AI 建议 prompt 构造的纯函数测试。

仅标准库，不 import Flask、不连数据库/Redis、不访问网络。

背景：服务端把"风险标签 ['低分']"与"最近得分 100"两个未解释口径的数据
并列喂给 LLM，LLM 据此推断"数据记录异常或系统误判"，误导教师排查不存
在的系统故障。实际上"低分"标签在历史综合分 <60 或最近得分 <60 时都会
触发（services/teacher_analytics.py）。
"""
from utils.teacher_advice_prompt import (
    RISK_TAG_CALIBER_INSTRUCTION,
    format_attention_student_line,
    format_risk_reason,
)


def test_line_explains_low_tag_comes_from_history_when_latest_is_high():
    # 孙三场景：历史综合分 44（<60）触发低分标签，最近一次 100
    line = format_attention_student_line({
        'name': '孙三',
        'student_id': 'demo_s_003',
        'risk_tags': ['低分'],
        'latest_score': 100,
        'historical_score': 44,
    })

    assert '孙三' in line and 'demo_s_003' in line
    assert '100' in line and '44' in line
    # 必须显式给出低分标签的来源口径，防止 LLM 臆断为数据矛盾
    assert '历史综合分' in line
    assert '来自' in line


def test_line_normal_low_score_keeps_both_scores():
    line = format_attention_student_line({
        'name': '周四',
        'student_id': 'demo_s_004',
        'risk_tags': ['低分'],
        'latest_score': 40,
        'historical_score': 35,
    })

    assert '40' in line and '35' in line
    assert '低分' in line


def test_line_no_submission_shows_none_for_scores():
    line = format_attention_student_line({
        'name': '新手',
        'student_id': 'demo_s_099',
        'risk_tags': ['未提交'],
        'latest_score': None,
        'historical_score': None,
    })

    assert '未提交' in line
    assert '无' in line  # 最近得分无


def test_instruction_explains_tag_caliber_and_forbids_false_anomaly_claim():
    text = RISK_TAG_CALIBER_INSTRUCTION

    # 口径：低分标签在历史综合分或最近得分低于阈值时触发
    assert '历史综合分' in text
    assert '60' in text
    # 明确禁止：标签与最近得分并存不是数据矛盾，不得推断为系统异常
    assert '系统异常' in text or '系统误判' in text


def test_risk_reason_explains_low_tag_from_history():
    reason = format_risk_reason({
        'risk_tags': ['低分'],
        'latest_score': 100,
        'historical_score': 44,
    })

    assert '低分' in reason and '100' in reason and '44' in reason
    assert '历史综合分' in reason


def test_risk_reason_plain_low_score_stays_concise():
    reason = format_risk_reason({
        'risk_tags': ['低分'],
        'latest_score': 20,
        'historical_score': 30,
    })

    assert reason == '存在低分风险，最近得分 20'
