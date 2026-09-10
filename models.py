"""
数据库模型定义
"""
import json  # 添加json导入
import secrets
import threading
import time
from datetime import datetime as dt
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.session import Session as FlaskSQLAlchemySession
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin  # 添加UserMixin导入
from sqlalchemy import Index, UniqueConstraint, inspect, text
from sqlalchemy.exc import SQLAlchemyError

# 班级默认配置
DEFAULT_GRADE = '2024'
DEFAULT_MAJOR = '计算机相关专业'

class CodeSenseSession(FlaskSQLAlchemySession):
    """Allow a request-scoped demo engine without changing app configuration."""

    def get_bind(self, mapper=None, clause=None, bind=None, **kwargs):
        demo_bind = getattr(self, '_codesense_demo_bind', None)
        if demo_bind is not None and bind is None:
            return demo_bind
        return super().get_bind(mapper=mapper, clause=clause, bind=bind, **kwargs)


db = SQLAlchemy(session_options={'class_': CodeSenseSession})


def _database_cache_scope():
    """Return a stable cache namespace for the current SQLAlchemy bind."""

    try:
        return str(db.session.get_bind().url)
    except Exception:
        return 'default'


_CLASS_AVERAGE_CACHE = {}
_CLASS_AVERAGE_CACHE_LOCK = threading.RLock()
_CLASS_AVERAGE_CACHE_TTL = 15


class Class(db.Model):
    """班级模型"""
    __tablename__ = 'classes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # 班级名称
    school = db.Column(db.String(100), default='酷森思大学', nullable=False)  # 学校
    college = db.Column(db.String(100), default='计算机学院', nullable=False)  # 学院
    grade = db.Column(db.String(20))  # 年级
    major = db.Column(db.String(50))  # 专业
    teacher_id = db.Column(db.String(20), db.ForeignKey('users.student_id', ondelete='SET NULL'), nullable=True)
    teacher_bind_code = db.Column(db.String(20), unique=True, nullable=True)
    teacher_bind_code_updated_at = db.Column(db.DateTime, nullable=True)
    student_count = db.Column(db.Integer, default=0)  # 学生数量
    avg_score = db.Column(db.Float, default=0.0)  # 班级平均分
    total_submissions = db.Column(db.Integer, default=0)  # 班级总提交数
    created_at = db.Column(db.DateTime, default=dt.utcnow)
    updated_at = db.Column(db.DateTime, default=dt.utcnow, onupdate=dt.utcnow)
    
    # 与教师的关系 (一个班级对应一个教师)
    teacher = db.relationship('User', backref=db.backref('managed_classes', lazy='dynamic'), foreign_keys=[teacher_id])
    
    # 与学生的一对多关系
    students = db.relationship('User', backref='class_info', lazy='dynamic',
                             foreign_keys='User.class_id')

    @staticmethod
    def _generate_bind_code():
        """生成便于人工输入的班级绑定码。"""
        return secrets.token_urlsafe(6).replace('-', '').replace('_', '')[:8].upper()

    @classmethod
    def _unique_bind_code(cls):
        while True:
            code = cls._generate_bind_code()
            if not cls.query.filter_by(teacher_bind_code=code).first():
                return code

    def ensure_teacher_bind_code(self):
        """确保班级存在教师绑定码。"""
        if not self.teacher_bind_code:
            self.teacher_bind_code = self._unique_bind_code()
            self.teacher_bind_code_updated_at = dt.utcnow()
        return self.teacher_bind_code

    def reset_teacher_bind_code(self):
        """重置教师绑定码。"""
        self.teacher_bind_code = self._unique_bind_code()
        self.teacher_bind_code_updated_at = dt.utcnow()
        return self.teacher_bind_code
    
    def get_statistics(self):
        """获取班级统计信息"""
        # 用一次聚合查询替代“先取出所有学生再在 Python 中求和”。首页、
        # 班级列表和教师仪表盘都会调用这里，学生规模增长时差异很明显。
        student_stats = db.session.query(
            db.func.count(User.student_id),
            db.func.coalesce(db.func.sum(User.submit_count), 0),
            db.func.coalesce(db.func.avg(User.user_ascore), 0),
            db.func.coalesce(
                db.func.sum(db.case((User.submit_count > 0, 1), else_=0)),
                0,
            ),
        ).filter(
            User.class_name == self.name,
            User.usertype == '学生',
        ).one()

        student_count, total_submissions, avg_score, active_students = student_stats
        if not student_count:
            return {
                'student_count': 0,
                'avg_score': 0.0,
                'total_submissions': 0,
                'active_students': 0,
                'assignments_completed': 0
            }
        
        # 计算完成作业数 - 使用当前模块避免循环导入
        assignments_completed = db.session.query(Submission.assignment_id).join(User)\
                                .filter(User.class_name == self.name)\
                                .distinct().count()
        
        return {
            'student_count': int(student_count),
            'avg_score': round(avg_score, 2),
            'total_submissions': int(total_submissions or 0),
            'active_students': int(active_students or 0),
            'assignments_completed': assignments_completed
        }
    
    def get_top_students(self, limit=5):
        """获取班级前N名学生"""
        return self.students.filter_by(usertype='学生')\
                           .order_by(User.user_ascore.desc())\
                           .limit(limit).all()
    
    def get_assignment_progress(self, page=1, per_page=10):
        """获取班级作业完成进度 (分页形式)"""
        # 仅获取指派给当前班级的作业
        # 注意: target_classes格式类似 '软件工程24-1班,测试班级'
        assignments_query = Assignment.query.filter(Assignment.target_classes.contains(self.name))
        
        # 分页
        pagination = assignments_query.paginate(page=page, per_page=per_page, error_out=False)
        
        assignment_ids = [assignment.id for assignment in pagination.items]
        completed_by_assignment = {}
        if assignment_ids:
            rows = db.session.query(
                Submission.assignment_id,
                db.func.count(Submission.id),
            ).join(User).filter(
                User.class_name == self.name,
                User.usertype == '学生',
                Submission.assignment_id.in_(assignment_ids),
            ).group_by(Submission.assignment_id).all()
            completed_by_assignment = {assignment_id: int(count) for assignment_id, count in rows}

        total = db.session.query(User.student_id).filter(
            User.class_name == self.name,
            User.usertype == '学生',
        ).count()
        progress = []
        for assignment in pagination.items:
            completed = completed_by_assignment.get(assignment.id, 0)
            progress.append({
                'assignment': assignment,
                'completed': completed,
                'total': total,
                'progress_rate': round(completed / total * 100, 1) if total > 0 else 0
            })
        
        return {
            'items': progress,
            'pagination': pagination
        }
    
    @staticmethod
    def sync_from_users():
        """从用户数据同步班级信息"""
        # 获取所有不同的班级名称（仅限学生）
        class_names = db.session.query(User.class_name)\
                     .filter(User.class_name.isnot(None))\
                     .filter(User.usertype == '学生')\
                     .distinct().all()
        
        existing_classes = {cls.name: cls for cls in Class.query.all()}
        for (class_name,) in class_names:
            if not class_name:
                continue
                
            # 检查班级是否已存在
            existing_class = existing_classes.get(class_name)
            if not existing_class:
                # 创建新班级
                new_class = Class(
                    name=class_name,
                    grade=DEFAULT_GRADE,
                    major=DEFAULT_MAJOR
                )
                db.session.add(new_class)
                existing_classes[class_name] = new_class
        
        db.session.flush()
        
        # 清理旧的无用伪造班级数据（比如“教师”、“管理员”这些由于以前错误逻辑被同步进来的空班级）
        student_rows = db.session.query(
            User.class_name,
            db.func.count(User.student_id),
            db.func.coalesce(db.func.sum(User.submit_count), 0),
            db.func.coalesce(db.func.avg(User.user_ascore), 0),
        ).filter(User.usertype == '学生').group_by(User.class_name).all()
        student_stats = {
            class_name: {
                'student_count': int(student_count),
                'total_submissions': int(total_submissions or 0),
                'avg_score': float(avg_score or 0),
            }
            for class_name, student_count, total_submissions, avg_score in student_rows
            if class_name
        }

        for cls in list(existing_classes.values()):
            stats = student_stats.get(cls.name)
            if not stats or cls.name in ['教师', '管理员', '管理部门']:
                db.session.delete(cls)
                continue
            cls.student_count = stats['student_count']
            cls.avg_score = stats['avg_score']
            cls.total_submissions = stats['total_submissions']
        
        db.session.commit()
        return len(student_stats)


