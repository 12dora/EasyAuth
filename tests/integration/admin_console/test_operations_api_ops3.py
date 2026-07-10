from __future__ import annotations

from http import HTTPStatus
from json import dumps
from re import search
from typing import TYPE_CHECKING, Final

import pytest
from django.test import Client, override_settings

from easyauth.access_requests.models import (
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_STATUS_SUBMITTED,
    AccessRequest,
    AccessRequestGroup,
)
from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, ApprovalRule, AuthorizationGroup
from easyauth.audit.models import AuditLog
from easyauth.grants.models import GRANT_STATUS_REVOKED, AccessGrant

if TYPE_CHECKING:
    from django.conf import LazySettings

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-ops3"
ACCESS_REQUESTS_API_URL: Final = "/console/api/v1/operations/access-requests"
ACCESS_GRANTS_API_URL: Final = "/console/api/v1/operations/access-grants"
EMERGENCY_REVOKES_API_URL: Final = "/console/api/v1/operations/emergency-revokes"
AUDIT_LOGS_API_URL: Final = "/console/api/v1/audit-logs"
DEPENDENCY_HEALTH_API_URL: Final = "/console/api/v1/operations/dependency-health"


@pytest.fixture(autouse=True)
def _console_superuser_groups(settings: LazySettings) -> None:  # pyright: ignore[reportUnusedFunction]
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)


def test_ops3_console_operations_api_filters_access_requests_and_grants() -> None:
    # Given: 系统管理员查看多个 App、用户和状态的申请/授权数据。
    client = _logged_in_superuser("ops3-operations-admin")
    user = UserMirror.objects.create(authentik_user_id="ops3-operations-user")
    crm = App.objects.create(app_key="ops3-operations-crm", name="CRM")
    erp = App.objects.create(app_key="ops3-operations-erp", name="ERP")
    failed_request = AccessRequest.objects.create(
        user=user,
        app=crm,
        status=REQUEST_STATUS_GRANT_FAILED,
        reason="CRM 授权失败",
        idempotency_key="ops3-crm-failed",
        payload_digest="a" * 64,
    )
    _ = AuditLog.objects.create(
        actor_type="admin",
        actor_id="ops3-operations-admin",
        event_type="grant_apply_failed",
        target_type="access_request",
        target_id=str(failed_request.id),
        metadata={"error": "目录写入失败"},
    )
    _ = AccessRequest.objects.create(
        user=user,
        app=erp,
        status=REQUEST_STATUS_SUBMITTED,
        reason="ERP 等待审批",
        idempotency_key="ops3-erp-submitted",
        payload_digest="b" * 64,
    )
    _ = AccessGrant.objects.create(user=user, app=crm)
    _ = AccessGrant.objects.create(
        user=user,
        app=erp,
        status=GRANT_STATUS_REVOKED,
        is_current=False,
    )

    # When: 管理员按 App 和状态筛选申请与授权。
    requests_response = client.get(
        ACCESS_REQUESTS_API_URL,
        {"app_key": crm.app_key, "status": REQUEST_STATUS_GRANT_FAILED},
    )
    grants_response = client.get(
        ACCESS_GRANTS_API_URL,
        {"app_key": crm.app_key, "status": "active"},
    )

    # Then: API 只返回匹配筛选条件的运营记录。
    requests_body = requests_response.content.decode()
    grants_body = grants_response.content.decode()
    assert requests_response.status_code == HTTPStatus.OK
    assert grants_response.status_code == HTTPStatus.OK
    assert "CRM 授权失败" in requests_body
    assert "目录写入失败" in requests_body
    assert "ERP 等待审批" not in requests_body
    assert crm.app_key in grants_body
    assert erp.app_key not in grants_body


def test_ops3_access_request_failure_reason_uses_latest_failure_event() -> None:
    # Given: 同一失败申请存在多次只追加的失败审计事实。
    client = _logged_in_superuser("ops3-failure-reason-admin")
    user = UserMirror.objects.create(authentik_user_id="ops3-failure-reason-user")
    app = App.objects.create(app_key="ops3-failure-reason-app", name="Failure App")
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_GRANT_FAILED,
        reason="申请原因",
        idempotency_key="ops3-failure-reason-request",
        payload_digest="c" * 64,
    )
    for error in ("旧失败原因", "最新失败原因"):
        _ = AuditLog.objects.create(
            actor_type="admin",
            actor_id="ops3-failure-reason-admin",
            event_type="grant_apply_failed",
            target_type="access_request",
            target_id=str(access_request.id),
            metadata={"error": error},
        )

    # When: 管理员查询失败申请。
    response = client.get(ACCESS_REQUESTS_API_URL, {"status": REQUEST_STATUS_GRANT_FAILED})

    # Then: 列表只暴露最新权威失败事实。
    assert response.status_code == HTTPStatus.OK
    assert response.json()["data"][0]["failure_reason"] == "最新失败原因"


