"""
主要功能路由
"""
import datetime
import csv
import io
import json  # 添加json模块导入
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, Response, current_app, abort, g
from flask_login import login_required, current_user
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload
from models import (
    db,
    User,
    Assignment,
    Submission,
    SystemLog,
    SystemConfig,
    AbilityTrend,
    KnowledgePointScore,
    ThinkingSession,
    StudentLearningVector,
)
from services.teacher_analytics import build_teacher_dashboard_data
from services.learning_graph import (
    LearningGraphAccessError,
    build_student_learning_graph,
    build_teacher_knowledge_focus,
    build_teacher_knowledge_coverage,
)
from services.student_vector_health import build_teacher_learning_memory_health
from services.teacher_learning_actions import (
    TeacherLearningActionAccessError,
    build_teacher_learning_actions,
    send_learning_memory_refresh_reminders,
)
from services.demo_database import current_demo_run_id
from services.feedback import (
    FEEDBACK_CATEGORIES,
    FEEDBACK_CATEGORY_LABELS,
    FEEDBACK_STATUS_LABELS,
    FEEDBACK_STATUS_OPTIONS,
    FeedbackValidationError,
    FeedbackStatusError,
    create_feedback_record,
    find_feedback,
    list_feedback,
    next_feedback_status_options,
    save_feedback,
    update_feedback_status,
)
from services.notifications import (
    create_notification,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)
from services.submission_reviews import count_open_reviews
from services.session_lifecycle import latest_session_activity, session_lifecycle_payload
from services.action_center import build_action_center
from services.profile import get_profile_settings, PROFILE_VISIBILITY_PUBLIC
from services.student_vector_store import (
    StudentVectorRebuildError,
    get_student_vector_snapshot,
    list_student_learning_sources,
    rebuild_student_vector_index_with_retry,
    revoke_student_vector_source,
)
from utils.auth import admin_required
from utils.access import authoritative_class_name, assignment_target_class_filter, can_access_student
from utils.export_safety import safe_export_cell
from utils.maturity_calculator import calculate_maturity_components
from utils.sse import sse_event, sse_response
from utils.timezone import format_display_datetime

main = Blueprint('main', __name__)


def _write_export_row(writer, values):
    writer.writerow([safe_export_cell(value) for value in values])


_ANALYSIS_STATUS_LABELS = {
    'pending': '等待分析',
    'processing': '分析中',
    'completed': '已完成',
    'failed': '分析失败',
    'outdated': '等待刷新',
}


def _knowledge_profile_rows(profile):
    """Return the complete, stable-order C-language profile for templates."""
    rows = []
    for key, name in KnowledgePointScore.KNOWLEDGE_POINTS.items():
        item = dict(profile.get(key) or {})
        item.setdefault('score', 0)
        item.setdefault('total_attempts', 0)
        item.setdefault('correct_attempts', 0)
        item.setdefault('accuracy', 0)
        item.setdefault('average_difficulty', 0)
        rows.append({
            'key': key,
            'name': name,
            **item,
        })
    return rows


def _analysis_status_label(status):
    return _ANALYSIS_STATUS_LABELS.get(status, '等待分析')


def _learning_graph_fallback(scope):
    return {
        'nodes': [],
        'edges': [],
        'recommendations': [],
        'meta': {
            'scope': scope,
            'sample_size': 0,
            'assignment_count': 0,
            'knowledge_point_count': 0,
            'virtual_nodes': ['student:mastery'] if scope == 'student' else [],
        },
    }

# 添加编辑器测试路由
@main.route('/test_editor')
def test_editor():
    """编辑器测试页面"""
    return render_template('test_editor.html')

# 添加C++代码编辑器示例路由
@main.route('/cpp_editor_demo')
def cpp_editor_demo():
    """C++代码编辑器示例页面"""
    return render_template('cpp_editor_demo.html')

# 添加积木编程（Parsons Problems）演示路由
@main.route('/parsons_demo')
def parsons_demo():
    """积木编程演示页面"""
    return render_template('parsons_demo.html')

@main.route('/cot_demo')
def cot_demo():
    """思维链演示页面"""
    return render_template('cot_demo.html')

# 添加全局上下文处理器，使模板可以使用now()函数
@main.app_context_processor
def inject_now():
    return {'now': datetime.datetime.now}