class User(db.Model, UserMixin):  # 添加UserMixin继承
    """用户模型"""
    __tablename__ = 'users'
    student_id = db.Column(db.String(20), unique=True, nullable=False, primary_key=True)
    # student_id 仍是历史系统内部主键；student_number 表示可选的真实学号。
    student_number = db.Column(db.String(20), nullable=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    usertype = db.Column(db.Enum('学生', '教师', '管理员'), nullable=False)
    class_name = db.Column(db.String(50))
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=True)  # 新增班级外键
    full_name = db.Column(db.String(50))
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    # 兼容历史账号：只有邮箱注册账号会要求完成邮箱验证。
    email_verified_at = db.Column(db.DateTime, nullable=True)
    email_verification_required = db.Column(
        db.Boolean,
        default=False,
        server_default=text('0'),
        nullable=False,
    )
    registration_method = db.Column(
        db.String(32),
        default='legacy',
        server_default=text("'legacy'"),
        nullable=False,
    )
    avatar_path = db.Column(db.String(255), nullable=True)
    submit_count = db.Column(db.Integer, default=0)
    user_ascore = db.Column(db.Float, default=0.0)
    user_tscore = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=dt.utcnow)
    password_changed_at = db.Column(db.DateTime, nullable=True)
    current_session_id = db.Column(db.String(100), nullable=True, comment='当前合法的会话ID')
    
    # 定义与submissions的关系
    submissions = db.relationship('Submission', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    
    # 实现Flask-Login需要的属性和方法
    def get_id(self):
        """返回用户唯一标识符"""
        return self.student_id
    
    @property
    def is_active(self):
        """用户是否处于活动状态"""
        return True
    
    @property
    def is_authenticated(self):
        """用户是否已通过身份验证"""
        return True
    
    @property
    def is_anonymous(self):
        """用户是否是匿名用户"""
        return False
    
    @property
    def password(self):
        raise AttributeError('password不可读')
    
    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property 
    def is_admin(self):
        return self.usertype == '管理员'

    @property
    def is_teacher(self):
        return self.usertype == '教师'
        
    def get_ability_scores(self):
        """获取学生的详细能力评分
        
        返回:
            一个包含各种能力评分的字典
        """
        try:
            from utils.ability_scorer import ability_scorer
            return ability_scorer.calculate_detailed_ability_scores(self.student_id)
        except Exception:
            # 如果计算失败，返回基于现有数据的简单评分
            submissions = self.submissions.all()
            
            if not submissions:
                return {
                    'algorithm': 0,
                    'style': 0,
                    'functionality': 0,
                    'efficiency': 0,
                    'readability': 0
                }
            
            # 基于现有提交数据进行简单计算
            avg_score = sum(s.score for s in submissions if s.score) / len([s for s in submissions if s.score]) if any(s.score for s in submissions) else 0
            base_score = min(100, max(0, avg_score * 20))  # 转换为100分制
            
            return {
                'algorithm': base_score,     # 算法能力
                'style': base_score,         # 代码风格
                'functionality': base_score, # 功能实现
                'efficiency': base_score,    # 效率优化
                'readability': base_score    # 代码可读性
            }
    
    @staticmethod
    def get_class_average_scores(course_id=None):
        """获取班级平均能力评分
        
        参数:
            course_id: 课程ID，可选
            
        返回:
            一个包含班级平均能力评分的字典
        """
        cache_key = (_database_cache_scope(), course_id)
        now = time.monotonic()
        with _CLASS_AVERAGE_CACHE_LOCK:
            cached = _CLASS_AVERAGE_CACHE.get(cache_key)
            if cached and cached[0] > now:
                return cached[1]

        try:
            # 原实现是“班级 -> 学生 -> 提交记录”的多层 N+1 查询。
            # 这里只取评分 JSON 和总分，按学生先聚合，再按班级聚合，
            # 保持每个学生等权，同时把首页查询压缩为一次数据库往返。
            dimension_names = (
                'algorithm', 'style', 'functionality', 'efficiency', 'readability'
            )
            rows = db.session.query(
                User.student_id,
                User.class_name,
                Submission.ai_feedback,
                Submission.score,
            ).join(
                Submission, Submission.student_id == User.student_id
            ).filter(
                User.usertype == '学生',
                User.class_name.isnot(None),
            ).all()

            per_student = {}
            for student_id, class_name, ai_feedback, score in rows:
                item = per_student.setdefault(
                    student_id,
                    {'class_name': class_name, 'scores': {name: [] for name in dimension_names},
                     'fallback_scores': []},
                )
                if score is not None:
                    item['fallback_scores'].append(float(score) * 20)
                if not ai_feedback:
                    continue
                try:
                    feedback = json.loads(ai_feedback)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                for name in dimension_names:
                    value = feedback.get(f'{name}_score')
                    try:
                        if value is not None:
                            item['scores'][name].append(float(value) * 20)
                    except (TypeError, ValueError):
                        continue

            class_totals = {}
            for item in per_student.values():
                class_name = item['class_name']
                values = {}
                for name in dimension_names:
                    values[name] = (
                        sum(item['scores'][name]) / len(item['scores'][name])
                        if item['scores'][name] else 0.0
                    )
                if not any(values.values()) and item['fallback_scores']:
                    fallback = sum(item['fallback_scores']) / len(item['fallback_scores'])
                    values = {name: fallback for name in dimension_names}
                if not any(values.values()):
                    continue
                bucket = class_totals.setdefault(
                    class_name,
                    {'totals': {name: 0.0 for name in dimension_names}, 'count': 0},
                )
                for name in dimension_names:
                    bucket['totals'][name] += values[name]
                bucket['count'] += 1

            result = {
                class_name: {
                    name: bucket['totals'][name] / bucket['count']
                    for name in dimension_names
                }
                for class_name, bucket in class_totals.items()
                if bucket['count']
            }
            with _CLASS_AVERAGE_CACHE_LOCK:
                _CLASS_AVERAGE_CACHE[cache_key] = (
                    now + _CLASS_AVERAGE_CACHE_TTL,
                    result,
                )
            return result

        except Exception as e:
            import logging
            logging.error(f"获取班级平均能力评分时出错: {e}")
            return {}


class StudentRoster(db.Model):
    """教师导入的学生花名册，用于学生注册时自动绑定班级。"""
    __tablename__ = 'student_rosters'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(50), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id', ondelete='CASCADE'), nullable=False)
    class_name_snapshot = db.Column(db.String(50), nullable=False)
    imported_by = db.Column(db.String(20), db.ForeignKey('users.student_id', ondelete='SET NULL'), nullable=True)
    is_registered = db.Column(db.Boolean, default=False, nullable=False)
    registered_user_id = db.Column(db.String(20), db.ForeignKey('users.student_id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=dt.utcnow)
    updated_at = db.Column(db.DateTime, default=dt.utcnow, onupdate=dt.utcnow)

    class_info = db.relationship('Class', backref=db.backref('roster_entries', lazy='dynamic'))
    importer = db.relationship('User', foreign_keys=[imported_by])
    registered_user = db.relationship('User', foreign_keys=[registered_user_id])


class Assignment(db.Model):
    """作业模型"""
    __tablename__ = 'assignments'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    total_score = db.Column(db.Integer, default=0)
    average_score = db.Column(db.Float, default=0.0)
    count = db.Column(db.Integer, default=0)
    created_time = db.Column(db.DateTime, default=dt.utcnow)
    due_date = db.Column(db.DateTime, nullable=True)  # 截止日期
    target_classes = db.Column(db.Text)  # 存储目标班级列表，用逗号分隔
    difficulty_level = db.Column(db.Integer, default=1)  # 难度级别：1-5
    
    # 新增创建者ID，用于区分不同教师的作业
    creator_id = db.Column(db.String(20), db.ForeignKey('users.student_id'), nullable=True)
    creator = db.relationship('User', backref=db.backref('created_assignments', lazy='dynamic'))

    # 定义与submissions的关系
    submissions = db.relationship('Submission', backref='assignment', lazy='dynamic', cascade='all, delete-orphan')
    
    def get_target_class_list(self):
        """获取目标班级列表"""
        if not self.target_classes:
            return []
        return [cls.strip() for cls in self.target_classes.split(',') if cls.strip()]
    
    def set_target_classes(self, class_list):
        """设置目标班级列表"""
        if isinstance(class_list, list):
            self.target_classes = ','.join(class_list)
        else:
            self.target_classes = str(class_list)
    
    def get_class_progress(self):
        """获取各班级的完成进度"""
        target_classes = self.get_target_class_list()
        if not target_classes:
            return []

        totals = db.session.query(
            User.class_name,
            db.func.count(User.student_id),
        ).filter(
            User.class_name.in_(target_classes),
            User.usertype == '学生',
        ).group_by(User.class_name).all()
        total_by_class = {class_name: int(count) for class_name, count in totals}

        completed = db.session.query(
            User.class_name,
            db.func.count(Submission.id),
        ).join(Submission, Submission.student_id == User.student_id).filter(
            User.class_name.in_(target_classes),
            User.usertype == '学生',
            Submission.assignment_id == self.id,
        ).group_by(User.class_name).all()
        completed_by_class = {class_name: int(count) for class_name, count in completed}

        progress = []
        for class_name in target_classes:
            total_students = total_by_class.get(class_name, 0)
            completed_students = completed_by_class.get(class_name, 0)
            
            progress.append({
                'class_name': class_name,
                'total': total_students,
                'completed': completed_students,
                'progress_rate': round(completed_students / total_students * 100, 1) if total_students > 0 else 0
            })
        
        return progress


class TestCase(db.Model):
    """测试用例模型"""
    __tablename__ = 'test_cases'
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignments.id', ondelete='CASCADE'), nullable=False)
    input_data = db.Column(db.Text, nullable=False)   # 测试输入
    expected_output = db.Column(db.Text, nullable=False)  # 期望输出
    is_public = db.Column(db.Boolean, default=False)  # 是否对学生可见（样例）
    order_index = db.Column(db.Integer, default=0)    # 排序序号
    created_at = db.Column(db.DateTime, default=dt.utcnow)

    assignment = db.relationship('Assignment', backref=db.backref('test_cases', lazy='dynamic', cascade='all, delete-orphan'))

    def to_dict(self):
        return {
            'id': self.id,
            'assignment_id': self.assignment_id,
            'input_data': self.input_data,
            'expected_output': self.expected_output,
            'is_public': self.is_public,
            'order_index': self.order_index,
        }


class Submission(db.Model):
    """提交记录模型"""
    __tablename__ = 'submissions'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), db.ForeignKey('users.student_id', ondelete='CASCADE'), nullable=False)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignments.id', ondelete='CASCADE'), nullable=False)
    code = db.Column(db.Text, nullable=False)
    score = db.Column(db.Integer)
    language = db.Column(db.String(20), default='cpp')
    submitted_at = db.Column(db.DateTime, default=dt.utcnow)
    feedback = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending')  # 状态：pending, evaluated, failed
    ai_feedback = db.Column(db.Text, nullable=True)  # 大模型评估结果
    # 沙箱评判结果
    sandbox_status = db.Column(db.String(20), nullable=True)   # passed / partial / failed / error
    sandbox_passed = db.Column(db.Integer, default=0)          # 通过测试用例数
    sandbox_total = db.Column(db.Integer, default=0)           # 总测试用例数
    sandbox_detail = db.Column(db.Text, nullable=True)         # JSON：每个用例的结果详情


class SystemLog(db.Model):
    """系统活动日志模型"""
    __tablename__ = 'system_logs'
    id = db.Column(db.Integer, primary_key=True)
    log_type = db.Column(db.String(50), nullable=False)  # 日志类型：用户注册、作业添加、代码提交等
    user_id = db.Column(db.String(20), db.ForeignKey('users.student_id', ondelete='SET NULL'), nullable=True)  # 关联用户ID，可能为空
    content = db.Column(db.Text, nullable=False)  # 日志内容
    created_at = db.Column(db.DateTime, default=dt.utcnow)  # 创建时间
    icon = db.Column(db.String(50), default='bi bi-activity')  # 图标class，用于前端显示
    
    # 关联用户，nullable=True 允许用户被删除后日志依然保留
    user = db.relationship('User', backref=db.backref('logs', lazy='dynamic'), foreign_keys=[user_id])
    
    @staticmethod
    def add_log(log_type, content, user_id=None, icon=None):
        """添加日志的便捷方法"""
        # 根据不同类型设置默认图标
        if icon is None:
            if log_type == '用户注册':
                icon = 'bi bi-person-plus'
            elif log_type == '添加作业':
                icon = 'bi bi-file-earmark-code'
            elif log_type == '提交代码':
                icon = 'bi bi-code'
            elif log_type == '用户登录':
                icon = 'bi bi-box-arrow-in-right'
            else:
                icon = 'bi bi-activity'
                
        log = SystemLog(log_type=log_type, content=content, user_id=user_id, icon=icon)
        db.session.add(log)
        db.session.commit()
        return log
    
    
class AbilityTrend(db.Model):
    """学生能力发展趋势缓存表"""
    __tablename__ = 'ability_trends'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), db.ForeignKey('users.student_id', ondelete='CASCADE'), nullable=False, unique=True, index=True)
    analysis_markdown = db.Column(db.Text, nullable=True)  # Markdown格式的分析结果
    trend_data = db.Column(db.Text, nullable=True)  # 保留兼容性：JSON格式存储趋势分析结果
    last_updated = db.Column(db.DateTime, default=dt.utcnow)  # 最后更新时间
    submissions_count = db.Column(db.Integer, default=0)  # 基于多少次提交生成的分析
    status = db.Column(db.String(20), default='pending')  # pending, processing, completed, failed

    # 关联用户
    user = db.relationship('User', backref=db.backref('ability_trend', uselist=False))
    
    @staticmethod
    def get_or_create(student_id):
        """获取或创建学生的能力趋势记录"""
        from sqlalchemy.exc import IntegrityError
        trend = AbilityTrend.query.filter_by(student_id=student_id).first()
        if not trend:
            try:
                trend = AbilityTrend(student_id=student_id)
                db.session.add(trend)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                trend = AbilityTrend.query.filter_by(student_id=student_id).first()
        return trend
    
    @staticmethod
    def update_trend(student_id, trend_data, submissions_count):
        """更新学生的能力趋势数据（兼容旧版本JSON格式）"""
        trend = AbilityTrend.get_or_create(student_id)
        trend.trend_data = trend_data if isinstance(trend_data, str) else json.dumps(trend_data, ensure_ascii=False)
        trend.submissions_count = submissions_count
        trend.last_updated = dt.utcnow()
        trend.status = 'completed'
        db.session.commit()
        return trend

    @staticmethod
    def update_analysis(student_id, analysis_markdown, submissions_count):
        """更新学生的能力分析（Markdown格式）"""
        trend = AbilityTrend.get_or_create(student_id)
        trend.analysis_markdown = analysis_markdown
        trend.submissions_count = submissions_count
        trend.last_updated = dt.utcnow()
        trend.status = 'completed'
        db.session.commit()
        return trend

    @staticmethod
    def mark_as_processing(student_id):
        """标记为正在处理"""
        trend = AbilityTrend.get_or_create(student_id)
        trend.status = 'processing'
        db.session.commit()
        return trend

    @staticmethod
    def mark_as_outdated(student_id):
        """标记为需要更新（有新提交）"""
        trend = AbilityTrend.query.filter_by(student_id=student_id).first()
        if trend and trend.status == 'completed':
            trend.status = 'outdated'
            db.session.commit()
        return trend
    
    def get_trend_dict(self):
        """获取趋势数据的字典格式"""
        if not self.trend_data:
            return {
                "trend": "暂无足够数据进行能力趋势分析",
                "improvement": "请继续提交更多代码作业以获得个性化分析",
                "suggestions": [
                    "完成更多编程作业，积累提交记录",
                    "注意代码规范和可读性",
                    "尝试不同难度的编程问题"
                ]
            }
        try:
            return json.loads(self.trend_data)
        except (json.JSONDecodeError, TypeError):
            return {
                "trend": "数据格式异常，请联系管理员",
                "improvement": "系统将在下次提交后重新分析",
                "suggestions": []
            }


