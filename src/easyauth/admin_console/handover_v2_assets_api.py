"""处理控制台交接 v2 的应用、候选人、授权项与资产配置。"""

from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar, Final, cast

from django.db.models import Count
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.accounts.models import UserMirror
from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.handover_v2_support import action_or_none, not_found, parse_int
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App
from easyauth.lifecycle.api_errors import map_handover_exception
from easyauth.lifecycle.api_payloads import asset_type_item
from easyauth.lifecycle.assignments import (
    OverrideEntry,
    list_overrides,
    patch_asset_type_defaults,
    put_overrides,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover_validation import FetchActionItemsSpec, fetch_action_items
from easyauth.lifecycle.jurisdiction import list_receiver_candidates
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    TASK_OPEN_STATUSES,
    HandoverAppAction,
    HandoverTask,
)
from easyauth.webhooks.hooks import HookCallError

ITEMS_DEFAULT_PAGE_SIZE: Final = 50
ITEMS_MAX_PAGE_SIZE: Final = 200


class AssetTypePatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    default_action: str = Field(min_length=1, max_length=8)
    default_to_user_id: str | None = Field(default=None, max_length=128)


class OverrideItemPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    asset_id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=8)
    to_user_id: str | None = Field(default=None, max_length=128)
    label: str = Field(default="", max_length=120)


class OverridesPutPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    overrides_version: int = Field(ge=0)
    overrides: list[OverrideItemPayload] = Field(default_factory=list)


def console_handover_blocked_apps(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    rows = (
        HandoverAppAction.objects.filter(
            status=ACTION_STATUS_BLOCKED,
            task__status__in=TASK_OPEN_STATUSES,
        )
        .values("app_id", "app__app_key", "app__name", "app__alias")
        .annotate(blocked_task_count=Count("task_id", distinct=True))
        .order_by("app__app_key")
    )
    apps: list[JsonValue] = [
        {
            "app_key": row["app__app_key"],
            "app_name": row["app__name"],
            "app_alias": row["app__alias"],
            "blocked_task_count": row["blocked_task_count"],
        }
        for row in rows
    ]
    task_count = (
        HandoverTask.objects.filter(
            status__in=TASK_OPEN_STATUSES,
            app_actions__status=ACTION_STATUS_BLOCKED,
        )
        .distinct()
        .count()
    )
    response_payload: dict[str, JsonValue] = {
        "app_count": len(apps),
        "task_count": task_count,
        "apps": apps,
    }
    return json_response(response_payload)


def console_handover_app_options(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    # 超管跨部门: 不做管辖校验, subject_user_id 可选
    items: list[JsonValue] = [
        {
            "app_key": app.app_key,
            "app_name": app.name,
            "app_alias": app.alias,
            "handover_capability": app.handover_capability,
            "blocked_reason": (
                ""
                if app.handover_capability == "declared"
                else (
                    "capability_none"
                    if app.handover_capability == "none"
                    else "capability_undeclared"
                )
            ),
        }
        for app in App.objects.filter(is_active=True).order_by("app_key")
    ]
    return json_response({"items": items})


def console_handover_candidates(request: HttpRequest, task_id: int) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    task = HandoverTask.objects.select_related("subject_user").filter(pk=task_id).first()
    if task is None:
        return not_found()
    actor = UserMirror.objects.filter(authentik_user_id=actor_id).first()
    if actor is None:
        actor = task.subject_user
    q = request.GET.get("q", "")
    users = list_receiver_candidates(
        actor,
        subject=task.subject_user,
        q=q,
        exclude_actor=False,
    )
    return json_response(
        {
            "items": [
                {
                    "user_id": u.authentik_user_id,
                    "name": u.name,
                    "department": u.department,
                }
                for u in users
            ],
        },
    )


def console_handover_items(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    action = action_or_none(task_id, app_key)
    if action is None:
        return not_found()
    page = parse_int(request.GET.get("page"), 1)
    page_size = min(
        max(parse_int(request.GET.get("page_size"), ITEMS_DEFAULT_PAGE_SIZE), 1),
        ITEMS_MAX_PAGE_SIZE,
    )
    try:
        result = fetch_action_items(
            action,
            FetchActionItemsSpec(
                asset_type=asset_type,
                page=page,
                page_size=page_size,
                q=request.GET.get("q", ""),
                actor_id=actor_id,
            ),
        )
    except (HandoverConflictError, HandoverError, HookCallError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response(result)  # type: ignore[arg-type]


def console_handover_overrides(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    return _handle_handover_overrides(request, task_id, app_key, asset_type)


def _handle_handover_overrides(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    action = action_or_none(task_id, app_key)
    if action is None:
        return not_found()
    if request.method == "GET":
        return _list_handover_overrides(action, asset_type=asset_type)
    if request.method == "PUT":
        return _put_handover_overrides(request, action, asset_type=asset_type)
    return method_not_allowed_response()


def _list_handover_overrides(
    action: HandoverAppAction,
    *,
    asset_type: str,
) -> JsonResponse:
    try:
        result = list_overrides(action, type_key=asset_type)
        return json_response(cast("dict[str, JsonValue]", result))
    except HandoverError as error:
        return error_response(ErrorCode.NOT_FOUND, str(error), status=HTTPStatus.NOT_FOUND)


def _put_handover_overrides(
    request: HttpRequest,
    action: HandoverAppAction,
    *,
    asset_type: str,
) -> JsonResponse:
    try:
        payload = OverridesPutPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    try:
        result = put_overrides(
            action,
            type_key=asset_type,
            overrides_version=payload.overrides_version,
            overrides=[
                OverrideEntry(
                    asset_id=i.asset_id,
                    action=i.action,
                    to_user_id=i.to_user_id,
                    label=i.label,
                )
                for i in payload.overrides
            ],
        )
    except (HandoverConflictError, HandoverError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response(
        {
            "overrides_version": result.overrides_version,
            "confirm_version": result.confirm_version,
            "override_count": result.override_count,
            "dropped_invalid": result.dropped_invalid,
        },
    )


def console_handover_asset_type(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "PATCH":
        return method_not_allowed_response()
    action = action_or_none(task_id, app_key)
    if action is None:
        return not_found()
    try:
        payload = AssetTypePatchPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    try:
        asset, confirm_version = patch_asset_type_defaults(
            action,
            type_key=asset_type,
            default_action=payload.default_action,
            default_to_user_id=payload.default_to_user_id,
        )
    except (HandoverConflictError, HandoverError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response(
        {"asset_type": asset_type_item(asset), "confirm_version": confirm_version},
    )
