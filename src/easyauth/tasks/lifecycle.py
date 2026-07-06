from __future__ import annotations

from celery import shared_task

from easyauth.accounts.models import UserMirror
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.integrations.authentik.admin_client import (
    AuthentikAdminClient,
    AuthentikAdminError,
    AuthentikAdminNotConfiguredError,
    AuthentikAdminUserNotFoundError,
)
from easyauth.lifecycle.services import DISABLE_ACCOUNT_TASK_NAME


@shared_task(
    name=DISABLE_ACCOUNT_TASK_NAME,
    autoretry_for=(AuthentikAdminError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def disable_departed_account_task(user_mirror_id: int) -> str:
    """离职禁号 + 吊销会话(§1.2): 调 Authentik 标准 API, 失败指数退避重试。"""
    user = UserMirror.objects.filter(id=user_mirror_id).first()
    if user is None:
        return "user_missing"
    try:
        result = AuthentikAdminClient.from_settings().disable_user_and_revoke_sessions(
            user.authentik_user_id,
        )
    except AuthentikAdminNotConfiguredError:
        # 管理 API 未配置属部署缺陷: 显式审计告警, 不静默吞掉安全动作。
        _record_disable_event(
            user,
            ok=False,
            detail="authentik_admin_not_configured",
        )
        return "not_configured"
    except AuthentikAdminUserNotFoundError:
        _record_disable_event(user, ok=False, detail="authentik_user_not_found")
        return "user_not_found"
    _record_disable_event(
        user,
        ok=True,
        detail=f"sessions_revoked={result.revoked_session_count}",
    )
    return "disabled"


def _record_disable_event(user: UserMirror, *, ok: bool, detail: str) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id="lifecycle",
            action="lifecycle_account_disabled" if ok else "lifecycle_account_disable_failed",
            target_type="user",
            target_id=user.authentik_user_id,
            metadata={"detail": detail},
        ),
    )
