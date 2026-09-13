from __future__ import annotations

import pytest

from easyauth.accounts.avatar_url import (
    classify_avatar_url,
    is_safe_avatar_url,
    preferred_avatar_url,
    resolve_avatar_url,
    safe_avatar_url,
)
from easyauth.accounts.models import UserMirror

PHOTO = "https://static-legacy.dingtalk.com/media/user.jpg"
SAME_ORIGIN = "/media/avatars/user.png"
GENERATED_SVG = "data:image/svg+xml;base64,PHN2Zy4uLg=="
GENERATED_PNG = "data:image/png;base64,AAAA"
GENERATED_JPEG = "data:image/jpeg;base64,AAAA"
GENERATED_WEBP = "data:image/webp;base64,AAAA"
_DATA_PREFIX = "data:image/png;base64,"
_MAX_LENGTH = 16384


@pytest.mark.parametrize(
    "value",
    [PHOTO, SAME_ORIGIN, "/avatars/user.png?v=1"],
)
def test_safe_avatar_url_keeps_https_and_same_origin(value: str) -> None:
    assert classify_avatar_url(value) == "photo"
    assert is_safe_avatar_url(value) is True
    assert safe_avatar_url(value) == value


@pytest.mark.parametrize(
    "value",
    [GENERATED_SVG, GENERATED_PNG, GENERATED_JPEG, GENERATED_WEBP],
)
def test_safe_avatar_url_keeps_inline_generated_images(value: str) -> None:
    assert classify_avatar_url(value) == "generated"
    assert is_safe_avatar_url(value) is True
    assert safe_avatar_url(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://authentik.example.test/avatar.png",
        "javascript:alert(1)",
        "//evil.example.test/avatar.png",
        "https://",
        "/\\evil",
        "data:image/svg+xml;charset=utf-8;base64,PHN2Zy4uLg==",
        "data:image/svg+xml;utf8,PHN2Zy4uLg==",
        "data:text/html;base64,PHNjcmlwdD4=",
        "data:image/gif;base64,AAAA",
        "DATA:image/png;base64,AAAA",
        "data:image/png;base64,AAA AAA",
        "data:image/png;base64,",
        "data:image/jpg;base64,AAAA",
    ],
)
def test_safe_avatar_url_rejects_empty_and_unsafe_schemes(value: str) -> None:
    assert classify_avatar_url(value) == ""
    assert is_safe_avatar_url(value) is False
    assert safe_avatar_url(value) == ""


def test_safe_avatar_url_rejects_inline_image_over_length_cap() -> None:
    allowed = _DATA_PREFIX + ("A" * (_MAX_LENGTH - len(_DATA_PREFIX)))
    too_long = allowed + "A"
    assert classify_avatar_url(allowed) == "generated"
    assert safe_avatar_url(allowed) == allowed
    assert classify_avatar_url(too_long) == ""
    assert safe_avatar_url(too_long) == ""


def test_resolve_avatar_url_photo_always_wins() -> None:
    assert resolve_avatar_url("", PHOTO) == PHOTO
    assert resolve_avatar_url(GENERATED_SVG, PHOTO) == PHOTO
    assert resolve_avatar_url(SAME_ORIGIN, PHOTO) == PHOTO


def test_resolve_avatar_url_generated_does_not_overwrite_photo() -> None:
    assert resolve_avatar_url(PHOTO, GENERATED_SVG) == PHOTO
    assert resolve_avatar_url(SAME_ORIGIN, GENERATED_PNG) == SAME_ORIGIN


def test_resolve_avatar_url_generated_writes_when_current_is_empty_or_generated() -> None:
    assert resolve_avatar_url("", GENERATED_SVG) == GENERATED_SVG
    assert resolve_avatar_url(GENERATED_PNG, GENERATED_SVG) == GENERATED_SVG


def test_resolve_avatar_url_keeps_current_when_incoming_is_empty_or_unsafe() -> None:
    assert resolve_avatar_url(PHOTO, "") == PHOTO
    assert resolve_avatar_url(PHOTO, "javascript:alert(1)") == PHOTO
    assert resolve_avatar_url(GENERATED_SVG, "data:text/html;base64,AAAA") == GENERATED_SVG
    assert resolve_avatar_url("", "") == ""


def test_preferred_avatar_url_photo_beats_generated() -> None:
    assert preferred_avatar_url(GENERATED_SVG, PHOTO, GENERATED_PNG) == PHOTO
    assert preferred_avatar_url(GENERATED_SVG, "javascript:alert(1)") == GENERATED_SVG
    assert preferred_avatar_url("", "data:text/html;base64,AAAA") == ""


@pytest.mark.django_db
def test_user_mirror_full_clean_accepts_generated_svg_over_512_chars() -> None:
    avatar = _DATA_PREFIX + ("A" * 600)
    user = UserMirror(authentik_user_id="avatar-svg-full-clean", avatar_url=avatar)
    user.full_clean()
    user.save()
    user.refresh_from_db()
    assert user.avatar_url == avatar
