from __future__ import annotations

from django.test import RequestFactory, override_settings

from easyauth.config.rate_limit import client_ip


@override_settings(EASYAUTH_TRUSTED_PROXY_HOPS=0)
def test_client_ip_ignores_forwarded_for_by_default() -> None:
    # 默认不信任客户端可伪造的 X-Forwarded-For, 只用直连对端 REMOTE_ADDR。
    request = RequestFactory().get(
        "/",
        HTTP_X_FORWARDED_FOR="1.2.3.4, 5.6.7.8",
        REMOTE_ADDR="10.0.0.1",
    )
    assert client_ip(request) == "10.0.0.1"


@override_settings(EASYAUTH_TRUSTED_PROXY_HOPS=1)
def test_client_ip_uses_last_forwarded_hop_when_one_proxy_trusted() -> None:
    # 配置 1 层可信反代时, 从 XFF 右起第 1 跳取真实客户端 IP。
    request = RequestFactory().get(
        "/",
        HTTP_X_FORWARDED_FOR="9.9.9.9, 5.6.7.8",
        REMOTE_ADDR="10.0.0.1",
    )
    assert client_ip(request) == "5.6.7.8"


@override_settings(EASYAUTH_TRUSTED_PROXY_HOPS=1)
def test_client_ip_falls_back_to_remote_addr_without_forwarded() -> None:
    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1")
    assert client_ip(request) == "10.0.0.1"
