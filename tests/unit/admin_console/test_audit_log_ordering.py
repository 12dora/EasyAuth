from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol, cast

import pytest
from django.db.models import QuerySet
from django.test import Client
from django.utils import timezone

from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.audit.models import AuditLog
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    install_authentik_authority,
    reset_authentik_authority,
)

if TYPE_CHECKING:
    from datetime import datetime

    from pytest_django.fixtures import SettingsWrapper

    from easyauth.audit.models import JsonObject

pytestmark = pytest.mark.django_db

AUDIT_URL: Final = "/console/api/v1/audit-logs"


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


@pytest.fixture(autouse=True)
def _console_auth(monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)
    reset_authentik_authority()
    install_authentik_authority(monkeypatch)


def test_audit_logs_order_by_event_type_actor_target_app_and_created_at() -> None:
    client = _admin("ord-audit-admin")
    now = timezone.now()
    alpha = _log(
        event_type="alpha.event",
        actor_type="admin",
        actor_id="ada",
        target_type="app",
        target_id="aaa",
        metadata={"app_key": "ord-audit-a"},
        created_at=now - timedelta(hours=2),
    )
    zeta = _log(
        event_type="zeta.event",
        actor_type="user",
        actor_id="ben",
        target_type="user",
        target_id="zzz",
        metadata={"app_key": "ord-audit-z"},
        created_at=now,
    )
    mu = _log(
        event_type="mu.event",
        actor_type="admin",
        actor_id="cara",
        target_type="app",
        target_id="mmm",
        metadata={},
        created_at=now - timedelta(hours=1),
    )

    assert _events(client, "event_type") == [alpha.event_type, mu.event_type, zeta.event_type]
    assert _events(client, "-event_type") == [zeta.event_type, mu.event_type, alpha.event_type]
    assert _events(client, "actor") == [alpha.event_type, mu.event_type, zeta.event_type]
    assert _events(client, "-actor") == [zeta.event_type, mu.event_type, alpha.event_type]
    assert _events(client, "target") == [alpha.event_type, mu.event_type, zeta.event_type]
    assert _events(client, "-target") == [zeta.event_type, mu.event_type, alpha.event_type]
    assert _events(client, "app") == [alpha.event_type, zeta.event_type, mu.event_type]
    assert _events(client, "-app") == [zeta.event_type, alpha.event_type, mu.event_type]
    assert _events(client, "created_at") == [alpha.event_type, mu.event_type, zeta.event_type]
    assert _events(client, "-created_at") == [zeta.event_type, mu.event_type, alpha.event_type]


def test_audit_logs_reject_unknown_ordering() -> None:
    client = _admin("ord-audit-unknown-admin")
    response = client.get(AUDIT_URL, {"ordering": "does_not_exist"})
    _assert_unknown(response, "does_not_exist")


def _log(  # noqa: PLR0913 - 审计夹具按复合排序字段铺开。
    *,
    event_type: str,
    actor_type: str,
    actor_id: str,
    target_type: str,
    target_id: str,
    metadata: JsonObject,
    created_at: datetime,
) -> AuditLog:
    log = AuditLog.objects.create(
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )
    # AuditLog 禁止 QuerySet.update; 测试用基类 update 写入 created_at。
    _ = QuerySet.update(AuditLog.objects.filter(pk=log.pk), created_at=created_at)
    log.refresh_from_db()
    return log


def _admin(username: str) -> Client:
    return authenticate_console_admin(Client(HTTP_HOST="localhost"), username)


def _events(client: Client, ordering: str) -> list[str]:
    response = client.get(AUDIT_URL, {"ordering": ordering, "page_size": "20"})
    assert response.status_code == HTTPStatus.OK, response.content
    payload = cast("dict[str, JsonValue]", response.json())
    data = payload["data"]
    assert isinstance(data, list), payload
    events: list[str] = []
    for item in data:
        assert isinstance(item, dict), payload
        events.append(str(item["event_type"]))
    return events


def _assert_unknown(response: _JsonResponse, value: str) -> None:
    assert response.status_code == HTTPStatus.BAD_REQUEST
    payload = cast("dict[str, JsonValue]", response.json())
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["details"] == {"field": "ordering", "value": value}
