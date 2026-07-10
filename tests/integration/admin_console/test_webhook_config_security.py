from __future__ import annotations

import json
import socket
from http import HTTPStatus

import pytest
from django.contrib.auth.models import User
from django.test import Client

from easyauth.admin_console import webhook_config_api
from easyauth.applications.models import App, AppMembership
from easyauth.config import net
from easyauth.config.net import ValidatedHttpsUrl
from easyauth.webhooks.models import AppWebhookConfig

pytestmark = pytest.mark.django_db

LOGIN_PASSWORD = "console-login"  # noqa: S105 - 测试登录口令。


@pytest.mark.parametrize(
    "url",
    [
        "file:///dev/zero",
        "http://hooks.example.com/callback",
        "https://user:secret@hooks.example.com/callback",
        "https://hooks.example.com:8443/callback",
        "https://hooks.example.com/callback#fragment",
        "https://127.0.0.1/callback",
        "https://169.254.169.254/latest/meta-data",
    ],
)
def test_webhook_config_rejects_unsafe_url_without_persisting(url: str) -> None:
    client, app = _owner_client_and_app("webhook-config-invalid")

    response = client.put(
        _url(app),
        data=json.dumps(_payload(url)),
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert not AppWebhookConfig.objects.filter(app=app).exists()


def test_webhook_config_rejects_hostname_resolving_to_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app = _owner_client_and_app("webhook-config-private-dns")

    def private_dns(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 443))]

    monkeypatch.setattr(net.socket, "getaddrinfo", private_dns)

    response = client.put(
        _url(app),
        data=json.dumps(_payload("https://internal.example/callback")),
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert not AppWebhookConfig.objects.filter(app=app).exists()


def test_webhook_config_persists_exact_per_app_host_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app = _owner_client_and_app("webhook-config-allowlist")

    def validate(url: str, *, dns_timeout_seconds: float) -> ValidatedHttpsUrl:
        assert url.startswith("https://")
        assert dns_timeout_seconds > 0
        host = "hooks.example.com" if "hooks." in url else "lifecycle.example.com"
        return ValidatedHttpsUrl(host, 443, "/callback", ("8.8.8.8",))

    monkeypatch.setattr(webhook_config_api, "validate_public_https_url", validate)
    payload = _payload("https://hooks.example.com/callback")
    payload["handover_url"] = "https://lifecycle.example.com/handover"

    response = client.put(
        _url(app),
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.OK
    config = AppWebhookConfig.objects.get(app=app)
    assert config.allowed_hosts == ["hooks.example.com", "lifecycle.example.com"]


def _owner_client_and_app(suffix: str) -> tuple[Client, App]:
    username = f"{suffix}-owner"
    _ = User.objects.create_user(username=username, password=LOGIN_PASSWORD)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_PASSWORD) is True
    app = App.objects.create(app_key=f"{suffix}-app", name=suffix)
    _ = AppMembership.objects.create(app=app, user_id=username, role="owner")
    return client, app


def _url(app: App) -> str:
    return f"/console/api/v1/apps/{app.app_key}/webhook-config"


def _payload(approval_url: str) -> dict[str, object]:
    return {
        "enabled": True,
        "approval_callback_url": approval_url,
        "handover_url": "",
        "onboard_url": "",
        "rotate_secret": False,
    }
