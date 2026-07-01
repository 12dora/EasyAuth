from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.approval_rule_handlers import (
    ApprovalRulePatchError,
    patch_approval_rule,
)
from easyauth.admin_console.approval_rule_payloads import (
    ApprovalRuleCreatePayload,
    TargetType,
    create_target_key,
    create_target_type,
    payload_approvers,
)
from easyauth.admin_console.approval_rule_targets import (
    ApprovalRuleTarget,
    approval_rule_item,
    approval_rule_items,
    approval_rule_target_for_key,
)
from easyauth.admin_console.configuration import (
    ApprovalRuleCreateMutation,
    ConsoleMutationActor,
    create_approval_rule,
)
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor, can_manage_app, can_view_app

type AppApiResult = App | JsonResponse
type WriteContextResult = WriteContext | JsonResponse
type TargetResult = ApprovalRuleTarget | JsonResponse


class WriteContext(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    app: App
    actor: ConsoleActor


def console_approval_rules(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method == "GET":
        match _read_context(request, app_key):
            case App() as app:
                return _json_response({"items": approval_rule_items(app)})
            case JsonResponse() as response:
                return response
    if request.method == "POST":
        match _write_context(request, app_key):
            case WriteContext(app=app, actor=actor):
                return _create_rule(request, app, actor)
            case JsonResponse() as response:
                return response
    return _method_not_allowed_response()


def console_approval_rule_detail(
    request: HttpRequest,
    app_key: str,
    approval_rule_id: int,
) -> JsonResponse:
    if request.method != "PATCH":
        return _method_not_allowed_response()

    match _write_context(request, app_key):
        case WriteContext(app=app, actor=actor):
            return _patch_rule(request, app, actor, approval_rule_id)
        case JsonResponse() as response:
            return response


def _create_rule(request: HttpRequest, app: App, actor: ConsoleActor) -> JsonResponse:
    match _create_payload(request):
        case ApprovalRuleCreatePayload() as payload:
            pass
        case JsonResponse() as response:
            return response

    match _target_for_key(app, create_target_type(payload), create_target_key(payload)):
        case ApprovalRuleTarget() as target:
            pass
        case JsonResponse() as response:
            return response

    approver_userids = payload_approvers(payload)
    if approver_userids is None:
        return _validation_error_response("审批规则提交参数无效。")
    try:
        rule = create_approval_rule(
            ApprovalRuleCreateMutation(
                app=app,
                authorization_group=target.authorization_group,
                permission=target.permission,
                approver_userids=approver_userids,
                is_active=payload.is_active,
                actor=ConsoleMutationActor(actor_id=actor.user_id),
            ),
        )
    except DjangoValidationError as error:
        return _validation_error_response("审批规则参数无效。", {"errors": str(error)})
    return _json_response({"approval_rule": approval_rule_item(rule)}, status=HTTPStatus.CREATED)


def _patch_rule(
    request: HttpRequest,
    app: App,
    actor: ConsoleActor,
    approval_rule_id: int,
) -> JsonResponse:
    try:
        payload = patch_approval_rule(app, approval_rule_id, request.body, actor.user_id)
    except ApprovalRulePatchError as error:
        return _error_response(error.error_code, error.message, error.details, status=error.status)
    return _json_response(payload)


def _create_payload(request: HttpRequest) -> ApprovalRuleCreatePayload | JsonResponse:
    try:
        return ApprovalRuleCreatePayload.model_validate_json(request.body)
    except ValidationError as error:
        return _validation_error_response("审批规则提交参数无效。", {"errors": str(error)})


def _read_context(request: HttpRequest, app_key: str) -> AppApiResult:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return _error_response(ErrorCode.NOT_FOUND, "App 不存在。", status=HTTPStatus.NOT_FOUND)
    if not can_view_app(actor, app):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner/developer 可以访问该 App 审批规则。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app


def _write_context(request: HttpRequest, app_key: str) -> WriteContextResult:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return _error_response(ErrorCode.NOT_FOUND, "App 不存在。", status=HTTPStatus.NOT_FOUND)
    if not can_manage_app(actor, app):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner 可以维护该 App 审批规则。",
            status=HTTPStatus.FORBIDDEN,
        )
    return WriteContext(app=app, actor=actor)


def _target_for_key(app: App, target_type: TargetType, target_key: str) -> TargetResult:
    match approval_rule_target_for_key(app=app, target_type=target_type, target_key=target_key):
        case ApprovalRuleTarget() as target:
            return target
        case None:
            pass
    match target_type:
        case "authorization_group":
            message = "AuthorizationGroup 不属于当前 App。"
        case "permission":
            message = "Permission 不属于当前 App。"
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        status=HTTPStatus.BAD_REQUEST,
    )


def _validation_error_response(
    message: str,
    details: dict[str, JsonValue] | None = None,
) -> JsonResponse:
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        details,
        status=HTTPStatus.BAD_REQUEST,
    )


def _method_not_allowed_response() -> JsonResponse:
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        "不支持的请求方法。",
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )
