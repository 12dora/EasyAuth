from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import JsonValue
from easyauth.applications.models import App, AppMembership, ManagedScopePolicy
from easyauth.integrations.authentik.directory_client import AuthentikDirectoryError
from easyauth.integrations.authentik.directory_payloads import DingTalkManagedUsers

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-managed-users-preview"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes

    def json(self) -> dict[str, object]: ...


class DirectoryClientStub:
    def __init__(self, managed_users: DingTalkManagedUsers | None = None) -> None:
        self.managed_users: DingTalkManagedUsers | None = managed_users
        self.calls: list[tuple[str, str]] = []

    def get_managed_users(self, corp_id: str, manager_user_id: str) -> DingTalkManagedUsers:
        self.calls.append((corp_id, manager_user_id))
        if self.managed_users is None:
            message = "目录不可用"
            raise AuthentikDirectoryError(message)
        return self.managed_users


def test_managed_users_preview_returns_filtered_directory_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: developer 管理的 App 已启用钉钉主管链策略, 目标用户已有钉钉绑定。
    client = _logged_in_client("managed-preview-developer")
    app = _member_app("managed-preview-success", "managed-preview-developer", role="developer")
    _ = _enabled_policy(app)
    user = UserMirror.objects.create(
        authentik_user_id="managed-preview-manager",
        dingtalk_corp_id="ding-corp",
        dingtalk_userid="ding-manager",
    )
    directory_client = DirectoryClientStub(
        _managed_users(
            stale=False,
            resolved_at="2026-07-02T09:30:00Z",
            user_ids=(
                "managed-preview-manager",
                "managed-preview-subordinate-a",
                "managed-preview-subordinate-b",
            ),
        ),
    )
    monkeypatch.setattr(
        "easyauth.admin_console.managed_users_preview_api.AuthentikDirectoryClient.from_settings",
        lambda: directory_client,
    )

    # When: 成员预览该用户的 MANAGED_USERS 解析结果。
    response = client.post(
        _preview_url(app.app_key),
        data=dumps({"user_id": user.authentik_user_id}),
        content_type="application/json",
    )

    # Then: API 调用真实目录客户端接口, 并过滤掉被查询用户本人。
    assert response.status_code == HTTPStatus.OK
    assert directory_client.calls == [("ding-corp", "ding-manager")]
    assert response.json() == {
        "resolved": {
            "user_ids": [
                "managed-preview-subordinate-a",
                "managed-preview-subordinate-b",
            ],
            "resolver": "dingtalk_manager_chain",
            "resolved_at": "2026-07-02T09:30:00Z",
        },
        "diagnostics": [],
    }


def test_managed_users_preview_rejects_missing_or_disabled_policy() -> None:
    # Given: owner 管理两个 App, 其中一个没有策略, 另一个策略被停用。
    client = _logged_in_client("managed-preview-policy-owner")
    missing_policy_app = _member_app(
        "managed-preview-policy-missing",
        "managed-preview-policy-owner",
        role="owner",
    )
    disabled_policy_app = _member_app(
        "managed-preview-policy-disabled",
        "managed-preview-policy-owner",
        role="owner",
    )
    _ = _enabled_policy(disabled_policy_app, enabled=False)
    user = UserMirror.objects.create(
        authentik_user_id="managed-preview-policy-user",
        dingtalk_corp_id="ding-corp",
        dingtalk_userid="ding-user",
    )

    # When: 分别请求未配置和已停用策略的 App。
    missing_response = client.post(
        _preview_url(missing_policy_app.app_key),
        data=dumps({"user_id": user.authentik_user_id}),
        content_type="application/json",
    )
    disabled_response = client.post(
        _preview_url(disabled_policy_app.app_key),
        data=dumps({"user_id": user.authentik_user_id}),
        content_type="application/json",
    )

    # Then: API 快速失败并返回明确诊断码。
    assert missing_response.status_code == HTTPStatus.BAD_REQUEST
    assert _diagnostic_error_code(missing_response) == "managed_scope_policy_missing"
    assert disabled_response.status_code == HTTPStatus.BAD_REQUEST
    assert _diagnostic_error_code(disabled_response) == "managed_scope_policy_missing"


def test_managed_users_preview_rejects_user_without_dingtalk_binding() -> None:
    # Given: owner 管理的 App 已配置策略, 但目标用户缺少钉钉 corp/userid 绑定。
    client = _logged_in_client("managed-preview-binding-owner")
    app = _member_app("managed-preview-binding", "managed-preview-binding-owner", role="owner")
    _ = _enabled_policy(app)
    user = UserMirror.objects.create(authentik_user_id="managed-preview-unbound-user")

    # When: owner 请求预览该用户的管理范围。
    response = client.post(
        _preview_url(app.app_key),
        data=dumps({"user_id": user.authentik_user_id}),
        content_type="application/json",
    )

    # Then: API 返回业务校验错误, 不调用目录兜底。
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert _diagnostic_error_code(response) == "managed_scope_user_dingtalk_binding_missing"


