from __future__ import annotations

from email.message import Message
from http import HTTPStatus
from io import BytesIO
from json import dumps
from typing import TYPE_CHECKING, Final, Self, cast, final
from urllib.error import HTTPError, URLError

import pytest
from django.core.cache import cache
from django.test import Client

from easyauth.accounts.models import USER_STATUS_DISABLED, DingTalkUserMirror, UserMirror
from easyauth.admin_console.direct_grants_payloads import IDENTITY_XOR_MESSAGE
from easyauth.admin_console.directory_user_materialize import (
    AUTHENTIK_ACCOUNT_CONFLICT_MESSAGE,
    DIRECTORY_USER_INACTIVE_MESSAGE,
    DIRECTORY_USER_MATERIALIZED_ACTION,
    DIRECTORY_USER_NOT_FOUND_MESSAGE,
    MATERIALIZE_UNAVAILABLE_MESSAGE,
    UNION_ID_MISSING_MESSAGE,
)
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission
from easyauth.audit.models import AuditLog
from easyauth.grants.direct_grant import DIRECT_GRANT_APPLIED_ACTION
from easyauth.grants.models import AccessGrant
from tests.integration.admin_console.auth_helpers import authenticate_console_admin

if TYPE_CHECKING:
    from urllib.request import Request

    from easyauth.api.errors import JsonValue
    from easyauth.integrations.authentik.admin_client import AdminJson

pytestmark = pytest.mark.django_db

DIRECT_GRANTS_API_URL: Final = "/console/api/v1/direct-grants"
_SOURCE: Final = "dingtalk"
_CORP: Final = "ding-corp"
_USER_ID: Final = "0220123456"
_UUID: Final = "fdac7e94-a7ab-4311-9b57-436f3a35f3cb"
_MATERIALIZE_SUFFIX: Final = (
    f"/api/v3/sources/oauth/dingtalk-directory/{_SOURCE}/users/{_CORP}/{_USER_ID}/materialize/"
)


@final
class _FakeAdminClient:
    def __init__(self, entry: AdminJson) -> None:
        self.entry = entry
        self.get_user_calls = 0

    def get_user_by_uuid(self, sub: str) -> AdminJson:
        self.get_user_calls += 1
        assert sub == self.entry["uuid"]
        return self.entry

    def user_group_names_by_uuid(self, _sub: str) -> tuple[str, ...]:
        return ("EasyAuth Admins",)


def test_direct_grants_materialize_created_writes_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app, group = _catalog("dg-mat-created")
    _directory_person()
    materialize_calls = _patch_materialize_http(monkeypatch, created=True)
    admin = _patch_provision_admin(monkeypatch)

    response = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(_directory_payload(app_key=app.app_key, groups=[group.key])),
        content_type="application/json",
    )

    body = cast("dict[str, JsonValue]", response.json()["data"]["grant"])
    user = UserMirror.objects.get(authentik_user_id=_UUID)
    assert response.status_code == HTTPStatus.CREATED
    assert body["user_id"] == _UUID
    assert user.dingtalk_userid == _USER_ID
    assert user.dingtalk_corp_id == _CORP
    assert user.dingtalk_source_slug == _SOURCE
    assert materialize_calls == [_MATERIALIZE_SUFFIX]
    assert admin.get_user_calls == 1
    assert AccessGrant.objects.filter(user=user, app=app, is_current=True).count() == 1
    audit = AuditLog.objects.filter(
        event_type=DIRECTORY_USER_MATERIALIZED_ACTION,
        target_id=_UUID,
    ).get()
    assert audit.actor_type == "admin"
    assert audit.target_type == "user"
    assert audit.metadata == {
        "source_slug": _SOURCE,
        "corp_id": _CORP,
        "user_id": _USER_ID,
        "created": True,
    }
    assert AuditLog.objects.filter(event_type=DIRECT_GRANT_APPLIED_ACTION).count() == 1


def test_direct_grants_materialize_ignores_preexisting_provision_miss_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app, group = _catalog("dg-mat-miss-cache")
    _directory_person()
    _patch_materialize_http(monkeypatch, created=True)
    admin = _patch_provision_admin(monkeypatch)
    cache.set(f"authentik-provision-miss:{_UUID}", 1)

    response = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(_directory_payload(app_key=app.app_key, groups=[group.key])),
        content_type="application/json",
    )

    body = cast("dict[str, JsonValue]", response.json()["data"]["grant"])
    user = UserMirror.objects.get(authentik_user_id=_UUID)
    assert response.status_code == HTTPStatus.CREATED
    assert body["user_id"] == _UUID
    assert user.dingtalk_userid == _USER_ID
    assert admin.get_user_calls == 1
    assert cache.get(f"authentik-provision-miss:{_UUID}") is None
    assert AccessGrant.objects.filter(user=user, app=app, is_current=True).count() == 1