@main.route('/home')
@login_required
def home():
    """用户主页"""
    # 获取当前登录用户的个人信息
    user = current_user
    
    # 根据用户类型显示不同页面
    if user.is_admin:
        return redirect(url_for('main.admin_dashboard'))
    elif user.is_teacher:
        return redirect(url_for('main.teacher_dashboard'))
    else:
        student_id = current_user.student_id
        class_name = authoritative_class_name(current_user)

        now = datetime.datetime.now()
        
        # 1. 获取分配给该学生班级的作业（基础查询）
        assigned_assignments_query = Assignment.query
        if class_name:
            assigned_assignments_query = assigned_assignments_query.filter(
                assignment_target_class_filter(class_name)
            )
        else:
            # 如果没有班级，则没有作业
            assigned_assignments_query = assigned_assignments_query.filter(db.false())
        
        # 首页只需要作业 ID 和少量近期记录，不要把所有作业/代码正文
        # 一次性加载进 ORM identity map。一次查出 (id, due_date)，
        # 全部 id 与未截止 id 都在 Python 里派生，避免对同一批作业
        # 发两次查询（原来 active 过滤又走了一次 round-trip）。
        assigned_rows = assigned_assignments_query.with_entities(
            Assignment.id, Assignment.due_date,
        ).all()
        all_assigned_ids = [row[0] for row in assigned_rows]

        # 过滤出当前有效的作业（未过截止日期的或无截止日期的）
        active_assignment_ids = [
            row[0] for row in assigned_rows
            if row[1] is None or row[1] >= now
        ]

        # 2. 首页统计保留历史作业，避免截止日期过滤让学生误以为数据被清空。
        # 当前有效作业仍单独保留，供页面展示“当前未截止”信息。
        assignments_count = len(all_assigned_ids)
        active_assignments_count = len(active_assignment_ids)

        # “已提交”显示所有历史作业中已经提交过的独立题目数量。
        submitted_assignment_ids = [row[0] for row in db.session.query(
            Submission.assignment_id
        ).filter(
            Submission.student_id == student_id,
            Submission.assignment_id.in_(all_assigned_ids)
        ).distinct().all()]
        submissions_count = len(submitted_assignment_ids)

        # 平均得分的计算范围仍保留为所有已分配给该学生的作业，以反映整体表现
        average_score_query = db.session.query(func.avg(Submission.score)).filter(
            Submission.student_id == student_id,
            Submission.assignment_id.in_(all_assigned_ids)
        ).scalar()
        average_score = average_score_query if average_score_query else 0

        # 3. 获取首页需要展示的最近记录。完整历史在“提交记录”页面分页查看；
        # 限制这里的代码正文数量，避免一个学生的大量历史提交拖慢首页。
        submissions_query = Submission.query.filter(
            Submission.student_id == student_id,
            Submission.assignment_id.in_(all_assigned_ids)
        )
        submissions = submissions_query.options(
            joinedload(Submission.assignment)
        ).order_by(Submission.submitted_at.desc()).limit(5).all()
        
        # 异步架构：读取能力趋势分析任务状态。页面 GET 不能因为访问首页
        # 就创建数据库记录；首次任务由提交路径或显式分析请求负责。
        from models import AbilityTrend
        trend_record = AbilityTrend.query.filter_by(student_id=student_id).first()
        if not trend_record:
            trend_record = AbilityTrend(
                student_id=student_id,
                status='pending',
                submissions_count=0,
            )
        
        
        # 修复条件判断逻辑
        if trend_record.status == 'failed':
            ability_analysis = {
                "trend": "能力分析失败",
                "improvement": "在上次分析过程中出现问题，请稍后点击重试。",
                "suggestions": [],
                "_status": "failed",
                "_last_updated": trend_record.last_updated.strftime('%Y-%m-%d %H:%M:%S') if trend_record.last_updated else None
            }
        elif (trend_record.status == 'completed' and 
            trend_record.trend_data is not None and 
            len(str(trend_record.trend_data)) > 0):
            # 有已完成的分析结果，使用它
            try:
                ability_analysis = trend_record.get_trend_dict()
                # 添加状态信息供前端使用
                ability_analysis['_status'] = 'completed'
                ability_analysis['_last_updated'] = trend_record.last_updated.strftime('%Y-%m-%d %H:%M:%S') if trend_record.last_updated else None
            except Exception as e:
                current_app.logger.warning("解析学生 %s 的能力趋势失败: %s", student_id, type(e).__name__)
                # 解析失败时使用加载状态
                ability_analysis = {
                    "trend": "解析趋势数据时出现问题，请点击刷新重试",
                    "improvement": "数据解析错误，请稍后重试",
                    "suggestions": [],
                    "_status": "failed",
                    "_last_updated": trend_record.last_updated.strftime('%Y-%m-%d %H:%M:%S') if trend_record.last_updated else None
                }
        else:
            # 分析中或未开始，返回默认状态
            ability_analysis = {
                "trend": "正在为您分析编程能力发展趋势...",
                "improvement": "AI正在深度分析您的代码提交记录，请稍候...",
                "suggestions": [],
                "_status": trend_record.status,  # 添加状态信息供前端使用
                "_last_updated": trend_record.last_updated.strftime('%Y-%m-%d %H:%M:%S') if trend_record.last_updated else None
            }
        
        # 获取最近的作业
        class_name = authoritative_class_name(current_user)
        recent_assignments = []
        if class_name:
            recent_assignments = Assignment.query.filter(
                assignment_target_class_filter(class_name)
            ).order_by(Assignment.created_time.desc()).limit(4).all()

        # 会话连续性只读取当前学生自己的最近记录，并用一次聚合查询补充最后活动时间。
        recent_sessions = ThinkingSession.query.filter_by(
            student_id=student_id,
        ).options(
            joinedload(ThinkingSession.assignment),
        ).order_by(
            ThinkingSession.started_at.desc(),
            ThinkingSession.id.desc(),
        ).limit(3).all()
        activity_by_session = latest_session_activity([item.id for item in recent_sessions])
        recent_learning_sessions = []
        for item in recent_sessions:
            lifecycle = session_lifecycle_payload(
                item,
                last_activity_at=activity_by_session.get(item.id),
            )
            recent_learning_sessions.append({
                'assignment': item.assignment,
                'lifecycle': lifecycle,
            })

        # 首页直接渲染完整画像，前端 SSE 连接成功后再用同一份数据刷新，
        # 这样首屏不会只显示“加载中”，网络较慢时也能看到真实的演示数据。
        knowledge_profile = KnowledgePointScore.get_student_profile(student_id)
        knowledge_profile_rows = _knowledge_profile_rows(knowledge_profile)
        student_vector_snapshot = get_student_vector_snapshot(student_id)
        student_learning_sources = list_student_learning_sources(student_id)
        try:
            learning_graph = build_student_learning_graph(
                student_id=student_id,
                limit=8,
            )
        except LearningGraphAccessError:
            current_app.logger.warning(
                '学生 %s 的知识路径超出访问范围，使用空状态',
                student_id,
            )
            learning_graph = _learning_graph_fallback('student')
        except Exception:
            current_app.logger.exception(
                '加载学生 %s 的知识路径失败 request_id=%s',
                student_id,
                getattr(g, 'codesense_request_id', None),
            )
            learning_graph = _learning_graph_fallback('student')
        analysis_status = trend_record.status or 'pending'
        # 1. 通过统一的能力引擎获取雷达图数据
        ability_scores = current_user.get_ability_scores()
        algorithm_score = ability_scores.get('algorithm', 60)
        style_score = ability_scores.get('style', 60)
        functionality_score = ability_scores.get('functionality', 60)
        efficiency_score = ability_scores.get('efficiency', 60)
        readability_score = ability_scores.get('readability', 60)
        
        # 2. 获取班级平均能力得分
        class_averages = User.get_class_average_scores()
        class_name = authoritative_class_name(current_user)
        st_class_avg = class_averages.get(class_name, {})
        
        class_algorithm_score = st_class_avg.get('algorithm', 65)
        class_style_score = st_class_avg.get('style', 65)
        class_functionality_score = st_class_avg.get('functionality', 65)
        class_efficiency_score = st_class_avg.get('efficiency', 65)
        class_readability_score = st_class_avg.get('readability', 65)
        
        # 3. 准备能力数据的 JSON 格式供雷达图使用
        skills_data = {
            'student': {
                'algorithm': float(algorithm_score),
                'style': float(style_score),
                'functionality': float(functionality_score),
                'efficiency': float(efficiency_score),
                'readability': float(readability_score)
            },
            'class_average': {
                'algorithm': float(class_algorithm_score),
                'style': float(class_style_score),
                'functionality': float(class_functionality_score),
                'efficiency': float(class_efficiency_score),
                'readability': float(class_readability_score)
            }
        }
        
        # 使用前面已经计算出的班级平均分，避免重复执行一次全班统计。
        all_subs = Submission.query.with_entities(
            Submission.submitted_at,
            Submission.score,
        ).filter_by(student_id=student_id).order_by(Submission.submitted_at.asc()).all()
        
        # 使用统一的 maturity 计算器
        ability_scores = {
            'algorithm': float(algorithm_score),
            'style': float(style_score),
            'functionality': float(functionality_score),
            'efficiency': float(efficiency_score),
            'readability': float(readability_score)
        }
        maturity_result = calculate_maturity_components(
            all_subs,
            ability_scores=ability_scores,
            class_averages=class_averages,
            class_name=class_name
        )
        phi_avg = maturity_result['phi_avg']
        phi_freq = maturity_result['phi_freq']
        phi_std = maturity_result['phi_std']
        phi_grad = maturity_result['phi_grad']
        maturity_score = maturity_result['maturity_score']

        # 计算学生已提交的作业 ID 集合（用于前端高亮已完成任务）
        submitted_assignments = submitted_assignment_ids

        # 准备渲染数据
        context = {
            'user': user,
            'assignments_count': assignments_count,
            'active_assignments_count': active_assignments_count,
            'submissions_count': submissions_count,
            'average_score': average_score,
            'maturity_score': maturity_score,
            'phi_avg': round(phi_avg, 1),
            'phi_freq': round(phi_freq, 1),
            'phi_std': round(phi_std, 1),
            'phi_grad': round(phi_grad, 1),
            'recent_assignments': recent_assignments,
            'recent_learning_sessions': recent_learning_sessions,
            'submissions': submissions,
            'knowledge_profile': knowledge_profile,
            'knowledge_profile_rows': knowledge_profile_rows,
            'student_vector_snapshot': student_vector_snapshot,
            'student_learning_sources': student_learning_sources,
            'learning_graph': learning_graph,
            'ability_trend': trend_record,
            'analysis_status': analysis_status,
            'analysis_status_label': _analysis_status_label(analysis_status),
            'submitted_assignments': submitted_assignments,
            # 雷达图数据
            'algorithm_score': float(algorithm_score),
            'style_score': float(style_score),
            'functionality_score': float(functionality_score),
            'efficiency_score': float(efficiency_score),
            'readability_score': float(readability_score),
            'class_algorithm_score': float(class_algorithm_score),
            'class_style_score': float(class_style_score),
            'class_functionality_score': float(class_functionality_score),
            'class_efficiency_score': float(class_efficiency_score),
            'class_readability_score': float(class_readability_score),
            'skills_data_json': json.dumps(skills_data)  # 添加JSON格式的技能数据
        }
        
        return render_template('student_home.html', **context)

