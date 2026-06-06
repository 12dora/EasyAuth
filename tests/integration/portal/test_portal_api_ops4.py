from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.access_requests.models import (
    AccessRequest,
    AccessRequestPermission,
    AccessRequestRole,
)
from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App, ApprovalRule, Permission, Role
from easyauth.grants.models import (
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantPermission,
    AccessGrantRole,
)
from tests.integration.portal.json_helpers import json_object

pytestmark = pytest.mark.django_db

REQUESTS_API_URL: Final = "/portal/api/v1/me/access-requests"


@pytest.mark.parametrize("request_type", ["change", "revoke", "renew"])
def test_ops4_portal_api_submits_lifecycle_request_for_session_user(
    request_type: str,
) -> None:
    # Given: 当前员工已有当前授权, 并为生命周期目标角色配置了审批规则。
    client, user = _logged_in_client(f"ops4-lifecycle-{request_type}-user")
    app = App.objects.create(app_key=f"ops4-lifecycle-{request_type}", name="OPS4 CRM")
    keep_role = _requestable_role(app=app, key="viewer")
    old_role = _requestable_role(app=app, key="operator")
    new_role = _requestable_role(app=app, key="auditor")
    current_grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=timezone.now() + timedelta(days=7),
    )
    _ = AccessGrantRole.objects.create(grant=current_grant, role=keep_role)
    _ = AccessGrantRole.objects.create(grant=current_grant, role=old_role)
    expected_role_keys = _role_keys_for_lifecycle(
        request_type=request_type,
        keep_role=keep_role,
        old_role=old_role,
        new_role=new_role,
    )
    payload = _lifecycle_payload(
        app_key=app.app_key,
        request_type=request_type,
        role_keys=expected_role_keys,
    )

    # When: 员工提交 change、revoke 或 renew 申请。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(payload),
        content_type="application/json",
    )

    # Then: API 只为当前 session 用户创建对应生命周期申请, 不直接改写当前授权。
    access_request = AccessRequest.objects.get(user=user, app=app)
    role_keys = tuple(
        AccessRequestRole.objects.filter(access_request=access_request)
        .order_by("role__key")
        .values_list("role__key", flat=True),
    )
    assert response.status_code == HTTPStatus.CREATED
    assert access_request.request_type == request_type
    assert role_keys == tuple(sorted(expected_role_keys))
    assert AccessGrant.objects.get(id=current_grant.id).is_current is True


def test_ops4_portal_api_rejects_lifecycle_requester_spoofing() -> None:
    # Given: 登录员工尝试在生命周期申请 JSON 中伪造 requester。
    client, user = _logged_in_client("ops4-lifecycle-spoof-user")
    app = App.objects.create(app_key="ops4-lifecycle-spoof", name="OPS4 Spoof")
    role = _requestable_role(app=app, key="viewer")
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantRole.objects.create(grant=grant, role=role)

    # When: 员工提交包含 requester_user_id 的 change 申请。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            {
                **_lifecycle_payload(
                    app_key=app.app_key,
                    request_type="change",
                    role_keys=(role.key,),
                ),
                "requester_user_id": "ops4-other-user",
            },
        ),
        content_type="application/json",
    )

    # Then: API 拒绝请求体伪造 requester, 且不创建申请。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert AccessRequest.objects.count() == 0


@pytest.mark.parametrize("request_type", ["change", "revoke", "renew"])
def test_ops4_portal_api_rejects_lifecycle_request_for_other_user_grant(
    request_type: str,
) -> None:
    # Given: 当前员工没有目标应用授权, 只有另一个员工有当前授权。
    client, _user = _logged_in_client("ops4-lifecycle-cross-user")
    other_user = UserMirror.objects.create(authentik_user_id="ops4-lifecycle-owner")
    app = App.objects.create(app_key="ops4-lifecycle-cross", name="OPS4 Cross")
    role = _requestable_role(app=app, key="viewer")
    other_grant = AccessGrant.objects.create(user=other_user, app=app)
    _ = AccessGrantRole.objects.create(grant=other_grant, role=role)

    # When: 当前员工尝试对该应用提交生命周期申请。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            _lifecycle_payload(
                app_key=app.app_key,
                request_type=request_type,
                role_keys=(role.key,),
            ),
        ),
        content_type="application/json",
    )

    # Then: API 要求生命周期申请依赖当前员工自己的当前授权。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert AccessRequest.objects.count() == 0


def test_ops4_portal_api_rejects_lifecycle_extra_fields() -> None:
    # Given: 当前员工已有当前授权。
    client, user = _logged_in_client("ops4-lifecycle-extra-user")
    app = App.objects.create(app_key="ops4-lifecycle-extra", name="OPS4 Extra")
    role = _requestable_role(app=app, key="viewer")
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantRole.objects.create(grant=grant, role=role)

    # When: 员工提交包含未声明字段的 revoke 申请。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            {
                **_lifecycle_payload(
                    app_key=app.app_key,
                    request_type="revoke",
                    role_keys=(role.key,),
                ),
                "unexpected": "field",
            },
        ),
        content_type="application/json",
    )

    # Then: API 保持严格请求体边界, 不接受 extra fields。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert AccessRequest.objects.count() == 0


