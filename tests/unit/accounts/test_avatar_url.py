from __future__ import annotations

import pytest

from easyauth.accounts.avatar_url import is_safe_avatar_url, safe_avatar_url


@pytest.mark.parametrize(
    "value",
    [
        "https://static-legacy.dingtalk.com/media/user.jpg",
        "/media/avatars/user.png",
        "/avatars/user.png?v=1",
    ],
)
def test_safe_avatar_url_keeps_https_and_same_origin(value: str) -> None:
    assert is_safe_avatar_url(value) is True
    assert safe_avatar_url(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "data:image/svg+xml;base64,PHN2Zy4uLg==",
        "http://authentik.example.test/avatar.png",
        "javascript:alert(1)",
        "//evil.example.test/avatar.png",
        "https://",
        "/\\evil",
    ],
)
def test_safe_avatar_url_rejects_empty_and_unsafe_schemes(value: str) -> None:
    assert is_safe_avatar_url(value) is False
    assert safe_avatar_url(value) == ""
