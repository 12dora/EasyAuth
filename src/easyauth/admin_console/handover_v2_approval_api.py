"""处理控制台交接 v2 的审批规则替换查询与解决。"""

from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar, Protocol, cast

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.handover_v2_support import not_found
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.lifecycle.api_errors import map_handover_exception, reason_error
from easyauth.lifecycle.approvals import resolve_approval_rule_replacement
from easyauth.lifecycle.errors import HandoverConflictError
from easyauth.lifecycle.models import ApprovalRuleReplacementRequired


class ResolveReplacementPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    approver_user_ids: list[str] = Field(min_length=1)


class _ApprovalRuleWithAppId(Protocol):
    app_id: int


def console_approval_rule_replacements(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    resolved_raw = request.GET.get("resolved", "false").strip().lower()
    qs = ApprovalRuleReplacementRequired.objects.select_related(
        "approval_rule",
        "departed_user",
    )
    if resolved_raw in {"false", "0", ""}:
        qs = qs.filter(resolved_at__isnull=True)
    elif resolved_raw in {"true", "1"}:
        qs = qs.filter(resolved_at__isnull=False)
    total = qs.count()
    items: list[JsonValue] = [
        {
            "id": row.id,
            "approval_rule": {
                "id": row.approval_rule_id,
                "app_id": cast(
                    "_ApprovalRuleWithAppId",
                    cast("object", row.approval_rule),
                ).app_id,
            },
            "departed_user": {
                "user_id": row.departed_user.authentik_user_id,
                "name": row.departed_user.name,
            },
            "reason": row.reason,
            "created_at": datetime_value(row.created_at),
        }
        for row in qs.order_by("-created_at", "-id")[:200]
    ]
    response_payload: dict[str, JsonValue] = {"items": items, "total": total}
    return json_response(response_payload)


def console_approval_rule_replacement_resolve(
    request: HttpRequest,
    replacement_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    return _resolve_approval_rule_replacement(request, replacement_id, actor_id=actor_id)


def _resolve_approval_rule_replacement(
    request: HttpRequest,
    replacement_id: int,
    *,
    actor_id: str,
) -> JsonResponse:
    try:
        payload = ResolveReplacementPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    try:
        row = resolve_approval_rule_replacement(
            replacement_id,
            approver_user_ids=payload.approver_user_ids,
            actor_id=actor_id,
        )
    except LookupError:
        return not_found()
    except HandoverConflictError as error:
        mapped = map_handover_exception(error)
        return mapped or reason_error("already_resolved")
    except ValueError as error:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    return json_response(
        {
            "id": row.id,
            "resolved_at": datetime_value(row.resolved_at),
            "resolved_by": row.resolved_by,
        },
    )
