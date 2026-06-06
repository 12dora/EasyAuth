from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from easyauth.admin_console.approval_rule_payloads import (
    ApprovalRuleCreatePayload,
    ApprovalRulePatchPayload,
    TargetType,
    create_target_key,
    create_target_type,
    patch_has_target,
    patch_has_updates,
    patch_target_key,
    patch_target_type,
    payload_approvers,
)
from easyauth.admin_console.approval_rule_targets import (
    ApprovalRuleTarget,
    approval_rule_item,
    approval_rule_items,
    approval_rule_target,
    approval_rule_target_for_key,
    patched_approvers,
)
from easyauth.admin_console.configuration import (
    ApprovalRuleCreateMutation,
    ApprovalRuleMutation,
    ConsoleMutationActor,
    create_approval_rule,
    update_approval_rule,
)
from easyauth.api.errors import ErrorCode, ErrorResponse, JsonValue, build_error_response
from easyauth.applications.models import App, ApprovalRule
from easyauth.applications.ownership import ConsoleActor, can_manage_app, can_view_app

type ConsoleApiResult = ConsoleActor | JsonResponse
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
                role=target.role,
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
    match _patch_payload(request):
        case ApprovalRulePatchPayload() as payload:
            pass
        case JsonResponse() as response:
            return response

    rule = ApprovalRule.objects.filter(app=app, id=approval_rule_id).first()
    if rule is None:
        return _error_response(ErrorCode.NOT_FOUND, "审批规则不存在。", status=HTTPStatus.NOT_FOUND)

    match _patched_target(app, rule, payload):
        case ApprovalRuleTarget() as target:
            pass
        case JsonResponse() as response:
            return response

    approver_userids = patched_approvers(rule, payload_approvers(payload))
    is_active = rule.is_active if payload.is_active is None else payload.is_active
    try:
        updated_rule = update_approval_rule(
            ApprovalRuleMutation(
                app=app,
                rule=rule,
                role=target.role,
                permission=target.permission,
                approver_userids=approver_userids,
                is_active=is_active,
                actor=ConsoleMutationActor(actor_id=actor.user_id),
            ),
        )
    except DjangoValidationError as error:
        return _validation_error_response("审批规则参数无效。", {"errors": str(error)})
    return _json_response({"approval_rule": approval_rule_item(updated_rule)})


def _create_payload(request: HttpRequest) -> ApprovalRuleCreatePayload | JsonResponse:
    try:
        return ApprovalRuleCreatePayload.model_validate_json(request.body)
    except ValidationError as error:
        return _validation_error_response("审批规则提交参数无效。", {"errors": str(error)})


def _patch_payload(request: HttpRequest) -> ApprovalRulePatchPayload | JsonResponse:
    try:
        payload = ApprovalRulePatchPayload.model_validate_json(request.body)
    except ValidationError as error:
        return _validation_error_response("审批规则提交参数无效。", {"errors": str(error)})
    if not patch_has_updates(payload):
        return _validation_error_response("审批规则提交参数无效。")
    return payload


def _read_context(request: HttpRequest, app_key: str) -> AppApiResult:
    match _actor_from_request(request):
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
    match _actor_from_request(request):
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


def _actor_from_request(request: HttpRequest) -> ConsoleApiResult:
    user = request.user
    if not user.is_authenticated:
        return _error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "控制台登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    return ConsoleActor(
        user_id=user.get_username(),
        is_superuser=bool(getattr(user, "is_superuser", False)),
    )


def _target_for_key(app: App, target_type: TargetType, target_key: str) -> TargetResult:
    match approval_rule_target_for_key(app=app, target_type=target_type, target_key=target_key):
        case ApprovalRuleTarget() as target:
            return target
        case None:
            pass
    match target_type:
        case "role":
            message = "Role 不属于当前 App。"
        case "permission":
            message = "Permission 不属于当前 App。"
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        status=HTTPStatus.BAD_REQUEST,
    )


def _patched_target(
    app: App,
    rule: ApprovalRule,
    payload: ApprovalRulePatchPayload,
) -> TargetResult:
    if not patch_has_target(payload):
        return approval_rule_target(rule)
    return _target_for_key(app, patch_target_type(payload), patch_target_key(payload))


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


def _error_response(
    code: ErrorCode,
    message: str,
    details: dict[str, JsonValue] | None = None,
    *,
    status: HTTPStatus,
) -> JsonResponse:
    return _json_response(build_error_response(code, message, details), status=status)


def _json_response(
    payload: dict[str, JsonValue] | ErrorResponse,
    *,
    status: HTTPStatus = HTTPStatus.OK,
) -> JsonResponse:
    return JsonResponse(payload, status=status, json_dumps_params={"ensure_ascii": False})
