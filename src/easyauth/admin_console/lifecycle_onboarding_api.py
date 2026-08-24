"""处理岗位模板的维护与生命周期入职执行。"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.http import HttpRequest, JsonResponse
from pydantic import ValidationError

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.lifecycle_api_serializers import (
    OnboardingTemplateStatusPayload,
    OnboardPayload,
    TemplateItemPayload,
    TemplatePayload,
    active_user_or_none,
    not_found,
    template_item,
    validation_error,
)
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import App, AuthorizationGroup, Permission
from easyauth.lifecycle.models import (
    OnboardingTemplate,
    OnboardingTemplateRevision,
    OnboardingTemplateRevisionItem,
)
from easyauth.lifecycle.onboarding import onboard_user

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

ONBOARDING_TEMPLATE_DELETE_BLOCKED_MESSAGE = (
    "岗位模板包含不可变修订, 不支持删除; 请改为停用。"
)


def lifecycle_onboarding_templates(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        templates = OnboardingTemplate.objects.select_related("current_revision").prefetch_related(
            Prefetch(
                "current_revision__items",
                queryset=OnboardingTemplateRevisionItem.objects.select_related(
                    "app",
                    "authorization_group",
                    "permission",
                ).order_by("app__app_key", "id"),
                to_attr="_prefetched_items",
            ),
        ).order_by("name")
        items: list[JsonValue] = [template_item(t) for t in templates]
        return json_response({"data": items})
    if request.method == "POST":
        return _write_template(request, template=None)
    return method_not_allowed_response()


def lifecycle_onboarding_template_detail(
    request: HttpRequest,
    template_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    template = OnboardingTemplate.objects.filter(id=template_id).first()
    if template is None:
        return not_found("岗位模板不存在。")
    return _handle_template_detail_method(request, template)


def _handle_template_detail_method(
    request: HttpRequest,
    template: OnboardingTemplate,
) -> JsonResponse:
    if request.method == "GET":
        return json_response({"onboarding_template": template_item(template)})
    if request.method == "PATCH":
        # 仅含 is_active 的请求 = 列表操作列的启停切换, 轻量更新不重建模板项; 其余走完整模板写入。
        try:
            status = OnboardingTemplateStatusPayload.model_validate_json(request.body)
        except ValidationError:
            return _write_template(request, template=template)
        with transaction.atomic():
            template = (
                OnboardingTemplate.objects.select_for_update()
                .select_related("current_revision")
                .get(pk=template.id)
            )
            template.is_active = status.is_active
            template.save(update_fields=["is_active", "updated_at"])
        return json_response({"onboarding_template": template_item(template)})
    if request.method == "DELETE":
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            ONBOARDING_TEMPLATE_DELETE_BLOCKED_MESSAGE,
            status=HTTPStatus.CONFLICT,
        )
    return method_not_allowed_response()


def lifecycle_onboard(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    try:
        payload = OnboardPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return validation_error("入职参数无效。", {"errors": str(exc)})
    user = active_user_or_none(payload.user_id)
    if user is None:
        return validation_error("用户不存在或已停用。")
    template = OnboardingTemplate.objects.filter(id=payload.template_id, is_active=True).first()
    if template is None:
        return not_found("岗位模板不存在或未启用。")
    grants = onboard_user(user=user, template=template, actor_id=actor_id)
    return json_response(
        {
            "user_id": user.authentik_user_id,
            "template": template.name,
            "granted_app_count": len(grants),
        },
    )


def _write_template(
    request: HttpRequest,
    *,
    template: OnboardingTemplate | None,
) -> JsonResponse:
    try:
        payload = TemplatePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return validation_error("模板参数无效。", {"errors": str(exc)})
    if (
        OnboardingTemplate.objects.filter(name=payload.name)
        .exclude(id=template.id if template is not None else None)
        .exists()
    ):
        return validation_error("同名模板已存在。")
    resolved_items: list[OnboardingTemplateRevisionItem] = []
    for entry in payload.items:
        item = _resolve_template_item(entry)
        if isinstance(item, JsonResponse):
            return item
        try:
            item.full_clean(exclude={"revision"})
        except DjangoValidationError as exc:
            return validation_error("模板项参数无效。", {"errors": str(exc)})
        resolved_items.append(item)
    with transaction.atomic():
        if template is None:
            template = OnboardingTemplate.objects.create(
                name=payload.name,
                description=payload.description,
                is_active=payload.is_active,
            )
        else:
            template = OnboardingTemplate.objects.select_for_update().get(pk=template.id)
            template.name = payload.name
            template.description = payload.description
            template.is_active = payload.is_active
            template.save()
        next_revision = (
            OnboardingTemplateRevision.objects.filter(template=template).count() + 1
        )
        revision = OnboardingTemplateRevision.objects.create(
            template=template,
            revision=next_revision,
            name_snapshot=payload.name,
            description_snapshot=payload.description,
            is_active=payload.is_active,
        )
        for item in resolved_items:
            item.revision = revision
            item.save()
        template.current_revision = revision
        template.save(update_fields=["current_revision", "updated_at"])
    return json_response({"onboarding_template": template_item(template)})


def _resolve_template_item(
    entry: TemplateItemPayload,
) -> OnboardingTemplateRevisionItem | JsonResponse:
    app = App.objects.filter(app_key=entry.app_key, is_active=True).first()
    if app is None:
        return validation_error(f"应用 {entry.app_key} 不存在或未启用。")
    if bool(entry.authorization_group_key) == bool(entry.permission_key):
        return validation_error("模板项必须且只能指定授权组或权限之一。")
    group = None
    permission = None
    if entry.authorization_group_key:
        group = AuthorizationGroup.objects.filter(
            app=app,
            key=entry.authorization_group_key,
        ).first()
        if group is None:
            return validation_error(f"授权组 {entry.authorization_group_key} 不存在。")
    elif entry.permission_key:
        permission = Permission.objects.filter(app=app, key=entry.permission_key).first()
        if permission is None:
            return validation_error(f"权限 {entry.permission_key} 不存在。")
    else:
        return validation_error("模板项必须指定授权组或权限。")
    return OnboardingTemplateRevisionItem(
        app=app,
        authorization_group=group,
        permission=permission,
        scope_key=entry.scope_key,
        grant_type=entry.grant_type,
        duration_days=entry.duration_days,
    )
