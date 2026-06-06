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
from easyauth.applications.models import App, AppMembership, Permission, Role, RolePermission
from easyauth.audit.models import AuditLog

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-matrix-version"
STALE_VERSION: Final = "stale-version"
CURRENT_VERSION: Final = "current-version"


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
    def tracked_atomic() -> Generator[None, None, None]:
        nonlocal inside_matrix_write_transaction
        with real_atomic():
            inside_matrix_write_transaction = True
            try:
                yield
            finally:
                inside_matrix_write_transaction = False

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
            version=STALE_VERSION,
            role_id=role.id,
            permission_id=permission.id,
            enabled=True,
        ),
        content_type="application/json",
    )

    # Then: API 在写入前返回 409, 不创建 RolePermission 或审计。
    assert response.status_code == HTTPStatus.CONFLICT
    assert _json_string(response.content.decode(), "current_version") == CURRENT_VERSION
    assert RolePermission.objects.filter(role=role, permission=permission).exists() is False
    assert AuditLog.objects.count() == 0


def _member_app(app_key: str, username: str, *, role: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=username, role=role)
    return app


def _api_url(app_key: str, endpoint: str) -> str:
    return f"/console/api/v1/apps/{app_key}/{endpoint}"


def _matrix_payload(*, version: str, role_id: int, permission_id: int, enabled: bool) -> str:
    return dumps(
        {
            "version": version,
            "assignments": [
                {"role_id": role_id, "permission_id": permission_id, "enabled": enabled},
            ],
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