@pytest.mark.parametrize(
    ("directory_state", "expected_error_code"),
    [
        ("stale", "managed_scope_directory_stale"),
        ("unavailable", "managed_scope_directory_unavailable"),
    ],
)
def test_managed_users_preview_rejects_stale_or_unavailable_directory(
    monkeypatch: pytest.MonkeyPatch,
    directory_state: str,
    expected_error_code: str,
) -> None:
    # Given: App 策略和用户钉钉绑定有效, 但目录返回过期或不可用。
    client = _logged_in_client(f"managed-preview-directory-{expected_error_code}")
    app = _member_app(
        f"managed-preview-directory-{expected_error_code}",
        f"managed-preview-directory-{expected_error_code}",
        role="owner",
    )
    _ = _enabled_policy(app)
    user = UserMirror.objects.create(
        authentik_user_id=f"managed-preview-directory-user-{expected_error_code}",
        dingtalk_corp_id="ding-corp",
        dingtalk_userid="ding-manager",
    )
    managed_users = (
        _managed_users(
            stale=True,
            resolved_at="2026-07-02T10:00:00Z",
            user_ids=("managed-preview-stale-subordinate",),
        )
        if directory_state == "stale"
        else None
    )
    directory_client = DirectoryClientStub(managed_users)
    monkeypatch.setattr(
        "easyauth.admin_console.managed_users_preview_api.AuthentikDirectoryClient.from_settings",
        lambda: directory_client,
    )

    # When: owner 请求预览。
    response = client.post(
        _preview_url(app.app_key),
        data=dumps({"user_id": user.authentik_user_id}),
        content_type="application/json",
    )

    # Then: API 返回 400, diagnostics 带目录错误码。
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert _diagnostic_error_code(response) == expected_error_code


def test_managed_users_preview_enforces_app_membership_and_method() -> None:
    # Given: 目标 App 只允许 active owner/developer 访问。
    owner_client = _logged_in_client("managed-preview-security-owner")
    inactive_member_client = _logged_in_client("managed-preview-security-inactive")
    outsider_client = _logged_in_client("managed-preview-security-outsider")
    app = _member_app("managed-preview-security", "managed-preview-security-owner", role="owner")
    _ = AppMembership.objects.create(
        app=app,
        user_id="managed-preview-security-inactive",
        role="developer",
        is_active=False,
    )
    user = UserMirror.objects.create(
        authentik_user_id="managed-preview-security-user",
        dingtalk_corp_id="ding-corp",
        dingtalk_userid="ding-user",
    )

    # When: inactive 成员、非成员和非 POST 请求分别访问预览 API。
    inactive_response = inactive_member_client.post(
        _preview_url(app.app_key),
        data=dumps({"user_id": user.authentik_user_id}),
        content_type="application/json",
    )
    outsider_response = outsider_client.post(
        _preview_url(app.app_key),
        data=dumps({"user_id": user.authentik_user_id}),
        content_type="application/json",
    )
    get_response = owner_client.get(_preview_url(app.app_key))
    missing_app_response = owner_client.post(
        _preview_url("managed-preview-security-missing"),
        data=dumps({"user_id": user.authentik_user_id}),
        content_type="application/json",
    )

    # Then: API 区分权限、方法和不存在 App。
    assert inactive_response.status_code == HTTPStatus.FORBIDDEN
    assert outsider_response.status_code == HTTPStatus.FORBIDDEN
    assert get_response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert missing_app_response.status_code == HTTPStatus.NOT_FOUND


def _preview_url(app_key: str) -> str:
    return f"/console/api/v1/apps/{app_key}/managed-users-preview"


def _member_app(app_key: str, user_id: str, *, role: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=user_id, role=role)
    return app


def _enabled_policy(app: App, *, enabled: bool = True) -> ManagedScopePolicy:
    return ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
        enabled=enabled,
    )


def _managed_users(
    *,
    stale: bool,
    resolved_at: str,
    user_ids: tuple[str, ...],
) -> DingTalkManagedUsers:
    return DingTalkManagedUsers(
        source_slug="dingtalk",
        corp_id="ding-corp",
        manager_user_id="ding-manager",
        resolver="dingtalk_manager_chain",
        stale=stale,
        resolved_at=resolved_at,
        users=(),
        active_authentik_user_ids=user_ids,
    )


def _logged_in_client(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _diagnostic_error_code(response: HttpResponseLike) -> str:
    payload = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(payload, dict), response.content.decode()
    error = payload["error"]
    assert isinstance(error, dict), payload
    details = error["details"]
    assert isinstance(details, dict), payload
    diagnostics = details["diagnostics"]
    assert isinstance(diagnostics, list), payload
    first = diagnostics[0]
    assert isinstance(first, dict), payload
    error_code = first["error_code"]
    assert isinstance(error_code, str), payload
    return error_code
