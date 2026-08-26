# 本地超管拆分模块的无环叶子: 会话映射与 WebAuthn RP 名称。
# totp / passkeys / 门面均可导入本模块; 本模块不回引它们。
from __future__ import annotations

from collections.abc import Mapping
from typing import Final, cast

from django.conf import settings as django_settings

SETTING_WEBAUTHN_RP_NAME: Final = "EASYAUTH_WEBAUTHN_RP_NAME"


def session_mapping(value: object) -> Mapping[str, object] | None:
    return object_mapping(value)


def object_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    mapping = cast("Mapping[object, object]", value)
    if not all(isinstance(key, str) for key in mapping):
        return None
    return cast("Mapping[str, object]", mapping)


def webauthn_rp_name() -> str:
    value: object = getattr(django_settings, SETTING_WEBAUTHN_RP_NAME, "EasyAuth")
    return value if isinstance(value, str) and value else "EasyAuth"
