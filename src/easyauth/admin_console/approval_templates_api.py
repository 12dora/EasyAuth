from __future__ import annotations

import uuid
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, cast

from django.db.models import ProtectedError
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_payloads import list_payload
from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import App
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.workflows.models import ApprovalTemplate
from easyauth.workflows.services import (
    ApprovalCreateError,
    create_approval_instance,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

type JsonObject = dict[str, "JsonValue"]


class ApprovalTemplatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    app_key: str = Field(default="", max_length=64)
    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    dingtalk_process_code: str = Field(min_length=1, max_length=128)
    form_schema: dict[str, object] = Field(default_factory=dict)
    form_mapping: dict[str, object] = Field(default_factory=dict)
    is_active: bool = True


class ApprovalTemplatePatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    name: str | None = Field(default=None, min_length=1, max_length=128)
    dingtalk_process_code: str | None = Field(default=None, min_length=1, max_length=128)
    form_schema: dict[str, object] | None = None
    form_mapping: dict[str, object] | None = None
    is_active: bool | None = None


class ApprovalTemplateTestPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    app_key: str = Field(default="", max_length=64)
    originator_user_id: str = Field(min_length=1, max_length=128)
    form: dict[str, str] = Field(default_factory=dict)


def console_approval_templates(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        templates = ApprovalTemplate.objects.select_related("app").order_by("key")
        return json_response(list_payload([_template_item(t) for t in templates]))
    if request.method == "POST":
        return _create_template(request, actor_id)
    return method_not_allowed_response()


def console_approval_template_detail(request: HttpRequest, template_id: int) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    template = ApprovalTemplate.objects.select_related("app").filter(id=template_id).first()
    if template is None:
        return _not_found("审批模板不存在。")
    if request.method == "GET":
        return json_response({"approval_template": _template_item(template)})
    if request.method == "PATCH":
        return _patch_template(request, template, actor_id)
    if request.method == "DELETE":
        return _delete_template(template, actor_id)
    return method_not_allowed_response()


def console_approval_template_test(request: HttpRequest, template_id: int) -> JsonResponse:
    # "发起测试审批": 用真实凭证创建一笔审批实例, 验证 process_code/映射/连通性。
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    return _run_template_test(request, template_id=template_id, actor_id=actor_id)


def _run_template_test(
    request: HttpRequest,
    *,
    template_id: int,
    actor_id: str,
) -> JsonResponse:
    template = ApprovalTemplate.objects.select_related("app").filter(id=template_id).first()
    if template is None:
        return _not_found("审批模板不存在。")
    try:
        payload = ApprovalTemplateTestPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("测试参数无效。", {"errors": str(exc)})
    match _test_target_app(template, payload):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response
    try:
        instance, _created = create_approval_instance(
            app=app,
            template_key=template.key,
            originator_user_id=payload.originator_user_id,
            form=dict(payload.form),
            biz_key=f"console-test-{actor_id}-{template.id}-{uuid.uuid4().hex[:8]}",
            actor_id=f"console:{actor_id}",
        )
    except ApprovalCreateError as exc:
        return _validation_error(str(exc))
    return json_response(
        {
            "instance_id": str(instance.id),
            "status": instance.status,
            "dingtalk_process_instance_id": instance.dingtalk_process_instance_id,
        },
    )


def _test_target_app(
    template: ApprovalTemplate,
    payload: ApprovalTemplateTestPayload,
) -> App | JsonResponse:
    if template.app is not None:
        return template.app
    if not payload.app_key:
        return _validation_error("平台共用模板发起测试审批必须指定 app_key。")
    app = App.objects.filter(app_key=payload.app_key).first()
    if app is None:
        return _not_found("应用不存在。")
    return app


def _create_template(request: HttpRequest, actor_id: str) -> JsonResponse:
    try:
        payload = ApprovalTemplatePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("审批模板参数无效。", {"errors": str(exc)})
    app: App | None = None
    if payload.app_key:
        app = App.objects.filter(app_key=payload.app_key).first()
        if app is None:
            return _not_found("应用不存在。")
    if ApprovalTemplate.objects.filter(app=app, key=payload.key).exists():
        return _validation_error("同一作用域下模板 key 已存在。")
    template = ApprovalTemplate.objects.create(
        app=app,
        key=payload.key,
        name=payload.name,
        dingtalk_process_code=payload.dingtalk_process_code,
        form_schema=cast("dict[str, JsonValue]", dict(payload.form_schema)),
        form_mapping=cast("dict[str, JsonValue]", dict(payload.form_mapping)),
        is_active=payload.is_active,
    )
    _record_template_event(actor_id=actor_id, template=template, action="approval_template_created")
    return json_response(
        {"approval_template": _template_item(template)},
        status=HTTPStatus.CREATED,
    )


def _patch_template(
    request: HttpRequest,
    template: ApprovalTemplate,
    actor_id: str,
) -> JsonResponse:
    try:
        payload = ApprovalTemplatePatchPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("审批模板参数无效。", {"errors": str(exc)})
    if payload.name is not None:
        template.name = payload.name
    if payload.dingtalk_process_code is not None:
        template.dingtalk_process_code = payload.dingtalk_process_code
    if payload.form_schema is not None:
        template.form_schema = cast("dict[str, JsonValue]", dict(payload.form_schema))
    if payload.form_mapping is not None:
        template.form_mapping = cast("dict[str, JsonValue]", dict(payload.form_mapping))
    if payload.is_active is not None:
        template.is_active = payload.is_active
    template.save()
    _record_template_event(actor_id=actor_id, template=template, action="approval_template_updated")
    return json_response({"approval_template": _template_item(template)})


def _delete_template(template: ApprovalTemplate, actor_id: str) -> JsonResponse:
    # 删除前先留存标识: delete() 成功后 template.pk 会被置空, 无法再取 id。
    template_id = template.id
    template_key = template.key
    app_key = template.app.app_key if template.app is not None else ""
    try:
        _ = template.delete()
    except ProtectedError:
        # instances=PROTECT: 已被审批实例引用的模板不能删除, 提示改为停用。
        return _conflict("该审批模板已被审批实例引用, 不能删除; 可改为停用。")
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action="approval_template_deleted",
            target_type="approval_template",
            target_id=str(template_id),
            metadata={"key": template_key, "app_key": app_key},
        ),
    )
    return json_response({"deleted": True})


def _template_item(template: ApprovalTemplate) -> JsonObject:
    return {
        "id": template.id,
        "app_key": template.app.app_key if template.app is not None else "",
        "key": template.key,
        "name": template.name,
        "dingtalk_process_code": template.dingtalk_process_code,
        "form_schema": template.form_schema,
        "form_mapping": template.form_mapping,
        "is_active": template.is_active,
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
    }


def _record_template_event(
    *,
    actor_id: str,
    template: ApprovalTemplate,
    action: str,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action=action,
            target_type="approval_template",
            target_id=str(template.id),
            metadata={
                "key": template.key,
                "app_key": template.app.app_key if template.app is not None else "",
                "is_active": template.is_active,
            },
        ),
    )


def _validation_error(message: str, details: JsonObject | None = None) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        details,
        status=HTTPStatus.BAD_REQUEST,
    )


def _not_found(message: str) -> JsonResponse:
    return error_response(ErrorCode.NOT_FOUND, message, status=HTTPStatus.NOT_FOUND)


def _conflict(message: str) -> JsonResponse:
    return error_response(ErrorCode.SEMANTIC_VALIDATION_ERROR, message, status=HTTPStatus.CONFLICT)
