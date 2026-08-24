"""提供门户交接授权项, 覆盖项和资产类型端点。"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import ClassVar, Final, Literal, cast

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.responses import error_response, json_response
from easyauth.lifecycle.api_errors import map_handover_exception, reason_error
from easyauth.lifecycle.api_payloads import asset_type_item
from easyauth.lifecycle.assignments import (
    OverrideEntry,
    list_overrides,
    patch_asset_type_defaults,
    put_overrides,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover_validation import FetchActionItemsSpec, fetch_action_items
from easyauth.portal.handover_api import (
    action_for_user,
    method_not_allowed,
    parse_int,
    parse_page,
    portal_user,
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
    action: Literal["transfer", "release", "skip"]
    to_user_id: str | None = Field(default=None, max_length=128)
    label: str = Field(default="", max_length=120)


class OverridesPutPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    overrides_version: int = Field(ge=0)
    overrides: list[OverrideItemPayload] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _OverrideRequest:
    user: UserMirror
    task_id: int
    app_key: str
    asset_type: str


def portal_handover_items(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    match portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed()
    action = action_for_user(user, task_id, app_key, require_assignee=False)
    if isinstance(action, JsonResponse):
        return action
    page = parse_page(request.GET.get("page"))
    if page is None:
        return reason_error("items_page_out_of_range")
    page_size = parse_int(request.GET.get("page_size"), default=ITEMS_DEFAULT_PAGE_SIZE)
    page_size = min(max(page_size, 1), ITEMS_MAX_PAGE_SIZE)
    q = request.GET.get("q", "")
    try:
        result = fetch_action_items(
            action,
            FetchActionItemsSpec(
                asset_type=asset_type,
                page=page,
                page_size=page_size,
                q=q,
                actor_id=user.authentik_user_id,
            ),
        )
    except (HandoverConflictError, HandoverError, HookCallError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            {"reason": str(error)},
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response(result)  # type: ignore[arg-type]


def portal_handover_overrides(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    match portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    override_request = _OverrideRequest(user, task_id, app_key, asset_type)
    if request.method == "GET":
        return _get_portal_overrides(override_request)
    if request.method == "PUT":
        return _put_portal_overrides(request, override_request)
    return method_not_allowed()


def portal_handover_asset_type(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    asset_type: str,
) -> JsonResponse:
    match portal_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "PATCH":
        return method_not_allowed()
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
        with transaction.atomic():
            action = action_for_user(
                user,
                task_id,
                app_key,
                require_assignee=True,
                lock_for_mutation=True,
            )
            if isinstance(action, JsonResponse):
                return action
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
        {
            "asset_type": asset_type_item(asset),
            "confirm_version": confirm_version,
        },
    )


def _get_portal_overrides(spec: _OverrideRequest) -> JsonResponse:
    try:
        action = action_for_user(
            spec.user,
            spec.task_id,
            spec.app_key,
            require_assignee=False,
        )
        if isinstance(action, JsonResponse):
            return action
        payload = cast("dict[str, JsonValue]", list_overrides(action, type_key=spec.asset_type))
        return json_response(payload)
    except HandoverError as error:
        return error_response(
            ErrorCode.NOT_FOUND,
            str(error),
            status=HTTPStatus.NOT_FOUND,
        )


def _put_portal_overrides(request: HttpRequest, spec: _OverrideRequest) -> JsonResponse:
    try:
        payload = OverridesPutPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    asset_ids = [item.asset_id for item in payload.overrides]
    if len(asset_ids) != len(set(asset_ids)):
        return reason_error("duplicate_assignment")
    try:
        with transaction.atomic():
            action = action_for_user(
                spec.user,
                spec.task_id,
                spec.app_key,
                require_assignee=True,
                lock_for_mutation=True,
            )
            if isinstance(action, JsonResponse):
                return action
            result = put_overrides(
                action,
                type_key=spec.asset_type,
                overrides_version=payload.overrides_version,
                overrides=[
                    OverrideEntry(
                        asset_id=item.asset_id,
                        action=item.action,
                        to_user_id=item.to_user_id,
                        label=item.label,
                    )
                    for item in payload.overrides
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
