"""
用户管理相关路由
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app, jsonify
from flask_login import current_user
from itsdangerous import URLSafeTimedSerializer
from models import db, User, Submission, SystemLog, Class, AbilityTrend, KnowledgePointScore
from utils.auth import login_required, admin_required, admin_or_teacher_required, student_required
from tasks.ability_analysis import trigger_analysis_if_needed
from services.demo_database import current_demo_run_id
from services.profile import get_profile_settings, save_profile_settings
from services.submission_reviews import get_review_summaries
from utils.access import (
    authoritative_class_name,
    can_access_student,
    class_student_filter,
    managed_classes,
)
from utils.export_safety import safe_export_cell
from sqlalchemy import desc, func, or_
from forms import AdminPasswordResetForm, ChangePasswordForm, EditProfileForm
from services.password_reset import (
    build_password_reset_url,
    create_password_reset_token,
    password_reset_ttl_minutes,
)
from werkzeug.utils import secure_filename
import pandas as pd
import io
from datetime import datetime
import os
import random
import uuid

users = Blueprint('users', __name__)

_AVATAR_MAX_BYTES = 5 * 1024 * 1024


def _score_distribution(scores):
    """Return submission-score buckets for the canonical 0–100 scale."""
    return [
        sum(1 for score in scores if float(score) >= 80),
        sum(1 for score in scores if 60 <= float(score) < 80),
        sum(1 for score in scores if float(score) < 60),
    ]


def _normalize_email(value):
    return (value or '').strip().lower() or None


def _save_avatar(file_storage, user_id):
    if not file_storage or not file_storage.filename:
        return None
    filename = secure_filename(file_storage.filename)
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
        raise ValueError('头像仅支持 jpg、jpeg、png、gif、webp 格式')

    # 头像会落到静态目录，单个文件不能跟随全局请求上限无限占用磁盘。
    stream = getattr(file_storage, 'stream', None)
    if stream is not None:
        try:
            current_position = stream.tell()
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(0)
            header = stream.read(16)
            stream.seek(current_position)
            if size <= 0:
                raise ValueError('头像文件不能为空')
            if size > _AVATAR_MAX_BYTES:
                raise ValueError('头像文件不能超过 5 MB')
            signature_matches = {
                '.jpg': header.startswith(b'\xff\xd8\xff'),
                '.jpeg': header.startswith(b'\xff\xd8\xff'),
                '.png': header.startswith(b'\x89PNG\r\n\x1a\n'),
                '.gif': header.startswith((b'GIF87a', b'GIF89a')),
                '.webp': (
                    len(header) >= 12
                    and header[:4] == b'RIFF'
                    and header[8:12] == b'WEBP'
                ),
            }
            if not signature_matches.get(ext, False):
                raise ValueError('头像文件内容与扩展名不匹配')
        except (OSError, ValueError):
            raise

    avatar_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars')
    os.makedirs(avatar_dir, exist_ok=True)
    saved_name = f'{user_id}_{uuid.uuid4().hex}{ext}'
    file_storage.save(os.path.join(avatar_dir, saved_name))
    return f'static/uploads/avatars/{saved_name}'


@users.route('/users')
@login_required
@admin_required
def manage_users():
    # 获取搜索参数
    search = request.args.get('search', '')
    user_type = request.args.get('user_type', '')
    page = request.args.get('page', 1, type=int)
    
    # 构建查询
    query = User.query
    if search:
        query = query.filter(
            db.or_(
                User.username.ilike(f'%{search}%'),
                User.student_id.ilike(f'%{search}%'),
                User.student_number.ilike(f'%{search}%'),
                User.full_name.ilike(f'%{search}%')
            )
        )
    if user_type:
        query = query.filter_by(usertype=user_type)
    
    # 分页
    pagination = query.paginate(page=page, per_page=10, error_out=False)
    users = pagination.items
    
    # 计算统计数据
    total_users = User.query.count()
    total_submissions = db.session.query(
        func.coalesce(func.sum(User.submit_count), 0)
    ).scalar() or 0
    student_count = User.query.filter_by(usertype='学生').count()
    admin_count = User.query.filter_by(usertype='管理员').count()
    teacher_count = User.query.filter_by(usertype='教师').count()
    
    # 准备图表数据
    user_type_chart_data = {
        'labels': ['学生', '教师', '管理员'],
        'data': [student_count, teacher_count, admin_count]
    }
    
    # 准备提交数量分布数据
    submission_counts = db.session.query(
        db.func.count(User.student_id).label('count'),
        db.case(
            (User.submit_count <= 5, '0-5次'),
            (User.submit_count <= 10, '6-10次'),
            (User.submit_count <= 15, '11-15次'),
            (User.submit_count <= 20, '16-20次'),
            (db.true(), '20次以上')
        ).label('range')
    ).group_by('range').all()
    
    submission_chart_data = [0] * 5  # 初始化5个区间
    for count, range_name in submission_counts:
        if range_name == '0-5次':
            submission_chart_data[0] = count
        elif range_name == '6-10次':
            submission_chart_data[1] = count
        elif range_name == '11-15次':
            submission_chart_data[2] = count
        elif range_name == '16-20次':
            submission_chart_data[3] = count
        else:
            submission_chart_data[4] = count
    
    # 将列表转换为与user_type_chart_data相同格式的对象
    submission_chart_data = {
        'labels': ['0-5次', '6-10次', '11-15次', '16-20次', '20次以上'],
        'data': submission_chart_data
    }
    
    return render_template('users.html',
                         users=users,
                         pagination=pagination,
                         admin_reset_form=AdminPasswordResetForm(),
                         search_term=search,
                         user_type=user_type,
                         total_users=total_users,
                         total_submissions=total_submissions,
                         student_count=student_count,
                         admin_count=admin_count,
                         user_type_chart_data=user_type_chart_data,
                         submission_chart_data=submission_chart_data)


@users.route('/delete_user/<string:student_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(student_id):
    """删除用户"""
    user_to_delete = User.query.get_or_404(student_id)
    
    # 只允许删除学生用户，不允许删除管理员
    if user_to_delete.usertype == '学生':
        db.session.delete(user_to_delete)
        db.session.commit()
        flash('用户删除成功！')
    else:
        flash('无法删除管理员用户')
        
    return redirect(url_for('users.manage_users'))


@users.route('/view_submission')
@login_required
def view_submissions():
    """查看学生提交记录和学情分析"""
    try:
        # 优先使用URL参数中的student_id；没有参数时只允许查看当前账号。
        student_id = request.args.get('student_id') or current_user.student_id
        if not student_id:
            flash('会话已过期，请重新登录')
            return redirect(url_for('auth.login'))

        user = User.query.get_or_404(student_id)
        if not can_access_student(user, current_user):
            flash('您无权查看此学生的提交记录', 'danger')
            return redirect(url_for('main.home'))
            
        per_page = 10
        page = request.args.get('page', 1, type=int)  # 获取当前页码，默认为1
        # 查询学生的所有提交记录（用于统计）
        all_submissions = Submission.query.filter_by(student_id=student_id).all()
        scores = [sub.score for sub in all_submissions if sub.score is not None]
        
        # 分页获取提交记录
        submissions = (Submission.query
                    .filter_by(student_id=student_id)
                    .order_by(desc(Submission.submitted_at))
                    .paginate(page=page, per_page=per_page, error_out=False))
        
        # 3. 准备图表数据
        chart_data = {
            'x': [sub.assignment_id for sub in submissions.items],
            'y': [sub.score if sub.score is not None else 0 for sub in submissions.items],
            'pie_data': _score_distribution(scores),
        }
        
        # 4. 获取真实的能力分析数据
        ability_scores = user.get_ability_scores()
        class_avg_scores = User.get_class_average_scores()
        profile_class_name = authoritative_class_name(user)
        
        comprehensive_score = sum(ability_scores.values()) / 5 if ability_scores else 0
        dim_map = {
            'algorithm': '算法能力',
            'style': '代码风格',
            'functionality': '功能实现',
            'efficiency': '效率优化',
            'readability': '代码可读性'
        }
        strongest_dim = dim_map.get(max(ability_scores, key=ability_scores.get), '暂无') if ability_scores and comprehensive_score > 0 else '暂未定型'
        
        ability_data = {
            'student': ability_scores,
            'class_avg': class_avg_scores.get(profile_class_name, {
                'algorithm': 70, 'style': 70, 'functionality': 70, 'efficiency': 70, 'readability': 70
            })
        }

        knowledge_profile = KnowledgePointScore.get_student_profile(student_id)
        knowledge_profile_rows = []
        for key, name in KnowledgePointScore.KNOWLEDGE_POINTS.items():
            item = dict(knowledge_profile.get(key) or {})
            item.setdefault('score', 0)
            item.setdefault('total_attempts', 0)
            item.setdefault('correct_attempts', 0)
            item.setdefault('accuracy', 0)
            item.setdefault('average_difficulty', 0)
            knowledge_profile_rows.append({'key': key, 'name': name, **item})

        review_summaries = get_review_summaries(
            [submission.id for submission in submissions.items],
            actor=current_user,
        )
        
        # 5. 获取 AI 能力趋势分析
        ability_trend = AbilityTrend.query.filter_by(student_id=student_id).first()
        
        # 页面 GET 保持只读；需要重新生成时由“刷新分析”POST 显式触发。

        return render_template('submissions.html', 
                            submissions=submissions, 
                            user=user, 
                            chart_data=chart_data,
                            ability_data=ability_data,
                            knowledge_profile=knowledge_profile,
                            knowledge_profile_rows=knowledge_profile_rows,
                            ability_trend=ability_trend,
                            comprehensive_score=comprehensive_score,
                            strongest_dim=strongest_dim,
                            review_summaries=review_summaries)
    except Exception:
        current_app.logger.exception(
            '访问学情分析失败 student_id=%s actor_id=%s',
            student_id,
            current_user.student_id,
        )
        flash('访问学情分析时出错，请稍后重试。', 'danger')
        return redirect(url_for('main.home'))


@users.route('/refresh_analysis', methods=['POST'])
@login_required
@student_required
def refresh_analysis():
    """手动刷新能力分析"""
    student_id = current_user.student_id
    if not student_id:
        return jsonify({'status': 'error', 'message': '未找到学生 ID'}), 401
    
    # 强制触发重新分析
    triggered = trigger_analysis_if_needed(
        student_id,
        force=True,
        demo_run_id=current_demo_run_id(),
    )
    
    if triggered:
        return jsonify({'status': 'success', 'message': '已启动深度能力分析分析，请稍后刷新页面查看结果'})
    else:
        trend = AbilityTrend.query.filter_by(student_id=student_id).first()
        if trend and trend.status == 'failed':
            return jsonify({
                'status': 'error',
                'message': '能力分析服务暂时不可用，请稍后再试',
            }), 503
        return jsonify({'status': 'info', 'message': '分析任务正在处理中，请稍候'})

@users.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """编辑个人资料"""
    user = User.query.get(current_user.student_id)
    form = EditProfileForm()
    profile_settings = get_profile_settings(getattr(user, 'student_id', None))
    
    # 班级归属是权限边界的一部分，学生不能在个人资料页把自己切换到
    # 任意教学班；入班统一走花名册或教师提供的加入码。保留“清空当前
    # 班级”的兼容入口，避免历史账号被锁死，但不允许选择其它班级。
    if user.usertype == '学生':
        current_class_name = authoritative_class_name(user)
        form.class_name.choices = [('', '未分配')]
        if current_class_name:
            form.class_name.choices.append((current_class_name, current_class_name))
    else:
        form.class_name.choices = [('', '不适用于此账号')]

    if user.is_free_account:
        current_class_name = authoritative_class_name(user)
        form.class_name.choices = [
            (current_class_name, current_class_name or '未分配（请使用班级加入码）')
        ]
    
    if form.validate_on_submit():
        try:
            email = _normalize_email(form.email.data)
            if email:
                existing_email_user = User.query.filter(
                    db.func.lower(User.email) == email,
                    User.student_id != user.student_id
                ).first()
                if existing_email_user:
                    flash('邮箱已被其他账号使用', 'danger')
                    return render_template(
                        'edit_profile.html',
                        form=form,
                        user=user,
                        profile_settings=profile_settings,
                    )

            email_changed = email != _normalize_email(user.email)
            email_registration_reverification = (
                email_changed
                and getattr(user, 'registration_method', '') == 'email'
            )
            if email_registration_reverification and not email:
                flash('邮箱注册账号必须保留邮箱地址。', 'danger')
                return render_template('edit_profile.html', form=form, user=user)

            # 更新用户信息
            user.username = form.username.data
            user.full_name = form.full_name.data
            user.email = email

            avatar_path = _save_avatar(form.avatar.data, user.student_id)
            if avatar_path:
                user.avatar_path = avatar_path
            
            if user.is_free_account:
                # 即使有人手工构造请求，也不能借个人资料接口绕过加入码。
                if form.class_name.data != authoritative_class_name(user):
                    flash('自由账号请使用教师提供的班级加入码入班。', 'warning')
                    return render_template('edit_profile.html', form=form, user=user)
            else:
                requested_class_name = (form.class_name.data or '').strip()
                target_class = None
                if requested_class_name:
                    target_class = Class.query.filter_by(name=requested_class_name).first()
                    if not target_class:
                        flash('所选班级不存在，请刷新页面后重试。', 'danger')
                        return render_template(
                            'edit_profile.html',
                            form=form,
                            user=user,
                            profile_settings=profile_settings,
                        ), 400
                    user.class_name = target_class.name
                    user.class_id = target_class.id
                else:
                    user.class_name = None
                    user.class_id = None
            
            save_profile_settings(
                user.student_id,
                bio=form.bio.data,
                profile_visibility=form.profile_visibility.data,
                commit=False,
            )
            db.session.commit()

            if email_registration_reverification:
                raw_token = None
                try:
                    raw_token = create_email_verification_token(
                        user,
                        requested_ip=request.remote_addr,
                    )
                    send_email_verification_email(user, raw_token)
                except Exception:
                    if raw_token:
                        try:
                            revoke_email_verification_token(raw_token)
                        except Exception:
                            db.session.rollback()
                    current_app.logger.exception('邮箱变更后的验证邮件发送失败')
                    flash('资料已更新，但新邮箱验证邮件发送失败，请稍后重新发送。', 'warning')
                else:
                    flash('资料已更新，请查收新邮箱验证邮件并完成验证。', 'success')
            else:
                flash('资料更新成功！', 'success')
            return redirect(url_for('users.view_submissions'))
        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                '更新个人资料失败 student_id=%s',
                user.student_id,
            )
            flash('更新失败，请稍后重试。', 'danger')
    
    # 如果是GET请求，预填充表单
    if request.method == 'GET':
        form.username.data = user.username
        form.full_name.data = user.full_name
        form.email.data = user.email
        form.class_name.data = authoritative_class_name(user)
        form.bio.data = profile_settings.get('bio', '')
        form.profile_visibility.data = profile_settings.get('profile_visibility', 'private')

    return render_template(
        'edit_profile.html',
        form=form,
        user=user,
        profile_settings=profile_settings,
    )


@users.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    """登录用户修改密码"""
    user = User.query.get(current_user.student_id)
    form = ChangePasswordForm()

    if form.validate_on_submit():
        if not user.verify_password(form.current_password.data):
            flash('当前密码不正确', 'danger')
            return render_template('change_password.html', form=form)

        user.password = form.new_password.data
        user.password_changed_at = datetime.utcnow()
        db.session.commit()
        flash('密码修改成功，请使用新密码登录。', 'success')
        return redirect(url_for('main.profile'))

    return render_template('change_password.html', form=form)


@users.route('/users/reset_password/<string:student_id>', methods=['POST'])
@login_required
@admin_required
def admin_reset_password(student_id):
    """管理员为没有邮箱的用户生成一次性密码重置链接。"""
    form = AdminPasswordResetForm()
    if not form.validate_on_submit():
        flash('请求无效，请刷新页面后重试。', 'danger')
        return redirect(url_for('users.manage_users', search=student_id))

    user = User.query.get_or_404(student_id)
    try:
        raw_token = create_password_reset_token(
            user,
            requested_ip=request.remote_addr,
            created_by=current_user.student_id,
        )
        reset_url = build_password_reset_url(raw_token)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('管理员生成密码重置链接失败')
        flash('密码重置链接生成失败，请稍后重试。', 'danger')
    else:
        flash(
            f'已生成一次性密码重置链接（{password_reset_ttl_minutes()}分钟内有效，请复制给用户）：'
            f'{reset_url}',
            'success',
        )
    return redirect(url_for('users.manage_users', search=student_id))


@users.route('/export_users')
@login_required
@admin_required
def export_users():
    """导出用户数据为Excel"""
    try:
        # 获取所有用户数据
        users_data = User.query.all()
        
        # 准备数据
        data = []
        for user in users_data:
            data.append({
                '用户名': user.username,
                '学号': user.student_id,
                '姓名': user.full_name,
                '用户类型': user.usertype,
                '班级': authoritative_class_name(user),
                '提交次数': user.submit_count,
                '平均分数': round(user.user_ascore, 2) if user.user_ascore else 0,
                '总分': round(user.user_tscore, 2) if user.user_tscore else 0
            })
        
        # Excel 会把以 =、+、-、@ 开头的字符串当成公式执行；用户的
        # 姓名、用户名或班级名都可能来自外部输入，导出前统一按文本转义。
        data = [
            {
                key: safe_export_cell(value)
                for key, value in row.items()
            }
            for row in data
        ]
        # 创建DataFrame
        df = pd.DataFrame(data)
        
        # 创建一个内存中的Excel文件
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='用户数据', index=False)
            
            # 获取工作表对象
            worksheet = writer.sheets['用户数据']
            
            # 调整列宽
            for idx, col in enumerate(df.columns):
                max_length = max(df[col].astype(str).apply(len).max(), len(col)) + 2
                worksheet.set_column(idx, idx, max_length)
        
        output.seek(0)
        
        # 生成文件名 - 使用英文命名避免编码问题
        filename = f'user_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception:
        current_app.logger.exception('导出用户数据失败')
        flash('导出数据时发生错误，请稍后重试。', 'danger')
        return redirect(url_for('users.manage_users'))


@users.route('/view_student_details/<string:student_id>')
@login_required
@admin_or_teacher_required
def view_student_details(student_id):
    """管理员查看学生详情页面"""
    try:
        # 教师只能查看自己管理班级的学生，管理员才可以查看全部学生。
        user = User.query.get_or_404(student_id)
        if not can_access_student(user, current_user):
            flash('您没有权限查看该学生的详细信息', 'danger')
            return redirect(url_for('main.home'))
        
        # 查询学生的所有提交记录
        all_submissions = Submission.query.filter_by(student_id=student_id).all()
        scores = [sub.score for sub in all_submissions if sub.score is not None]
        
        # 分页获取提交记录
        per_page = 10
        page = request.args.get('page', 1, type=int)
        submissions = (Submission.query
                     .filter_by(student_id=student_id)
                     .order_by(desc(Submission.submitted_at))
                     .paginate(page=page, per_page=per_page, error_out=False))
        
        # 准备图表数据
        chart_data = {
            'x': [sub.assignment_id for sub in submissions.items],
            'y': [sub.score if sub.score is not None else 0 for sub in submissions.items],
            'pie_data': _score_distribution(scores),
        }
        
        # 计算学生的提交统计
        submission_stats = {
            'total': len(all_submissions),
            'average_score': round(sum(scores) / len(scores), 2) if scores else 0,
            'max_score': max(scores) if scores else 0,
            'min_score': min(scores) if scores else 0,
            'score_distribution': {
                '80–100分': _score_distribution(scores)[0],
                '60–79分': _score_distribution(scores)[1],
                '0–59分': _score_distribution(scores)[2],
            }
        }
        
        # 获取最近提交记录
        recent_submissions = (Submission.query
                            .filter_by(student_id=student_id)
                            .order_by(desc(Submission.submitted_at))
                            .limit(5)
                            .all())
        
        # 获取学生排名信息。教师只能看到自己管理班级内的排名，避免通过
        # 总人数或名次推断其他班级的组织数据；管理员仍可查看全局排名。
        if current_user.is_admin:
            all_students = (User.query
                            .filter_by(usertype='学生')
                            .order_by(desc(User.user_ascore))
                            .all())
        else:
            managed = managed_classes(current_user)
            class_filters = [class_student_filter(cls) for cls in managed]
            all_students = (
                User.query.filter(
                    User.usertype == '学生',
                    or_(*class_filters),
                ).order_by(desc(User.user_ascore)).all()
                if class_filters else []
            )
        student_ranks = {student.student_id: i+1 for i, student in enumerate(all_students)}
        
        return render_template('student_details.html', 
                              user=user,
                              submissions=submissions,
                              chart_data=chart_data,
                              submission_stats=submission_stats,
                              recent_submissions=recent_submissions,
                              student_rank=student_ranks.get(student_id, 'N/A'),
                              total_students=len(all_students))
                              
    except Exception:
        current_app.logger.exception(
            '访问学生详情页面失败 student_id=%s actor_id=%s',
            student_id,
            current_user.student_id,
        )
        flash('访问学生详情页面时出错，请稍后重试。', 'danger')
        return redirect(url_for('users.manage_users'))


@users.route('/view_staff_details/<string:student_id>')
@login_required
@admin_required
def view_staff_details(student_id):
    """管理员查看教师/管理员详情页面"""
    user = User.query.get_or_404(student_id)
    # 获取该用户管理的班级（教师）
    managed_classes = []
    if hasattr(user, 'managed_classes'):
        managed_classes = user.managed_classes.all()
    # 获取操作日志
    recent_logs = SystemLog.query.filter_by(user_id=student_id).order_by(SystemLog.created_at.desc()).limit(10).all()
    return render_template('staff_details.html',
                           user=user,
                           managed_classes=managed_classes,
                           recent_logs=recent_logs)


@users.route('/invite-teacher', methods=['GET', 'POST'])
@login_required
@admin_required
def invite_teacher():
    """展示当前有效的教师邀请链接；只有 POST 才会刷新链接。"""
    from models import InviteToken
    if request.method == 'POST':
        # 只有明确的刷新动作才作废旧链接，避免 GET 预取、浏览器刷新或
        # 邮件扫描器意外消耗管理员刚生成的邀请。
        try:
            InviteToken.invalidate_all_unused()
            serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
            token = serializer.dumps('teacher-invitation', salt='teacher-reg-salt')
            InviteToken.create(token_str=token, created_by=current_user.student_id)
            flash('新的教师邀请链接已生成，24小时内有效。', 'success')
        except Exception:
            db.session.rollback()
            current_app.logger.exception('生成教师邀请链接失败')
            flash('生成邀请链接失败，请稍后重试。', 'danger')

    active_token = InviteToken.query.filter_by(
        created_by=current_user.student_id,
        is_used=False,
    ).filter(
        InviteToken.expires_at > datetime.utcnow(),
    ).order_by(InviteToken.created_at.desc()).first()
    invite_url = (
        url_for('auth.register_teacher', token=active_token.token, _external=True)
        if active_token else None
    )
    return render_template('invite_teacher.html', invite_url=invite_url) 
