"""工作通知 OA 头: 应用中文展示名与色带。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from django.conf import settings

from easyauth.applications.notify_appearance import (
    EASYAUTH_NOTIFY_HEAD_BGCOLOR,
    normalize_notify_head_bgcolor,
    palette_notify_head_bgcolor,
)
from easyauth.notify.contracts import NotifyAcceptError

if TYPE_CHECKING:
    from easyauth.applications.models import App

EASYAUTH_DEFAULT_HEAD_TEXT: Final = "统一身份认证"
HEAD_TEXT_REQUIRED_MESSAGE: Final = "应用名称不能为空。"


def is_easyauth_notify_identity(app: App) -> bool:
    return app.app_key == "easyauth" or app.app_key.startswith("easyauth-")


def easyauth_notify_head_text() -> str:
    configured = str(getattr(settings, "EASYAUTH_SITE_TITLE", "")).strip()
    return configured or EASYAUTH_DEFAULT_HEAD_TEXT


def resolve_notify_head(*, app: App, app_display_name: str = "") -> tuple[str, str]:
    """返回 (head.text, head.bgcolor)。展示名永不回落到 app_key。"""
    if is_easyauth_notify_identity(app):
        return easyauth_notify_head_text(), EASYAUTH_NOTIFY_HEAD_BGCOLOR
    text = app_display_name.strip() or app.name.strip()
    if not text:
        raise NotifyAcceptError(
            kind="validation_error",
            message=HEAD_TEXT_REQUIRED_MESSAGE,
            field="app_display_name",
        )
    return text, resolve_app_head_bgcolor(app)


def resolve_app_head_bgcolor(app: App) -> str:
    configured = app.notify_head_bgcolor.strip()
    if not configured:
        return palette_notify_head_bgcolor(app.id)
    return normalize_notify_head_bgcolor(configured)
