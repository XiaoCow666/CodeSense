"""邮箱注册验证令牌、限流和邮件发送服务。"""

import hashlib
import html
import secrets
from datetime import datetime, timedelta

from flask import current_app, url_for

from models import EmailVerificationToken, User, db
from services.password_reset import SMTPMailer


def _token_digest(raw_token):
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


def _token_ttl():
    value = current_app.config.get('EMAIL_VERIFICATION_TOKEN_TTL_MINUTES', 30)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 30
    return max(5, min(value, 1440))


def email_verification_ttl_minutes():
    """返回当前邮箱验证令牌的有效分钟数。"""
    return _token_ttl()


def _request_interval():
    value = current_app.config.get('EMAIL_VERIFICATION_REQUEST_INTERVAL_SECONDS', 60)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 60
    return max(0, min(value, 86400))


def has_recent_email_verification_request(user, now=None):
    """检查账号是否处于验证邮件发送冷却期。"""
    now = now or datetime.utcnow()
    threshold = now - timedelta(seconds=_request_interval())
    return EmailVerificationToken.query.filter(
        EmailVerificationToken.user_id == user.student_id,
        EmailVerificationToken.created_at >= threshold,
        EmailVerificationToken.expires_at > now,
        EmailVerificationToken.used_at.is_(None),
        EmailVerificationToken.revoked_at.is_(None),
    ).first() is not None


def create_email_verification_token(user, requested_ip=None):
    """创建邮箱验证令牌并使该账号之前的令牌失效。"""
    now = datetime.utcnow()
    EmailVerificationToken.query.filter(
        EmailVerificationToken.user_id == user.student_id,
        EmailVerificationToken.used_at.is_(None),
        EmailVerificationToken.revoked_at.is_(None),
    ).update({'revoked_at': now}, synchronize_session=False)

    raw_token = secrets.token_urlsafe(32)
    record = EmailVerificationToken(
        user_id=user.student_id,
        token_hash=_token_digest(raw_token),
        created_at=now,
        expires_at=now + timedelta(minutes=_token_ttl()),
        requested_ip=(requested_ip or '')[:45] or None,
    )
    db.session.add(record)
    db.session.commit()
    return raw_token


def revoke_email_verification_token(raw_token):
    """撤销未使用的邮箱验证令牌，例如邮件投递失败时。"""
    if not raw_token:
        return False
    record = EmailVerificationToken.query.filter_by(
        token_hash=_token_digest(raw_token)
    ).first()
    if not record or record.used_at or record.revoked_at:
        return False
    record.revoked_at = datetime.utcnow()
    db.session.commit()
    return True


def get_valid_email_verification_token(raw_token, lock=False):
    """获取仍可使用的邮箱验证令牌。"""
    raw_token = (raw_token or '').strip()
    if not raw_token or len(raw_token) > 256:
        return None

    query = EmailVerificationToken.query.filter_by(
        token_hash=_token_digest(raw_token)
    )
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


def consume_email_verification_token(raw_token):
    """消费一次性邮箱验证令牌并标记账号已验证。"""
    record = get_valid_email_verification_token(raw_token, lock=True)
    if not record:
        return None

    user = db.session.get(User, record.user_id)
    if not user:
        return None

    now = datetime.utcnow()
    user.email_verified_at = now
    user.email_verification_required = False
    record.used_at = now
    EmailVerificationToken.query.filter(
        EmailVerificationToken.user_id == user.student_id,
        EmailVerificationToken.id != record.id,
        EmailVerificationToken.used_at.is_(None),
        EmailVerificationToken.revoked_at.is_(None),
    ).update({'revoked_at': now}, synchronize_session=False)
    db.session.commit()
    return user


def build_email_verification_url(raw_token):
    """生成使用配置域名的绝对邮箱验证链接。"""
    path = url_for('auth.verify_email', token=raw_token)
    base_url = (current_app.config.get('APP_BASE_URL') or '').strip().rstrip('/')
    if base_url:
        return f'{base_url}{path}'
    return url_for('auth.verify_email', token=raw_token, _external=True)


def send_email_verification_email(user, raw_token):
    """向新账号发送邮箱验证邮件。"""
    if not user.email:
        raise ValueError('邮箱注册账号缺少邮箱地址')

    verification_url = build_email_verification_url(raw_token)
    ttl_minutes = email_verification_ttl_minutes()
    subject = 'CodeSense 酷森思邮箱验证'
    text_body = (
        '您好，欢迎注册 CodeSense 酷森思。\n\n'
        f'请在 {ttl_minutes} 分钟内打开下面的链接验证邮箱：\n'
        f'{verification_url}\n\n'
        '如果这不是您本人操作，请忽略此邮件。'
    )
    safe_url = html.escape(verification_url, quote=True)
    html_body = (
        '<p>您好，欢迎注册 CodeSense 酷森思。</p>'
        f'<p>请在 {ttl_minutes} 分钟内点击下面的按钮验证邮箱：</p>'
        f'<p><a href="{safe_url}">验证邮箱</a></p>'
        '<p>如果这不是您本人操作，请忽略此邮件。</p>'
    )
    mailer = current_app.extensions.get('codesense_mailer') or SMTPMailer()
    mailer.send(user.email, subject, text_body, html_body)
    return verification_url