@main.route('/admin_dashboard')
@login_required
@admin_required
def admin_dashboard():
    """管理员仪表盘，仅管理员可访问并只展示数据库中的真实数据。"""
    empty_chart_data = {
        'assignments': {'labels': [], 'counts': []},
        'scores': {'labels': [], 'counts': [], 'colors': []},
        'activity': {'labels': [], 'counts': []},
    }

    try:
        total_users = User.query.count()
        total_assignments = Assignment.query.count()
        total_submissions = Submission.query.count()
        average_score = db.session.query(func.avg(Submission.score)).scalar() or 0

        now = datetime.datetime.utcnow()
        recent_activities = []
        for log in SystemLog.query.order_by(
            SystemLog.created_at.desc()
        ).limit(10).all():
            created_at = log.created_at or now
            elapsed_seconds = max(0, int((now - created_at).total_seconds()))
            if elapsed_seconds >= 86400:
                time_str = f"{elapsed_seconds // 86400}天前"
            elif elapsed_seconds >= 3600:
                time_str = f"{elapsed_seconds // 3600}小时前"
            elif elapsed_seconds >= 60:
                time_str = f"{elapsed_seconds // 60}分钟前"
            else:
                time_str = "刚刚"
            recent_activities.append({
                'icon': log.icon or 'bi bi-activity',
                'message': log.content,
                'time': time_str,
            })

        assignments_data = db.session.query(
            Assignment.title,
            func.count(Submission.id).label('submit_count'),
        ).outerjoin(
            Submission, Assignment.id == Submission.assignment_id
        ).group_by(
            Assignment.id
        ).order_by(
            func.count(Submission.id).desc()
        ).limit(10).all()

        score_distribution = db.session.query(
            Submission.score,
            func.count(Submission.id).label('count'),
        ).filter(
            Submission.score.isnot(None)
        ).group_by(
            Submission.score
        ).order_by(
            Submission.score
        ).all()

        today = now.date()
        date_range = [
            (today - datetime.timedelta(days=offset)).strftime('%Y-%m-%d')
            for offset in range(29, -1, -1)
        ]
        daily_counts = {date_key: 0 for date_key in date_range}
        daily_submissions = db.session.query(
            func.date(Submission.submitted_at).label('day'),
            func.count(Submission.id).label('count'),
        ).filter(
            Submission.submitted_at >= today - datetime.timedelta(days=29)
        ).group_by(
            func.date(Submission.submitted_at)
        ).all()
        for row in daily_submissions:
            day_key = str(row.day)
            if day_key in daily_counts:
                daily_counts[day_key] = int(row.count)

        palette = [
            'rgba(54, 162, 235, 0.8)',
            'rgba(75, 192, 192, 0.8)',
            'rgba(255, 205, 86, 0.8)',
            'rgba(255, 159, 64, 0.8)',
            'rgba(255, 99, 132, 0.8)',
        ]
        score_labels = [f"{row.score}" for row in score_distribution]
        chart_data = {
            'assignments': {
                'labels': [row.title for row in assignments_data],
                'counts': [int(row.submit_count) for row in assignments_data],
            },
            'scores': {
                'labels': score_labels,
                'counts': [int(row.count) for row in score_distribution],
                'colors': [
                    palette[index % len(palette)]
                    for index, _ in enumerate(score_distribution)
                ],
            },
            'activity': {
                'labels': date_range,
                'counts': [daily_counts[date_key] for date_key in date_range],
            },
        }

        return render_template(
            'admin_dashboard.html',
            total_users=total_users,
            total_assignments=total_assignments,
            total_submissions=total_submissions,
            average_score=average_score,
            recent_activities=recent_activities,
            chart_data=chart_data,
            chart_data_error=False,
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            '加载管理员仪表盘统计数据失败 request_id=%s',
            getattr(g, 'codesense_request_id', None),
        )
        flash('管理员仪表盘统计数据暂时无法加载，请稍后重试。', 'danger')
        return render_template(
            'admin_dashboard.html',
            total_users=0,
            total_assignments=0,
            total_submissions=0,
            average_score=0,
            recent_activities=[],
            chart_data=empty_chart_data,
            chart_data_error=True,
        )


@main.route('/student/rebuild-learning-memory', methods=['POST'])
@login_required
def rebuild_student_learning_memory():
    """Rebuild the current student's private learning index."""

    if getattr(current_user, 'usertype', None) != '学生':
        flash('只有学生可以更新自己的学习记忆。', 'warning')
        return redirect(url_for('main.home'))

    try:
        snapshot = rebuild_student_vector_index_with_retry(current_user.student_id)
    except StudentVectorRebuildError:
        flash('学习记忆更新失败，原有记录仍然保留，请稍后重试。', 'danger')
    else:
        flash(
            f"学习记忆已更新，共保留 {snapshot['active_count']} 条本人记录。",
            'success',
        )
    return redirect(url_for('main.home'))


@main.route('/student/learning-memory/revoke', methods=['POST'])
@login_required
def revoke_student_learning_memory_source():
    """撤回当前学生的一条学习来源。"""

    if getattr(current_user, 'usertype', None) != '学生':
        flash('只有学生可以管理自己的学习记忆。', 'warning')
        return redirect(url_for('main.home'))

    source_type = (request.form.get('source_type') or '').strip()
    source_id = (request.form.get('source_id') or '').strip()
    if not source_type or not source_id:
        flash('请选择要撤回的学习来源。', 'warning')
        return redirect(url_for('main.home'))

    matching_rows = StudentLearningVector.query.filter_by(
        student_id=current_user.student_id,
        source_type=source_type,
        source_id=source_id,
        scope_type='student_private',
    ).all()
    if not matching_rows or not any(row.status == 'active' for row in matching_rows):
        flash('学习来源不存在或已经撤回。', 'warning')
        return redirect(url_for('main.home'))

    revoke_student_vector_source(
        current_user.student_id,
        source_type,
        source_id,
    )
    flash('学习来源已撤回，后续学习记忆更新也会保留此选择。', 'success')
    return redirect(url_for('main.home'))


