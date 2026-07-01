from __future__ import annotations

from http import HTTPStatus
from typing import final, override

from django.core.exceptions import ValidationError as DjangoValidationError
from pydantic import ValidationError

from easyauth.admin_console.approval_rule_payloads import (
    ApprovalRulePatchPayload,
    patch_has_target,
    patch_has_updates,
    patch_target_key,
    patch_target_type,
    payload_approvers,
)
from easyauth.admin_console.approval_rule_targets import (
    ApprovalRuleTarget,
    approval_rule_item,
    approval_rule_target,
    approval_rule_target_for_key,
    patched_approvers,
)
from easyauth.admin_console.configuration import (
    ApprovalRuleMutation,
    ConsoleMutationActor,
    update_approval_rule,
)
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, ApprovalRule

APPROVAL_RULE_NOT_FOUND = "审批规则不存在。"
APPROVAL_RULE_INVALID = "审批规则参数无效。"
APPROVAL_RULE_PAYLOAD_INVALID = "审批规则提交参数无效。"
AUTHORIZATION_GROUP_TARGET_INVALID = "AuthorizationGroup 不属于当前 App。"
PERMISSION_TARGET_INVALID = "Permission 不属于当前 App。"


@final
class ApprovalRulePatchError(Exception):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        details: dict[str, JsonValue] | None,
        status: HTTPStatus,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details
        self.status = status

    @override
    def __str__(self) -> str:
        return self.message


def patch_approval_rule(
    app: App,
    approval_rule_id: int,
    body: bytes,
    actor_id: str,
) -> dict[str, JsonValue]:
    payload = _patch_payload(body)
    rule = ApprovalRule.objects.filter(app=app, id=approval_rule_id).first()
    if rule is None:
        raise ApprovalRulePatchError(
            ErrorCode.NOT_FOUND,
            APPROVAL_RULE_NOT_FOUND,
            None,
            HTTPStatus.NOT_FOUND,
        )
    target = _patched_target(app, rule, payload)
    approver_userids = patched_approvers(rule, payload_approvers(payload))
    is_active = rule.is_active if payload.is_active is None else payload.is_active
    try:
        updated_rule = update_approval_rule(
            ApprovalRuleMutation(
                app=app,
                rule=rule,
                authorization_group=target.authorization_group,
                permission=target.permission,
                approver_userids=approver_userids,
                is_active=is_active,
                actor=ConsoleMutationActor(actor_id=actor_id),
            ),
        )
    except DjangoValidationError as exc:
        message = APPROVAL_RULE_INVALID
        raise _validation_error(message, {"errors": str(exc)}) from exc
    return {"approval_rule": approval_rule_item(updated_rule)}


def _patch_payload(body: bytes) -> ApprovalRulePatchPayload:
    try:
        payload = ApprovalRulePatchPayload.model_validate_json(body)
    except ValidationError as exc:
        message = APPROVAL_RULE_PAYLOAD_INVALID
        raise _validation_error(message, {"errors": str(exc)}) from exc
    if not patch_has_updates(payload):
        message = APPROVAL_RULE_PAYLOAD_INVALID
        raise _validation_error(message)
    return payload


def _patched_target(
    app: App,
    rule: ApprovalRule,
    payload: ApprovalRulePatchPayload,
) -> ApprovalRuleTarget:
    if not patch_has_target(payload):
        return approval_rule_target(rule)
    match approval_rule_target_for_key(
        app=app,
        target_type=patch_target_type(payload),
        target_key=patch_target_key(payload),
    ):
        case ApprovalRuleTarget() as target:
            return target
        case None:
            pass
    message = (
        AUTHORIZATION_GROUP_TARGET_INVALID
        if patch_target_type(payload) == "authorization_group"
        else PERMISSION_TARGET_INVALID
    )
    raise ApprovalRulePatchError(
        ErrorCode.VALIDATION_ERROR,
        message,
        None,
        HTTPStatus.BAD_REQUEST,
    )


def _validation_error(
    message: str,
    details: dict[str, JsonValue] | None = None,
) -> ApprovalRulePatchError:
    return ApprovalRulePatchError(
        ErrorCode.VALIDATION_ERROR,
        message,
        details,
        HTTPStatus.BAD_REQUEST,
    )
