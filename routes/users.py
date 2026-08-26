"""
用户管理相关路由
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_file, current_app, jsonify
from itsdangerous import URLSafeTimedSerializer
from models import db, User, Submission, SystemLog, Class, AbilityTrend
from utils.auth import login_required, admin_required, admin_or_teacher_required
from tasks.ability_analysis import trigger_analysis_if_needed
from services.demo_database import current_demo_run_id
from sqlalchemy import desc
from forms import ChangePasswordForm, EditProfileForm
from werkzeug.utils import secure_filename
import pandas as pd
import io
from datetime import datetime
import os
import random
import uuid

users = Blueprint('users', __name__)


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
    total_submissions = sum(user.submit_count for user in User.query.all())
    student_count = User.query.filter_by(usertype='学生').count()
    admin_count = User.query.filter_by(usertype='管理员').count()
    teacher_count = User.query.filter_by(usertype='教师').count()
    
    print("\n=== 用户统计数据 ===")
    print(f"总用户数: {total_users}")
    print(f"学生数量: {student_count}")
    print(f"教师数量: {teacher_count}")
    print(f"管理员数量: {admin_count}")
    print(f"总提交数: {total_submissions}")
    
    # 准备图表数据
    user_type_chart_data = {
        'labels': ['学生', '教师', '管理员'],
        'data': [student_count, teacher_count, admin_count]
    }
    
    print("\n=== 用户类型图表数据 ===")
    print(user_type_chart_data)
    
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
    
    print("\n=== 原始提交数量分布数据 ===")
    print(submission_counts)
    
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
    
    print("\n=== 处理后的提交数量图表数据 ===")
    print(submission_chart_data)
    
    return render_template('users.html',
                         users=users,
                         pagination=pagination,
                         search_term=search,
                         user_type=user_type,
                         total_users=total_users,
                         total_submissions=total_submissions,
                         student_count=student_count,
                         admin_count=admin_count,
                         user_type_chart_data=user_type_chart_data,
                         submission_chart_data=submission_chart_data)


@users.route('/delete_user/<string:student_id>', methods=['GET', 'POST'])
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
        # 优先使用URL参数中的student_id，如果没有则使用会话中的student_id
        student_id = request.args.get('student_id') or session.get('student_id')
        if not student_id:
            flash('会话已过期，请重新登录')
            return redirect(url_for('auth.login'))
            
        # 检查权限：允许管理员、任课教师或本人查看
        if session.get('usertype') not in ['管理员', '教师'] and session.get('student_id') != student_id:
            flash('您无权查看此学生的提交记录', 'danger')
            return redirect(url_for('main.home'))
            
        per_page = 10
        page = request.args.get('page', 1, type=int)  # 获取当前页码，默认为1
        session['spage'] = page
        
        # 查询学生的所有提交记录（用于统计）
        all_submissions = Submission.query.filter_by(student_id=student_id).all()
        scores = [sub.score for sub in all_submissions if sub.score is not None]
        
        # 分页获取提交记录
        submissions = (Submission.query
                    .filter_by(student_id=student_id)
                    .order_by(desc(Submission.submitted_at))
                    .paginate(page=page, per_page=per_page, error_out=False))
        
        # 获取学生信息
        user = User.query.get_or_404(student_id)
        
        # 3. 准备图表数据
        chart_data = {
            'x': [sub.assignment_id for sub in submissions.items],
            'y': [sub.score if sub.score is not None else 0 for sub in submissions.items],
            'pie_data': [
                scores.count(5) if 5 in scores else 0,
                scores.count(4) if 4 in scores else 0,
                scores.count(3) if 3 in scores else 0,
                scores.count(2) if 2 in scores else 0,
                scores.count(1) if 1 in scores else 0
            ]
        }
        
        # 4. 获取真实的能力分析数据
        ability_scores = user.get_ability_scores()
        class_avg_scores = User.get_class_average_scores()
        
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
            'class_avg': class_avg_scores.get(user.class_name, {
                'algorithm': 70, 'style': 70, 'functionality': 70, 'efficiency': 70, 'readability': 70
            })
        }
        
        # 5. 获取 AI 能力趋势分析
        ability_trend = AbilityTrend.query.filter_by(student_id=student_id).first()
        
        # 如果没有分析或者已过期，尝试触发异步生成
        if not ability_trend or ability_trend.status in ['pending', 'outdated', 'failed']:
            trigger_analysis_if_needed(
                student_id,
                demo_run_id=current_demo_run_id(),
            )
        
        return render_template('submissions.html', 
                            submissions=submissions, 
                            user=user, 
                            chart_data=chart_data,
                            ability_data=ability_data,
                            ability_trend=ability_trend,
                            comprehensive_score=comprehensive_score,
                            strongest_dim=strongest_dim)
    except Exception as e:
        import traceback
        print(f'访问学情分析时出错: {str(e)}')
        print(traceback.format_exc())
        flash(f'访问学情分析时出错: {str(e)}')
        return redirect(url_for('main.home'))


@users.route('/refresh_analysis')
@login_required
def refresh_analysis():
    """手动刷新能力分析"""
    student_id = session.get('student_id')
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
        return jsonify({'status': 'info', 'message': '分析任务正在处理中，请稍候'})

@users.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """编辑个人资料"""
    user = User.query.get(session.get('student_id'))
    form = EditProfileForm()
    
    # 获取所有班级作为下拉选项
    classes = Class.query.all()
    form.class_name.choices = [('', '未分配')] + [(c.name, c.name) for c in classes]
    
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
                    return render_template('edit_profile.html', form=form, user=user)

            # 更新用户信息
            user.username = form.username.data
            user.full_name = form.full_name.data
            user.email = email
            user.class_name = form.class_name.data

            avatar_path = _save_avatar(form.avatar.data, user.student_id)
            if avatar_path:
                user.avatar_path = avatar_path
            
            # 同时更新 class_id 以保持一致
            if form.class_name.data:
                target_class = Class.query.filter_by(name=form.class_name.data).first()
                if target_class:
                    user.class_id = target_class.id
            else:
                user.class_id = None
            
            db.session.commit()
            flash('资料更新成功！', 'success')
            return redirect(url_for('users.view_submissions'))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败：{str(e)}', 'danger')
    
    # 如果是GET请求，预填充表单
    if request.method == 'GET':
        form.username.data = user.username
        form.full_name.data = user.full_name
        form.email.data = user.email
        form.class_name.data = user.class_name
    
    return render_template('edit_profile.html', form=form, user=user)


@users.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    """登录用户修改密码"""
    user = User.query.get(session.get('student_id'))
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
                '班级': user.class_name,
                '提交次数': user.submit_count,
                '平均分数': round(user.user_ascore, 2) if user.user_ascore else 0,
                '总分': round(user.user_tscore, 2) if user.user_tscore else 0
            })
        
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
        
    except Exception as e:
        flash(f'导出数据时发生错误：{str(e)}', 'danger')
        return redirect(url_for('users.manage_users'))


@users.route('/view_student_details/<string:student_id>')
@login_required
@admin_or_teacher_required
def view_student_details(student_id):
    """管理员查看学生详情页面"""
    try:
        # 获取学生信息
        user = User.query.get_or_404(student_id)
        
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
            'pie_data': [
                scores.count(5) if 5 in scores else 0,
                scores.count(4) if 4 in scores else 0,
                scores.count(3) if 3 in scores else 0,
                scores.count(2) if 2 in scores else 0,
                scores.count(1) if 1 in scores else 0
            ]
        }
        
        # 计算学生的提交统计
        submission_stats = {
            'total': len(all_submissions),
            'average_score': round(sum(scores) / len(scores), 2) if scores else 0,
            'max_score': max(scores) if scores else 0,
            'min_score': min(scores) if scores else 0,
            'score_distribution': {
                '5分': scores.count(5) if 5 in scores else 0,
                '4分': scores.count(4) if 4 in scores else 0,
                '3分': scores.count(3) if 3 in scores else 0,
                '2分': scores.count(2) if 2 in scores else 0,
                '1分': scores.count(1) if 1 in scores else 0
            }
        }
        
        # 获取最近提交记录
        recent_submissions = (Submission.query
                            .filter_by(student_id=student_id)
                            .order_by(desc(Submission.submitted_at))
                            .limit(5)
                            .all())
        
        # 获取学生排名信息
        all_students = (User.query
                       .filter_by(usertype='学生')
                       .order_by(desc(User.user_ascore))
                       .all())
        student_ranks = {student.student_id: i+1 for i, student in enumerate(all_students)}
        
        return render_template('student_details.html', 
                              user=user,
                              submissions=submissions,
                              chart_data=chart_data,
                              submission_stats=submission_stats,
                              recent_submissions=recent_submissions,
                              student_rank=student_ranks.get(student_id, 'N/A'),
                              total_students=len(all_students))
                              
    except Exception as e:
        import traceback
        print(f'访问学生详情页面时出错: {str(e)}')
        print(traceback.format_exc())
        flash(f'访问学生详情页面时出错: {str(e)}', 'danger')
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


@users.route('/invite-teacher')
@login_required
@admin_required
def invite_teacher():
    """生成一个用于教师注册的邀请链接（24小时有效，单次使用，且每次进入页面都会刷新唯一有效链接）"""
    from models import InviteToken
    # 先作废之前所有未使用的邀请链接，实现“邀请一次一刷新”
    try:
        InviteToken.invalidate_all_unused()
    except Exception as e:
        current_app.logger.error(f"作废旧邀请码失败: {e}")

    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    token = serializer.dumps('teacher-invitation', salt='teacher-reg-salt')
    InviteToken.create(token_str=token, created_by=session.get('student_id'))
    invite_url = url_for('auth.register_teacher', token=token, _external=True)
    return render_template('invite_teacher.html', invite_url=invite_url) 
