from __future__ import annotations

from http import HTTPStatus

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from pydantic import ValidationError

from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.apps_api_payloads import AppCreatePayload, AppPatchPayload
from easyauth.admin_console.apps_api_reads import app_detail_item, visible_app
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, AppMembership
from easyauth.applications.ownership import ConsoleActor, can_manage_app
from easyauth.audit.services import AuditRecord, AuditService


def create_app(request: HttpRequest) -> JsonResponse:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    return _create_app_for_actor(request, actor)


def patch_app(request: HttpRequest, app_key: str) -> JsonResponse:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    match visible_app(actor, app_key):
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
    return _json_response({"app": app_detail_item(actor, app)})


def delete_app(request: HttpRequest, app_key: str) -> JsonResponse | HttpResponse:
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

    match visible_app(actor, app_key):
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


def _payload_error_response(message: str, error: ValidationError) -> JsonResponse:
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        {"errors": str(error)},
        status=HTTPStatus.BAD_REQUEST,
    )


def _create_app_for_actor(request: HttpRequest, actor: ConsoleActor) -> JsonResponse:
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

    owner_user_ids, developer_user_ids = _create_app_member_ids(payload, actor)

    try:
        app = _save_created_app(payload, actor, owner_user_ids, developer_user_ids)
    except IntegrityError:
        return _error_response(
            ErrorCode.CONFLICT,
            "应用或成员关系已存在。",
            status=HTTPStatus.CONFLICT,
        )

    return _json_response({"app": app_detail_item(actor, app)}, status=HTTPStatus.CREATED)


def _create_app_member_ids(
    payload: AppCreatePayload,
    actor: ConsoleActor,
) -> tuple[list[str], list[str]]:
    owner_user_ids = payload.owner_user_ids or [actor.user_id]
    developer_user_ids = [
        user_id for user_id in payload.developer_user_ids if user_id not in set(owner_user_ids)
    ]
    return owner_user_ids, developer_user_ids


def _save_created_app(
    payload: AppCreatePayload,
    actor: ConsoleActor,
    owner_user_ids: list[str],
    developer_user_ids: list[str],
) -> App:
    with transaction.atomic():
        app = App.objects.create(
            app_key=payload.app_key,
            name=payload.name,
            description=payload.description,
            is_active=payload.is_active,
        )
        memberships = [
            AppMembership(app=app, user_id=user_id, role="owner") for user_id in owner_user_ids
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
    return app


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
