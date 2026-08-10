"""E2E 窄门: EASYAUTH_E2E_ALLOW_INSECURE_WEBHOOK_HOSTS 仅 DEBUG 生效。"""

from __future__ import annotations

import pytest
from django.test import override_settings

from easyauth.config.net import (
    BlockedHostError,
    InvalidWebhookUrlError,
    e2e_allowed_insecure_webhook_hosts,
    parse_https_url,
    validate_public_https_url,
)


def test_e2e_allowlist_inert_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EASYAUTH_E2E_ALLOW_INSECURE_WEBHOOK_HOSTS", raising=False)
    with override_settings(DEBUG=True):
        assert e2e_allowed_insecure_webhook_hosts() == frozenset()
        with pytest.raises((BlockedHostError, InvalidWebhookUrlError)):
            _ = parse_https_url("http://127.0.0.1:18010/hook")
        with pytest.raises((BlockedHostError, InvalidWebhookUrlError)):
            _ = parse_https_url("https://127.0.0.1/hook")


def test_e2e_allowlist_inert_when_debug_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASYAUTH_E2E_ALLOW_INSECURE_WEBHOOK_HOSTS", "127.0.0.1")
    with override_settings(DEBUG=False):
        assert e2e_allowed_insecure_webhook_hosts() == frozenset()
        with pytest.raises((BlockedHostError, InvalidWebhookUrlError)):
            _ = parse_https_url("http://127.0.0.1:18010/api/v1/easyauth/lifecycle/handover")


def test_e2e_allowlist_permits_loopback_http_when_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EASYAUTH_E2E_ALLOW_INSECURE_WEBHOOK_HOSTS", "127.0.0.1")
    with override_settings(DEBUG=True):
        assert e2e_allowed_insecure_webhook_hosts() == frozenset({"127.0.0.1"})
        parsed = parse_https_url(
            "http://127.0.0.1:18010/api/v1/easyauth/lifecycle/handover",
        )
        assert parsed.hostname == "127.0.0.1"
        assert parsed.port == 18010
        assert parsed.allow_insecure_http is True
        assert parsed.request_target == "/api/v1/easyauth/lifecycle/handover"

        validated = validate_public_https_url(
            "http://127.0.0.1:18010/api/v1/easyauth/lifecycle/handover",
            allowed_hosts=("127.0.0.1",),
        )
        assert validated.addresses == ("127.0.0.1",)
        assert validated.allow_insecure_http is True


def test_e2e_allowlist_does_not_open_other_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EASYAUTH_E2E_ALLOW_INSECURE_WEBHOOK_HOSTS", "127.0.0.1")
    with override_settings(DEBUG=True):
        # 未列入 allowlist 的环回/私网仍拒绝
        with pytest.raises((BlockedHostError, InvalidWebhookUrlError)):
            _ = parse_https_url("http://10.0.0.8:8080/hook")
        with pytest.raises((BlockedHostError, InvalidWebhookUrlError)):
            _ = parse_https_url("http://localhost:18010/hook")
        # 公网 https 默认路径不受影响(仍可 parse; DNS 公网校验在 validate 阶段)
        public = parse_https_url("https://hooks.example.com/callback")
        assert public.hostname == "hooks.example.com"
        assert public.allow_insecure_http is False
        assert public.port == 443
