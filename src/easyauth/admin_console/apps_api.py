from __future__ import annotations

import re
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from easyauth.admin_console.api_payloads import paginated_list_payload
from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.api_responses import method_not_allowed_response
from easyauth.admin_console.operation_filters import Page, paginate_queryset
from easyauth.admin_console.permission_template_api_data import template_version_item
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.pagination import pagination_item
from easyauth.applications.configuration import (
    ConfigurationIssue,
    ConfigurationReadiness,
    configuration_readiness_for_app,
)
from easyauth.applications.models import (
    App,
    AppCredential,
    AppMembership,
    OAuthClientBinding,
    Permission,
    PermissionTemplateVersion,
    Role,
)
from easyauth.applications.ownership import (
    ConsoleActor,
    can_manage_app,
)
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from django.db.models import QuerySet

type VisibleAppResult = App | JsonResponse

APP_KEY_INVALID_MESSAGE: Final = "app_key 格式无效。"
APP_KEY_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
NAME_BLANK_MESSAGE: Final = "name 不能为空。"
CONFIGURATION_ISSUE_TARGET_TYPES: Final = {
    "app_inactive": "app",
    "active_credential_missing": "credential",
    "active_permission_missing": "permission",
    "active_authorization_group_missing": "authorization_group",
    "active_owner_missing": "membership",
    "requestable_authorization_group_approval_rule_missing": "authorization_group",
    "authorization_group_grant_target_inactive": "authorization_group_grant",
    "managed_scope_app_default_policy_missing": "authorization_group_grant",
    "managed_scope_grant_policy_missing": "authorization_group_grant",
    "managed_scope_policy_disabled": "authorization_group_grant",
    "permission_supported_scopes_missing": "permission",
    "permission_group_inactive": "permission_group",
}


class AppCreatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    app_key: str = Field(max_length=64)
    name: str = Field(max_length=128)
    description: str = ""
    is_active: bool = True
    owner_user_ids: list[str] = Field(default_factory=list)
    developer_user_ids: list[str] = Field(default_factory=list)

    @field_validator("app_key")
    @classmethod
    def validate_app_key(cls, value: str) -> str:
        normalized = value.strip()
        if APP_KEY_PATTERN.fullmatch(normalized) is None:
            raise ValueError(APP_KEY_INVALID_MESSAGE)
        return normalized

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError(NAME_BLANK_MESSAGE)
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("owner_user_ids", "developer_user_ids")
    @classmethod
    def normalize_user_ids(cls, value: list[str]) -> list[str]:
        return _normalize_user_ids(value)


class AppPatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized == "":
            raise ValueError(NAME_BLANK_MESSAGE)
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


def console_apps(request: HttpRequest) -> JsonResponse:
    if request.method == "POST":
        return _create_app(request)
    if request.method != "GET":
        return method_not_allowed_response()

    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    page = paginate_queryset(_filter_apps(_visible_apps_queryset(actor), request), request.GET)
    return _items_response(tuple(_app_item(app) for app in page.items), page)


def console_app_detail(request: HttpRequest, app_key: str) -> JsonResponse | HttpResponse:
    if request.method == "PATCH":
        return _patch_app(request, app_key)
    if request.method == "DELETE":
        return _delete_app(request, app_key)
    if request.method != "GET":
        return method_not_allowed_response()

    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    match _visible_app(actor, app_key):
        case App() as app:
            return _json_response({"app": _app_detail_item(actor, app)})
        case JsonResponse() as response:
            return response


