from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.api.errors import JsonValue
from easyauth.applications.models import App, AppMembership, ManagedScopePolicy
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-managed-scope-policy"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


def test_owner_reads_empty_app_default_managed_scope_policy() -> None:
    # Given: owner 管理一个尚未配置 MANAGED_USERS App 默认策略的 App。
    client = _logged_in_user("managed-policy-empty-owner")
    app = _member_app("managed-policy-empty", "managed-policy-empty-owner", role="owner")

    # When: owner 读取 App 默认管理范围策略。
    response = client.get(_policy_url(app.app_key))

    # Then: API 返回空策略和空有效状态。
    body = _response_json(response)
    assert response.status_code == HTTPStatus.OK
    assert body == {
        "managed_scope_policy": None,
        "effective_managed_scope_policy": None,
    }


def test_owner_patches_and_reads_app_default_managed_scope_policy() -> None:
    # Given: owner 管理一个 App。
    client = _logged_in_user("managed-policy-owner")
    app = _member_app("managed-policy-app", "managed-policy-owner", role="owner")

    # When: owner 启用 App 默认 MANAGED_USERS 策略。
    patched = client.patch(
        _policy_url(app.app_key),
        data=dumps(
            {
                "managed_scope_policy": {
                    "mode": "override",
                    "enabled": True,
                    "resolver": "dingtalk_manager_chain",
                },
            },
        ),
        content_type="application/json",
    )
    read_back = client.get(_policy_url(app.app_key))

    # Then: API 保存 app_default 策略, 并返回有效状态。
    patched_body = _response_json(patched)
    read_body = _response_json(read_back)
    policy = ManagedScopePolicy.objects.get(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
    )
    expected = {
        "managed_scope_policy": {
            "id": policy.id,
            "target_type": "app_default",
            "target_id": app.id,
            "scope": "MANAGED_USERS",
            "resolver": "dingtalk_manager_chain",
            "enabled": True,
        },
        "effective_managed_scope_policy": {
            "resolver": "dingtalk_manager_chain",
            "enabled": True,
            "source": "app_default",
            "inherited_from": None,
            "health_status": "healthy",
            "health_message": "管理范围策略已配置。",
        },
    }
    assert patched.status_code == HTTPStatus.OK
    assert read_back.status_code == HTTPStatus.OK
    assert patched_body == expected
    assert read_body == expected
    assert policy.resolver == "dingtalk_manager_chain"
    assert policy.enabled is True
    audit_log = AuditLog.objects.get(event_type="managed_scope_policy_updated")
    assert audit_log.actor_type == "user"
    assert audit_log.actor_id == "managed-policy-owner"
    assert audit_log.target_type == "app"
    assert audit_log.target_id == str(app.id)
    assert audit_log.metadata == {
        "app_key": app.app_key,
        "scope": "MANAGED_USERS",
        "resolver": "dingtalk_manager_chain",
    }


def test_owner_disables_app_default_managed_scope_policy() -> None:
    # Given: owner 管理一个已有有效 App 默认策略的 App。
    client = _logged_in_user("managed-policy-disable-owner")
    app = _member_app("managed-policy-disable", "managed-policy-disable-owner", role="owner")
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
        enabled=True,
    )

    # When: owner 将 resolver 改为 disabled。
    response = client.patch(
        _policy_url(app.app_key),
        data=dumps(
            {
                "managed_scope_policy": {
                    "mode": "disabled",
                    "enabled": False,
                    "resolver": "disabled",
                },
            },
        ),
        content_type="application/json",
    )

    # Then: 策略被保存为 disabled, 控制台响应明确展示不启用状态。
    body = _response_json(response)
    policy = ManagedScopePolicy.objects.get(app=app, target_type="app_default", target_id=app.id)
    assert response.status_code == HTTPStatus.OK
    assert body["managed_scope_policy"] == {
        "id": policy.id,
        "target_type": "app_default",
        "target_id": app.id,
        "scope": "MANAGED_USERS",
        "resolver": "disabled",
        "enabled": True,
    }
    assert body["effective_managed_scope_policy"] == {
        "resolver": "disabled",
        "enabled": True,
        "source": "app_default",
        "inherited_from": None,
        "health_status": "disabled",
        "health_message": "应用默认管理范围策略不启用。",
    }
    assert policy.resolver == "disabled"
    assert policy.enabled is True