@pytest.mark.parametrize("metadata", [{}, {"error": ""}, {"error": 42}])
def test_ops3_access_request_failure_reason_fails_on_invalid_contract(
    metadata: dict[str, object],
) -> None:
    # Given: 失败申请缺少合法的失败原因事实。
    client = _logged_in_superuser("ops3-invalid-failure-reason-admin")
    user = UserMirror.objects.create(authentik_user_id="ops3-invalid-failure-reason-user")
    app = App.objects.create(app_key="ops3-invalid-failure-reason-app", name="Failure App")
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_GRANT_FAILED,
        reason="申请原因",
        idempotency_key="ops3-invalid-failure-reason-request",
        payload_digest="d" * 64,
    )
    if metadata:
        _ = AuditLog.objects.create(
            actor_type="admin",
            actor_id="ops3-invalid-failure-reason-admin",
            event_type="grant_apply_failed",
            target_type="access_request",
            target_id=str(access_request.id),
            metadata=metadata,
        )

    # When: 管理员读取运营列表。
    response = client.get(ACCESS_REQUESTS_API_URL, {"status": REQUEST_STATUS_GRANT_FAILED})

    # Then: API 明确报告契约错误, 不伪造原因或静默省略字段。
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "授权失败原因事实缺失或无效。",
        "details": {"request_id": access_request.id},
    }


def test_ops3_console_emergency_revoke_requires_superuser_reason_and_csrf() -> None:
    # Given: 普通登录用户和系统管理员都尝试对当前授权执行紧急撤权。
    normal_client = _logged_in_user("ops3-normal-user")
    admin_client = _logged_in_superuser("ops3-emergency-admin", enforce_csrf_checks=True)
    target_user = UserMirror.objects.create(authentik_user_id="ops3-emergency-target")
    app = App.objects.create(app_key="ops3-emergency-app", name="Emergency CRM")
    grant = AccessGrant.objects.create(
        user=target_user,
        app=app,
    )
    csrf_token = _extract_csrf_token(
        admin_client.get(f"/console/apps/{app.app_key}/").content.decode(),
    )
    payload = {
        "user_id": target_user.authentik_user_id,
        "app_key": app.app_key,
        "reason": "安全事件应急",
    }

    # When: 普通用户、缺少 CSRF 的管理员、合法管理员分别提交紧急撤权。
    forbidden = normal_client.post(
        EMERGENCY_REVOKES_API_URL,
        data=dumps(payload),
        content_type="application/json",
    )
    missing_csrf = admin_client.post(
        EMERGENCY_REVOKES_API_URL,
        data=dumps(payload),
        content_type="application/json",
    )
    accepted = admin_client.post(
        EMERGENCY_REVOKES_API_URL,
        data=dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    # Then: 只有带 CSRF 的系统管理员可撤权, 且写入紧急撤权审计。
    grant.refresh_from_db()
    assert forbidden.status_code == HTTPStatus.FORBIDDEN
    assert missing_csrf.status_code == HTTPStatus.FORBIDDEN
    assert accepted.status_code == HTTPStatus.OK
    assert accepted.json()["status"] == "accepted"
    assert grant.status == GRANT_STATUS_REVOKED
    emergency_audit = AuditLog.objects.get(event_type="emergency_revoke_applied")
    assert emergency_audit.actor_id == "ops3-emergency-admin"
    assert emergency_audit.metadata["reason"] == "安全事件应急"
    assert emergency_audit.metadata["app_key"] == app.app_key


def test_ops3_console_emergency_revoke_rejects_empty_reason() -> None:
    # Given: 系统管理员准备提交缺少原因的紧急撤权请求。
    client = _logged_in_superuser("ops3-empty-reason-admin")
    target_user = UserMirror.objects.create(authentik_user_id="ops3-empty-reason-target")
    app = App.objects.create(app_key="ops3-empty-reason-app", name="Emergency CRM")
    _ = AccessGrant.objects.create(user=target_user, app=app)

    # When: 管理员提交空原因。
    response = client.post(
        EMERGENCY_REVOKES_API_URL,
        data=dumps(
            {
                "user_id": target_user.authentik_user_id,
                "app_key": app.app_key,
                "reason": "",
            },
        ),
        content_type="application/json",
    )

    # Then: API 拒绝请求且不撤销授权。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert AccessGrant.objects.get(user=target_user, app=app).status == "active"
    assert AuditLog.objects.count() == 0


def test_ops3_console_retry_grant_failed_applies_once_without_reincrementing_version() -> None:
    # Given: 系统管理员面对一条 grant_failed 申请, 目标用户还没有当前授权。
    client = _logged_in_superuser("ops3-retry-admin")
    target_user = UserMirror.objects.create(authentik_user_id="ops3-retry-target")
    app = App.objects.create(app_key="ops3-retry-app", name="Retry CRM")
    group = AuthorizationGroup.objects.create(app=app, key="auditor", kind="role", name="审计员")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    access_request = AccessRequest.objects.create(
        user=target_user,
        app=app,
        status=REQUEST_STATUS_GRANT_FAILED,
        reason="首次授权落库失败",
        idempotency_key="ops3-retry-request",
        payload_digest="e" * 64,
    )
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)

    # When: 管理员执行重试, 随后对已处理申请重复重试。
    first = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "修复后重试"}),
        content_type="application/json",
    )
    repeated = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "重复提交"}),
        content_type="application/json",
    )

    # Then: 第一次重试创建授权并更新申请, 重复重试作为 no-op 成功返回。
    access_request.refresh_from_db()
    grant = AccessGrant.objects.get(user=target_user, app=app)
    assert first.status_code == HTTPStatus.OK
    assert repeated.status_code == HTTPStatus.OK
    assert repeated.json() == {
        "request_id": access_request.id,
        "grant_id": grant.id,
        "version": 1,
        "status": REQUEST_STATUS_GRANT_APPLIED,
    }
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED
    assert AccessGrant.objects.filter(user=target_user, app=app).count() == 1
    assert grant.version == 1
    assert AuditLog.objects.filter(event_type="access_request_grant_retry_applied").count() == 1


