from __future__ import annotations

from http import HTTPStatus
from typing import Protocol

import pytest
from django.http import HttpRequest, JsonResponse
from django.test import Client, override_settings

from easyauth.config.middleware import SafeNotFoundMiddleware

pytestmark = pytest.mark.django_db


class _TestResponse(Protocol):
    content: bytes
    status_code: int


def test_not_found_page_uses_safe_branded_page_without_urlconf_details() -> None:
    client = Client()

    with override_settings(DEBUG=False):
        response = client.get("/missing/internal/path/")

    _assert_safe_not_found_page(response)


def test_root_url_redirects_to_portal() -> None:
    client = Client()

    response = client.get("/")

    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/portal/"


def test_debug_not_found_page_does_not_expose_urlconf_details() -> None:
    client = Client()

    with override_settings(DEBUG=True):
        response = client.get("/missing/internal/path/")

    _assert_safe_not_found_page(response)


def test_disabled_dev_login_uses_safe_not_found_page_in_debug_mode() -> None:
    client = Client()

    with override_settings(DEBUG=True, EASYAUTH_ENABLE_DEV_LOGIN=False):
        response = client.get("/auth/dev-login/")

    html = response.content.decode()
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert "页面没有找到" in html
    assert "Using the URLconf defined in" not in html


def test_safe_not_found_middleware_does_not_replace_json_not_found_response() -> None:
    middleware = SafeNotFoundMiddleware(
        lambda _request: JsonResponse(
            {"error": {"code": "NOT_FOUND"}},
            status=HTTPStatus.NOT_FOUND,
        ),
    )

    response = middleware(HttpRequest())

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.headers["Content-Type"].startswith("application/json")
    assert response.content == b'{"error": {"code": "NOT_FOUND"}}'


def _assert_safe_not_found_page(response: _TestResponse) -> None:
    html = response.content.decode()
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert "页面没有找到" in html
    assert 'href="/auth/login/?next=/portal/"' in html
    assert 'href="/portal/"' in html
    assert "Using the URLconf defined in" not in html
    assert "tried these URL patterns" not in html
    assert "The current path" not in html
    assert "admin/" not in html