@main.route('/teacher_dashboard')
@login_required
def teacher_dashboard():
    """教师仪表盘"""
    if not current_user.is_teacher:
        flash('您没有权限访问此页面', 'danger')
        return redirect(url_for('main.home'))

    teacher = current_user
    dashboard = build_teacher_dashboard_data(teacher)
    try:
        learning_graph = build_teacher_knowledge_coverage(
            viewer_id=teacher.student_id,
            limit=10,
        )
    except LearningGraphAccessError:
        current_app.logger.warning(
            '教师 %s 的班级知识覆盖超出访问范围，使用空状态',
            teacher.student_id,
        )
        learning_graph = _learning_graph_fallback('teacher_class')
    except Exception:
        current_app.logger.exception(
            '加载教师 %s 的班级知识覆盖失败 request_id=%s',
            teacher.student_id,
            getattr(g, 'codesense_request_id', None),
        )
        learning_graph = _learning_graph_fallback('teacher_class')

    learning_memory_health = build_teacher_learning_memory_health(teacher)
    teacher_learning_actions = build_teacher_learning_actions(teacher, limit=12)
    
    from models import TeacherAISuggestion
    ai_suggestions = {sug.class_id: sug for sug in TeacherAISuggestion.query.filter_by(teacher_id=teacher.student_id).all()}
    open_review_count = count_open_reviews(teacher)

    return render_template('teacher_home.html',
                           teacher=teacher,
                           dashboard=dashboard,
                           managed_classes=dashboard['managed_classes'],
                           student_count=dashboard['student_count'],
                           student_rows=dashboard['student_rows'],
                           total_submissions=dashboard['total_submissions'],
                           recent_submissions=dashboard['recent_submissions'],
                           submission_trend=dashboard['submission_trend'],
                           class_cards=dashboard['class_cards'],
                           attention=dashboard['attention'],
                           chart_data=dashboard['chart_data'],
                           learning_graph=learning_graph,
                           learning_memory_health=learning_memory_health,
                           teacher_learning_actions=teacher_learning_actions,
                           ai_suggestions=ai_suggestions,
                           open_review_count=open_review_count)


@main.route('/teacher/classes/<int:class_id>/learning-memory-reminder', methods=['POST'])
@login_required
def teacher_learning_memory_reminder(class_id):
    """向指定班级中需要更新索引的学生发送站内提醒。"""

    if not current_user.is_teacher:
        abort(403)

    try:
        result = send_learning_memory_refresh_reminders(
            current_user,
            class_id,
            url=url_for('main.home') + '#student-learning-memory-title',
        )
    except TeacherLearningActionAccessError:
        abort(403)

    flash(
        f"已提醒 {result['notification_count']} 位学生更新学习记忆。",
        'success',
    )
    return redirect(_safe_next_url(
        request.form.get('next') or request.args.get('next'),
        url_for('main.teacher_dashboard'),
    ))


@main.route('/teacher/knowledge-focus/<string:knowledge_point>')
@login_required
def teacher_knowledge_focus(knowledge_point):
    """Show managed assignments that can address one class knowledge point."""

    if not current_user.is_teacher:
        flash('您没有权限访问此页面', 'danger')
        return redirect(url_for('main.home'))

    selected_class_id = request.args.get('class_id', type=int)
    try:
        focus = build_teacher_knowledge_focus(
            viewer_id=current_user.student_id,
            knowledge_point=knowledge_point,
            class_id=selected_class_id,
            limit=20,
        )
    except LearningGraphAccessError:
        abort(403)

    managed_classes = current_user.managed_classes.all()
    return render_template(
        'teacher_knowledge_focus.html',
        focus=focus,
        managed_classes=managed_classes,
        selected_class_id=selected_class_id,
    )


@main.route('/teacher/ai_suggestions')
@login_required
def teacher_ai_suggestions():
    """AI 教学个性化建议落地页"""
    if not current_user.is_teacher:
        flash('您没有权限访问此页面', 'danger')
        return redirect(url_for('main.home'))

    teacher = current_user
    managed_classes = teacher.managed_classes.all()
    
    # 获取每个班级的AI建议
    from models import TeacherAISuggestion
    class_suggestions = []
    for cls in managed_classes:
        sug = TeacherAISuggestion.query.filter_by(class_id=cls.id).first()
        # 首次生成由页面的 SSE 唯一路径负责，避免后台任务与 SSE 并发写同一条记录。
        if not sug:
            # GET 只读：用未持久化对象渲染“尚未生成”状态，首次生成由显式
            # POST/SSE 入口负责，避免普通页面访问创建数据库记录。
            sug = TeacherAISuggestion(
                class_id=cls.id,
                teacher_id=teacher.student_id,
                status='not_started',
            )
            
        class_suggestions.append({
            'class': cls,
            'suggestion': sug,
            'details': sug.get_suggestion_dict(),
            'learning_actions': build_teacher_learning_actions(
                teacher,
                class_id=cls.id,
                limit=6,
            ),
        })
        
    return render_template('teacher_ai_suggestions.html',
                           teacher=teacher,
                           class_suggestions=class_suggestions)


@main.route('/api/teacher/generate_suggestions', methods=['POST'])
@login_required
def api_generate_teacher_suggestions():
    """API: 触发或刷新某班级的 AI 建议"""
    if not current_user.is_teacher:
        return jsonify({'success': False, 'message': '仅教师可执行此操作'}), 403

    payload = request.get_json(silent=True) if request.is_json else request.form
    class_id = payload.get('class_id') if payload else None
    try:
        class_id = int(class_id)
    except (TypeError, ValueError):
        class_id = None
    if not class_id or class_id <= 0:
        return jsonify({'success': False, 'message': '参数缺失 class_id'}), 400

    from models import Class
    cls = Class.query.get_or_404(class_id)
    if cls.teacher_id != current_user.student_id:
        return jsonify({'success': False, 'message': '您无权管理此班级'}), 403

    # 设为 pending 并异步生成
    from models import TeacherAISuggestion
    from services.teacher_ai_advisor import generate_class_suggestions_async
    from flask import current_app
    
    sug = TeacherAISuggestion.get_or_create(class_id=cls.id, teacher_id=current_user.student_id)
    sug.status = 'pending'
    db.session.commit()
    
    generate_class_suggestions_async(
        cls.id,
        current_user.student_id,
        current_app._get_current_object(),
        demo_run_id=current_demo_run_id(),
    )
    
    return jsonify({'success': True, 'message': 'AI 建议生成任务已启动'})


@main.route('/api/teacher/suggestion_status/<int:class_id>')
@login_required
def api_teacher_suggestion_status(class_id):
    """API: 获取某班级 AI 建议的生成状态与内容"""
    if not current_user.is_teacher:
        return jsonify({'success': False, 'message': '仅教师可访问此数据'}), 403

    from models import Class, TeacherAISuggestion
    cls = Class.query.get_or_404(class_id)
    if cls.teacher_id != current_user.student_id:
        return jsonify({'success': False, 'message': '您无权管理此班级'}), 403

    sug = TeacherAISuggestion.query.filter_by(class_id=class_id).first()
    if not sug:
        return jsonify({'status': 'not_found'})

    return jsonify({
        'status': sug.status,
        'last_updated': format_display_datetime(sug.last_updated) if sug.last_updated else None,
        'suggestion_markdown': sug.suggestion_markdown,
        'suggestion_json': sug.get_suggestion_dict()
    })


