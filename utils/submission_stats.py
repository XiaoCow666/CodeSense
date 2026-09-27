"""提交分数统计的纯函数。

从路由中提取，便于不依赖 Flask/数据库直接测试。口径与同项目其他平均分
计算保持一致：未评分提交（score is None）既不进分子也不进分母；没有任何
已评分提交时属于"无数据"，回退为 0，而不是把未评分当 0 分拉低均值。
"""
from typing import Iterable, Tuple


def submission_score_stats(submissions: Iterable) -> Tuple[float, int]:
    """返回 ``(average_score, best_score)``，仅统计已评分提交。

    - 平均分：sum(score) / 已评分条数；
    - 最高分：已评分分数的最大值；
    - 无已评分提交（含空列表、全部未评分）：返回 ``(0, 0)``。

    注意真实 0 分是有效分数，会正常参与计算，不会被当成缺失。
    """
    scores = [
        submission.score
        for submission in submissions
        if getattr(submission, "score", None) is not None
    ]
    if not scores:
        return 0, 0
    return sum(scores) / len(scores), max(scores)