def test_ops4_portal_api_accepts_empty_role_keys_for_full_revoke() -> None:
    # Given: 当前员工已有当前授权, 想主动撤销整个 App 授权。
    client, user = _logged_in_client("ops4-lifecycle-full-revoke-user")
    app = App.objects.create(app_key="ops4-lifecycle-full-revoke", name="OPS4 Full Revoke")
    role = _requestable_role(app=app, key="viewer")
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantRole.objects.create(grant=grant, role=role)

    # When: 员工提交 role_keys 为空的 revoke 申请。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            _lifecycle_payload(
                app_key=app.app_key,
                request_type="revoke",
                role_keys=(),
            ),
        ),
        content_type="application/json",
    )

    # Then: API 创建全量撤销申请, 但不直接改写当前授权事实。
    access_request = AccessRequest.objects.get(user=user, app=app)
    assert response.status_code == HTTPStatus.CREATED
    assert access_request.request_type == "revoke"
    assert AccessRequestRole.objects.filter(access_request=access_request).count() == 0
    assert AccessGrant.objects.get(id=grant.id).is_current is True


def test_ops4_portal_api_submits_lifecycle_request_with_permission_keys() -> None:
    # Given: 当前员工已有 direct Permission 授权, 目标权限配置了审批规则。
    client, user = _logged_in_client("ops4-lifecycle-permission-user")
    app = App.objects.create(app_key="ops4-lifecycle-permission", name="OPS4 Permission")
    old_permission = _requestable_permission(app=app, key="invoice.read")
    new_permission = _requestable_permission(app=app, key="invoice.write")
    current_grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantPermission.objects.create(grant=current_grant, permission=old_permission)

    # When: 员工提交只包含 permission_keys 的 change 申请。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            _lifecycle_payload(
                app_key=app.app_key,
                request_type="change",
                role_keys=(),
                permission_keys=(new_permission.key,),
            ),
        ),
        content_type="application/json",
    )

    # Then: API 创建 direct Permission 目标申请, 不要求角色目标。
    access_request = AccessRequest.objects.get(user=user, app=app)
    permission_keys = tuple(
        AccessRequestPermission.objects.filter(access_request=access_request).values_list(
            "permission__key",
            flat=True,
        ),
    )
    response_item = json_object(response)["access_request"]
    assert isinstance(response_item, dict), response.content.decode()
    assert response.status_code == HTTPStatus.CREATED
    assert response_item["permissions"] == [new_permission.key]
    assert response_item["permission_names"] == [new_permission.name]
    assert access_request.request_type == "change"
    assert permission_keys == (new_permission.key,)
    assert AccessRequestRole.objects.filter(access_request=access_request).count() == 0
    assert AccessGrant.objects.get(id=current_grant.id).is_current is True


def _logged_in_client(authentik_user_id: str) -> tuple[Client, UserMirror]:
    client = Client()
    user = UserMirror.objects.create(
        authentik_user_id=authentik_user_id,
        name="门户用户",
        status=USER_STATUS_ACTIVE,
    )
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
    return client, user


def _requestable_role(*, app: App, key: str) -> Role:
    role = Role.objects.create(app=app, key=key, name=key, requestable=True)
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])
    return role


def _requestable_permission(*, app: App, key: str) -> Permission:
    permission = Permission.objects.create(app=app, key=key, name=key)
    _ = ApprovalRule.objects.create(
        app=app,
        permission=permission,
        approver_userids=["manager-001"],
    )
    return permission


def _lifecycle_payload(
    *,
    app_key: str,
    request_type: str,
    role_keys: tuple[str, ...],
    permission_keys: tuple[str, ...] = (),
) -> dict[str, str | list[str] | None]:
    return {
        "app_key": app_key,
        "request_type": request_type,
        "role_keys": list(role_keys),
        "permission_keys": list(permission_keys),
        "grant_type": GRANT_TYPE_TIMED,
        "grant_expires_at": (timezone.now() + timedelta(days=30)).isoformat(),
        "reason": f"提交 {request_type} 申请",
    }


def _role_keys_for_lifecycle(
    *,
    request_type: str,
    keep_role: Role,
    old_role: Role,
    new_role: Role,
) -> tuple[str, ...]:
    match request_type:
        case "change":
            return (new_role.key,)
        case "revoke":
            return (keep_role.key,)
        case "renew":
            return (keep_role.key, old_role.key)
        case _:
            raise AssertionError(request_type)
