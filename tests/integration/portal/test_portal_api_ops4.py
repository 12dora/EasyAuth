from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    AccessRequest,
    AccessRequestGroup,
    AccessRequestPermission,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, ApprovalRule, AppScope, AuthorizationGroup, Permission
from easyauth.grants.models import (
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from tests.integration.portal.helpers import logged_in_client
from tests.integration.portal.json_helpers import json_object

pytestmark = pytest.mark.django_db

REQUESTS_API_URL: Final = "/portal/api/v1/me/access-requests"
DEFAULT_SCOPE_KEY: Final = "GLOBAL"


@pytest.mark.parametrize("request_type", ["change", "revoke", "renew"])
def test_ops4_portal_api_submits_lifecycle_request_for_session_user(
    request_type: str,
) -> None:
    # Given: 当前员工已有当前授权, 并配置生命周期目标授权组。
    client, user = logged_in_client(f"ops4-lifecycle-{request_type}-user")
    app = App.objects.create(app_key=f"ops4-lifecycle-{request_type}", name="OPS4 CRM")
    keep_group = _requestable_group(app=app, key="viewer")
    old_group = _requestable_group(app=app, key="operator")
    new_group = _requestable_group(app=app, key="auditor")
    current_grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=timezone.now() + timedelta(days=7),
    )
    _ = AccessGrantGroup.objects.create(grant=current_grant, authorization_group=keep_group)
    _ = AccessGrantGroup.objects.create(grant=current_grant, authorization_group=old_group)
    expected_group_keys = _group_keys_for_lifecycle(
        request_type=request_type,
        keep_group=keep_group,
        old_group=old_group,
        new_group=new_group,
    )
    payload = _lifecycle_payload(
        app_key=app.app_key,
        request_type=request_type,
        authorization_group_keys=expected_group_keys,
    )

    # When: 员工提交 change、revoke 或 renew 申请。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(payload),
        content_type="application/json",
    )

    # Then: API 只为当前 session 用户创建对应生命周期申请, 不直接改写当前授权。
    access_request = AccessRequest.objects.get(user=user, app=app)
    group_keys = tuple(
        AccessRequestGroup.objects.filter(access_request=access_request)
        .order_by("authorization_group__key")
        .values_list("authorization_group__key", flat=True),
    )
    assert response.status_code == HTTPStatus.CREATED
    assert access_request.request_type == request_type
    assert group_keys == tuple(sorted(expected_group_keys))
    assert AccessGrant.objects.get(id=current_grant.id).is_current is True


def test_ops4_portal_api_rejects_lifecycle_requester_spoofing() -> None:
    # Given: 登录员工尝试在生命周期申请 JSON 中伪造 requester。
    client, user = logged_in_client("ops4-lifecycle-spoof-user")
    app = App.objects.create(app_key="ops4-lifecycle-spoof", name="OPS4 Spoof")
    group = _requestable_group(app=app, key="viewer")
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=group)

    # When: 员工提交包含 requester_user_id 的 change 申请。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            {
                **_lifecycle_payload(
                    app_key=app.app_key,
                    request_type="change",
                    authorization_group_keys=(group.key,),
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
    client, _user = logged_in_client("ops4-lifecycle-cross-user")
    other_user = UserMirror.objects.create(authentik_user_id="ops4-lifecycle-owner")
    app = App.objects.create(app_key="ops4-lifecycle-cross", name="OPS4 Cross")
    group = _requestable_group(app=app, key="viewer")
    other_grant = AccessGrant.objects.create(user=other_user, app=app)
    _ = AccessGrantGroup.objects.create(grant=other_grant, authorization_group=group)

    # When: 当前员工尝试对该应用提交生命周期申请。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            _lifecycle_payload(
                app_key=app.app_key,
                request_type=request_type,
                authorization_group_keys=(group.key,),
            ),
        ),
        content_type="application/json",
    )

    # Then: API 要求生命周期申请依赖当前员工自己的当前授权。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert AccessRequest.objects.count() == 0


def test_ops4_portal_api_rejects_lifecycle_extra_fields() -> None:
    # Given: 当前员工已有当前授权。
    client, user = logged_in_client("ops4-lifecycle-extra-user")
    app = App.objects.create(app_key="ops4-lifecycle-extra", name="OPS4 Extra")
    group = _requestable_group(app=app, key="viewer")
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=group)

    # When: 员工提交包含未声明字段的 revoke 申请。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            {
                **_lifecycle_payload(
                    app_key=app.app_key,
                    request_type="revoke",
                    authorization_group_keys=(group.key,),
                ),
                "unexpected": "field",
            },
        ),
        content_type="application/json",
    )

    # Then: API 保持严格请求体边界, 不接受 extra fields。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert AccessRequest.objects.count() == 0


