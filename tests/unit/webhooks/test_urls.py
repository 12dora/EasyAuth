from __future__ import annotations

import socket
import threading

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from easyauth.config.net import (
    BlockedHostError,
    InvalidWebhookUrlError,
    parse_https_url,
    validate_public_https_url,
)
from easyauth.config.settings.base import parse_trusted_webhook_hosts

TRUSTED_HOST = "etrade.jiefakj.com"
PRIVATE_ADDRESS = "172.17.0.1"
SHARED_ADDRESS = "100.64.0.1"


def _stub_dns(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    def fake_dns(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    def fake_resolve(
        _hostname: str,
        *,
        port: int,
        timeout_seconds: float | None,
    ) -> tuple[tuple[object, ...], ...]:
        _ = (port, timeout_seconds)
        return ((socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)),)

    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
    monkeypatch.setattr("easyauth.config.net_dns._resolve_addresses", fake_resolve)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://example.com/hook",
        "https://user:secret@example.com/hook",
        "https://example.com:8443/hook",
        "https://example.com/hook#fragment",
        "https://example.com./hook",
        "https://127.0.0.1/hook",
        "https://169.254.169.254/latest/meta-data",
    ],
)
def test_parse_https_url_rejects_unsafe_shapes(url: str) -> None:
    with pytest.raises((BlockedHostError, InvalidWebhookUrlError)):
        _ = parse_https_url(url)


def test_validate_public_https_url_rejects_private_dns_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def private_dns(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", private_dns)

    with pytest.raises(BlockedHostError):
        _ = validate_public_https_url("https://hooks.example.com/callback")


def test_validate_public_https_url_rejects_any_mixed_private_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mixed_dns(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed_dns)

    with pytest.raises(BlockedHostError):
        _ = validate_public_https_url("https://hooks.example.com/callback")


def test_validate_public_https_url_enforces_per_app_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def public_dns(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", public_dns)

    with pytest.raises(InvalidWebhookUrlError, match="允许列表"):
        _ = validate_public_https_url(
            "https://attacker.example/callback",
            allowed_hosts=("hooks.example.com",),
        )

    result = validate_public_https_url(
        "https://hooks.example.com/callback?event=1",
        allowed_hosts=("hooks.example.com",),
    )
    assert result.hostname == "hooks.example.com"
    assert result.addresses == ("8.8.8.8",)
    assert result.request_target == "/callback?event=1"


def test_parse_https_url_percent_encodes_unicode_request_target() -> None:
    result = parse_https_url("https://hooks.example.com/回调?q=中文")

    assert result.request_target == "/%E5%9B%9E%E8%B0%83?q=%E4%B8%AD%E6%96%87"


def test_validate_public_https_url_bounds_dns_resolution_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_resolver = threading.Event()

    def slow_dns(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        _ = release_resolver.wait(timeout=1)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", slow_dns)

    try:
        with pytest.raises(BlockedHostError, match="解析超时"):
            _ = validate_public_https_url(
                "https://hooks.example.com/callback",
                dns_timeout_seconds=0.01,
            )
    finally:
        release_resolver.set()


def test_validate_public_https_url_rejects_private_dns_when_allowlist_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_dns(monkeypatch, PRIVATE_ADDRESS)

    with (
        override_settings(EASYAUTH_TRUSTED_WEBHOOK_HOSTS=()),
        pytest.raises(BlockedHostError),
    ):
        _ = validate_public_https_url(f"https://{TRUSTED_HOST}/callback")


@pytest.mark.parametrize("address", [PRIVATE_ADDRESS, SHARED_ADDRESS])
def test_validate_public_https_url_accepts_trusted_host_private_address(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    address: str,
) -> None:
    _stub_dns(monkeypatch, address)

    with (
        override_settings(EASYAUTH_TRUSTED_WEBHOOK_HOSTS=(TRUSTED_HOST,)),
        caplog.at_level("INFO", logger="easyauth.config.net_policy"),
    ):
        result = validate_public_https_url(f"https://{TRUSTED_HOST}/callback")

    assert result.hostname == TRUSTED_HOST
    assert result.addresses == (address,)
    assert result.allow_insecure_http is False
    assert result.port == 443
    assert any(
        TRUSTED_HOST in record.message and address in record.message for record in caplog.records
    )


def test_validate_public_https_url_accepts_trusted_host_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_dns(monkeypatch, PRIVATE_ADDRESS)

    with override_settings(EASYAUTH_TRUSTED_WEBHOOK_HOSTS=(TRUSTED_HOST,)):
        result = validate_public_https_url("https://ETRADE.JIEFAKJ.COM/callback")

    assert result.hostname == TRUSTED_HOST
    assert result.addresses == (PRIVATE_ADDRESS,)


def test_validate_public_https_url_rejects_trusted_host_http_and_non_443_port() -> None:
    with override_settings(EASYAUTH_TRUSTED_WEBHOOK_HOSTS=(TRUSTED_HOST,)):
        with pytest.raises(InvalidWebhookUrlError):
            _ = parse_https_url(f"http://{TRUSTED_HOST}/callback")
        with pytest.raises(InvalidWebhookUrlError):
            _ = parse_https_url(f"https://{TRUSTED_HOST}:8443/callback")


def test_validate_public_https_url_rejects_trusted_host_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_dns(monkeypatch, "127.0.0.1")

    with (
        override_settings(EASYAUTH_TRUSTED_WEBHOOK_HOSTS=(TRUSTED_HOST,)),
        pytest.raises(BlockedHostError),
    ):
        _ = validate_public_https_url(f"https://{TRUSTED_HOST}/callback")


def test_validate_public_https_url_rejects_subdomain_of_trusted_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_dns(monkeypatch, PRIVATE_ADDRESS)

    with (
        override_settings(EASYAUTH_TRUSTED_WEBHOOK_HOSTS=(TRUSTED_HOST,)),
        pytest.raises(BlockedHostError),
    ):
        _ = validate_public_https_url("https://api.etrade.jiefakj.com/callback")


@pytest.mark.parametrize("raw", ["*.example.com", "10.0.0.1", "host:443"])
def test_parse_trusted_webhook_hosts_rejects_wildcard_ip_and_port(raw: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="精确主机名"):
        _ = parse_trusted_webhook_hosts(raw)


def test_parse_trusted_webhook_hosts_normalises_and_drops_empties() -> None:
    assert parse_trusted_webhook_hosts("") == ()
    assert parse_trusted_webhook_hosts(" ETRADE.JIEFAKJ.COM , , tradedata.jiefakj.com ") == (
        "etrade.jiefakj.com",
        "tradedata.jiefakj.com",
    )