class SystemConfig(db.Model):
    """系统配置模型"""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(200))
    type = db.Column(db.String(20), default='string')
    updated_at = db.Column(db.DateTime, default=dt.now, onupdate=dt.now)

    _cache = {}
    _cache_lock = threading.RLock()
    _cache_ttl_seconds = 30

    @staticmethod
    def _convert_value(config, default=None):
        if not config:
            return default
        if config.type == 'int':
            return int(config.value) if config.value else 0
        if config.type == 'float':
            return float(config.value) if config.value else 0.0
        if config.type == 'bool':
            return config.value.lower() in ('true', '1', 'yes', 'y') if config.value else False
        return config.value

    @staticmethod
    def _cache_key(key):
        """Scope cache entries to the currently bound database.

        Public demo runs dynamically swap the SQLAlchemy bind, and tests often
        create several temporary databases in one process. A plain key cache
        could otherwise leak a setting between those databases.
        """

        try:
            bind = db.session.get_bind()
            scope = str(bind.url)
        except Exception:
            scope = 'default'
        return scope, key

    @staticmethod
    def get_value(key, default=None):
        """获取配置值"""
        now = time.monotonic()
        cache_key = SystemConfig._cache_key(key)
        with SystemConfig._cache_lock:
            cached = SystemConfig._cache.get(cache_key)
            if cached and cached[0] > now:
                return cached[1]

        config = SystemConfig.query.filter_by(key=key).first()
        value = SystemConfig._convert_value(config, default)
        with SystemConfig._cache_lock:
            SystemConfig._cache[cache_key] = (now + SystemConfig._cache_ttl_seconds, value)
        return value
    
    @staticmethod
    def set_value(key, value, description=None, value_type='string'):
        """设置配置值"""
        # 将值转换为字符串进行存储
        str_value = str(value) if value is not None else None
        
        # 查找或创建配置项
        config = SystemConfig.query.filter_by(key=key).first()
        if not config:
            config = SystemConfig(
                key=key,
                value=str_value,
                description=description or key,
                type=value_type
            )
            db.session.add(config)
        else:
            config.value = str_value
            if description:
                config.description = description
            config.type = value_type
        
        db.session.commit()
        cache_key = SystemConfig._cache_key(key)
        with SystemConfig._cache_lock:
            SystemConfig._cache.pop(cache_key, None)
        return config

    @staticmethod
    def clear_cache():
        """清空进程内配置缓存，供测试或运维更新后调用。"""

        with SystemConfig._cache_lock:
            SystemConfig._cache.clear()


