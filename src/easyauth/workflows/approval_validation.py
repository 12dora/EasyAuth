from __future__ import annotations

import hashlib
import json
import math
from typing import TYPE_CHECKING, cast

from django.core.exceptions import ValidationError

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.integrations.dingtalk.api_client import DingTalkFormComponent
from easyauth.workflows.approval_types import (
    FORM_SCHEMA_INVALID_MESSAGE,
    ORIGINATOR_INVALID_MESSAGE,
    TEMPLATE_NOT_FOUND_MESSAGE,
    ApprovalCreateError,
    ApprovalCreateRequest,
    ApprovalSubmission,
)
from easyauth.workflows.models import ApprovalTemplate

if TYPE_CHECKING:
    from collections.abc import Mapping

    from easyauth.applications.models import App
    from easyauth.applications.ops_models import JsonValue


def validated_approval_submission(request: ApprovalCreateRequest) -> ApprovalSubmission:
    template = (
        _active_template(request.app, request.template_key)
        if request.selected_template is None
        else _selected_active_template(
            request.app,
            request.template_key,
            request.selected_template,
        )
    )
    originator = _valid_originator(request.originator_user_id)
    normalized_form, form_components = _validated_form(template, request.form)
    payload_hash = _payload_hash(
        originator_user_id=request.originator_user_id,
        form=normalized_form,
    )
    return ApprovalSubmission(
        app=request.app,
        template=template,
        originator=originator,
        normalized_form=normalized_form,
        form_components=form_components,
        payload_hash=payload_hash,
    )


def _active_template(app: App, template_key: str) -> ApprovalTemplate:
    # 优先 app 专属模板, 其次平台共用模板。
    template = (
        ApprovalTemplate.objects.filter(app=app, key=template_key, is_active=True).first()
        or ApprovalTemplate.objects.filter(
            app__isnull=True,
            key=template_key,
            is_active=True,
        ).first()
    )
    if template is None:
        raise ApprovalCreateError(kind="template_not_found", message=TEMPLATE_NOT_FOUND_MESSAGE)
    return template


def _selected_active_template(
    app: App,
    template_key: str,
    template: ApprovalTemplate,
) -> ApprovalTemplate:
    if (
        not template.is_active
        or template.key != template_key
        or (template.app_id is not None and template.app_id != app.id)
    ):
        raise ApprovalCreateError(kind="template_not_found", message=TEMPLATE_NOT_FOUND_MESSAGE)
    return template


def _valid_originator(originator_user_id: str) -> UserMirror:
    originator = UserMirror.objects.filter(
        authentik_user_id=originator_user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    # 钉钉 userid 映射只在 EasyAuth(§0.4): 发起审批必须能换算, 否则明确报错。
    if originator is None or not originator.dingtalk_userid:
        raise ApprovalCreateError(kind="originator_invalid", message=ORIGINATOR_INVALID_MESSAGE)
    return originator


def _validated_form(
    template: ApprovalTemplate,
    form: Mapping[str, JsonValue],
) -> tuple[dict[str, JsonValue], tuple[DingTalkFormComponent, ...]]:
    try:
        template.full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as error:
        raise ApprovalCreateError(
            kind="validation_error",
            message=f"{FORM_SCHEMA_INVALID_MESSAGE} {error}",
        ) from error

    schema = cast("dict[str, dict[str, object]]", template.form_schema)
    unknown_fields = set(form) - set(schema)
    if unknown_fields:
        names = "、".join(sorted(unknown_fields))
        raise ApprovalCreateError(
            kind="validation_error",
            message=f"form 包含 form_schema 未声明的字段: {names}。",
        )
    missing_fields = {
        field_name
        for field_name, definition in schema.items()
        if definition.get("required", False) and field_name not in form
    }
    if missing_fields:
        names = "、".join(sorted(missing_fields))
        raise ApprovalCreateError(
            kind="validation_error",
            message=f"form 缺少必填字段: {names}。",
        )

    mapping = cast("dict[str, str]", template.form_mapping)
    normalized: dict[str, JsonValue] = {}
    components: list[DingTalkFormComponent] = []
    for field_name, value in form.items():
        field_type = cast("str", schema[field_name]["type"])
        if not _form_value_matches_type(value, field_type):
            raise ApprovalCreateError(
                kind="validation_error",
                message=f"form 字段 {field_name} 必须是 {field_type} 类型。",
            )
        normalized[field_name] = value
        components.append(
            DingTalkFormComponent(
                name=mapping.get(field_name, field_name),
                value=_dingtalk_form_value(value),
            ),
        )
    return normalized, tuple(components)


def _form_value_matches_type(value: JsonValue, field_type: str) -> bool:
    match field_type:
        case "string":
            return isinstance(value, str)
        case "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        case "number":
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            )
        case "boolean":
            return isinstance(value, bool)
        case _:
            return False


def _dingtalk_form_value(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    raise ApprovalCreateError(kind="validation_error", message=FORM_SCHEMA_INVALID_MESSAGE)


def _payload_hash(*, originator_user_id: str, form: dict[str, JsonValue]) -> str:
    canonical = json.dumps(
        {"originator_user_id": originator_user_id, "form": form},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
