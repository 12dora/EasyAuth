"""门户会话用户: 从 Authentik session 解析在职 UserMirror。"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.http import JsonResponse

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.api.errors import ErrorCode
from easyauth.api.responses import error_response

if TYPE_CHECKING:
    from django.http import HttpRequest

type PortalUserResult = UserMirror | JsonResponse

PORTAL_LOGIN_EXPIRED_MESSAGE = "员工门户登录已失效。"

__all__ = ["PORTAL_LOGIN_EXPIRED_MESSAGE", "portal_user"]


def portal_user(request: HttpRequest) -> PortalUserResult:
    authentik_user_id = request.session.get(AUTHENTIK_SESSION_KEY)
    if not isinstance(authentik_user_id, str):
        return _unauthorized()
    user = UserMirror.objects.filter(
        authentik_user_id=authentik_user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if user is None:
        request.session.pop(AUTHENTIK_SESSION_KEY, None)
        return _unauthorized()
    return user


def _unauthorized() -> JsonResponse:
    return error_response(
        ErrorCode.AUTHENTICATION_FAILED,
        PORTAL_LOGIN_EXPIRED_MESSAGE,
        status=HTTPStatus.UNAUTHORIZED,
    )