def test_ops4_portal_api_accepts_empty_group_keys_for_full_revoke() -> None:
    # Given: 当前员工已有当前授权, 想主动撤销整个 App 授权。
    client, user = logged_in_client("ops4-lifecycle-full-revoke-user")
    app = App.objects.create(app_key="ops4-lifecycle-full-revoke", name="OPS4 Full Revoke")
    group = _requestable_group(app=app, key="viewer")
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=group)

    # When: 员工提交 authorization_group_keys 为空的 revoke 申请。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            _lifecycle_payload(
                    app_key=app.app_key,
                    request_type="revoke",
                    authorization_group_keys=(),
                ),
        ),
        content_type="application/json",
    )

    # Then: API 创建全量撤销申请, 但不直接改写当前授权事实。
    access_request = AccessRequest.objects.get(user=user, app=app)
    assert response.status_code == HTTPStatus.CREATED
    assert access_request.request_type == "revoke"
    assert AccessRequestGroup.objects.filter(access_request=access_request).count() == 0
    assert AccessGrant.objects.get(id=grant.id).is_current is True


def test_ops4_portal_api_submits_lifecycle_request_with_permission_keys() -> None:
    # Given: 当前员工已有 direct Permission 授权, 目标权限配置了审批规则。
    client, user = logged_in_client("ops4-lifecycle-permission-user")
    app = App.objects.create(app_key="ops4-lifecycle-permission", name="OPS4 Permission")
    old_permission = _requestable_permission(app=app, key="invoice.read")
    new_permission = _requestable_permission(app=app, key="invoice.write")
    current_grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantPermission.objects.create(
        grant=current_grant,
        permission=old_permission,
        scope_key=DEFAULT_SCOPE_KEY,
    )

    # When: 员工提交只包含 permission_keys 的 change 申请。
    response = client.post(
        REQUESTS_API_URL,
        data=dumps(
            _lifecycle_payload(
                app_key=app.app_key,
                request_type="change",
                authorization_group_keys=(),
                direct_grants=((new_permission.key, DEFAULT_SCOPE_KEY),),
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
    assert response_item["direct_grants"] == [
        {
            "permission": new_permission.key,
            "permission_name": new_permission.name,
            "scope": DEFAULT_SCOPE_KEY,
        },
    ]
    assert access_request.request_type == "change"
    assert permission_keys == (new_permission.key,)
    assert AccessRequestGroup.objects.filter(access_request=access_request).count() == 0
    assert AccessGrant.objects.get(id=current_grant.id).is_current is True


def _requestable_group(*, app: App, key: str) -> AuthorizationGroup:
    group = AuthorizationGroup.objects.create(
        app=app,
        key=key,
        kind="role",
        name=key,
        requestable=True,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    return group


def _requestable_permission(*, app: App, key: str) -> Permission:
    _ = AppScope.objects.get_or_create(app=app, key=DEFAULT_SCOPE_KEY, defaults={"name": "Global"})
    permission = Permission.objects.create(
        app=app,
        key=key,
        name=key,
        supported_scopes=[DEFAULT_SCOPE_KEY],
    )
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
    authorization_group_keys: tuple[str, ...],
    direct_grants: tuple[tuple[str, str], ...] = (),
) -> dict[str, str | list[str] | list[dict[str, str]] | None]:
    return {
        "app_key": app_key,
        "request_type": request_type,
        "authorization_group_keys": list(authorization_group_keys),
        "direct_grants": [
            {"permission": permission_key, "scope": scope_key}
            for permission_key, scope_key in direct_grants
        ],
        "grant_type": GRANT_TYPE_TIMED,
        "grant_expires_at": (timezone.now() + timedelta(days=30)).isoformat(),
        "reason": f"提交 {request_type} 申请",
    }


def _group_keys_for_lifecycle(
    *,
    request_type: str,
    keep_group: AuthorizationGroup,
    old_group: AuthorizationGroup,
    new_group: AuthorizationGroup,
) -> tuple[str, ...]:
    match request_type:
        case "change":
            return (new_group.key,)
        case "revoke":
            return (keep_group.key,)
        case "renew":
            return (keep_group.key, old_group.key)
        case _:
            raise AssertionError(request_type)