class StudentQuestion(db.Model):
    """学生提问记录模型"""
    __tablename__ = 'student_questions'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), db.ForeignKey('users.student_id'), nullable=False)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignments.id'), nullable=False)
    question = db.Column(db.Text, nullable=False)  # 学生的问题
    code_snapshot = db.Column(db.Text, nullable=True)  # 提问时的代码快照
    answer = db.Column(db.Text, nullable=True)  # AI的回答
    is_helpful = db.Column(db.Boolean, nullable=True)  # 学生是否标记为有帮助（可选）
    asked_at = db.Column(db.DateTime, default=dt.now)
    
    # 关联
    student = db.relationship('User', backref=db.backref('questions', lazy=True))
    assignment = db.relationship('Assignment', backref=db.backref('questions', lazy=True))
    
    def __repr__(self):
        return f'<StudentQuestion {self.id} by {self.student_id} for assignment {self.assignment_id}>'


class CodeAdviceRequest(db.Model):
    """代码建议请求记录"""
    __tablename__ = 'code_advice_requests'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(50), db.ForeignKey('users.student_id'), nullable=False)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignments.id'), nullable=True)
    code_snapshot = db.Column(db.Text, nullable=False, comment='请求时的代码快照')
    language = db.Column(db.String(20), nullable=False, default='cpp', comment='代码语言')
    advice = db.Column(db.Text, nullable=True, comment='生成的建议内容')
    requested_at = db.Column(db.DateTime, nullable=False, default=dt.now)
    
    # 关联
    student = db.relationship('User', backref=db.backref('advice_requests', lazy=True))
    assignment = db.relationship('Assignment', backref=db.backref('advice_requests', lazy=True))
    
    def __init__(self, student_id, code_snapshot, language='cpp', assignment_id=None, advice=None, requested_at=None):
        self.student_id = student_id
        self.assignment_id = assignment_id
        self.code_snapshot = code_snapshot
        self.language = language
        self.advice = advice
        self.requested_at = requested_at or dt.now()
    
    def __repr__(self):
        return f'<CodeAdviceRequest {self.id}: {self.student_id} - {self.requested_at}>'


