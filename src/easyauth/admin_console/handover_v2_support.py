"""提供控制台交接 v2 端点共用的查询与错误响应。"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from easyauth.admin_console.api_responses import error_response
from easyauth.api.errors import ErrorCode
from easyauth.lifecycle.models import HandoverAppAction

if TYPE_CHECKING:
    from django.http import JsonResponse


def action_or_none(task_id: int, app_key: str) -> HandoverAppAction | None:
    return (
        HandoverAppAction.objects.select_related(
            "app",
            "task",
            "task__subject_user",
            "grant_receiver",
        )
        .filter(task_id=task_id, app__app_key=app_key)
        .first()
    )


def parse_int(raw: str | None, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def not_found() -> JsonResponse:
    return error_response(ErrorCode.NOT_FOUND, "资源不存在。", status=HTTPStatus.NOT_FOUND)