def console_app_configuration_status(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method != "GET":
        return method_not_allowed_response()
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    match _visible_app(actor, app_key):
        case App() as app:
            readiness = configuration_readiness_for_app(app)
            issues: list[JsonValue] = []
            issues.extend(_configuration_issue_item(issue) for issue in readiness.issues)
            payload: dict[str, JsonValue] = {
                "app_key": app.app_key,
                "status": readiness.status,
                # 统一列表键为 canonical data(与 api_payloads.list_payload 一致), 不再用 items。
                "data": issues,
            }
            return _json_response(payload)
        case JsonResponse() as response:
            return response


def _create_app(request: HttpRequest) -> JsonResponse:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    if not actor.is_superuser:
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有系统管理员可以创建应用。",
            status=HTTPStatus.FORBIDDEN,
        )

    try:
        payload = AppCreatePayload.model_validate_json(request.body)
    except ValidationError as error:
        return _payload_error_response("应用参数无效。", error)

    if App.objects.filter(app_key=payload.app_key).exists():
        return _error_response(
            ErrorCode.CONFLICT,
            "应用标识已存在。",
            status=HTTPStatus.CONFLICT,
        )

    owner_user_ids = payload.owner_user_ids or [actor.user_id]
    developer_user_ids = [
        user_id for user_id in payload.developer_user_ids if user_id not in set(owner_user_ids)
    ]

    try:
        with transaction.atomic():
            app = App.objects.create(
                app_key=payload.app_key,
                name=payload.name,
                description=payload.description,
                is_active=payload.is_active,
            )
            memberships = [
                AppMembership(app=app, user_id=user_id, role="owner")
                for user_id in owner_user_ids
            ]
            memberships.extend(
                AppMembership(app=app, user_id=user_id, role="developer")
                for user_id in developer_user_ids
            )
            _ = AppMembership.objects.bulk_create(memberships)
            owner_metadata: list[JsonValue] = list(owner_user_ids)
            developer_metadata: list[JsonValue] = list(developer_user_ids)
            _record_app_event(
                app,
                actor,
                "console_app_created",
                {
                    "app_key": app.app_key,
                    "owner_user_ids": owner_metadata,
                    "developer_user_ids": developer_metadata,
                    "is_active": app.is_active,
                },
            )
    except IntegrityError:
        return _error_response(
            ErrorCode.CONFLICT,
            "应用或成员关系已存在。",
            status=HTTPStatus.CONFLICT,
        )

    return _json_response({"app": _app_detail_item(actor, app)}, status=HTTPStatus.CREATED)


def _patch_app(request: HttpRequest, app_key: str) -> JsonResponse:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    match _visible_app(actor, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response

    try:
        payload = AppPatchPayload.model_validate_json(request.body)
    except ValidationError as error:
        return _payload_error_response("应用参数无效。", error)

    changed_fields = _patch_changed_fields(payload)
    if not changed_fields:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "应用参数无效。",
            status=HTTPStatus.BAD_REQUEST,
        )

    if permission_response := _app_patch_permission_response(actor, app, changed_fields):
        return permission_response

    for field_name, value in changed_fields.items():
        setattr(app, field_name, value)
    with transaction.atomic():
        app.save(update_fields=[*changed_fields, "updated_at"])
        _record_app_event(app, actor, "console_app_updated", changed_fields)
    return _json_response({"app": _app_detail_item(actor, app)})


def _delete_app(request: HttpRequest, app_key: str) -> JsonResponse | HttpResponse:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    if not actor.is_superuser:
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有系统管理员可以删除应用。",
            status=HTTPStatus.FORBIDDEN,
        )

    match _visible_app(actor, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response

    metadata: dict[str, JsonValue] = {
        "app_key": app.app_key,
        "name": app.name,
        "is_active": app.is_active,
    }
    with transaction.atomic():
        _record_app_event(app, actor, "console_app_deleted", metadata)
        _ = app.delete()
    return HttpResponse(status=HTTPStatus.NO_CONTENT)


def _visible_app(actor: ConsoleActor, app_key: str) -> VisibleAppResult:
    _ = actor
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return _error_response(
            ErrorCode.NOT_FOUND,
            "应用不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    return app


def _normalize_user_ids(user_ids: list[str]) -> list[str]:
    normalized_ids: list[str] = []
    seen: set[str] = set()
    for user_id in user_ids:
        normalized = user_id.strip()
        if normalized == "" or normalized in seen:
            continue
        seen.add(normalized)
        normalized_ids.append(normalized)
    return normalized_ids


def _patch_changed_fields(payload: AppPatchPayload) -> dict[str, JsonValue]:
    changed_fields: dict[str, JsonValue] = {}
    if "name" in payload.model_fields_set and payload.name is not None:
        changed_fields["name"] = payload.name
    if "description" in payload.model_fields_set and payload.description is not None:
        changed_fields["description"] = payload.description
    if "is_active" in payload.model_fields_set and payload.is_active is not None:
        changed_fields["is_active"] = payload.is_active
    return changed_fields


def _app_patch_permission_response(
    actor: ConsoleActor,
    app: App,
    changed_fields: dict[str, JsonValue],
) -> JsonResponse | None:
    if not can_manage_app(actor, app):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "没有权限编辑应用。",
            status=HTTPStatus.FORBIDDEN,
        )
    if not actor.is_superuser and "is_active" in changed_fields:
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有系统管理员可以启停应用。",
            status=HTTPStatus.FORBIDDEN,
        )
    return None