def init_db(app):
    """初始化数据库"""
    with app.app_context():
        if not app.config.get('DB_AUTO_INIT', True):
            return

        db.create_all()  # 创建数据库表

        # 兼容历史数据库：先用 inspector 判断缺列，再执行 ALTER，避免每次
        # 启动都发送一串必然失败的 ALTER TABLE 请求。
        column_migrations = {
            'assignments': {
                'due_date': 'ALTER TABLE assignments ADD COLUMN due_date DATETIME NULL',
            },
            'users': {
                'current_session_id': 'ALTER TABLE users ADD COLUMN current_session_id VARCHAR(100) NULL',
                'email': 'ALTER TABLE users ADD COLUMN email VARCHAR(120) NULL',
                'email_verified_at': 'ALTER TABLE users ADD COLUMN email_verified_at DATETIME NULL',
                'email_verification_required': 'ALTER TABLE users ADD COLUMN email_verification_required BOOLEAN NOT NULL DEFAULT 0',
                'registration_method': "ALTER TABLE users ADD COLUMN registration_method VARCHAR(32) NOT NULL DEFAULT 'legacy'",
                'avatar_path': 'ALTER TABLE users ADD COLUMN avatar_path VARCHAR(255) NULL',
                'password_changed_at': 'ALTER TABLE users ADD COLUMN password_changed_at DATETIME NULL',
                'student_number': 'ALTER TABLE users ADD COLUMN student_number VARCHAR(20) NULL',
            },
            'classes': {
                'teacher_bind_code': 'ALTER TABLE classes ADD COLUMN teacher_bind_code VARCHAR(20) NULL',
                'teacher_bind_code_updated_at': 'ALTER TABLE classes ADD COLUMN teacher_bind_code_updated_at DATETIME NULL',
                'school': "ALTER TABLE classes ADD COLUMN school VARCHAR(100) DEFAULT '酷森思大学'",
                'college': "ALTER TABLE classes ADD COLUMN college VARCHAR(100) DEFAULT '计算机学院'",
            },
        }
        try:
            with db.engine.begin() as conn:
                inspector = inspect(conn)
                for table_name, migrations in column_migrations.items():
                    existing_columns = {
                        column['name'] for column in inspector.get_columns(table_name)
                    }
                    for column_name, statement in migrations.items():
                        if column_name in existing_columns:
                            continue
                        conn.execute(db.text(statement))
                        print(f'已添加 {table_name}.{column_name} 列')
        except Exception as e:
            # 生产部署使用显式 maintenance 命令；开发环境仍保留兼容性降级。
            print(f'自动迁移跳过: {type(e).__name__}: {e}')

        if app.config.get('DB_ENSURE_INDEXES', True):
            ensure_performance_indexes(app)

        try:
            missing_bind_codes = Class.query.filter(Class.teacher_bind_code.is_(None)).all()
            for cls in missing_bind_codes:
                cls.ensure_teacher_bind_code()
            if missing_bind_codes:
                db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'班级绑定码初始化跳过: {type(e).__name__}: {e}')

        # 初始化系统设置
        default_settings = {
            'site_name': {
                'value': 'CodeSense 酷森思',
                'description': '网站名称',
                'type': 'string'
            },
            'site_description': {
                'value': '一个用于评估学生编程能力的在线平台',
                'description': '网站描述',
                'type': 'string'
            },
            'enable_registration': {
                'value': 'true',
                'description': '是否允许新用户注册',
                'type': 'bool'
            },
            'login_message': {
                'value': '欢迎登录 CodeSense 酷森思',
                'description': '登录页面欢迎消息',
                'type': 'string'
            },
            'default_user_score': {
                'value': '60',
                'description': '新用户默认初始分数',
                'type': 'int'
            },
            'submissions_per_day': {
                'value': '10',
                'description': '每日最大提交次数',
                'type': 'int'
            },
            'admin_email': {
                'value': 'daiyupeng5@gmail.com',
                'description': '管理员联系邮箱',
                'type': 'string'
            },
            'system_version': {
                'value': '1.0.0',
                'description': '系统版本',
                'type': 'string'
            }
        }
        
        # 一次查询取出全部配置，避免每个默认项单独 SELECT。
        existing_settings = {
            item.key: item
            for item in SystemConfig.query.filter(
                SystemConfig.key.in_(list(default_settings))
            ).all()
        }
        for key, setting in default_settings.items():
            if key not in existing_settings:
                db.session.add(SystemConfig(
                    key=key,
                    value=setting['value'],
                    description=setting['description'],
                    type=setting['type']
                ))
        
        try:
            db.session.commit()
        except Exception as e:
            print(f"初始化系统设置时出错: {str(e)}")
            db.session.rollback()