def test_owner_deletes_app_default_managed_scope_policy() -> None:
    # Given: owner 管理一个已有默认策略的 App。
    client = _logged_in_user("managed-policy-delete-owner")
    app = _member_app("managed-policy-delete", "managed-policy-delete-owner", role="owner")
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
        enabled=True,
    )

    # When: owner 将应用默认策略清空。
    response = client.patch(
        _policy_url(app.app_key),
        data=dumps({"managed_scope_policy": None}),
        content_type="application/json",
    )

    # Then: App 默认策略被删除, 控制台返回空策略。
    body = _response_json(response)
    assert response.status_code == HTTPStatus.OK
    assert body == {
        "managed_scope_policy": None,
        "effective_managed_scope_policy": None,
    }
    assert ManagedScopePolicy.objects.filter(app=app).exists() is False


def test_developer_reads_but_cannot_patch_app_default_managed_scope_policy() -> None:
    # Given: developer 是 active App 成员。
    client = _logged_in_user("managed-policy-developer")
    app = _member_app("managed-policy-developer-app", "managed-policy-developer", role="developer")

    # When: developer 读取并尝试写入 App 默认策略。
    read_response = client.get(_policy_url(app.app_key))
    patch_response = client.patch(
        _policy_url(app.app_key),
        data=dumps(
            {
                "managed_scope_policy": {
                    "mode": "override",
                    "enabled": True,
                    "resolver": "dingtalk_manager_chain",
                },
            },
        ),
        content_type="application/json",
    )

    # Then: developer 可读但不能维护策略。
    assert read_response.status_code == HTTPStatus.OK
    assert patch_response.status_code == HTTPStatus.FORBIDDEN
    assert ManagedScopePolicy.objects.filter(app=app).exists() is False


def test_non_member_cannot_read_app_default_managed_scope_policy() -> None:
    # Given: 普通用户不属于目标 App。
    client = _logged_in_user("managed-policy-outsider")
    app = App.objects.create(app_key="managed-policy-outsider-app", name="Outsider")
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )

    # When: 普通用户读取该 App 默认策略。
    response = client.get(_policy_url(app.app_key))

    # Then: API 拒绝访问且不泄漏 resolver。
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert "dingtalk_manager_chain" not in response.content.decode()


def test_patch_rejects_invalid_resolver_and_unknown_app() -> None:
    # Given: owner 管理一个 App。
    client = _logged_in_user("managed-policy-invalid-owner")
    app = _member_app("managed-policy-invalid", "managed-policy-invalid-owner", role="owner")

    # When: owner 提交无效 resolver, 并访问不存在的 App。
    invalid_resolver = client.patch(
        _policy_url(app.app_key),
        data=dumps(
            {
                "managed_scope_policy": {
                    "mode": "override",
                    "enabled": True,
                    "resolver": "local_org_tree",
                },
            },
        ),
        content_type="application/json",
    )
    unknown_app = client.get(_policy_url("managed-policy-missing"))

    # Then: API 使用控制台错误格式返回校验错误和不存在错误。
    invalid_body = _response_json(invalid_resolver)
    unknown_body = _response_json(unknown_app)
    invalid_error = _json_object(invalid_body["error"])
    invalid_details = _json_object(invalid_error["details"])
    invalid_errors = invalid_details["errors"]
    unknown_error = _json_object(unknown_body["error"])
    assert invalid_resolver.status_code == HTTPStatus.BAD_REQUEST
    assert invalid_error["code"] == "VALIDATION_ERROR"
    assert isinstance(invalid_errors, str)
    assert "resolver" in invalid_errors
    assert unknown_app.status_code == HTTPStatus.NOT_FOUND
    assert unknown_error["code"] == "NOT_FOUND"


def _member_app(app_key: str, username: str, *, role: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=username, role=role)
    return app


def _logged_in_user(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _policy_url(app_key: str) -> str:
    return f"/console/api/v1/apps/{app_key}/managed-scope-policy"


def _response_json(response: HttpResponseLike) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(parsed, dict), response.content.decode()
    return parsed


def _json_object(value: JsonValue) -> dict[str, JsonValue]:
    assert isinstance(value, dict), value
    return value
