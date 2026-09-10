"""密码重置令牌、邮件投递和账号查找服务。"""

import hashlib
import html
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage

from flask import current_app, url_for

from models import PasswordResetToken, User, db


class MailConfigurationError(RuntimeError):
    """邮件服务未配置完整。"""


class SMTPMailer:
    """使用标准库发送密码重置邮件。"""

    def send(self, recipient, subject, text_body, html_body=None):
        server = (current_app.config.get('MAIL_SERVER') or '').strip()
        username = (current_app.config.get('MAIL_USERNAME') or '').strip()
        password = current_app.config.get('MAIL_PASSWORD') or ''
        sender = (current_app.config.get('MAIL_DEFAULT_SENDER') or username).strip()
        if not server or not sender:
            raise MailConfigurationError('邮件服务尚未配置')

        message = EmailMessage()
        message['Subject'] = subject
        message['From'] = sender
        message['To'] = recipient
        message.set_content(text_body)
        if html_body:
            message.add_alternative(html_body, subtype='html')

        port = int(current_app.config.get('MAIL_PORT', 587))
        timeout = int(current_app.config.get('MAIL_TIMEOUT_SECONDS', 10))
        use_ssl = bool(current_app.config.get('MAIL_USE_SSL', False))
        use_tls = bool(current_app.config.get('MAIL_USE_TLS', True)) and not use_ssl
        smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP

        with smtp_class(server, port, timeout=timeout) as smtp:
            smtp.ehlo()
            if use_tls:
                smtp.starttls()
                smtp.ehlo()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)


def _token_digest(raw_token):
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


def _token_ttl():
    value = current_app.config.get('PASSWORD_RESET_TOKEN_TTL_MINUTES', 30)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 30
    return max(5, min(value, 1440))


def password_reset_ttl_minutes():
    """返回当前密码重置令牌的有效分钟数，供页面文案复用。"""
    return _token_ttl()


def _request_interval():
    value = current_app.config.get('PASSWORD_RESET_REQUEST_INTERVAL_SECONDS', 60)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 60
    return max(0, min(value, 86400))


def find_user_by_identifier(identifier):
    """按用户名、学号、内部账号 ID 或邮箱查找用户。"""
    identifier = (identifier or '').strip()
    if not identifier:
        return None
    normalized_email = identifier.lower()
    return User.query.filter(
        db.or_(
            User.username == identifier,
            User.student_id == identifier,
            User.student_number == identifier,
            db.func.lower(User.email) == normalized_email,
        )
    ).first()


def has_recent_reset_request(user, now=None):
    """检查账号是否处于重置请求冷却期。"""
    now = now or datetime.utcnow()
    threshold = now - timedelta(seconds=_request_interval())
    return PasswordResetToken.query.filter(
        PasswordResetToken.user_id == user.student_id,
        PasswordResetToken.created_at >= threshold,
        PasswordResetToken.expires_at > now,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.revoked_at.is_(None),
    ).first() is not None


def create_password_reset_token(user, requested_ip=None, created_by=None):
    """创建令牌并使该账号之前未使用的令牌失效。"""
    now = datetime.utcnow()
    PasswordResetToken.query.filter(
        PasswordResetToken.user_id == user.student_id,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.revoked_at.is_(None),
    ).update({'revoked_at': now}, synchronize_session=False)

    raw_token = secrets.token_urlsafe(32)
    record = PasswordResetToken(
        user_id=user.student_id,
        token_hash=_token_digest(raw_token),
        created_at=now,
        expires_at=now + timedelta(minutes=_token_ttl()),
        requested_ip=(requested_ip or '')[:45] or None,
        created_by=created_by,
    )
    db.session.add(record)
    db.session.commit()
    return raw_token


def revoke_password_reset_token(raw_token):
    """撤销未使用的令牌，例如邮件投递失败时。"""
    if not raw_token:
        return False
    record = PasswordResetToken.query.filter_by(
        token_hash=_token_digest(raw_token)
    ).first()
    if not record or record.used_at or record.revoked_at:
        return False
    record.revoked_at = datetime.utcnow()
    db.session.commit()
    return True


def get_valid_password_reset_token(raw_token, lock=False):
    """获取仍可使用的重置令牌。"""
    raw_token = (raw_token or '').strip()
    if not raw_token or len(raw_token) > 256:
        return None

    query = PasswordResetToken.query.filter_by(token_hash=_token_digest(raw_token))
    if lock:
        query = query.with_for_update()
    record = query.first()
    now = datetime.utcnow()
    if (
        not record
        or record.used_at is not None
        or record.revoked_at is not None
        or record.expires_at <= now
    ):
        return None
    return record


def consume_password_reset_token(raw_token, new_password):
    """消费一次性令牌并更新密码；失败时返回 None。"""
    record = get_valid_password_reset_token(raw_token, lock=True)
    if not record:
        return None

    user = db.session.get(User, record.user_id)
    if not user:
        return None

    now = datetime.utcnow()
    user.password = new_password
    user.password_changed_at = now
    # 使重置前的所有已登录会话失效，避免旧会话继续使用。
    user.current_session_id = None
    record.used_at = now
    PasswordResetToken.query.filter(
        PasswordResetToken.user_id == user.student_id,
        PasswordResetToken.id != record.id,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.revoked_at.is_(None),
    ).update({'revoked_at': now}, synchronize_session=False)
    db.session.commit()
    return user


def build_password_reset_url(raw_token):
    """生成使用配置域名的绝对重置链接。"""
    path = url_for('auth.reset_password', token=raw_token)
    base_url = (current_app.config.get('APP_BASE_URL') or '').strip().rstrip('/')
    if base_url:
        return f'{base_url}{path}'
    return url_for('auth.reset_password', token=raw_token, _external=True)


def send_password_reset_email(user, raw_token):
    """向用户绑定邮箱发送重置链接。"""
    reset_url = build_password_reset_url(raw_token)
    ttl_minutes = password_reset_ttl_minutes()
    subject = 'CodeSense 酷森思密码重置'
    text_body = (
        '您好，\n\n'
        f'我们收到了您的密码重置请求。请在 {ttl_minutes} 分钟内打开下面的链接设置新密码：\n'
        f'{reset_url}\n\n'
        '如果这不是您本人操作，请忽略此邮件。'
    )
    safe_url = html.escape(reset_url, quote=True)
    html_body = (
        '<p>您好，</p>'
        f'<p>我们收到了您的密码重置请求，请在 {ttl_minutes} 分钟内点击下面的按钮设置新密码：</p>'
        f'<p><a href="{safe_url}">重置密码</a></p>'
        '<p>如果这不是您本人操作，请忽略此邮件。</p>'
    )
    mailer = current_app.extensions.get('codesense_mailer') or SMTPMailer()
    mailer.send(user.email, subject, text_body, html_body)
    return reset_url
