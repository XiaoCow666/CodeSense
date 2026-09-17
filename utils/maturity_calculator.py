"""成熟度评分计算工具 - 统一处理 φ_avg, φ_freq, φ_std, φ_grad 的计算逻辑"""
import statistics
from datetime import datetime
from utils.scoring import normalize_mixed_score

# 从 code_evaluator 导入权重常量（避免循环导入，直接复制常量定义）
MATURITY_WEIGHTS = {
    'phi_avg': 0.4,
    'phi_grad': 0.3,
    'phi_freq': 0.15,
    'phi_std': 0.15
}


def calculate_maturity_components(all_subs, ability_scores=None, class_averages=None, class_name=None):
    """
    计算成熟度评分的四个分量

    Args:
        all_subs: 排序后的提交记录列表 (按 submitted_at 升序)
        ability_scores: 学生各维度得分 dict (可选，用于 home 页)
        class_averages: 班级平均分 dict (可选)
        class_name: 班级名称 (可选)

    Returns:
        dict: 包含 phi_avg, phi_freq, phi_std, phi_grad 的字典
    """
    result = {
        'phi_avg': 80,
        'phi_freq': 0,
        'phi_std': 100,
        'phi_grad': 50,
        'maturity_score': 0
    }

    if not all_subs:
        result['maturity_score'] = 0
        return result

    # 1. φ_avg (相对得分): 对齐班级基准线的平均表现
    if ability_scores and class_averages and class_name:
        student_avg_val = sum(ability_scores.values()) / 5
        st_class_avg = class_averages.get(class_name, {})
        class_avg_val = sum(st_class_avg.values()) / 5 if st_class_avg else 60
        result['phi_avg'] = min(1.2, student_avg_val / class_avg_val) * 80 if class_avg_val > 0 else 80

    # 2. φ_freq (提交密度): 衡量练习规律性
    first_sub = all_subs[0].submitted_at
    now_time = datetime.now()
    days_diff = (now_time - first_sub).days + 1
    submissions_per_day = len(all_subs) / days_diff
    result['phi_freq'] = min(100, submissions_per_day * 100)

    # 3. φ_std (稳定性): 惩罚项，检测稳定性偏离
    # 成熟度的历史公式按 0–5 计算，提交分本身统一落库为百分制，
    # 这里仅在公式内部换算，输出仍然是 0–100。
    scores = [
        (normalize_mixed_score(s.score) or 0) / 20
        for s in all_subs
        if s.score is not None
    ]
    if len(scores) > 1:
        std_dev = statistics.stdev(scores)
        result['phi_std'] = max(0, 100 - (std_dev * 20))
    else:
        result['phi_std'] = 100

    # 4. φ_grad (进步梯度): 一阶导数逻辑，计算成长斜率
    if len(all_subs) >= 4:
        half_len = len(all_subs) // 2
        first_half = all_subs[:half_len]
        second_half = all_subs[half_len:]
        avg_init = sum(
            (normalize_mixed_score(s.score) or 0) / 20
            for s in first_half
            if s.score is not None
        ) / len(first_half)
        avg_recent = sum(
            (normalize_mixed_score(s.score) or 0) / 20
            for s in second_half
            if s.score is not None
        ) / len(second_half)
        growth = avg_recent - avg_init
        result['phi_grad'] = min(100, max(0, 50 + growth * 10))

    # 计算总分
    result['maturity_score'] = round(min(100, (
        result['phi_avg'] * MATURITY_WEIGHTS['phi_avg'] +
        result['phi_grad'] * MATURITY_WEIGHTS['phi_grad'] +
        result['phi_freq'] * MATURITY_WEIGHTS['phi_freq'] +
        result['phi_std'] * MATURITY_WEIGHTS['phi_std']
    )), 1)

    return result