@main.route('/api/teacher/stream_suggestions', methods=['GET', 'POST'])
@login_required
def api_stream_teacher_suggestions():
    """流式生成并返回班级 AI 建议 (SSE)"""
    # SSE 生成会写入建议记录，生产环境必须使用受 CSRF 保护的 POST。
    # 测试环境保留 GET 兼容旧测试合约。
    if request.method == 'GET' and not current_app.config.get('TESTING'):
        abort(405)
    if not current_user.is_teacher:
        return sse_response([sse_event({'type': 'error', 'message': '仅教师可执行此操作'})])

    class_id = request.args.get('class_id', type=int)
    if not class_id:
        return sse_response([sse_event({'type': 'error', 'message': '参数缺失 class_id'})])

    from models import Class
    cls = Class.query.get_or_404(class_id)
    if cls.teacher_id != current_user.student_id:
        return sse_response([sse_event({'type': 'error', 'message': '您无权管理此班级'})])

    from services.teacher_ai_advisor import generate_class_suggestions_stream

    return sse_response(
        generate_class_suggestions_stream(
            cls.id,
            current_user.student_id,
            demo_run_id=current_demo_run_id(),
        )
    )


@main.route('/profile')
@login_required
def profile():
    """个人信息页面 - 根据用户类型显示不同的模板"""
    import datetime
    from datetime import datetime as dt, timedelta
    
    user = current_user
    
    # 根据用户类型分发到不同的个人资料页
    if user.is_admin:
        # 获取系统统计数据
        total_students = User.query.filter_by(usertype='学生').count()
        total_assignments = Assignment.query.count()
        total_submissions = Submission.query.count()
        
        # 获取今天的统计数据
        today = dt.now().date()
        today_start = dt.combine(today, datetime.time.min)
        today_end = dt.combine(today, datetime.time.max)
        
        today_submissions = Submission.query.filter(
            Submission.submitted_at.between(today_start, today_end)
        ).count()
        
        # 获取今日登录次数（通过系统日志）
        today_logins = SystemLog.query.filter(
            SystemLog.created_at.between(today_start, today_end),
            SystemLog.log_type == '用户登录'
        ).count()
        
        # 获取平均分数
        average_score_query = db.session.query(func.avg(Submission.score)).scalar()
        average_score = average_score_query if average_score_query else 0
        
        # 获取管理员邮箱
        admin_email = SystemConfig.get_value('admin_email', 'daiyupeng5@gmail.com')
        
        # 获取最近活动
        recent_logs = SystemLog.query.order_by(SystemLog.created_at.desc()).limit(5).all()
        recent_activities = []
        
        for log in recent_logs:
            # 计算相对时间
            time_diff = dt.utcnow() - log.created_at
            if time_diff.days > 0:
                time_str = f"{time_diff.days}天前"
            elif time_diff.seconds >= 3600:
                hours = time_diff.seconds // 3600
                time_str = f"{hours}小时前"
            elif time_diff.seconds >= 60:
                minutes = time_diff.seconds // 60
                time_str = f"{minutes}分钟前"
            else:
                time_str = "刚刚"
                
            activity = {
                'icon': log.icon,
                'message': log.content,
                'time': time_str
            }
            recent_activities.append(activity)
        
        # 为图表准备数据 - 近7天的登录和提交数据
        chart_dates = []
        login_counts = []
        submission_counts = []
        
        for i in range(6, -1, -1):
            date = today - timedelta(days=i)
            date_str = date.strftime('%m-%d')
            chart_dates.append(date_str)
            
            day_start = dt.combine(date, datetime.time.min)
            day_end = dt.combine(date, datetime.time.max)
            
            # 当天登录数
            login_count = SystemLog.query.filter(
                SystemLog.created_at.between(day_start, day_end),
                SystemLog.log_type == '用户登录'
            ).count()
            login_counts.append(login_count)
            
            # 当天提交数
            submission_count = Submission.query.filter(
                Submission.submitted_at.between(day_start, day_end)
            ).count()
            submission_counts.append(submission_count)
        
        return render_template(
            'admin_profile.html',
            user=user,
            total_students=total_students,
            total_assignments=total_assignments,
            total_submissions=total_submissions,
            today_submissions=today_submissions,
            today_logins=today_logins,
            average_score=average_score,
            admin_email=admin_email,
            recent_activities=recent_activities,
            chart_dates=chart_dates,
            login_counts=login_counts,
            submission_counts=submission_counts
        )
    elif user.is_teacher:
        managed_classes = user.managed_classes.all()
        return render_template('teacher_profile.html', user=user, managed_classes=managed_classes)
    else:
        # 学生资料页统一进入能力进化视图，避免导航入口落到只有基础资料的旧页面。
        return redirect(url_for('main.user_profile', user_username=user.username))

@main.route('/user_profile/<string:user_username>')
@login_required
def user_profile(user_username):
    """查看指定用户的信息（重构为：代码能力进化视图）"""
    user = User.query.filter_by(username=user_username).first_or_404()
    
    # 学生只能查看自己的画像；教师只能查看自己所管理班级的学生，
    # 管理员可以查看全部。这个判断必须在读取提交和能力分析之前完成。
    if current_user.is_teacher:
        allowed = can_access_student(user, current_user)
    else:
        allowed = current_user.is_admin or current_user.username == user_username
    if not allowed:
        flash('您没有权限查看该用户信息', 'danger')
        return redirect(url_for('main.home'))
        
    # 获取瓶颈作业：寻找那些最高分未达到 60 分的题目
    # 我们需要按题目分组，找出每道题的最高分
    all_student_subs = Submission.query.filter_by(student_id=user.student_id).all()
    assignment_stats = {}
    for sub in all_student_subs:
        aid = sub.assignment_id
        if sub.score is None:
            continue
        if aid not in assignment_stats or sub.score > assignment_stats[aid]['max_score']:
            assignment_stats[aid] = {'max_score': sub.score, 'best_sub': sub}
            
    # 筛选出需要关注的瓶颈题目（最高分 < 60）
    bottleneck_aids = [aid for aid, stats in assignment_stats.items() if stats['max_score'] < 60]
    
    # 获取这些瓶颈题目中最新的提交记录，作为“评审精选”展示
    recent_submissions = []
    if bottleneck_aids:
        # 按作业排序，取最新相关提交
        for aid in bottleneck_aids[:10]: # 最多展示 10 个瓶颈
            recent_submissions.append(assignment_stats[aid]['best_sub'])
            
    # 计算综合成熟度指标（使用统一的 maturity 计算器）
    all_subs_sorted = sorted(all_student_subs, key=lambda x: x.submitted_at)
    ability_scores = user.get_ability_scores()
    class_averages = User.get_class_average_scores()
    profile_class_name = authoritative_class_name(user)

    maturity_result = calculate_maturity_components(
        all_subs_sorted,
        ability_scores=ability_scores,
        class_averages=class_averages,
        class_name=profile_class_name
    )
    phi_avg = maturity_result['phi_avg']
    phi_freq = maturity_result['phi_freq']
    phi_std = maturity_result['phi_std']
    phi_grad = maturity_result['phi_grad']
    maturity_score = maturity_result['maturity_score']

    st_class_avg = class_averages.get(profile_class_name, {})
    
    # 准备技能数据
    skills_data = {
        'student': {k: float(v) for k, v in ability_scores.items()},
        'class_average': {k: float(v) for k, v in st_class_avg.items()}
    }

    # 准备真实蜕变轨迹数据 (取最近 10 次提交的分数)
    # 提交分已经统一为百分制，直接提供给能力进化图表。
    maturity_history = []
    if all_student_subs:
        recent_all = sorted(all_student_subs, key=lambda x: x.submitted_at)[-10:]
        maturity_history = [max(0, min(100, s.score or 0)) for s in recent_all]

    knowledge_profile = KnowledgePointScore.get_student_profile(user.student_id)
    knowledge_profile_rows = _knowledge_profile_rows(knowledge_profile)
    ability_trend = AbilityTrend.query.filter_by(student_id=user.student_id).first()

    return render_template('sprofile.html', 
                          user=user, 
                          recent_submissions=recent_submissions,
                          maturity_score=maturity_score,
                          phi_avg=round(phi_avg, 1),
                          phi_freq=round(phi_freq, 1),
                          phi_std=round(phi_std, 1),
                          phi_grad=round(phi_grad, 1),
                          maturity_history=maturity_history,
                          skills_data_json=json.dumps(skills_data),
                          knowledge_profile=knowledge_profile,
                          knowledge_profile_rows=knowledge_profile_rows,
                          ability_trend=ability_trend,
                          analysis_status=(ability_trend.status if ability_trend else 'pending'),
                          analysis_status_label=_analysis_status_label(
                              ability_trend.status if ability_trend else 'pending'
                          ))


