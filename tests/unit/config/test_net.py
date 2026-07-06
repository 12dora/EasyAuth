from __future__ import annotations

import pytest

from easyauth.config.net import InsecureUrlError, require_secure_url


@pytest.mark.parametrize(
    "url",
    [
        "https://authentik.example.com",
        "http://localhost:19000",
        "http://127.0.0.1:19000",
        # Docker 容器访问宿主的专用主机名: 流量只走本机 bridge, 与环回同一信任边界。
        "http://host.docker.internal:19000",
    ],
)
def test_require_secure_url_allows_https_and_local_http(url: str) -> None:
    require_secure_url(url, allow_local_http=True)


@pytest.mark.parametrize(
    "url",
    [
        "http://authentik.example.com",
        "http://192.168.1.10:19000",
        "http://evil-host.docker.internal.example.com",
    ],
)
def test_require_secure_url_rejects_remote_http(url: str) -> None:
    with pytest.raises(InsecureUrlError):
        require_secure_url(url, allow_local_http=True)


def test_require_secure_url_rejects_local_http_when_not_allowed() -> None:
    with pytest.raises(InsecureUrlError):
        require_secure_url("http://localhost:19000", allow_local_http=False)