class KnowledgePointScore(db.Model):
    """知识点评分模型"""
    __tablename__ = 'knowledge_point_scores'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), db.ForeignKey('users.student_id', ondelete='CASCADE'), nullable=False)
    knowledge_point = db.Column(db.String(50), nullable=False)  # 知识点名称
    score = db.Column(db.Float, default=0.0)  # 得分 (0-100)
    total_attempts = db.Column(db.Integer, default=0)  # 总尝试次数
    correct_attempts = db.Column(db.Integer, default=0)  # 正确次数
    average_difficulty = db.Column(db.Float, default=0.0)  # 平均题目难度
    last_updated = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=dt.utcnow)

    # 关系
    student = db.relationship('User', backref='knowledge_scores')

    # C语言知识点常量
    KNOWLEDGE_POINTS = {
        'basic_syntax': '基础语法',
        'pointer': '指针',
        'function': '函数',
        'array': '数组',
        'string': '字符串',
        'struct': '结构体',
        'file_io': '文件操作',
        'dynamic_memory': '动态内存',
        'linked_list': '链表',
        'tree': '树',
        'sorting': '排序算法',
        'searching': '搜索算法',
        'recursion': '递归'
    }

    @staticmethod
    def get_or_create(student_id, knowledge_point):
        """获取或创建知识点评分记录"""
        record = KnowledgePointScore.query.filter_by(
            student_id=student_id,
            knowledge_point=knowledge_point
        ).first()

        if not record:
            record = KnowledgePointScore(
                student_id=student_id,
                knowledge_point=knowledge_point
            )
            db.session.add(record)
            db.session.flush()

        return record

    @staticmethod
    def update_score(student_id, knowledge_point, assignment_score, difficulty=1.0, weight=1.0):
        """
        更新学生知识点评分

        Args:
            student_id: 学生ID
            knowledge_point: 知识点名称
            assignment_score: 本次作业得分 (0-100)
            difficulty: 题目难度系数 (0.5-2.0)
            weight: 知识点权重 (0.1-2.0)
        """
        record = KnowledgePointScore.get_or_create(student_id, knowledge_point)

        # 更新尝试次数
        record.total_attempts += 1
        if assignment_score >= 60:
            record.correct_attempts += 1

        # 更新平均难度
        if record.total_attempts == 1:
            record.average_difficulty = difficulty
        else:
            record.average_difficulty = (record.average_difficulty * (record.total_attempts - 1) + difficulty) / record.total_attempts

        # 计算新分数 - 考虑难度和权重
        # 公式：新分数 = 0.6 * 旧分数 + 0.4 * (本次得分 * 难度系数 * 权重)
        difficulty_bonus = min(difficulty, 2.0)  # 难度加成最高2倍
        weighted_score = assignment_score * difficulty_bonus * weight

        if record.total_attempts == 1:
            record.score = min(weighted_score, 100.0)
        else:
            record.score = min(0.6 * record.score + 0.4 * weighted_score, 100.0)

        record.last_updated = dt.utcnow()
        db.session.commit()

        return record

    @staticmethod
    def get_student_profile(student_id):
        """
        获取学生的知识点画像
        返回所有知识点的评分字典
        """
        scores = KnowledgePointScore.query.filter_by(student_id=student_id).all()

        profile = {}
        for score in scores:
            profile[score.knowledge_point] = {
                'score': round(score.score, 1),
                'name': KnowledgePointScore.KNOWLEDGE_POINTS.get(score.knowledge_point, score.knowledge_point),
                'total_attempts': score.total_attempts,
                'correct_attempts': score.correct_attempts,
                'accuracy': round(score.correct_attempts / score.total_attempts * 100, 1) if score.total_attempts > 0 else 0,
                'average_difficulty': round(score.average_difficulty, 2),
                'last_updated': score.last_updated.strftime('%Y-%m-%d %H:%M') if score.last_updated else None
            }

        # 补充未测试的知识点
        for key, name in KnowledgePointScore.KNOWLEDGE_POINTS.items():
            if key not in profile:
                profile[key] = {
                    'score': 0,
                    'name': name,
                    'total_attempts': 0,
                    'correct_attempts': 0,
                    'accuracy': 0,
                    'average_difficulty': 0,
                    'last_updated': None
                }

        return profile


class AssignmentKnowledgePoint(db.Model):
    """作业知识点关联模型"""
    __tablename__ = 'assignment_knowledge_points'

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignments.id', ondelete='CASCADE'), nullable=False)
    knowledge_point = db.Column(db.String(50), nullable=False)
    weight = db.Column(db.Float, default=1.0)  # 权重
    difficulty = db.Column(db.Float, default=1.0)  # 难度系数
    auto_detected = db.Column(db.Boolean, default=False)  # 是否AI自动检测
    created_at = db.Column(db.DateTime, default=dt.utcnow)

    # 关系
    assignment = db.relationship('Assignment', backref=db.backref('knowledge_points', cascade='all, delete-orphan'))

    @staticmethod
    def add_to_assignment(assignment_id, knowledge_point, weight=1.0, difficulty=1.0, auto_detected=False):
        """为作业添加知识点标签"""
        # 检查是否已存在
        existing = AssignmentKnowledgePoint.query.filter_by(
            assignment_id=assignment_id,
            knowledge_point=knowledge_point
        ).first()

        if existing:
            # 更新权重和难度
            existing.weight = weight
            existing.difficulty = difficulty
            existing.auto_detected = auto_detected
        else:
            # 创建新记录
            kp = AssignmentKnowledgePoint(
                assignment_id=assignment_id,
                knowledge_point=knowledge_point,
                weight=weight,
                difficulty=difficulty,
                auto_detected=auto_detected
            )
            db.session.add(kp)

        db.session.commit()

    @staticmethod
    def get_assignment_knowledge_points(assignment_id):
        """获取作业的所有知识点"""
        return AssignmentKnowledgePoint.query.filter_by(assignment_id=assignment_id).all()

    @staticmethod
    def remove_from_assignment(assignment_id, knowledge_point):
        """从作业移除知识点"""
        AssignmentKnowledgePoint.query.filter_by(
            assignment_id=assignment_id,
            knowledge_point=knowledge_point
        ).delete()
        db.session.commit() 

class InviteToken(db.Model):
    """教师邀请Token，支持24小时过期和单次使用"""
    __tablename__ = 'invite_tokens'
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(256), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=dt.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.String(20), db.ForeignKey('users.student_id', ondelete='SET NULL'), nullable=True)

    @staticmethod
    def create(token_str, created_by=None):
        record = InviteToken(
            token=token_str,
            expires_at=dt.utcnow() + __import__("datetime").timedelta(hours=24),
            created_by=created_by
        )
        db.session.add(record)
        db.session.commit()
        return record

    @staticmethod
    def validate(token_str):
        """仅校验token是否有效（存在、未使用、未过期），不标记为已使用"""
        record = InviteToken.query.filter_by(token=token_str).first()
        if not record:
            return False, '无效的邀请链接'
        if record.is_used:
            return False, '该邀请链接已被使用'
        if dt.utcnow() > record.expires_at:
            return False, '邀请链接已过期，请联系管理员获取新链接'
        return True, ''

    @staticmethod
    def mark_as_used(token_str):
        """将token标记为已使用"""
        record = InviteToken.query.filter_by(token=token_str).first()
        if record and not record.is_used:
            record.is_used = True
            record.used_at = dt.utcnow()
            db.session.commit()
            return True
        return False

    @staticmethod
    def invalidate_all_unused():
        """作废以前所有未使用的邀请链接"""
        now = dt.utcnow()
        unused_tokens = InviteToken.query.filter_by(is_used=False).filter(InviteToken.expires_at > now).all()
        for t in unused_tokens:
            t.expires_at = now  # 将过期时间设为当前时间即为失效
        db.session.commit()

    @staticmethod
    def validate_and_use(token_str):
        """
        校验并使用token。
        注意：为了更好的用户体验，注册页面加载时应只用 validate()，
        只有在表单提交成功后才调用 mark_as_used()。
        """
        ok, err_msg = InviteToken.validate(token_str)
        if ok:
            InviteToken.mark_as_used(token_str)
        return ok, err_msg


