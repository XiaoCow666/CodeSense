"""登录身份绑定服务，为邮箱之外的 OAuth/社交账号接入提供统一入口。"""

import hashlib

from sqlalchemy.exc import IntegrityError

from models import AuthIdentity, User, db


class AuthIdentityConflict(ValueError):
    """第三方身份已绑定到其他账号，或账号已有同类身份。"""


def _normalize_provider(provider):
    provider = (provider or '').strip().lower()
    if not provider or len(provider) > 32:
        raise ValueError('登录身份提供方无效')
    return provider


def _subject_hash(provider, provider_subject):
    provider = _normalize_provider(provider)
    provider_subject = str(provider_subject or '').strip()
    if not provider_subject:
        raise ValueError('第三方身份标识不能为空')
    return hashlib.sha256(
        f'{provider}:\0{provider_subject}'.encode('utf-8')
    ).hexdigest()


def find_user_by_identity(provider, provider_subject):
    """按提供方和第三方 subject 查找已绑定的用户。"""
    provider = _normalize_provider(provider)
    subject_hash = _subject_hash(provider, provider_subject)
    identity = AuthIdentity.query.filter_by(
        provider=provider,
        provider_subject_hash=subject_hash,
    ).first()
    return identity.user if identity else None


def bind_identity(user, provider, provider_subject, provider_email=None):
    """将第三方身份绑定到用户，避免身份被重复认领。"""
    if not isinstance(user, User):
        raise ValueError('待绑定用户无效')

    provider = _normalize_provider(provider)
    subject_hash = _subject_hash(provider, provider_subject)
    existing_identity = AuthIdentity.query.filter_by(
        provider=provider,
        provider_subject_hash=subject_hash,
    ).first()
    if existing_identity and existing_identity.user_id != user.student_id:
        raise AuthIdentityConflict('该第三方账号已绑定到其他用户')

    existing_provider = AuthIdentity.query.filter_by(
        user_id=user.student_id,
        provider=provider,
    ).first()
    if existing_provider and existing_provider.id != getattr(existing_identity, 'id', None):
        raise AuthIdentityConflict('该用户已绑定此登录方式')

    identity = existing_identity or existing_provider
    if identity:
        identity.provider_email = (provider_email or '').strip().lower() or None
    else:
        identity = AuthIdentity(
            user_id=user.student_id,
            provider=provider,
            provider_subject_hash=subject_hash,
            provider_email=(provider_email or '').strip().lower() or None,
        )
        db.session.add(identity)

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise AuthIdentityConflict('该第三方账号已被其他用户绑定') from exc
    return identity
