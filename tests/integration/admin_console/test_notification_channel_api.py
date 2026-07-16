from __future__ import annotations

from http import HTTPStatus
from json import dumps, loads
from typing import cast
from unittest.mock import patch

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppMembership, AppNotificationChannel
from easyauth.audit.models import AuditLog
from easyauth.integrations.dingtalk.api_client import DingTalkApiError

pytestmark = pytest.mark.django_db


def _client(user_id: str) -> Client:
    _ = UserMirror.objects.create(authentik_user_id=user_id)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user_id
    session.save()
    return client


def _app() -> App:
    app = App.objects.create(app_key="notify-channel-api", name="Notify Channel")
    _ = AppMembership.objects.create(app=app, user_id="channel-owner", role="owner")
    _ = AppMembership.objects.create(app=app, user_id="channel-developer", role="developer")
    return app


def _url(app: App, suffix: str = "") -> str:
    base = f"/console/api/v1/apps/{app.app_key}/notification-channel"
    return f"{base}/{suffix}" if suffix else base


def _payload(*, secret: str | None, agent_id: str = "1001") -> dict[str, str]:
    payload = {
        "name": "EasyTrade 钉钉应用",
        "dingtalk_app_key": "easytrade-key",
        "agent_id": agent_id,
    }
    if secret is not None:
        payload["dingtalk_app_secret"] = secret
    return payload


def test_owner_versions_channel_without_exposing_or_auditing_secret() -> None:
    app = _app()
    owner = _client("channel-owner")
    first_secret = "first-channel-secret"  # noqa: S105 - 测试专用固定值。
    second_secret = "second-channel-secret"  # noqa: S105 - 测试专用固定值。

    first = owner.put(
        _url(app),
        data=dumps(_payload(secret=first_secret)),
        content_type="application/json",
    )
    second = owner.put(
        _url(app),
        data=dumps(_payload(secret=second_secret, agent_id="1002")),
        content_type="application/json",
    )
    listed = owner.get(_url(app))

    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CREATED
    body = listed.content.decode()
    decoded = cast("dict[str, object]", loads(body))
    payload = cast("dict[str, object]", decoded["notification_channel"])
    assert payload["version"] == 2  # noqa: PLR2004
    assert payload["agent_id"] == "1002"
    assert payload["app_secret_configured"] is True
    assert first_secret not in body
    assert second_secret not in body
    channels = list(AppNotificationChannel.objects.filter(app=app).order_by("version"))
    assert [row.is_active for row in channels] == [False, True]
    assert channels[0].dingtalk_app_secret == first_secret
    assert channels[1].dingtalk_app_secret == second_secret
    for audit in AuditLog.objects.all():
        assert first_secret not in str(audit.metadata)
        assert second_secret not in str(audit.metadata)


def test_developer_can_read_but_cannot_write_or_test_channel() -> None:
    app = _app()
    owner = _client("channel-owner")
    developer = _client("channel-developer")
    _ = owner.put(
        _url(app),
        data=dumps(_payload(secret="developer-read-secret")),  # noqa: S106
        content_type="application/json",
    )

    assert developer.get(_url(app)).status_code == HTTPStatus.OK
    denied_put = developer.put(
        _url(app),
        data=dumps(_payload(secret="denied-secret")),  # noqa: S106
        content_type="application/json",
    )
    denied_test = developer.post(_url(app, "test"), content_type="application/json")
    assert denied_put.status_code == HTTPStatus.FORBIDDEN
    assert denied_test.status_code == HTTPStatus.FORBIDDEN


def test_first_create_requires_secret_and_update_can_reuse_it() -> None:
    app = _app()
    owner = _client("channel-owner")
    missing = owner.put(
        _url(app),
        data=dumps(_payload(secret=None)),
        content_type="application/json",
    )
    assert missing.status_code == HTTPStatus.BAD_REQUEST
    assert AppNotificationChannel.objects.filter(app=app).exists() is False

    original_secret = "reuse-channel-secret"  # noqa: S105 - 测试专用固定值。
    created = owner.put(
        _url(app),
        data=dumps(_payload(secret=original_secret)),
        content_type="application/json",
    )
    omitted = owner.put(
        _url(app),
        data=dumps(_payload(secret=None, agent_id="2002")),
        content_type="application/json",
    )
    blank_payload = _payload(secret="", agent_id="2003")
    blank = owner.put(
        _url(app),
        data=dumps(blank_payload),
        content_type="application/json",
    )

    assert created.status_code == HTTPStatus.CREATED
    assert omitted.status_code == HTTPStatus.CREATED
    assert blank.status_code == HTTPStatus.CREATED
    channels = list(AppNotificationChannel.objects.filter(app=app).order_by("version"))
    assert [row.dingtalk_app_secret for row in channels] == [original_secret] * 3
    assert [row.agent_id for row in channels] == ["1001", "2002", "2003"]


def test_validation_error_does_not_echo_secret_input() -> None:
    app = _app()
    owner = _client("channel-owner")
    secret_marker = "secret-must-not-echo"  # noqa: S105 - 测试专用固定值。
    payload = cast("dict[str, object]", cast("object", _payload(secret=None)))
    payload["dingtalk_app_secret"] = {"unexpected": secret_marker}

    response = owner.put(
        _url(app),
        data=dumps(payload),
        content_type="application/json",
    )

    body = response.content.decode()
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert secret_marker not in body
    assert loads(body)["error"]["details"]["fields"] == ["dingtalk_app_secret"]


def test_owner_connectivity_test_uses_active_channel() -> None:
    app = _app()
    owner = _client("channel-owner")
    _ = owner.put(
        _url(app),
        data=dumps(_payload(secret="connectivity-secret")),  # noqa: S106
        content_type="application/json",
    )
    with patch(
        "easyauth.admin_console.notification_channel_api.DingTalkApiClient.get_access_token",
        return_value="access-token",
    ) as get_access_token:
        response = owner.post(_url(app, "test"), content_type="application/json")
    assert response.status_code == HTTPStatus.OK
    assert loads(response.content) == {"ok": True, "version": 1}
    get_access_token.assert_called_once_with(force_refresh=True)


def test_connectivity_error_does_not_echo_upstream_body() -> None:
    app = _app()
    owner = _client("channel-owner")
    secret = "connectivity-hidden-secret"  # noqa: S105 - 测试专用固定值。
    _ = owner.put(
        _url(app),
        data=dumps(_payload(secret=secret)),
        content_type="application/json",
    )
    upstream_marker = f"upstream rejected appSecret={secret}"
    with patch(
        "easyauth.admin_console.notification_channel_api.DingTalkApiClient.get_access_token",
        side_effect=DingTalkApiError(upstream_marker),
    ):
        response = owner.post(_url(app, "test"), content_type="application/json")

    body = response.content.decode()
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert upstream_marker not in body
    assert secret not in body
    for audit in AuditLog.objects.all():
        assert upstream_marker not in str(audit.metadata)
        assert secret not in str(audit.metadata)
