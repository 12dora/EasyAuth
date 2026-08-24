"""处理生命周期转岗授权差异的生成与确认。"""

from __future__ import annotations

from http import HTTPStatus

from django.http import HttpRequest, JsonResponse
from pydantic import ValidationError

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.lifecycle_api_serializers import (
    GrantDiffBuildPayload,
    GrantDiffConfirmPayload,
    not_found,
    plan_item,
    task_or_none,
    validation_error,
)
from easyauth.api.errors import ErrorCode
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.models import HandoverTask, OnboardingTemplate
from easyauth.lifecycle.transfer import build_transfer_grant_diff, confirm_transfer_grant_diff


def lifecycle_grant_diff(
    request: HttpRequest,
    task_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    task = task_or_none(task_id)
    if task is None:
        return not_found("交接单不存在。")
    return _build_grant_diff(request, task)


def _build_grant_diff(request: HttpRequest, task: HandoverTask) -> JsonResponse:
    try:
        payload = GrantDiffBuildPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return validation_error("差异参数无效。", {"errors": str(exc)})
    template = OnboardingTemplate.objects.filter(id=payload.template_id, is_active=True).first()
    if template is None:
        return not_found("岗位模板不存在或未启用。")
    try:
        plan = build_transfer_grant_diff(task=task, template=template)
    except HandoverConflictError as error:
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.CONFLICT,
        )
    return json_response({"transfer_plan": plan_item(plan)})


def lifecycle_grant_diff_confirm(
    request: HttpRequest,
    task_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    task = task_or_none(task_id)
    if task is None:
        return not_found("交接单不存在。")
    return _confirm_grant_diff(request, task, actor_id)


def _confirm_grant_diff(
    request: HttpRequest,
    task: HandoverTask,
    actor_id: str,
) -> JsonResponse:
    try:
        payload = GrantDiffConfirmPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return validation_error("确认参数无效。", {"errors": str(exc)})
    try:
        plan = confirm_transfer_grant_diff(
            task=task,
            revoke_keys=payload.revoke_keys,
            add_keys=payload.add_keys,
            plan_revision=payload.plan_revision,
            actor_id=actor_id,
        )
    except HandoverConflictError as error:
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.CONFLICT,
        )
    except HandoverError as error:
        return validation_error(str(error))
    return json_response({"transfer_plan": plan_item(plan)})
