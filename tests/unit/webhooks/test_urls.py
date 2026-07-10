from __future__ import annotations

import socket
import threading

import pytest

from easyauth.config import net
from easyauth.config.net import (
    BlockedHostError,
    InvalidWebhookUrlError,
    parse_https_url,
    validate_public_https_url,
)


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

    monkeypatch.setattr(net.socket, "getaddrinfo", private_dns)

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

    monkeypatch.setattr(net.socket, "getaddrinfo", mixed_dns)

    with pytest.raises(BlockedHostError):
        _ = validate_public_https_url("https://hooks.example.com/callback")


def test_validate_public_https_url_enforces_per_app_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def public_dns(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(net.socket, "getaddrinfo", public_dns)

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


def test_validate_public_https_url_bounds_dns_resolution_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_resolver = threading.Event()

    def slow_dns(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        _ = release_resolver.wait(timeout=1)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(net.socket, "getaddrinfo", slow_dns)

    try:
        with pytest.raises(BlockedHostError, match="解析超时"):
            _ = validate_public_https_url(
                "https://hooks.example.com/callback",
                dns_timeout_seconds=0.01,
            )
    finally:
        release_resolver.set()
