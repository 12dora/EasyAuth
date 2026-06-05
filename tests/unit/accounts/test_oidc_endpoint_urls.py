from __future__ import annotations

import pytest

from easyauth.accounts import oidc_exchange
from easyauth.accounts.auth import OidcSessionError


def test_local_loopback_http_oidc_endpoint_is_allowed_for_dev() -> None:
    # Given
    endpoint = "http://127.0.0.1:19000/application/o/token/"

    # When
    request = oidc_exchange.oidc_endpoint_request(
        endpoint,
        headers={"Accept": "application/json"},
    )

    # Then
    assert request.full_url == endpoint


def test_docker_host_http_oidc_endpoint_is_allowed_for_dev_container() -> None:
    # Given
    endpoint = "http://host.docker.internal:19000/application/o/token/"

    # When
    request = oidc_exchange.oidc_endpoint_request(
        endpoint,
        headers={"Accept": "application/json"},
    )

    # Then
    assert request.full_url == endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://authentik.example.test/application/o/token/",
        "http://192.168.1.10:19000/application/o/token/",
    ],
)
def test_non_loopback_http_oidc_endpoint_is_rejected(endpoint: str) -> None:
    # Given

    # When
    with pytest.raises(OidcSessionError) as error:
        _ = oidc_exchange.oidc_endpoint_request(
            endpoint,
            headers={"Accept": "application/json"},
        )

    # Then
    assert "endpoint must use HTTPS" in str(error.value)