def _record_app_event(
    app: App,
    actor: ConsoleActor,
    action: str,
    metadata: dict[str, JsonValue],
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor.user_id,
            action=action,
            target_type="app",
            target_id=str(app.id),
            metadata=metadata,
        ),
    )


def _app_item(app: App) -> dict[str, JsonValue]:
    readiness = configuration_readiness_for_app(app)
    return {
        "id": app.id,
        "app_key": app.app_key,
        "name": app.name,
        "description": app.description,
        "is_active": app.is_active,
        "owners": _app_owner_ids(app),
        "configuration_status": readiness.status,
        "updated_at": app.updated_at.isoformat(),
    }


def _app_detail_item(actor: ConsoleActor, app: App) -> dict[str, JsonValue]:
    item = _app_item(app)
    item["can_manage"] = can_manage_app(actor, app)
    item["developers"] = _app_member_ids(app, "developer")
    item["role_count"] = Role.objects.filter(app=app).count()
    item["permission_count"] = Permission.objects.filter(app=app).count()
    item["active_credential_count"] = _active_credential_count(app)
    item["latest_template_version"] = _latest_template_version_item(app)
    item["configuration_summary"] = _configuration_summary(
        configuration_readiness_for_app(app),
    )
    return item


def _configuration_issue_item(issue: ConfigurationIssue) -> dict[str, JsonValue]:
    return {
        "code": issue.code,
        "severity": issue.severity,
        "level": issue.severity,
        "message": issue.message,
        "subject": issue.subject,
        "target_type": CONFIGURATION_ISSUE_TARGET_TYPES.get(issue.code, "configuration_issue"),
        "target_id": issue.subject,
    }


def _app_owner_ids(app: App) -> list[JsonValue]:
    return _app_member_ids(app, "owner")


def _app_member_ids(app: App, role: str) -> list[JsonValue]:
    memberships = AppMembership.objects.filter(app=app, role=role, is_active=True).order_by(
        "user_id",
    )
    result: list[JsonValue] = []
    result.extend(memberships.values_list("user_id", flat=True))
    return result


def _visible_apps_queryset(actor: ConsoleActor) -> QuerySet[App]:
    _ = actor
    return App.objects.order_by("app_key")


def _filter_apps(queryset: QuerySet[App], request: HttpRequest) -> QuerySet[App]:
    queryset = _filter_app_status(queryset, request.GET.get("status", ""))
    owner_user_id = request.GET.get("owner_user_id", "")
    if owner_user_id == "":
        return queryset
    return queryset.filter(
        memberships__user_id=owner_user_id,
        memberships__role="owner",
        memberships__is_active=True,
    ).distinct()


def _filter_app_status(queryset: QuerySet[App], status: str) -> QuerySet[App]:
    match status:
        case "active":
            return queryset.filter(is_active=True)
        case "inactive":
            return queryset.filter(is_active=False)
        case "":
            return queryset
        case _:
            return queryset


def _active_credential_count(app: App) -> int:
    static_count = AppCredential.objects.filter(app=app, is_active=True).count()
    oauth_count = OAuthClientBinding.objects.filter(app=app, is_active=True).count()
    return static_count + oauth_count


def _latest_template_version_item(app: App) -> JsonValue:
    template_version = (
        PermissionTemplateVersion.objects.filter(app=app).order_by("-version").first()
    )
    if template_version is None:
        return None
    return template_version_item(template_version)


def _configuration_summary(readiness: ConfigurationReadiness) -> dict[str, JsonValue]:
    return {
        "status": readiness.status,
        "issue_count": len(readiness.issues),
        "blocking_count": _issue_count(readiness, "blocking"),
        "warning_count": _issue_count(readiness, "warning"),
    }


def _issue_count(readiness: ConfigurationReadiness, severity: str) -> int:
    return sum(1 for issue in readiness.issues if issue.severity == severity)


def _payload_error_response(message: str, error: ValidationError) -> JsonResponse:
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        {"errors": str(error)},
        status=HTTPStatus.BAD_REQUEST,
    )


def _items_response(
    items: tuple[dict[str, JsonValue], ...],
    page: Page[App],
) -> JsonResponse:
    result: list[JsonValue] = []
    result.extend(items)
    return _json_response(
        paginated_list_payload(items=result, pagination=pagination_item(page)),
    )