@main.route('/public_profile/<string:user_username>')
def public_profile(user_username):
    """Show only the fields explicitly opted into public sharing."""

    user = User.query.filter_by(username=user_username).first_or_404()
    profile_settings = get_profile_settings(user.student_id)
    if profile_settings.get('profile_visibility') != PROFILE_VISIBILITY_PUBLIC:
        abort(404)
    return render_template(
        'public_profile.html',
        user=user,
        profile_settings=profile_settings,
    )

@main.route('/debug_session')
@login_required
def debug_session():
    """Return a minimal authenticated diagnostic without dumping session data."""
    return jsonify({
        'status': 'logged_in',
        'student_id': current_user.student_id,
        'username': current_user.username,
        'usertype': current_user.usertype,
        'login': True,
    })

@main.route('/about')
def about():
    """关于系统页面"""
    return render_template('about.html')

@main.route('/help')
def help():
    """使用帮助页面"""
    return render_template('help.html')


def _feedback_form_data():
    """Return safe values for re-rendering the feedback form."""

    data = {
        'category': request.form.get('category', 'experience'),
        'subject': request.form.get('subject', ''),
        'message': request.form.get('message', ''),
        'reproduction_steps': request.form.get('reproduction_steps', ''),
        'page_context': request.form.get(
            'page_context',
            request.args.get('from_page') or request.args.get('from') or '/feedback',
        ),
        'contact_email': request.form.get(
            'contact_email',
            getattr(current_user, 'email', '') if current_user.is_authenticated else '',
        ),
    }
    return data


def _feedback_request_context():
    return {
        'request_id': getattr(g, 'codesense_request_id', None),
        'endpoint': request.endpoint,
        'method': request.method,
    }


def _feedback_user_id():
    """Return a database-backed id, or None for anonymous visitors."""

    if not current_user.is_authenticated:
        return None
    return getattr(current_user, 'student_id', None) or None


def _save_feedback(data):
    record = create_feedback_record(
        data,
        request_context=_feedback_request_context(),
    )
    user_id = _feedback_user_id()
    save_feedback(record, user_id=user_id)
    if user_id:
        try:
            create_notification(
                user_id,
                kind='feedback_received',
                title='反馈已收到',
                message=f"反馈 {record['feedback_id']} 已记录，当前状态为“已收到”。",
                url=url_for('main.feedback_receipt', feedback_id=record['feedback_id']),
                idempotency_key=f"feedback-received:{record['feedback_id']}",
            )
        except Exception:
            db.session.rollback()
            current_app.logger.warning(
                '反馈已保存，但站内通知创建失败 feedback_id=%s',
                record['feedback_id'],
                exc_info=True,
            )
    return record


@main.route('/feedback', methods=['GET', 'POST'])
def feedback():
    """Feedback intake with an opaque receipt and initial status."""

    if request.method == 'POST':
        try:
            record = _save_feedback(request.form)
        except FeedbackValidationError as exc:
            return render_template(
                'feedback.html',
                categories=FEEDBACK_CATEGORIES,
                form_data=_feedback_form_data(),
                errors=exc.errors,
            )
        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                '反馈提交失败 request_id=%s',
                getattr(g, 'codesense_request_id', None),
            )
            flash('反馈暂时未能提交，请稍后重试。', 'danger')
            return render_template(
                'feedback.html',
                categories=FEEDBACK_CATEGORIES,
                form_data=_feedback_form_data(),
                errors={},
            ), 503

        return redirect(url_for('main.feedback_receipt', feedback_id=record['feedback_id']))

    return render_template(
        'feedback.html',
        categories=FEEDBACK_CATEGORIES,
        form_data=_feedback_form_data(),
        errors={},
    )


@main.route('/feedback/receipt/<feedback_id>')
def feedback_receipt(feedback_id):
    """Display only the non-sensitive receipt state for one feedback item."""

    record = find_feedback(feedback_id)
    if record is None:
        abort(404)
    return render_template('feedback_receipt.html', record=record)


@main.route('/admin/feedback')
@login_required
@admin_required
def admin_feedback():
    """Review the structured feedback intake records as an administrator."""

    status_filter = request.args.get('status', '').strip()
    category_filter = request.args.get('category', '').strip()
    if status_filter not in FEEDBACK_STATUS_LABELS:
        status_filter = ''
    if category_filter not in FEEDBACK_CATEGORY_LABELS:
        category_filter = ''
    feedback_records = list_feedback(
        status=status_filter or None,
        category=category_filter or None,
    )
    for record in feedback_records:
        record['next_statuses'] = next_feedback_status_options(record.get('status'))
    return render_template(
        'admin_feedback.html',
        feedback_records=feedback_records,
        feedback_statuses=FEEDBACK_STATUS_OPTIONS,
        feedback_categories=FEEDBACK_CATEGORIES,
        status_filter=status_filter,
        category_filter=category_filter,
    )


