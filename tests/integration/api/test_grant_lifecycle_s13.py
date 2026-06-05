from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from re import escape, findall, search
from typing import Final, Protocol

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.admin_console.grants import emergency_revoke_for_user
from easyauth.applications.models import App, Permission
from easyauth.applications.services import StaticTokenService
from easyauth.grants.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantPermission,
)
from easyauth.tasks.grants import cleanup_expired_grants

pytestmark = pytest.mark.django_db

EXPIRED_VERSION: Final = 2


class HttpResponseLike(Protocol):
    status_code: int
    content: bytes


def test_s13_permission_query_returns_empty_after_expiration_cleanup() -> None:
    # Given: 应用 token 可查询一个已经到期但尚未清理的 timed grant。
    now = timezone.now()
    user = UserMirror.objects.create(authentik_user_id="s13-api-expired-user")
    app = App.objects.create(app_key="s13-api-expired-app", name="S13 API Expired App")
    issue = StaticTokenService.create_token(app=app, name="S13 API integration")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=now - timedelta(seconds=1),
    )
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission)

    # When: 定时清理运行后, 应用再次查询该用户权限。
    result = cleanup_expired_grants(now=now)
    response = Client().get(
        f"/api/v1/apps/{app.app_key}/users/{user.authentik_user_id}/permissions",
        HTTP_AUTHORIZATION=f"Bearer {issue.plaintext_token}",
    )

    # Then: 查询结果为空权限, 但保留撤权后的版本号。
    assert result.expired_count == 1
    assert response.status_code == HTTPStatus.OK
    assert _json_string_array(response, "roles") == []
    assert _json_string_array(response, "permissions") == []
    assert _json_int(response, "version") == EXPIRED_VERSION


def test_s13_permission_query_returns_empty_after_emergency_revoke() -> None:
    # Given: 应用 token 可查询一个 active permanent grant。
    user = UserMirror.objects.create(authentik_user_id="s13-api-revoked-user")
    app = App.objects.create(app_key="s13-api-revoked-app", name="S13 API Revoked App")
    issue = StaticTokenService.create_token(app=app, name="S13 revoke integration")
    permission = Permission.objects.create(app=app, key="order.read", name="Read orders")
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
    )
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission)

    # When: 管理员执行紧急撤权后, 应用再次查询该用户权限。
    result = emergency_revoke_for_user(
        user=user,
        reason="suspected_compromise",
        actor_id="security-admin",
    )
    response = Client().get(
        f"/api/v1/apps/{app.app_key}/users/{user.authentik_user_id}/permissions",
        HTTP_AUTHORIZATION=f"Bearer {issue.plaintext_token}",
    )

    # Then: 查询结果为空权限, 但保留撤权后的版本号。
    assert result.revoked_count == 1
    assert response.status_code == HTTPStatus.OK
    assert _json_string_array(response, "roles") == []
    assert _json_string_array(response, "permissions") == []
    assert _json_int(response, "version") == EXPIRED_VERSION


def _json_string_array(response: HttpResponseLike, key: str) -> list[str]:
    array_content = _json_field_match(response, key, r'"{key}"\s*:\s*\[(.*?)\]')
    return findall(r'"([^"]*)"', array_content)


def _json_int(response: HttpResponseLike, key: str) -> int:
    return int(_json_field_match(response, key, r'"{key}"\s*:\s*(\d+)'))


def _json_field_match(response: HttpResponseLike, key: str, pattern: str) -> str:
    match search(pattern.format(key=escape(key)), response.content.decode()):
        case None:
            raise AssertionError(response.content.decode())
        case result:
            return result.group(1)
