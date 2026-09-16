"""工作通知 OA 头: 调用应用中文名与色带。

钉钉发送工作通知时会把 oa.head.text 改写成服务号名称, 调用方中文名不能靠页眉传达。
head.text 仍按登记名填写(非工作通知场景才看得见); 用户可见身份走 body.title 前缀与色带。
"""

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


def resolve_notify_display_name(*, app: App, app_display_name: str = "") -> str:
    """调用方中文名: 供 body.title 前缀。永不回落到 app_key。"""
    if is_easyauth_notify_identity(app):
        return easyauth_notify_head_text()
    text = app_display_name.strip() or app.name.strip()
    if not text:
        raise NotifyAcceptError(
            kind="validation_error",
            message=HEAD_TEXT_REQUIRED_MESSAGE,
            field="app_display_name",
        )
    return text


def resolve_notify_head(*, app: App) -> tuple[str, str]:
    """返回 (head.text, head.bgcolor)。head.text 不含 app_display_name 覆盖。"""
    if is_easyauth_notify_identity(app):
        return easyauth_notify_head_text(), EASYAUTH_NOTIFY_HEAD_BGCOLOR
    text = app.name.strip()
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