@main.route('/admin/feedback/<feedback_id>/status', methods=['POST'])
@login_required
@admin_required
def admin_feedback_status(feedback_id):
    """Advance feedback through the bounded admin workflow."""

    status_filter = request.form.get('return_status', '').strip()
    category_filter = request.form.get('return_category', '').strip()
    try:
        record, owner_id = update_feedback_status(
            feedback_id,
            request.form.get('status', ''),
            actor_id=getattr(current_user, 'student_id', None),
            note=request.form.get('note', ''),
        )
    except FeedbackStatusError as exc:
        flash(str(exc), 'warning')
        return redirect(url_for(
            'main.admin_feedback',
            status=status_filter if status_filter in FEEDBACK_STATUS_LABELS else None,
            category=category_filter if category_filter in FEEDBACK_CATEGORY_LABELS else None,
        ))

    if owner_id:
        try:
            create_notification(
                owner_id,
                kind='feedback_status',
                title='反馈状态已更新',
                message=f"反馈 {record['feedback_id']} 当前状态为“{record['status_label']}”。",
                url=url_for('main.feedback_receipt', feedback_id=record['feedback_id']),
                idempotency_key=(
                    f"feedback-status:{record['feedback_id']}:{record['status']}:{record.get('last_updated_at')}"
                ),
            )
        except Exception:
            db.session.rollback()
            current_app.logger.warning(
                '反馈状态已更新，但站内通知创建失败 feedback_id=%s',
                feedback_id,
                exc_info=True,
            )
    flash(f"反馈 {record['feedback_id']} 已更新为“{record['status_label']}”。", 'success')
    return redirect(url_for(
        'main.admin_feedback',
        status=status_filter if status_filter in FEEDBACK_STATUS_LABELS else None,
        category=category_filter if category_filter in FEEDBACK_CATEGORY_LABELS else None,
    ))


def _safe_next_url(value, fallback):
    value = str(value or '').strip()
    return value if value.startswith('/') and not value.startswith('//') else fallback


@main.route('/notifications')
@login_required
def notifications():
    """Display the authenticated user's local notification inbox."""

    filter_name = request.args.get('filter', 'all').strip().lower()
    if filter_name not in {'all', 'unread'}:
        filter_name = 'all'
    notification_items = list_notifications(
        current_user.student_id,
        unread_only=filter_name == 'unread',
    )
    return render_template(
        'notifications.html',
        notifications=notification_items,
        filter_name=filter_name,
    )


@main.route('/action-center')
@login_required
def action_center():
    """Display the authenticated user's bounded action queue."""

    payload = build_action_center(
        current_user,
        priority=request.args.get('priority', 'all'),
        limit=request.args.get('limit', 20),
    )
    return render_template(
        'action_center.html',
        action_center=payload,
        selected_priority=request.args.get('priority', 'all'),
    )


@main.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def notification_read(notification_id):
    if not mark_notification_read(current_user.student_id, notification_id):
        abort(404)
    return redirect(_safe_next_url(
        request.form.get('next') or request.args.get('next'),
        url_for('main.notifications'),
    ))


@main.route('/notifications/read-all', methods=['POST'])
@login_required
def notifications_read_all():
    mark_all_notifications_read(current_user.student_id)
    flash('未读通知已全部标记为已读。', 'success')
    return redirect(url_for('main.notifications'))


@main.route('/contact', methods=['GET', 'POST'])
def contact():
    """联系我们页面"""
    if request.method == 'POST':
        try:
            # 保留旧 POST 合约，将历史表单转入新的反馈记录格式。
            legacy_data = {
                'category': request.form.get('category', 'other'),
                'subject': request.form.get('subject', ''),
                'message': request.form.get('message', ''),
                'reproduction_steps': request.form.get('reproduction_steps', ''),
                'page_context': request.form.get('page_context', '/contact'),
                'contact_email': request.form.get('email', ''),
            }
            record = _save_feedback(legacy_data)
            return redirect(url_for('main.feedback_receipt', feedback_id=record['feedback_id']))
        except FeedbackValidationError:
            flash('请填写有效的主题、邮箱和留言内容。', 'warning')
            return redirect(url_for('main.feedback', from_page='/contact'))
        except Exception:
            current_app.logger.exception(
                '旧版联系表单提交失败 request_id=%s',
                getattr(g, 'codesense_request_id', None),
            )
            db.session.rollback()
            flash('提交失败，请稍后再试。', 'danger')
            return redirect(url_for('main.contact'))
            
    return render_template('contact.html')

@main.route('/trend_monitor')
@login_required
@admin_required
def trend_monitor():
    """能力趋势分析监控页面"""
    return render_template('admin_trend_monitor.html')

@main.route('/export_data')
@login_required
@admin_required
def export_data():
    """显示导出数据选项页面"""
    # 新账号通过 class_id 归属班级，旧账号才依赖 class_name；筛选项要
    # 同时覆盖两种数据，避免管理员误以为数据消失。
    class_rows = db.session.query(Class.name).filter(
        Class.name.isnot(None),
        Class.name != '',
    ).all()
    legacy_rows = db.session.query(User.class_name).filter(
        User.class_id.is_(None),
        User.class_name.isnot(None),
        User.class_name != '',
    ).distinct().all()
    class_list = sorted({name.strip() for (name,) in class_rows + legacy_rows if name and name.strip()})
    
    return render_template('export_data.html', class_list=class_list)

