"""
身份验证相关路由
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
import uuid
from itsdangerous import URLSafeTimedSerializer, SignatureExpired
from flask_login import login_user, logout_user, current_user
from models import db, Class, StudentRoster, User, SystemLog, SystemConfig
from forms import LoginForm, RegistrationForm
from services.demo_experience import (
    DEMO_STUDENT_ID,
    DEMO_TEACHER_ID,
    ensure_demo_experience,
)
from utils.auth import redirect_if_logged_in

auth = Blueprint('auth', __name__)


def _establish_login_session(user, source=None):
    """建立单点登录会话，并同步 Flask-Login 与旧版 session 字段。"""
    new_session_id = uuid.uuid4().hex
    user.current_session_id = new_session_id
    db.session.commit()

    login_user(user)
    session['current_session_id'] = new_session_id
    session['student_id'] = user.student_id
    session['username'] = user.username
    session['full_name'] = user.full_name or user.username
    session['usertype'] = user.usertype
    session['login'] = True

    prefix = f'[{source}] ' if source else ''
    SystemLog.add_log(
        log_type='用户登录',
        content=f'{prefix}用户 {user.username} ({user.full_name}) 登录了系统',
        user_id=user.student_id,
    )
    return new_session_id


@auth.route('/')
def index():
    """首页，重定向到登录页面"""
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    session.clear()
    return redirect(url_for('auth.login'))


@auth.route('/login', methods=['GET', 'POST'])
@redirect_if_logged_in
def login():
    """登录页面"""
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data
        current_app.logger.info(f"登录尝试 - 用户名: {username}, IP: {request.remote_addr}")
        user = User.query.filter(
            db.or_(
                User.username == username,
                db.func.lower(User.email) == username.lower()
            )
        ).first()
        if user and user.verify_password(password):
            # 单点登录逻辑：生成新的会话ID，令旧会话失效
            new_session_id = uuid.uuid4().hex
            user.current_session_id = new_session_id
            db.session.commit()
            
            login_user(user)
            session['current_session_id'] = new_session_id
            session['student_id'] = user.student_id
            session['username'] = user.username
            session['full_name'] = user.full_name
            session['usertype'] = user.usertype
            session['login'] = True
            SystemLog.add_log(
                log_type='用户登录',
                content=f'用户 {user.username} ({user.full_name}) 登录了系统',
                user_id=user.student_id
            )
            current_app.logger.info(f"登录成功 - 用户: {user.username} ({user.full_name}), 类型: {user.usertype}, IP: {request.remote_addr}")
            try:
                from utils.async_tasks import add_ability_trend_task
                task_id = add_ability_trend_task(user.student_id)
                current_app.logger.info(f"用户 {user.student_id} 登录成功，已触发能力趋势分析任务: {task_id}")
            except Exception as e:
                current_app.logger.warning(f"触发能力趋势分析任务失败: {e}")
            flash('登录成功！', 'success')
            return redirect(url_for('main.home'))
        else:
            current_app.logger.warning(f"登录失败 - 用户名: {username}, IP: {request.remote_addr}, 原因: {'用户不存在' if not user else '密码错误'}")
            flash('用户名或密码错误，请重试！', 'danger')
    login_message = SystemConfig.get_value('login_message', '欢迎登录 CodeSense 酷森思')
    site_name = SystemConfig.get_value('site_name', 'CodeSense 酷森思')
    return render_template('login.html', form=form, login_message=login_message, site_name=site_name)


@auth.route('/demo-login/<role>')
@redirect_if_logged_in
def demo_login(role):
    """公开演示入口：准备演示数据后，按角色进入对应体验首页。"""
    if role not in ('student', 'teacher'):
        flash('该演示入口不可用，请返回登录页重试。', 'warning')
        return redirect(url_for('auth.login'))

    try:
        demo = ensure_demo_experience()
        user_id = DEMO_STUDENT_ID if role == 'student' else DEMO_TEACHER_ID
        user = User.query.get(user_id)
        if not user:
            raise RuntimeError('演示账号初始化后不存在')

        _establish_login_session(user, source='公开演示')
        if role == 'student':
            return redirect(url_for('thinking.arena', assignment_id=demo.assignment_id))
        return redirect(url_for('main.home'))
    except Exception:
        db.session.rollback()
        current_app.logger.exception('公开演示入口初始化失败')
        flash('演示入口暂时不可用，请稍后重试。', 'warning')
        return redirect(url_for('auth.login'))


@auth.route('/register', methods=['GET', 'POST'])
@redirect_if_logged_in
def register():
    """注册页面 - 仅限学生"""
    enable_registration = SystemConfig.get_value('enable_registration', True)
    if not enable_registration:
        flash('系统当前不允许新用户注册，请联系管理员', 'warning')
        return redirect(url_for('auth.login'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        username = form.username.data
        student_id = form.student_id.data
        email = (form.email.data or '').strip().lower() or None
        current_app.logger.info(f"学生注册尝试 - 用户名: {username}, 学号: {student_id}, IP: {request.remote_addr}")
        
        existing_user = User.query.filter(
            (User.username == username) | (User.student_id == student_id)
        ).first()
        
        if existing_user:
            current_app.logger.warning(f"注册失败 - 用户名或学号已存在: {username}/{student_id}, IP: {request.remote_addr}")
            flash('用户名或学号已存在，请使用其他的用户名和学号', 'danger')
            return render_template('register.html', form=form)

        if email and User.query.filter(db.func.lower(User.email) == email).first():
            flash('邮箱已被使用，请更换邮箱或直接登录。', 'danger')
            return render_template('register.html', form=form)

        roster = StudentRoster.query.filter_by(student_id=student_id).first()
        if not roster:
            current_app.logger.warning(f"注册失败 - 学号不在导入名单中: {student_id}, IP: {request.remote_addr}")
            flash('未在教师导入的学生名单中找到该学号，请联系任课教师或管理员导入名单后再注册。', 'danger')
            return render_template('register.html', form=form)

        target_class = Class.query.get(roster.class_id)
        if not target_class:
            current_app.logger.warning(f"注册失败 - 花名册班级不存在: {student_id}, class_id={roster.class_id}")
            flash('学生名单关联的班级不存在，请联系管理员处理。', 'danger')
            return render_template('register.html', form=form)
        
        try:
            user = User(
                username=username,
                student_id=student_id,
                usertype='学生',
                full_name=form.full_name.data or roster.full_name,
                email=email,
                class_name=target_class.name,
                class_id=target_class.id
            )
            user.password = form.password.data
            db.session.add(user)
            roster.is_registered = True
            roster.registered_user_id = student_id
            db.session.commit()
            
            SystemLog.add_log(
                log_type='用户注册',
                content=f'新学生 {user.username} ({user.full_name}) 注册成功',
                user_id=user.student_id
            )
            current_app.logger.info(f"注册成功 - 用户: {user.username}, 学号: {user.student_id}, 类型: 学生, 班级: {user.class_name}, IP: {request.remote_addr}")
            flash('注册成功，请登录！', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            error_msg = f"注册失败 - 数据库错误: {username}, 错误: {str(e)}"
            current_app.logger.error(error_msg, exc_info=True)
            flash('注册失败，请稍后重试', 'danger')
            return render_template('register.html', form=form)
        
    return render_template('register.html', form=form)


@auth.route('/register/teacher/<token>', methods=['GET', 'POST'])
def register_teacher(token):
    """教师邀请注册页面"""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = serializer.loads(token, salt='teacher-reg-salt', max_age=86400) # 24 hours
        if data != 'teacher-invitation':
            raise Exception("Invalid token data.")
    except SignatureExpired:
        flash('邀请链接已过期，请联系管理员获取新链接。', 'danger')
        return redirect(url_for('auth.login'))
    except Exception as e:
        current_app.logger.warning(f"教师邀请token无效: {token}, 错误: {e}")
        flash('无效的邀请链接。', 'danger')
        return redirect(url_for('auth.login'))

    # 数据库层单次使用校验
    try:
        from models import InviteToken
        ok, err_msg = InviteToken.validate(token)
        if not ok:
            flash(err_msg, 'danger')
            return redirect(url_for('auth.login'))
    except Exception:
        pass  # invite_tokens 表不存在时降级为仅签名校验

    form = RegistrationForm()
    form.class_name.render_kw = {'style': 'display: none;'}
    form.class_name.label.text = ''

    if form.validate_on_submit():
        username = form.username.data
        teacher_id = form.student_id.data
        email = (form.email.data or '').strip().lower() or None

        existing_user = User.query.filter(
            (User.username == username) | (User.student_id == teacher_id)
        ).first()

        if existing_user:
            flash('用户名或教师工号已存在。', 'danger')
            return render_template('register_teacher.html', form=form, token=token)

        if email and User.query.filter(db.func.lower(User.email) == email).first():
            flash('邮箱已被使用，请更换邮箱或直接登录。', 'danger')
            return render_template('register_teacher.html', form=form, token=token)

        try:
            user = User(
                username=username,
                student_id=teacher_id,
                usertype='教师',
                full_name=form.full_name.data,
                email=email
            )
            user.password = form.password.data
            db.session.add(user)
            db.session.commit()

            # 注册成功后标记 token 为已使用
            try:
                InviteToken.mark_as_used(token)
            except Exception as e:
                current_app.logger.error(f"标记邀请码已使用失败: {e}")

            SystemLog.add_log(
                log_type='用户注册',
                content=f'新教师 {user.username} ({user.full_name}) 通过邀请链接注册成功',
                user_id=user.student_id
            )
            flash('教师账户注册成功，请登录！', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"教师注册失败: {e}", exc_info=True)
            flash('注册过程中发生错误，请稍后重试。', 'danger')
            return render_template('register_teacher.html', form=form, token=token)

    return render_template('register_teacher.html', form=form, token=token)


@auth.route('/logout')
def logout():
    """登出处理"""
    user_id = session.get('student_id')
    username = session.get('username')
    full_name = session.get('full_name', '未知用户')
    
    current_app.logger.info(f"用户登出 - 用户: {username} ({full_name}), 学号: {user_id}, IP: {request.remote_addr}")
    
    logout_user()
    session.clear()
    
    if user_id:
        SystemLog.add_log(
            log_type='用户登出',
            content=f'用户 {username} ({full_name}) 退出了系统',
            user_id=user_id,
            icon='bi bi-box-arrow-right'
        )
    
    flash('您已成功退出', 'info')
    return redirect(url_for('auth.login'))


@auth.route('/sandbox-login/<student_id>')
def sandbox_login(student_id):
    """开发和测试模式下的免密快捷登录"""
    if not (current_app.config.get('DEBUG') or current_app.config.get('TESTING')):
        current_app.logger.warning(f"拒绝沙箱登录尝试：非开发或测试模式。IP: {request.remote_addr}")
        return "Forbidden", 403
        
    user = User.query.get(student_id)
    if not user:
        flash(f'沙箱登录失败：用户 {student_id} 不存在', 'danger')
        return redirect(url_for('auth.login'))
        
    # 单点登录逻辑：生成新的会话ID，令旧会话失效
    new_session_id = uuid.uuid4().hex
    user.current_session_id = new_session_id
    db.session.commit()
    
    login_user(user)
    session['current_session_id'] = new_session_id
    session['student_id'] = user.student_id
    session['username'] = user.username
    session['full_name'] = user.full_name or user.username
    session['usertype'] = user.usertype
    session['login'] = True
    
    SystemLog.add_log(
        log_type='用户登录',
        content=f'[沙箱] 用户 {user.username} ({user.full_name}) 免密登录系统',
        user_id=user.student_id
    )
    current_app.logger.info(f"[沙箱登录] - 用户: {user.username}, 类型: {user.usertype}, IP: {request.remote_addr}")
    
    # 异步触发能力趋势任务
    try:
        from utils.async_tasks import add_ability_trend_task
        add_ability_trend_task(user.student_id)
    except Exception:
        pass
        
    flash(f'已通过沙箱快捷登录为 {user.full_name or user.username} ({user.usertype})', 'success')
    return redirect(url_for('main.home'))
