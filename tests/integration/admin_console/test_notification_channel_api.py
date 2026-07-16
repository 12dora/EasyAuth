from __future__ import annotations

from http import HTTPStatus
from json import dumps, loads
from unittest.mock import patch

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppMembership, AppNotificationChannel
from easyauth.audit.models import AuditLog

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


def _payload(*, secret: str, agent_id: str = "1001") -> dict[str, str]:
    return {
        "name": "EasyTrade 钉钉应用",
        "dingtalk_app_key": "easytrade-key",
        "dingtalk_app_secret": secret,
        "agent_id": agent_id,
    }


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
    payload = loads(body)["notification_channel"]
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
