"""submission_history 页分数统计的纯函数测试。

统计逻辑提取到 ``utils/submission_stats.py``（仅标准库，不 import Flask、
不连数据库/Redis、不访问网络）。用 SimpleNamespace 轻量假对象验证。

覆盖背景：routes/assignments.py 学生提交历史页旧实现把未评分提交当 0
（sum(s.score or 0) / len(全部)），与同文件 L546/L588 及官方统计口径
不一致；且全未评分时 best_score 泄漏 None。
"""
from types import SimpleNamespace

from utils.submission_stats import submission_score_stats


def _sub(score):
    return SimpleNamespace(score=score)


def _stats(scores):
    return submission_score_stats([_sub(v) for v in scores])


def test_average_uses_only_scored_submissions():
    # [40, 40, 未评分, 43]：未评分不进分子也不进分母 → 123/3 = 41
    average, best = _stats([40, 40, None, 43])
    assert average == 41
    assert best == 43


def test_neutral_zero_when_all_submissions_unscored():
    # 全部未评分 = 无数据：avg/best 均回退 0，best 不再泄漏 None
    average, best = _stats([None, None])
    assert average == 0
    assert best == 0


def test_empty_submission_list_returns_zero_pair():
    assert submission_score_stats([]) == (0, 0)


def test_normal_path_unchanged():
    average, best = _stats([70, 80, 60])
    assert average == 70
    assert best == 80


def test_real_zero_score_is_not_treated_as_missing():
    # 0 是真实分数：参与平均与最佳，不被当成未评分丢弃
    average, best = _stats([0, 80])
    assert average == 40
    assert best == 80