def test_direct_grants_materialize_idempotent_authentik_still_provisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app, group = _catalog("dg-mat-ak-existing")
    _directory_person()
    _patch_materialize_http(monkeypatch, created=False)
    _patch_provision_admin(monkeypatch)

    response = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(_directory_payload(app_key=app.app_key, groups=[group.key])),
        content_type="application/json",
    )

    body = cast("dict[str, JsonValue]", response.json()["data"]["grant"])
    audit = AuditLog.objects.filter(
        event_type=DIRECTORY_USER_MATERIALIZED_ACTION,
        target_id=_UUID,
    ).get()
    assert response.status_code == HTTPStatus.CREATED
    assert body["user_id"] == _UUID
    assert audit.metadata["created"] is False


def test_direct_grants_directory_user_uses_existing_user_mirror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app, group = _catalog("dg-mat-existing")
    _directory_person()
    existing = UserMirror.objects.create(
        authentik_user_id="already-mirrored",
        dingtalk_source_slug=_SOURCE,
        dingtalk_corp_id=_CORP,
        dingtalk_userid=_USER_ID,
    )
    monkeypatch.setattr(
        "easyauth.integrations.authentik.directory_client.urlopen",
        _fail_if_called,
    )

    response = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(_directory_payload(app_key=app.app_key, groups=[group.key])),
        content_type="application/json",
    )

    body = cast("dict[str, JsonValue]", response.json()["data"]["grant"])
    assert response.status_code == HTTPStatus.CREATED
    assert body["user_id"] == existing.authentik_user_id
    assert AuditLog.objects.filter(event_type=DIRECTORY_USER_MATERIALIZED_ACTION).count() == 0
    assert AccessGrant.objects.filter(user=existing, app=app, is_current=True).count() == 1


def test_direct_grants_rejects_both_or_neither_identity() -> None:
    client, app, group = _catalog("dg-mat-xor")
    both = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(
            {
                **_directory_payload(app_key=app.app_key, groups=[group.key]),
                "user_id": "some-user",
            },
        ),
        content_type="application/json",
    )
    neither = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(
            {
                "app_key": app.app_key,
                "authorization_group_keys": [group.key],
                "direct_grants": [],
                "grant_type": "permanent",
                "grant_expires_at": None,
                "reason": "管理员直接授权",
            },
        ),
        content_type="application/json",
    )

    assert both.status_code == HTTPStatus.BAD_REQUEST
    assert both.json()["error"]["code"] == "VALIDATION_ERROR"
    assert both.json()["error"]["message"] == IDENTITY_XOR_MESSAGE
    assert neither.status_code == HTTPStatus.BAD_REQUEST
    assert neither.json()["error"]["code"] == "VALIDATION_ERROR"
    assert neither.json()["error"]["message"] == IDENTITY_XOR_MESSAGE


def test_direct_grants_directory_user_missing_and_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app, group = _catalog("dg-mat-lookup")
    monkeypatch.setattr(
        "easyauth.integrations.authentik.directory_client.urlopen",
        _fail_if_called,
    )

    missing = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(_directory_payload(app_key=app.app_key, groups=[group.key])),
        content_type="application/json",
    )
    _directory_person(status=USER_STATUS_DISABLED)
    inactive = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(_directory_payload(app_key=app.app_key, groups=[group.key])),
        content_type="application/json",
    )
    DingTalkUserMirror.objects.all().delete()
    _directory_person(tombstone=True)
    tombstone = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(_directory_payload(app_key=app.app_key, groups=[group.key])),
        content_type="application/json",
    )

    assert missing.status_code == HTTPStatus.NOT_FOUND
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    assert missing.json()["error"]["message"] == DIRECTORY_USER_NOT_FOUND_MESSAGE
    assert inactive.status_code == HTTPStatus.CONFLICT
    assert inactive.json()["error"]["code"] == "CONFLICT"
    assert inactive.json()["error"]["message"] == DIRECTORY_USER_INACTIVE_MESSAGE
    assert tombstone.status_code == HTTPStatus.CONFLICT
    assert tombstone.json()["error"]["message"] == DIRECTORY_USER_INACTIVE_MESSAGE


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("union_id_missing", UNION_ID_MISSING_MESSAGE),
        ("username_conflict", AUTHENTIK_ACCOUNT_CONFLICT_MESSAGE),
        ("binding_conflict", AUTHENTIK_ACCOUNT_CONFLICT_MESSAGE),
        ("directory_user_inactive", DIRECTORY_USER_INACTIVE_MESSAGE),
    ],
)
def test_direct_grants_maps_authentik_409_codes(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    message: str,
) -> None:
    client, app, group = _catalog(f"dg-mat-409-{code}")
    _directory_person()
    _patch_materialize_http(monkeypatch, conflict_code=code)

    response = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(_directory_payload(app_key=app.app_key, groups=[group.key])),
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["error"]["code"] == "CONFLICT"
    assert response.json()["error"]["message"] == message
    assert UserMirror.objects.filter(dingtalk_userid=_USER_ID).count() == 0
    assert AuditLog.objects.filter(event_type=DIRECTORY_USER_MATERIALIZED_ACTION).count() == 0