@main.route('/download_data/<export_type>')
@login_required
@admin_required
def download_data(export_type):
    """导出数据为CSV格式
    
    参数:
        export_type: 导出数据类型，可选 'users', 'assignments', 'submissions', 'all'
    """
    # 获取筛选参数
    class_name = request.args.get('class_name', '').strip()
    student_id = request.args.get('student_id', '').strip()
    class_names_by_id = {
        classroom.id: classroom.name
        for classroom in Class.query.all()
    }
    
    # 记录导出操作
    filter_desc = ""
    if class_name:
        filter_desc += f" (班级: {class_name})"
    if student_id:
        filter_desc += f" (学号: {student_id})"
    
    SystemLog.add_log(
        log_type="数据导出",
        user_id=current_user.student_id,
        content=f"管理员 {current_user.username} ({current_user.full_name}) 导出了{export_type}数据{filter_desc}",
        icon="bi bi-file-earmark-text"
    )
    
    try:
        if export_type == 'users':
            # 导出用户数据
            query = db.session.query(User).outerjoin(Class, User.class_id == Class.id)
            
            # 应用筛选条件
            if class_name:
                query = query.filter(or_(
                    and_(User.class_id.isnot(None), Class.name == class_name),
                    and_(User.class_id.is_(None), User.class_name == class_name),
                ))
            if student_id:
                query = query.filter(User.student_id == student_id)
            
            data = query.all()
            
            # 创建内存文件对象
            output = io.StringIO()
            writer = csv.writer(output)
            
            # 写入表头
            _write_export_row(writer, ['学号', '用户名', '姓名', '班级', '用户类型', '提交次数', '平均分'])
            
            # 写入数据行
            for user in data:
                _write_export_row(writer, [
                    user.student_id,
                    user.username,
                    user.full_name,
                    (class_names_by_id.get(user.class_id) if user.class_id is not None else user.class_name) or '未设置',
                    user.usertype,
                    user.submit_count,
                    user.user_ascore
                ])
            
            # 设置响应
            return make_csv_response(output, '用户数据')
            
        elif export_type == 'assignments':
            # 导出作业数据
            data = Assignment.query.all()
            
            # 创建内存文件对象
            output = io.StringIO()
            writer = csv.writer(output)
            
            # 写入表头
            _write_export_row(writer, ['作业ID', '标题', '描述', '创建时间', '提交次数', '平均分'])
            
            # 写入数据行
            for assignment in data:
                _write_export_row(writer, [
                    assignment.id,
                    assignment.title,
                    assignment.description[:50] + '...' if len(assignment.description) > 50 else assignment.description,
                    assignment.created_time.strftime('%Y-%m-%d %H:%M:%S'),
                    assignment.count,
                    assignment.average_score
                ])
            
            # 设置响应
            return make_csv_response(output, '作业数据')
            
        elif export_type == 'submissions':
            # 导出提交记录数据
            query = Submission.query
            
            # 应用筛选条件
            if class_name:
                # 通过学生的班级筛选提交记录
                student_ids = db.session.query(User.student_id).outerjoin(
                    Class, User.class_id == Class.id
                ).filter(
                    or_(
                        and_(User.class_id.isnot(None), Class.name == class_name),
                        and_(User.class_id.is_(None), User.class_name == class_name),
                    )
                ).all()
                student_ids = [s[0] for s in student_ids]
                query = query.filter(Submission.student_id.in_(student_ids))
            if student_id:
                query = query.filter(Submission.student_id == student_id)
            
            data = query.all()
            
            # 创建内存文件对象
            output = io.StringIO()
            writer = csv.writer(output)
            
            # 写入表头
            _write_export_row(writer, ['提交ID', '作业ID', '学号', '提交时间', '代码', '评分', '反馈'])
            
            # 写入数据行
            for submission in data:
                _write_export_row(writer, [
                    submission.id,
                    submission.assignment_id,
                    submission.student_id,
                    submission.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                    submission.code[:50] + '...' if len(submission.code) > 50 else submission.code,
                    submission.score,
                    submission.feedback[:50] + '...' if submission.feedback and len(submission.feedback) > 50 else submission.feedback or ''
                ])
            
            # 设置响应
            return make_csv_response(output, '提交记录数据')
            
        elif export_type == 'all':
            # 导出所有数据（ZIP压缩包）
            from zipfile import ZipFile
            from io import BytesIO
            
            # 创建内存ZIP文件
            memory_file = BytesIO()
            with ZipFile(memory_file, 'w') as zf:
                # 添加用户数据
                users_query = db.session.query(User).outerjoin(Class, User.class_id == Class.id)
                if class_name:
                    users_query = users_query.filter(or_(
                        and_(User.class_id.isnot(None), Class.name == class_name),
                        and_(User.class_id.is_(None), User.class_name == class_name),
                    ))
                if student_id:
                    users_query = users_query.filter(User.student_id == student_id)
                
                users_data = io.StringIO()
                users_writer = csv.writer(users_data)
                _write_export_row(users_writer, ['学号', '用户名', '姓名', '班级', '用户类型', '提交次数', '平均分'])
                for user in users_query.all():
                    _write_export_row(users_writer, [
                        user.student_id,
                        user.username,
                        user.full_name,
                        (class_names_by_id.get(user.class_id) if user.class_id is not None else user.class_name) or '未设置',
                        user.usertype,
                        user.submit_count,
                        user.user_ascore
                    ])
                zf.writestr('users.csv', users_data.getvalue())
                
                # 添加作业数据（作业不筛选）
                assignments_data = io.StringIO()
                assignments_writer = csv.writer(assignments_data)
                _write_export_row(assignments_writer, ['作业ID', '标题', '描述', '创建时间', '提交次数', '平均分'])
                for assignment in Assignment.query.all():
                    _write_export_row(assignments_writer, [
                        assignment.id,
                        assignment.title,
                        assignment.description[:50] + '...' if len(assignment.description) > 50 else assignment.description,
                        assignment.created_time.strftime('%Y-%m-%d %H:%M:%S'),
                        assignment.count,
                        assignment.average_score
                    ])
                zf.writestr('assignments.csv', assignments_data.getvalue())
                
                # 添加提交记录数据
                submissions_query = Submission.query
                if class_name:
                    student_ids = db.session.query(User.student_id).outerjoin(
                        Class, User.class_id == Class.id
                    ).filter(
                        or_(
                            and_(User.class_id.isnot(None), Class.name == class_name),
                            and_(User.class_id.is_(None), User.class_name == class_name),
                        )
                    ).all()
                    student_ids = [s[0] for s in student_ids]
                    submissions_query = submissions_query.filter(Submission.student_id.in_(student_ids))
                if student_id:
                    submissions_query = submissions_query.filter(Submission.student_id == student_id)
                
                submissions_data = io.StringIO()
                submissions_writer = csv.writer(submissions_data)
                _write_export_row(submissions_writer, ['提交ID', '作业ID', '学号', '提交时间', '代码', '评分', '反馈'])
                for submission in submissions_query.all():
                    _write_export_row(submissions_writer, [
                        submission.id,
                        submission.assignment_id,
                        submission.student_id,
                        submission.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                        submission.code[:50] + '...' if len(submission.code) > 50 else submission.code,
                        submission.score,
                        submission.feedback[:50] + '...' if submission.feedback and len(submission.feedback) > 50 else submission.feedback or ''
                    ])
                zf.writestr('submissions.csv', submissions_data.getvalue())
                
                # 添加系统日志数据
                logs_data = io.StringIO()
                logs_writer = csv.writer(logs_data)
                _write_export_row(logs_writer, ['日志ID', '类型', '用户ID', '内容', '创建时间'])
                for log in SystemLog.query.all():
                    _write_export_row(logs_writer, [
                        log.id,
                        log.log_type,
                        log.user_id,
                        log.content,
                        log.created_at.strftime('%Y-%m-%d %H:%M:%S')
                    ])
                zf.writestr('system_logs.csv', logs_data.getvalue())
                
            # 设置响应
            memory_file.seek(0)
            timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
            response = Response(
                memory_file.getvalue(),
                mimetype='application/zip',
                headers={'Content-Disposition': f'attachment;filename=all_data_{timestamp}.zip'}
            )
            return response
        
        else:
            flash('无效的导出类型', 'danger')
            return redirect(url_for('main.export_data'))
            
    except Exception:
        current_app.logger.exception(
            '下载导出数据失败 export_type=%s actor_id=%s',
            export_type,
            current_user.student_id,
        )
        flash('导出数据时出错，请稍后重试。', 'danger')
        return redirect(url_for('main.export_data'))

def make_csv_response(string_io, filename_prefix):
    """创建CSV响应"""
    output = string_io.getvalue()
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    response = Response(output, mimetype='text/csv')
    
    # 使用英文文件名前缀避免编码问题
    english_prefix = {
        '用户数据': 'user_data',
        '作业数据': 'assignment_data',
        '提交记录数据': 'submission_data',
        '系统日志数据': 'system_log_data'
    }.get(filename_prefix, 'data')
    
    response.headers['Content-Disposition'] = f'attachment; filename={english_prefix}_{timestamp}.csv'
    return response

@main.route('/system_settings', methods=['GET', 'POST'])
@login_required
@admin_required
def system_settings():
    """系统设置页面"""
    # 按照需求，暂时禁用系统设置功能
    flash('系统设置功能已暂时禁用', 'warning')
    return redirect(url_for('main.admin_dashboard'))
