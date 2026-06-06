from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest
from django.contrib.auth.models import User
from django.test import Client

from easyauth.applications.models import App, AppMembership
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-ops3"
AUDIT_LOGS_API_URL: Final = "/console/api/v1/audit-logs"


def test_ops3_owner_can_query_owned_app_audit_logs_with_app_key_filter() -> None:
    # Given: owner 只拥有 CRM App, 审计日志中同时存在其他 App 记录。
    client = _logged_in_user("ops3-audit-owner")
    crm = _owned_app("ops3-owner-audit-crm", "ops3-audit-owner")
    erp = App.objects.create(app_key="ops3-owner-audit-erp", name="ERP")
    _audit_log(app_key=crm.app_key, event_type="permission_template_imported")
    _audit_log(app_key=erp.app_key, event_type="emergency_revoke_applied")

    # When: owner 使用 app_key 查询自己 App 的审计日志。
    response = client.get(AUDIT_LOGS_API_URL, {"app_key": crm.app_key})

    # Then: API 只返回 owner 所属 App 的审计记录。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert crm.app_key in body
    assert erp.app_key not in body
    assert "permission_template_imported" in body
    assert "emergency_revoke_applied" not in body


def test_ops3_owner_cannot_query_unowned_app_audit_logs() -> None:
    # Given: owner 只拥有 CRM App, 另一个 ERP App 有审计日志。
    client = _logged_in_user("ops3-audit-owner-scope")
    _ = _owned_app("ops3-owner-scope-crm", "ops3-audit-owner-scope")
    erp = App.objects.create(app_key="ops3-owner-scope-erp", name="ERP")
    _audit_log(app_key=erp.app_key, event_type="permission_template_imported")

    # When: owner 使用其他 App 的 app_key 查询审计日志。
    response = client.get(AUDIT_LOGS_API_URL, {"app_key": erp.app_key})

    # Then: API 拒绝越权查询且不泄露目标审计内容。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert erp.app_key not in body
    assert "permission_template_imported" not in body


def test_ops3_developer_cannot_query_app_audit_logs() -> None:
    # Given: developer 可查看 App 接入资料, 但不是 owner。
    client = _logged_in_user("ops3-audit-developer")
    app = App.objects.create(app_key="ops3-developer-audit-app", name="Developer App")
    _ = AppMembership.objects.create(app=app, user_id="ops3-audit-developer", role="developer")
    _audit_log(app_key=app.app_key, event_type="permission_template_imported")

    # When: developer 查询该 App 审计日志。
    response = client.get(AUDIT_LOGS_API_URL, {"app_key": app.app_key})

    # Then: API 拒绝非 owner 查询。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert app.app_key not in body
    assert "permission_template_imported" not in body


def test_ops3_superuser_can_query_global_audit_logs_without_app_key_filter() -> None:
    # Given: 系统管理员面对多个 App 的审计日志。
    client = _logged_in_superuser("ops3-audit-global-admin")
    _audit_log(app_key="ops3-global-audit-crm", event_type="permission_template_imported")
    _audit_log(app_key="ops3-global-audit-erp", event_type="emergency_revoke_applied")

    # When: 系统管理员不带 app_key 查询全局审计日志。
    response = client.get(AUDIT_LOGS_API_URL)

    # Then: API 保持系统管理员全局审计视图。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "ops3-global-audit-crm" in body
    assert "ops3-global-audit-erp" in body


def _owned_app(app_key: str, owner_user_id: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=owner_user_id, role="owner")
    return app


def _audit_log(*, app_key: str, event_type: str) -> None:
    _ = AuditLog.objects.create(
        actor_type="user",
        actor_id="owner",
        event_type=event_type,
        target_type="app",
        target_id=app_key,
        metadata={"app_key": app_key},
    )


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _logged_in_user(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client
