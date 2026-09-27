"""
基于班级整体数据的学生能力评分系统
"""
import numpy as np
from models import db, Class, User, Submission
from sqlalchemy import and_, or_
from utils.access import authoritative_class_name
from utils.scoring import normalize_mixed_score
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

class AbilityScorer:
    """学生能力评分计算器"""
    
    def __init__(self):
        self.weights = {
            'submission_frequency': 0.25,    # 提交频率权重
            'average_score': 0.35,          # 平均分权重  
            'consistency': 0.20,             # 稳定性权重
            'improvement': 0.20              # 进步程度权重
        }
    
    def calculate_student_ability_score(self, student_id: str) -> float:
        """
        计算学生的综合能力评分
        
        参数:
            student_id: 学生ID
            
        返回:
            float: 综合能力评分 (0-100分)
        """
        try:
            user = User.query.get(student_id)
            if not user or user.usertype != '学生':
                return 0.0
            
            # 获取学生的提交记录
            submissions = list(user.submissions.with_entities(
                Submission.submitted_at,
                Submission.score,
            ).order_by(Submission.submitted_at).all())
            
            if not submissions:
                return 0.0
            
            # 获取班级数据用于相对评分
            class_data = self._get_class_comparison_data(authoritative_class_name(user))
            
            # 计算各项指标
            submission_score = self._calculate_submission_frequency_score(submissions, class_data)
            average_score = self._calculate_average_score(submissions, class_data)
            consistency_score = self._calculate_consistency_score(submissions)
            improvement_score = self._calculate_improvement_score(submissions)
            
            # 加权平均
            final_score = (
                submission_score * self.weights['submission_frequency'] +
                average_score * self.weights['average_score'] +
                consistency_score * self.weights['consistency'] +
                improvement_score * self.weights['improvement']
            )
            
            # 内部指标仍沿用原来的 0–5 权重模型，统一输出百分制。
            final_score = max(0.0, min(5.0, final_score)) * 20
            
            logger.info(f"学生 {student_id} 能力评分: {final_score:.2f} (提交频率:{submission_score:.2f}, 平均分:{average_score:.2f}, 稳定性:{consistency_score:.2f}, 进步:{improvement_score:.2f})")
            
            return final_score
            
        except Exception as e:
            logger.error(f"计算学生 {student_id} 能力评分时出错: {e}")
            return 0.0
    
    def _get_class_comparison_data(self, class_name: str) -> Dict:
        """获取班级对比数据"""
        if not class_name:
            return {'avg_submissions': 1, 'avg_score': 2.5, 'total_students': 1}
        
        try:
            # 只取统计所需的标量列，避免加载用户对象和密码哈希。
            classroom = Class.query.filter_by(name=class_name).first()
            legacy_scope = and_(User.class_id.is_(None), User.class_name == class_name)
            class_scope = or_(User.class_id == classroom.id, legacy_scope) if classroom else legacy_scope
            class_students = User.query.filter(
                class_scope,
                User.usertype == '学生',
            ).with_entities(User.student_id, User.submit_count).all()
            if not class_students:
                return {'avg_submissions': 1, 'avg_score': 2.5, 'total_students': 1}
            
            # 计算班级统计数据
            total_submissions = sum(s.submit_count or 0 for s in class_students)
            avg_submissions = total_submissions / len(class_students) if class_students else 1
            
            # 计算班级平均分
            all_scores = [row.average_score for row in db.session.query(
                Submission.student_id,
                db.func.avg(Submission.score).label('average_score'),
            ).filter(
                Submission.student_id.in_([student_id for student_id, _ in class_students]),
                Submission.score.isnot(None),
            ).group_by(Submission.student_id).all()]
            
            normalized_scores = [
                (normalize_mixed_score(score) or 0) / 20
                for score in all_scores
            ]
            avg_score = sum(normalized_scores) / len(normalized_scores) if normalized_scores else 2.5
            
            return {
                'avg_submissions': max(1, avg_submissions),
                'avg_score': avg_score,
                'total_students': len(class_students)
            }
        except Exception as e:
            logger.error(f"获取班级 {class_name} 对比数据时出错: {e}")
            return {'avg_submissions': 1, 'avg_score': 2.5, 'total_students': 1}
    
    def _calculate_submission_frequency_score(self, submissions: List[Submission], class_data: Dict) -> float:
        """计算提交频率得分 (0-5分)"""
        if not submissions:
            return 0.0
        
        user_submissions = len(submissions)
        class_avg = class_data['avg_submissions']
        
        # 相对于班级平均水平的比例
        ratio = user_submissions / class_avg
        
        # 转换为0-5分，以班级平均为3分
        if ratio >= 2.0:
            return 5.0
        elif ratio >= 1.5:
            return 4.0 + (ratio - 1.5) * 2.0  # 4.0-5.0
        elif ratio >= 1.0:
            return 3.0 + (ratio - 1.0) * 2.0  # 3.0-4.0
        elif ratio >= 0.5:
            return 1.5 + (ratio - 0.5) * 3.0  # 1.5-3.0
        else:
            return ratio * 3.0                 # 0.0-1.5
    
    def _calculate_average_score(self, submissions: List[Submission], class_data: Dict) -> float:
        """计算平均分得分（内部 0-5 指标）。"""
        if not submissions:
            return 0.0
        
        # 计算学生平均分
        scores = [
            (normalize_mixed_score(s.score) or 0) / 20
            for s in submissions
            if s.score is not None
        ]
        if not scores:
            return 0.0
        
        user_avg = sum(scores) / len(scores)
        class_avg = class_data['avg_score']
        
        # 相对于班级平均水平
        ratio = user_avg / class_avg if class_avg > 0 else 1.0
        
        # 转换为0-5分
        if ratio >= 1.5:
            return 5.0
        elif ratio >= 1.2:
            return 4.0 + (ratio - 1.2) / 0.3  # 4.0-5.0
        elif ratio >= 0.8:
            return 2.0 + (ratio - 0.8) / 0.4 * 2.0  # 2.0-4.0  
        else:
            return ratio / 0.8 * 2.0  # 0.0-2.0
    
    def _calculate_consistency_score(self, submissions: List[Submission]) -> float:
        """计算稳定性得分 (0-5分)"""
        if len(submissions) < 2:
            return 3.0  # 默认中等分数
        
        # 计算分数的标准差
        scores = [
            (normalize_mixed_score(s.score) or 0) / 20
            for s in submissions
            if s.score is not None
        ]
        if len(scores) < 2:
            return 3.0
        
        std_dev = np.std(scores)
        
        # 标准差越小，稳定性越高
        if std_dev <= 0.5:
            return 5.0
        elif std_dev <= 1.0:
            return 4.0
        elif std_dev <= 1.5:
            return 3.0
        elif std_dev <= 2.0:
            return 2.0
        else:
            return 1.0
    
    def _calculate_improvement_score(self, submissions: List[Submission]) -> float:
        """计算进步程度得分 (0-5分)"""
        if len(submissions) < 3:
            return 3.0  # 默认中等分数
        
        # 获取有分数的提交记录
        scored_submissions = [s for s in submissions if s.score is not None]
        if len(scored_submissions) < 3:
            return 3.0
        
        # 计算前1/3和后1/3的平均分
        n = len(scored_submissions)
        first_third = scored_submissions[:n//3] if n >= 3 else scored_submissions[:1]
        last_third = scored_submissions[-n//3:] if n >= 3 else scored_submissions[-1:]
        
        first_avg = sum(
            (normalize_mixed_score(s.score) or 0) / 20 for s in first_third
        ) / len(first_third)
        last_avg = sum(
            (normalize_mixed_score(s.score) or 0) / 20 for s in last_third
        ) / len(last_third)
        
        improvement = last_avg - first_avg
        
        # 转换为0-5分
        if improvement >= 2.0:
            return 5.0
        elif improvement >= 1.0:
            return 4.0
        elif improvement >= 0.5:
            return 3.5
        elif improvement >= 0:
            return 3.0
        elif improvement >= -0.5:
            return 2.5
        elif improvement >= -1.0:
            return 2.0
        else:
            return 1.0
    
    def calculate_detailed_ability_scores(self, student_id: str) -> Dict[str, float]:
        """
        计算学生的详细能力评分 (Average View)
        
        返回:
            Dict: 包含各项能力的详细评分 (0-100)
        """
        try:
            user = User.query.get(student_id)
            if not user or user.usertype != '学生':
                return {k: 0.0 for k in ['algorithm', 'style', 'functionality', 'efficiency', 'readability']}
            
            # 获取所有提交 (不要一开始就过滤掉没有 ai_feedback 的，否则会导致基础分无法回算)
            all_submissions = list(user.submissions.with_entities(
                Submission.ai_feedback,
                Submission.score,
            ).all())
            if not all_submissions:
                return {k: 0.0 for k in ['algorithm', 'style', 'functionality', 'efficiency', 'readability']}
            
            # 记录各维度的总分和计数
            totals = {k: 0.0 for k in ['algorithm', 'style', 'functionality', 'efficiency', 'readability']}
            valid_counts = {k: 0 for k in ['algorithm', 'style', 'functionality', 'efficiency', 'readability']}
            
            import json
            for sub in all_submissions:
                if sub.ai_feedback:
                    try:
                        data = json.loads(sub.ai_feedback)
                        for key in totals:
                            score_key = f"{key}_score"
                            if score_key in data:
                                normalized_value = normalize_mixed_score(data[score_key])
                                if normalized_value is not None:
                                    totals[key] += normalized_value
                                    valid_counts[key] += 1
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
            
            # 计算平均分
            avg_scores = {}
            for key in totals:
                avg_scores[key] = totals[key] / valid_counts[key] if valid_counts[key] > 0 else 0.0
            
            # 极速回归补偿：如果所有维度都是 0（可能由于解析失败或旧数据），则采用系统总分
            if sum(avg_scores.values()) == 0:
                normalized_scores = [
                    normalize_mixed_score(s.score)
                    for s in all_submissions
                    if s.score is not None
                ]
                normalized_scores = [score for score in normalized_scores if score is not None]
                base = (
                    min(100, sum(normalized_scores) / len(normalized_scores))
                    if normalized_scores else 0
                )
                avg_scores = {k: base for k in avg_scores}
                
            return avg_scores
            
        except Exception as e:
            logger.error(f"计算学生 {student_id} 详细能力评分时出错: {e}")
            return {k: 0.0 for k in ['algorithm', 'style', 'functionality', 'efficiency', 'readability']}
    
    def update_all_students_scores(self):
        """更新所有学生的能力评分"""
        try:
            students = User.query.filter_by(usertype='学生').all()
            updated_count = 0
            
            logger.info(f"开始更新 {len(students)} 名学生的能力评分...")
            
            for student in students:
                try:
                    new_score = self.calculate_student_ability_score(student.student_id)
                    old_score = student.user_ascore
                    
                    student.user_ascore = new_score
                    db.session.add(student)
                    
                    if abs(new_score - old_score) > 0.1:  # 只记录显著变化
                        logger.info(f"更新学生 {student.student_id}({student.full_name}) 评分: {old_score:.2f} -> {new_score:.2f}")
                    
                    updated_count += 1
                    
                except Exception as e:
                    logger.error(f"更新学生 {student.student_id} 评分失败: {e}")
                    continue
            
            db.session.commit()
            logger.info(f"✅ 成功更新 {updated_count} 名学生的能力评分")
            
            return updated_count
            
        except Exception as e:
            logger.error(f"批量更新学生评分时出错: {e}")
            db.session.rollback()
            return 0

# 全局评分器实例
ability_scorer = AbilityScorer()