class PasswordResetToken(db.Model):
    """一次性密码重置令牌，只保存令牌摘要，不保存原始令牌。"""
    __tablename__ = 'password_reset_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.String(20),
        db.ForeignKey('users.student_id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=dt.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    used_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    requested_ip = db.Column(db.String(45), nullable=True)
    created_by = db.Column(
        db.String(20),
        db.ForeignKey('users.student_id', ondelete='SET NULL'),
        nullable=True,
    )


class EmailVerificationToken(db.Model):
    """邮箱注册验证令牌，只保存令牌摘要，不保存原始令牌。"""
    __tablename__ = 'email_verification_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.String(20),
        db.ForeignKey('users.student_id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=dt.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    used_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    requested_ip = db.Column(db.String(45), nullable=True)

    user = db.relationship(
        'User',
        backref=db.backref('email_verification_tokens', lazy='dynamic'),
    )


class AuthIdentity(db.Model):
    """可扩展的登录身份绑定表，为后续接入社交账号预留。"""
    __tablename__ = 'auth_identities'
    __table_args__ = (
        UniqueConstraint(
            'provider',
            'provider_subject_hash',
            name='uq_auth_identities_provider_subject',
        ),
        UniqueConstraint(
            'user_id',
            'provider',
            name='uq_auth_identities_user_provider',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.String(20),
        db.ForeignKey('users.student_id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    provider = db.Column(db.String(32), nullable=False)
    # 不保存第三方原始 subject；统一保存带 provider 作用域的 SHA-256 摘要。
    provider_subject_hash = db.Column(db.String(64), nullable=False)
    provider_email = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=dt.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=dt.utcnow, onupdate=dt.utcnow, nullable=False)

    user = db.relationship(
        'User',
        backref=db.backref('auth_identities', lazy='dynamic'),
    )


# ============================================================
# 三阶段引导式学习系统（Guided Learning Arena）数据模型
# 独立表，不修改任何现有模型
# ============================================================

class AssignmentThinkingPreset(db.Model):
    """AI预设数据表 — 老师发布作业后由AI自动生成"""
    __tablename__ = 'assignment_thinking_presets'

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignments.id', ondelete='CASCADE'), nullable=False, unique=True)
    reference_code = db.Column(db.Text, nullable=True)  # 标准答案代码
    key_steps = db.Column(db.Text, nullable=True)  # JSON: 关键解题步骤列表
    code_blocks = db.Column(db.Text, nullable=True)  # JSON: 正确代码块列表（含缩进层级）
    noise_blocks = db.Column(db.Text, nullable=True)  # JSON: 噪声代码块列表
    quiz_steps = db.Column(db.Text, nullable=True)  # JSON: 阶段二逐步选择/填空题数据
    difficulty_config = db.Column(db.Text, nullable=True)  # JSON: 费曼阶段难度配置
    algorithm_summary = db.Column(db.Text, nullable=True)  # 标准算法简述（阶段1脚手架文本）
    status = db.Column(db.String(20), default='pending')  # pending / generating / ready / failed
    error_message = db.Column(db.Text, nullable=True)  # 生成失败时的错误信息
    created_at = db.Column(db.DateTime, default=dt.utcnow)
    updated_at = db.Column(db.DateTime, default=dt.utcnow, onupdate=dt.utcnow)

    # 关系
    assignment = db.relationship('Assignment', backref=db.backref('thinking_preset', uselist=False))

    def get_key_steps(self):
        """获取关键步骤列表"""
        if not self.key_steps:
            return []
        try:
            return json.loads(self.key_steps)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_code_blocks(self):
        """获取代码块列表"""
        if not self.code_blocks:
            return []
        try:
            return json.loads(self.code_blocks)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_noise_blocks(self):
        """获取噪声块列表"""
        if not self.noise_blocks:
            return []
        try:
            return json.loads(self.noise_blocks)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_quiz_steps(self):
        """获取阶段二逐步选择/填空题数据"""
        if not self.quiz_steps:
            return []
        try:
            steps = json.loads(self.quiz_steps)
            if self.reference_code and steps:
                import re
                custom_types = re.findall(r'(?:struct|class)\s+\w+\s*\{(?:[^{}]|\{[^{}]*\})*?\};', self.reference_code, re.DOTALL)
                if custom_types:
                    types_str = "\n".join(custom_types) + "\n\n"
                    first_step = steps[0]
                    if 'part_header' in first_step:
                        header = first_step.get('part_header') or ''
                        # Avoid duplicate injection
                        first_type_name = re.search(r'(?:struct|class)\s+(\w+)', custom_types[0])
                        has_already = False
                        if first_type_name:
                            has_already = first_type_name.group(1) in header
                        if not has_already:
                            first_step['part_header'] = types_str + header
            return steps
        except (json.JSONDecodeError, TypeError):
            return []

    def get_difficulty_config(self):
        """获取难度配置"""
        if not self.difficulty_config:
            return {'feynman_rounds': 5, 'student_persona': 'curious'}
        try:
            return json.loads(self.difficulty_config)
        except (json.JSONDecodeError, TypeError):
            return {'feynman_rounds': 5, 'student_persona': 'curious'}

    def get_algorithm_summary(self):
        """获取算法简述（阶段1脚手架）"""
        return self.algorithm_summary or ''


class ThinkingSession(db.Model):
    """学生学习会话表 — 记录一次完整的三阶段学习过程"""
    __tablename__ = 'thinking_sessions'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), db.ForeignKey('users.student_id', ondelete='CASCADE'), nullable=False)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignments.id', ondelete='CASCADE'), nullable=False)
    current_stage = db.Column(db.Integer, default=1)  # 当前阶段 1/2/3
    # 阶段1数据
    stage1_description = db.Column(db.Text, nullable=True)  # 学生的自然语言描述
    stage1_score = db.Column(db.Float, nullable=True)  # 思路匹配度 (0-100)
    stage1_hint_count = db.Column(db.Integer, default=0)  # 阶段1提示请求次数
    # 阶段2数据
    stage2_block_order = db.Column(db.Text, nullable=True)  # JSON: 学生拼装的代码块顺序
    stage2_completed = db.Column(db.Boolean, default=False)
    stage2_hint_count = db.Column(db.Integer, default=0)
    # 阶段3数据
    stage3_completed = db.Column(db.Boolean, default=False)
    stage3_teacher_rounds = db.Column(db.Integer, default=0)  # 老师Agent对话轮次
    stage3_student_rounds = db.Column(db.Integer, default=0)  # 坏学生Agent对话轮次
    # 总览
    total_time_seconds = db.Column(db.Integer, default=0)  # 总用时(秒)
    started_at = db.Column(db.DateTime, default=dt.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='in_progress')  # in_progress / completed / abandoned

    # 关系
    student = db.relationship('User', backref=db.backref('thinking_sessions', lazy='dynamic'))
    assignment = db.relationship('Assignment', backref=db.backref('thinking_sessions', lazy='dynamic'))
    logs = db.relationship('ThinkingStageLog', backref='session', lazy='dynamic', cascade='all, delete-orphan')

    def to_summary_dict(self):
        """生成供老师查看的摘要"""
        return {
            'id': self.id,
            'student_id': self.student_id,
            'assignment_id': self.assignment_id,
            'current_stage': self.current_stage,
            'stage1_score': self.stage1_score,
            'stage2_completed': self.stage2_completed,
            'stage3_completed': self.stage3_completed,
            'total_time_seconds': self.total_time_seconds,
            'hint_count': self.stage1_hint_count + self.stage2_hint_count,
            'started_at': self.started_at.strftime('%Y-%m-%d %H:%M:%S') if self.started_at else None,
            'completed_at': self.completed_at.strftime('%Y-%m-%d %H:%M:%S') if self.completed_at else None,
            'status': self.status
        }


class ThinkingStageLog(db.Model):
    """交互过程日志 — 记录每一次对话、操作、事件"""
    __tablename__ = 'thinking_stage_logs'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('thinking_sessions.id', ondelete='CASCADE'), nullable=False)
    stage = db.Column(db.Integer, nullable=False)  # 阶段 1/2/3
    event_type = db.Column(db.String(50), nullable=False)  # chat / hint_request / block_move / stage_pass / description_submit 等
    role = db.Column(db.String(30), nullable=True)  # student / teacher_agent / student_agent
    content = db.Column(db.Text, nullable=True)  # 内容
    metadata_json = db.Column(db.Text, nullable=True)  # JSON: 额外元数据
    created_at = db.Column(db.DateTime, default=dt.utcnow)

    def get_metadata(self):
        """获取元数据"""
        if not self.metadata_json:
            return {}
        try:
            return json.loads(self.metadata_json)
        except (json.JSONDecodeError, TypeError):
            return {}


class TeacherAISuggestion(db.Model):
    """教师首页和落地页 AI 个性化建议"""
    __tablename__ = 'teacher_ai_suggestions'

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.String(20), db.ForeignKey('users.student_id', ondelete='CASCADE'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id', ondelete='CASCADE'), nullable=False, unique=True, index=True)
    suggestion_markdown = db.Column(db.Text, nullable=True)  # AI 建议 Markdown 内容
    suggestion_json = db.Column(db.Text, nullable=True)      # 结构化建议（重点学生、弱势知识点、推荐补练作业）
    last_updated = db.Column(db.DateTime, default=dt.utcnow)  # 最后更新时间
    status = db.Column(db.String(20), default='pending')      # pending, processing, completed, failed

    # 关系
    teacher = db.relationship('User', backref=db.backref('class_ai_suggestions', lazy='dynamic'))
    classroom = db.relationship('Class', backref=db.backref('ai_suggestion', uselist=False))

    @staticmethod
    def get_or_create(class_id, teacher_id):
        """获取或创建 AI 建议记录"""
        from sqlalchemy.exc import IntegrityError
        suggestion = TeacherAISuggestion.query.filter_by(class_id=class_id).first()
        if not suggestion:
            try:
                suggestion = TeacherAISuggestion(class_id=class_id, teacher_id=teacher_id)
                db.session.add(suggestion)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                suggestion = TeacherAISuggestion.query.filter_by(class_id=class_id).first()
        return suggestion

    def get_suggestion_dict(self):
        """解析 JSON 格式的建议"""
        if not self.suggestion_json:
            return {}
        try:
            return json.loads(self.suggestion_json)
        except (json.JSONDecodeError, TypeError):
            return {}


# 高频列表、统计和阶段三恢复查询使用的组合索引。它们集中声明在模型末尾，
# 既会进入新库 metadata，也可以由 ensure_performance_indexes 补到历史库。
PERFORMANCE_INDEXES = (
    Index('ix_users_student_number', User.student_number),
    Index('ix_users_class_name_usertype', User.class_name, User.usertype),
    Index('ix_users_class_id_usertype', User.class_id, User.usertype),
    Index('ix_assignments_creator_created', Assignment.creator_id, Assignment.created_time),
    Index('ix_submissions_student_submitted', Submission.student_id, Submission.submitted_at),
    Index('ix_submissions_assignment_submitted', Submission.assignment_id, Submission.submitted_at),
    Index('ix_test_cases_assignment_order', TestCase.assignment_id, TestCase.order_index),
    Index('ix_system_logs_user_created', SystemLog.user_id, SystemLog.created_at),
    Index('ix_system_logs_type_created', SystemLog.log_type, SystemLog.created_at),
    Index('ix_ability_trends_status_updated', AbilityTrend.status, AbilityTrend.last_updated),
    Index('ix_student_questions_student_assignment_time', StudentQuestion.student_id, StudentQuestion.assignment_id, StudentQuestion.asked_at),
    Index('ix_code_advice_student_time', CodeAdviceRequest.student_id, CodeAdviceRequest.requested_at),
    Index('ix_assignment_kp_assignment_name', AssignmentKnowledgePoint.assignment_id, AssignmentKnowledgePoint.knowledge_point),
    Index('ix_invite_tokens_used_expiry', InviteToken.is_used, InviteToken.expires_at),
    Index(
        'ix_email_verification_tokens_user_expiry',
        EmailVerificationToken.user_id,
        EmailVerificationToken.expires_at,
    ),
    Index('ix_thinking_sessions_student_assignment', ThinkingSession.student_id, ThinkingSession.assignment_id),
    Index('ix_thinking_sessions_assignment_status', ThinkingSession.assignment_id, ThinkingSession.status),
    Index('ix_thinking_logs_session_stage_time', ThinkingStageLog.session_id, ThinkingStageLog.stage, ThinkingStageLog.created_at),
    Index('ix_teacher_ai_suggestions_teacher', TeacherAISuggestion.teacher_id),
)


def ensure_performance_indexes(app=None):
    """Create declared indexes that are missing from an existing database.

    ``checkfirst`` makes the operation idempotent. Errors are logged and do not
    prevent a development server from starting; production should run the
    explicit maintenance command before bringing workers online.
    """

    created = 0
    try:
        engine = db.engine
        for index in PERFORMANCE_INDEXES:
            try:
                index.create(bind=engine, checkfirst=True)
                created += 1
            except SQLAlchemyError as exc:
                if app is not None:
                    app.logger.warning(
                        '索引维护跳过 %s: %s', index.name, type(exc).__name__
                    )
        if app is not None and created:
            app.logger.info('性能索引检查完成，共处理 %d 个索引', created)
    except Exception as exc:
        if app is not None:
            app.logger.warning('性能索引检查失败: %s', type(exc).__name__)
    return created
