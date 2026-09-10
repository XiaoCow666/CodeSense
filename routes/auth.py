"""
身份验证相关路由
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
import uuid
from itsdangerous import URLSafeTimedSerializer, SignatureExpired
from flask_login import login_user, logout_user, current_user
from models import db, Class, StudentRoster, User, SystemLog, SystemConfig
from forms import (
    LoginForm,
    EmailRegistrationForm,
    EmailVerificationForm,
    EmailVerificationRequestForm,
    PasswordResetRequestForm,
    RegistrationForm,
    ResetPasswordForm,
)
from services.demo_experience import (
    DEMO_STUDENT_ID,
    DEMO_TEACHER_ID,
    seed_demo_experience,
)
from services.demo_database import (
    DEMO_ROLE_SESSION_KEY,
    DEMO_SESSION_KEY,
    activate_demo_run,
    create_demo_run,
    current_demo_run_id,
    destroy_demo_run,
    login_demo_run,
)
from services.password_reset import (
    consume_password_reset_token,
    create_password_reset_token,
    find_user_by_identifier,
    get_valid_password_reset_token,
    has_recent_reset_request,
    revoke_password_reset_token,
    send_password_reset_email,
)
from services.email_verification import (
    consume_email_verification_token,
    create_email_verification_token,
    get_valid_email_verification_token,
    has_recent_email_verification_request,
    revoke_email_verification_token,
    send_email_verification_email,
)
from utils.auth import redirect_if_logged_in

auth = Blueprint('auth', __name__)

PASSWORD_RESET_NOTICE = (
    '如果账号存在且已绑定邮箱，系统会发送重置链接；'
    '若未收到邮件，请检查垃圾邮件或联系管理员。'
)


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
                db.func.lower(User.email) == username.lower(),
                User.student_id == username,
                User.student_number == username,
            )
        ).first()
        if user and user.verify_password(password):
            if (
                getattr(user, 'email_verification_required', False)
                and not getattr(user, 'email_verified_at', None)
            ):
                current_app.logger.info(
                    '邮箱注册账号尚未验证，拒绝登录 - 用户: %s, IP: %s',
                    user.username,
                    request.remote_addr,
                )
                flash('邮箱尚未验证，请先查收验证邮件；如果没有收到，可以重新发送。', 'warning')
                return redirect(url_for('auth.login'))

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


@auth.route('/forgot-password', methods=['GET', 'POST'])
@redirect_if_logged_in
def forgot_password():
    """申请密码重置链接，不向外暴露账号是否存在。"""
    form = PasswordResetRequestForm()
    if form.validate_on_submit():
        user = find_user_by_identifier(form.identifier.data)
        if user and user.email and not has_recent_reset_request(user):
            raw_token = None
            try:
                raw_token = create_password_reset_token(
                    user,
                    requested_ip=request.remote_addr,
                )
                send_password_reset_email(user, raw_token)
            except Exception:
                db.session.rollback()
                if raw_token:
                    try:
                        revoke_password_reset_token(raw_token)
                    except Exception:
                        db.session.rollback()
                current_app.logger.exception('密码重置邮件发送失败')
            else:
                current_app.logger.info('密码重置邮件已提交发送')

        flash(PASSWORD_RESET_NOTICE, 'info')
        return redirect(url_for('auth.forgot_password'))

    return render_template('forgot_password.html', form=form)


@auth.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """校验一次性令牌并设置新密码。"""
    raw_token = (
        request.args.get('token')
        or request.form.get('token')
        or ''
    ).strip()
    form = ResetPasswordForm()
    if request.method == 'GET':
        form.token.data = raw_token

    token_record = get_valid_password_reset_token(raw_token)
    if request.method == 'GET':
        return render_template(
            'reset_password.html',
            form=form,
            token=raw_token,
            token_valid=token_record is not None,
        )

    if not form.validate_on_submit() or token_record is None:
        return render_template(
            'reset_password.html',
            form=form,
            token=raw_token,
            token_valid=token_record is not None,
        )

    user = consume_password_reset_token(raw_token, form.password.data)
    if not user:
        return render_template(
            'reset_password.html',
            form=form,
            token=raw_token,
            token_valid=False,
        )

    flash('密码重置成功，请使用新密码登录。', 'success')
    return redirect(url_for('auth.login'))


@auth.route('/demo-login/<role>')
@redirect_if_logged_in
def demo_login(role):
    """公开演示入口：为本次会话创建独立临时库后进入对应体验首页。"""
    if role not in ('student', 'teacher'):
        flash('该演示入口不可用，请返回登录页重试。', 'warning')
        return redirect(url_for('auth.login'))

    run = None
    try:
        run = create_demo_run(role)
        if not activate_demo_run(run.run_id):
            raise RuntimeError('临时体验数据库无法激活')
        # The run marker must be present before any subsequent request or
        # Flask-Login user loading can resolve the temporary database.
        session[DEMO_SESSION_KEY] = run.run_id
        session[DEMO_ROLE_SESSION_KEY] = role
        demo = seed_demo_experience(run)
        login_demo_run(run)
        if role == 'student':
            # 真实环境首次进入体验时即启动一次能力分析，分析结果会被
            # 缓存在本次临时库中；测试环境由专门的任务测试控制线程。
            if not current_app.config.get('TESTING'):
                from tasks.ability_analysis import trigger_analysis_if_needed
                trigger_analysis_if_needed(
                    DEMO_STUDENT_ID,
                    demo_run_id=run.run_id,
                )
            return redirect(url_for('thinking.arena', assignment_id=demo.assignment_id))
        return redirect(url_for('main.home'))
    except Exception:
        db.session.rollback()
        if run is not None:
            db.session.remove()
            try:
                destroy_demo_run(run.run_id)
            except Exception:
                current_app.logger.exception('清理失败的公开体验临时库失败')
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


def _new_email_account_id():
    """生成不与历史学号冲突的内部账号 ID。"""
    while True:
        candidate = f'e-{uuid.uuid4().hex[:18]}'
        if not User.query.filter_by(student_id=candidate).first():
            return candidate


@auth.route('/register/email', methods=['GET', 'POST'])
@redirect_if_logged_in
def register_email():
    """通过邮箱创建不依赖学生名单的学生账号。"""
    enable_registration = SystemConfig.get_value('enable_registration', True)
    if not enable_registration:
        flash('系统当前不允许新用户注册，请联系管理员', 'warning')
        return redirect(url_for('auth.login'))

    form = EmailRegistrationForm()
    if form.validate_on_submit():
        username = (form.username.data or '').strip()
        email = (form.email.data or '').strip().lower()
        full_name = (form.full_name.data or '').strip() or username

        if not username:
            form.username.errors.append('用户名不能为空')
            return render_template('email_register.html', form=form)

        current_app.logger.info(
            '邮箱注册尝试 - 用户名: %s, IP: %s',
            username,
            request.remote_addr,
        )

        existing_user = User.query.filter(User.username == username).first()
        if existing_user:
            flash('用户名已存在，请使用其他用户名。', 'danger')
            return render_template('email_register.html', form=form)

        if User.query.filter(db.func.lower(User.email) == email).first():
            flash('邮箱已被使用，请更换邮箱或直接登录。', 'danger')
            return render_template('email_register.html', form=form)

        try:
            user = User(
                student_id=_new_email_account_id(),
                username=username,
                usertype='学生',
                full_name=full_name,
                email=email,
                registration_method='email',
                email_verification_required=True,
            )
            user.password = form.password.data
            db.session.add(user)
            db.session.commit()
            SystemLog.add_log(
                log_type='用户注册',
                content=f'新邮箱账号 {user.username} ({user.full_name}) 注册成功，等待邮箱验证',
                user_id=user.student_id,
            )
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('邮箱注册保存失败 - 用户: %s, 错误: %s', username, e, exc_info=True)
            flash('注册失败，请稍后重试。', 'danger')
            return render_template('email_register.html', form=form)

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
            current_app.logger.exception('邮箱验证邮件发送失败 - 用户: %s', user.student_id)
            flash('账号已创建，但验证邮件暂时发送失败，请稍后在登录页重新发送验证邮件。', 'warning')
        else:
            flash('注册成功，请查收邮箱验证邮件，完成验证后再登录。', 'success')
        return redirect(url_for('auth.login'))

    return render_template('email_register.html', form=form)


@auth.route('/verify-email', methods=['GET', 'POST'])
def verify_email():
    """展示并确认邮箱验证令牌；GET 不消费令牌，避免被邮件扫描器误用。"""
    raw_token = (
        request.args.get('token')
        or request.form.get('token')
        or ''
    ).strip()
    form = EmailVerificationForm()
    if request.method == 'GET':
        form.token.data = raw_token

    token_record = get_valid_email_verification_token(raw_token)
    if request.method == 'GET':
        return render_template(
            'verify_email.html',
            form=form,
            token=raw_token,
            token_valid=token_record is not None,
        )

    if not form.validate_on_submit() or token_record is None:
        return render_template(
            'verify_email.html',
            form=form,
            token=raw_token,
            token_valid=False,
        )

    user = consume_email_verification_token(raw_token)
    if not user:
        return render_template(
            'verify_email.html',
            form=form,
            token=raw_token,
            token_valid=False,
        )

    SystemLog.add_log(
        log_type='邮箱验证',
        content=f'用户 {user.username} 完成邮箱验证',
        user_id=user.student_id,
    )
    flash('邮箱验证成功，请使用注册邮箱和密码登录。', 'success')
    return redirect(url_for('auth.login'))


@auth.route('/resend-verification', methods=['GET', 'POST'])
@redirect_if_logged_in
def resend_verification():
    """为尚未验证的邮箱注册账号重新发送验证邮件。"""
    form = EmailVerificationRequestForm()
    if request.method == 'GET':
        form.email.data = (request.args.get('email') or '').strip().lower()

    if form.validate_on_submit():
        email = (form.email.data or '').strip().lower()
        user = User.query.filter(db.func.lower(User.email) == email).first()
        raw_token = None
        if (
            user
            and getattr(user, 'email_verification_required', False)
            and not getattr(user, 'email_verified_at', None)
            and not has_recent_email_verification_request(user)
        ):
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
                current_app.logger.exception('重新发送邮箱验证邮件失败')

        flash('如果该邮箱对应未完成验证的账号，系统会发送新的验证邮件；请检查收件箱和垃圾邮件。', 'info')
        return redirect(url_for('auth.resend_verification'))

    return render_template('resend_verification.html', form=form)


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
    demo_run_id = current_demo_run_id()
    user_id = session.get('student_id')
    username = session.get('username')
    full_name = session.get('full_name', '未知用户')
    
    current_app.logger.info(f"用户登出 - 用户: {username} ({full_name}), 学号: {user_id}, IP: {request.remote_addr}")
    
    logout_user()
    session.clear()

    if demo_run_id:
        db.session.remove()
        demo_data_removed = True
        try:
            demo_data_removed = destroy_demo_run(demo_run_id)
        except Exception:
            current_app.logger.exception('公开体验临时库清理失败')
            demo_data_removed = False
        if demo_data_removed:
            flash('本次体验已结束，体验数据已清除', 'info')
        else:
            flash('本次体验已结束，临时数据将在后台完成清理', 'warning')
        return redirect(url_for('auth.login'))
    
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
