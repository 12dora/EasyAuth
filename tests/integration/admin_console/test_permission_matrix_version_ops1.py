from __future__ import annotations

from contextlib import contextmanager
from http import HTTPStatus
from json import dumps
from re import escape, search
from typing import TYPE_CHECKING, Final

import pytest
from django.contrib.auth.models import User
from django.db import transaction as django_transaction
from django.test import Client

import easyauth.admin_console.permission_catalog_api as catalog_api
from easyauth.applications.models import (
    App,
    AppMembership,
    AppScope,
    Permission,
    Role,
    RolePermission,
)
from easyauth.audit.models import AuditLog

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-matrix-version"
STALE_VERSION: Final = "stale-version"
CURRENT_VERSION: Final = "current-version"
EXPECTED_CATALOG_VERSION: Final = 7


def test_ops1_matrix_save_rechecks_catalog_version_inside_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: owner 使用打开页面时看到的旧矩阵版本提交。
    client = _logged_in_user("ops1-matrix-transaction-version")
    app = _member_app(
        "ops1-matrix-transaction-version",
        "ops1-matrix-transaction-version",
        role="owner",
    )
    role = Role.objects.create(app=app, key="auditor", name="Auditor")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    inside_matrix_write_transaction = False
    real_atomic = django_transaction.atomic

    @contextmanager
    def tracked_atomic_context() -> Generator[None, None, None]:
        nonlocal inside_matrix_write_transaction
        with real_atomic():
            inside_matrix_write_transaction = True
            try:
                yield
            finally:
                inside_matrix_write_transaction = False

    def tracked_atomic(*args: object, **kwargs: object) -> object:
        if args and callable(args[0]):
            return real_atomic(*args, **kwargs)
        return tracked_atomic_context()

    def catalog_version_reloaded_in_transaction(_app: App) -> str:
        if inside_matrix_write_transaction:
            return CURRENT_VERSION
        return STALE_VERSION

    monkeypatch.setattr(django_transaction, "atomic", tracked_atomic)
    monkeypatch.setattr(catalog_api, "catalog_version", catalog_version_reloaded_in_transaction)

    # When: 事务内重读版本时目录已经变为新版本。
    response = client.post(
        _api_url(app.app_key, "role-permission-matrix"),
        data=_matrix_payload(
            base_version=STALE_VERSION,
            role_key=role.key,
            permission_key=permission.key,
        ),
        content_type="application/json",
    )

    # Then: API 在写入前返回 409, 不创建 RolePermission 或审计。
    assert response.status_code == HTTPStatus.CONFLICT
    assert _json_string(response.content.decode(), "current_version") == CURRENT_VERSION
    assert RolePermission.objects.filter(role=role, permission=permission).exists() is False
    assert AuditLog.objects.count() == 0


def test_ops1_catalog_payload_uses_app_catalog_version() -> None:
    # Given: App 的目录版本已经由统一服务维护。
    client = _logged_in_user("ops1-catalog-payload-version")
    app = _member_app("ops1-catalog-payload-version", "ops1-catalog-payload-version", role="owner")
    app.catalog_version = EXPECTED_CATALOG_VERSION
    app.save(update_fields=["catalog_version", "updated_at"])
    _ = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")

    # When: owner 查询权限目录。
    response = client.get(_api_url(app.app_key, "permissions"))

    # Then: payload 使用 App.catalog_version 作为主目录版本, 不再使用目录 hash。
    assert response.status_code == HTTPStatus.OK
    assert response.json()["catalog_version"] == EXPECTED_CATALOG_VERSION
    assert response.json()["version"] == str(EXPECTED_CATALOG_VERSION)


def test_ops1_permission_create_bumps_catalog_version() -> None:
    # Given: owner 面对一个已有目录版本的 App。
    client = _logged_in_user("ops1-permission-bumps-version")
    app = _member_app(
        "ops1-permission-bumps-version",
        "ops1-permission-bumps-version",
        role="owner",
    )
    initial_version = app.catalog_version
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="Global")

    # When: owner 新增 Permission。
    response = client.post(
        _api_url(app.app_key, "permissions"),
        data=dumps(
            {
                "key": "invoice.read",
                "name": "Read invoices",
                "supported_scopes": [scope.key],
            },
        ),
        content_type="application/json",
    )

    # Then: 写操作通过统一目录版本服务提升版本。
    app.refresh_from_db()
    assert response.status_code == HTTPStatus.CREATED
    assert app.catalog_version == initial_version + 1
    assert AuditLog.objects.filter(
        actor_id="ops1-permission-bumps-version",
        event_type="app_catalog_version_bumped",
        metadata__reason="permission_created",
        metadata__catalog_version=app.catalog_version,
    ).exists()


def _member_app(app_key: str, username: str, *, role: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=username, role=role)
    return app


def _api_url(app_key: str, endpoint: str) -> str:
    return f"/console/api/v1/apps/{app_key}/{endpoint}"


def _matrix_payload(*, base_version: str, role_key: str, permission_key: str) -> str:
    return dumps(
        {
            "base_version": base_version,
            "add": [{"role_key": role_key, "permission_key": permission_key}],
        },
    )


def _json_string(body: str, key: str) -> str:
    match = search(rf'"{escape(key)}"\s*:\s*"([^"]*)"', body)
    if match is None:
        raise AssertionError(body)
    return match.group(1)


def _logged_in_user(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client