def test_direct_grants_directory_user_transport_failure_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app, group = _catalog("dg-mat-503")
    _directory_person()

    def fake_urlopen(_request: Request, *, timeout: float) -> object:
        _ = timeout
        reason = "authentik down"
        raise URLError(reason)

    monkeypatch.setattr("easyauth.integrations.authentik.directory_client.urlopen", fake_urlopen)

    response = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(_directory_payload(app_key=app.app_key, groups=[group.key])),
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert response.json()["error"]["message"] == MATERIALIZE_UNAVAILABLE_MESSAGE
    assert AccessGrant.objects.count() == 0


def test_direct_grants_validates_targets_before_materialize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _app, group = _catalog("dg-mat-validate-first")
    _directory_person()
    monkeypatch.setattr(
        "easyauth.integrations.authentik.directory_client.urlopen",
        _fail_if_called,
    )

    response = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(_directory_payload(app_key="missing-app", groups=[group.key])),
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["error"]["code"] == "NOT_FOUND"


def _catalog(prefix: str) -> tuple[Client, App, AuthorizationGroup]:
    client = Client(HTTP_HOST="localhost")
    authenticate_console_admin(client, f"{prefix}-admin")
    admin = UserMirror.objects.get(authentik_user_id=f"{prefix}-admin")
    admin.is_console_admin = True
    admin.save(update_fields=["is_console_admin", "updated_at"])
    app = App.objects.create(app_key=f"{prefix}-app", name=prefix)
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    _ = Permission.objects.create(
        app=app,
        key="order.order.view",
        name="查看订单",
        supported_scopes=["GLOBAL"],
    )
    group = AuthorizationGroup.objects.create(
        app=app,
        key="sales",
        kind="role",
        name="销售",
        requestable=False,
    )
    return client, app, group


def _directory_person(*, status: str = "active", tombstone: bool = False) -> DingTalkUserMirror:
    return DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        user_id=_USER_ID,
        name="张甜",
        status=status,
        is_tombstone=tombstone,
    )


def _directory_payload(*, app_key: str, groups: list[str]) -> dict[str, object]:
    return {
        "directory_user": {
            "source_slug": _SOURCE,
            "corp_id": _CORP,
            "user_id": _USER_ID,
        },
        "app_key": app_key,
        "authorization_group_keys": groups,
        "direct_grants": [],
        "grant_type": "permanent",
        "grant_expires_at": None,
        "reason": "管理员直接授权",
    }


def _patch_materialize_http(
    monkeypatch: pytest.MonkeyPatch,
    *,
    created: bool = True,
    conflict_code: str | None = None,
) -> list[str]:
    calls: list[str] = []

    def fake_urlopen(request: Request, *, timeout: float) -> object:
        _ = timeout
        path = request.full_url.split("://", 1)[-1]
        suffix = path[path.find("/api/") :]
        calls.append(suffix)
        if conflict_code is not None:
            raise HTTPError(
                request.full_url,
                HTTPStatus.CONFLICT,
                "conflict",
                Message(),
                BytesIO(dumps({"code": conflict_code}).encode()),
            )
        assert request.get_method() == "POST"
        assert request.data == b"{}"
        return _OkResponse(
            dumps(
                {
                    "created": created,
                    "user": {
                        "pk": 12,
                        "uuid": _UUID,
                        "username": _USER_ID,
                        "name": "张甜",
                        "is_active": True,
                    },
                },
            ).encode(),
        )

    monkeypatch.setattr("easyauth.integrations.authentik.directory_client.urlopen", fake_urlopen)
    return calls


def _patch_provision_admin(monkeypatch: pytest.MonkeyPatch) -> _FakeAdminClient:
    admin = _FakeAdminClient(
        {
            "pk": 12,
            "username": _USER_ID,
            "name": "张甜",
            "is_active": True,
            "uuid": _UUID,
            "attributes": {
                "dingtalk": {
                    "source_slug": _SOURCE,
                    "corp_id": _CORP,
                    "user_id": _USER_ID,
                    "name": "张甜",
                },
            },
        },
    )
    monkeypatch.setattr(
        "easyauth.accounts.authentik_provisioning.AuthentikAdminClient.from_settings",
        lambda: admin,
    )
    return admin


def _fail_if_called(*_args: object, **_kwargs: object) -> object:
    message = "不得在校验失败或已有 UserMirror 时访问 Authentik"
    raise AssertionError(message)


class _OkResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self._consumed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _amount: int = -1) -> bytes:
        if self._consumed:
            return b""
        self._consumed = True
        return self._body

    def getheader(self, _name: str) -> str | None:
        return None