def test_ops3_console_audit_logs_api_filters_event_type_and_app_key() -> None:
    # Given: 系统管理员需要筛选指定 App 和事件类型的审计日志。
    client = _logged_in_superuser("ops3-audit-admin")
    _ = AuditLog.objects.create(
        actor_type="user",
        actor_id="owner",
        event_type="permission_template_imported",
        target_type="app",
        target_id="crm",
        metadata={"app_key": "ops3-audit-crm", "version": 1},
    )
    _ = AuditLog.objects.create(
        actor_type="user",
        actor_id="owner",
        event_type="permission_template_imported",
        target_type="app",
        target_id="erp",
        metadata={"app_key": "ops3-audit-erp", "version": 1},
    )
    _ = AuditLog.objects.create(
        actor_type="admin",
        actor_id="security",
        event_type="emergency_revoke_applied",
        target_type="app",
        target_id="crm",
        metadata={"app_key": "ops3-audit-crm", "reason": "security"},
    )

    # When: 管理员按 app_key 和 event_type 查询审计日志。
    response = client.get(
        AUDIT_LOGS_API_URL,
        {"app_key": "ops3-audit-crm", "event_type": "permission_template_imported"},
    )

    # Then: API 只返回匹配的审计记录。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "ops3-audit-crm" in body
    assert "permission_template_imported" in body
    assert "ops3-audit-erp" not in body
    assert "emergency_revoke_applied" not in body


def test_ops3_console_dependency_health_is_read_only_and_secret_free() -> None:
    # Given: 系统管理员需要查看依赖健康状态摘要。
    client = _logged_in_superuser("ops3-health-admin")

    # When: 管理员读取 dependency health API。
    response = client.get(DEPENDENCY_HEALTH_API_URL)

    # Then: 响应包含核心依赖状态, 且不暴露 secret 类字段。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "authentik" in body
    assert "dingtalk" in body
    assert "celery" in body
    assert "secret" not in body.lower()
    assert "token" not in body.lower()


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_ops3_console_superuser_group_session_can_read_operations() -> None:
    # Given: Authentik session 中包含系统管理员组。
    client = _logged_in_superuser("ops3-group-admin")

    # When
    response = client.get(ACCESS_REQUESTS_API_URL)

    # Then
    assert response.status_code == HTTPStatus.OK


def _logged_in_superuser(
    username: str,
    *,
    enforce_csrf_checks: bool = False,
) -> Client:
    return _authentik_client(
        username,
        enforce_csrf_checks=enforce_csrf_checks,
        groups=("easyauth-admins",),
    )


def _logged_in_user(username: str) -> Client:
    return _authentik_client(username)


def _authentik_client(
    username: str,
    *,
    enforce_csrf_checks: bool = False,
    groups: tuple[str, ...] = (),
) -> Client:
    user, _created = UserMirror.objects.get_or_create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost", enforce_csrf_checks=enforce_csrf_checks)
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session["easyauth_authentik_groups"] = list(groups or ("EasyAuth Admins",))
    session.save()
    return client


def _extract_csrf_token(html: str) -> str:
    match = search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    if match is None:
        raise AssertionError(html)
    return match.group(1)
