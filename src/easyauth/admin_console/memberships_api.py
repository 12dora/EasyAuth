from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar, Literal

from django.db import IntegrityError, transaction
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_payloads import list_payload
from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, AppMembership
from easyauth.applications.ownership import ConsoleActor, can_view_app
from easyauth.audit.services import AuditRecord, AuditService

type VisibleAppResult = App | JsonResponse
type ManageableAppResult = tuple[App, ConsoleActor] | JsonResponse
type MembershipRole = Literal["owner", "developer"]


class MembershipCreatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    role: MembershipRole


class MembershipPatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    role: MembershipRole | None = None
    is_active: bool | None = None


def console_app_memberships(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method == "POST":
        return _create_membership(request, app_key)
    if request.method != "GET":
        return _method_not_allowed()

    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    match _visible_app(actor, app_key):
        case App() as app:
            memberships = AppMembership.objects.filter(app=app).order_by("user_id", "role")
            return _items_response(
                tuple(_membership_item(membership) for membership in memberships),
            )
        case JsonResponse() as response:
            return response


def console_app_membership_detail(
    request: HttpRequest,
    app_key: str,
    membership_id: int,
) -> JsonResponse:
    if request.method != "PATCH":
        return _method_not_allowed()
    return _update_membership(request, app_key, membership_id)


def _create_membership(request: HttpRequest, app_key: str) -> JsonResponse:
    match _manageable_app(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response

    try:
        payload = MembershipCreatePayload.model_validate_json(request.body)
    except ValidationError as error:
        return _payload_error_response(error)

    if AppMembership.objects.filter(
        app=app,
        user_id=payload.user_id,
        role=payload.role,
        is_active=True,
    ).exists():
        return _membership_conflict_response()

    try:
        with transaction.atomic():
            membership = AppMembership.objects.create(
                app=app,
                user_id=payload.user_id,
                role=payload.role,
            )
            _record_membership_event(app, actor, "console_app_membership_created", membership)
    except IntegrityError:
        return _membership_conflict_response()
    return _json_response(
        {"membership": _membership_item(membership, include_id=True)},
        status=HTTPStatus.CREATED,
    )


def _update_membership(request: HttpRequest, app_key: str, membership_id: int) -> JsonResponse:
    match _manageable_app(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response

    membership = AppMembership.objects.filter(app=app, id=membership_id).first()
    if membership is None:
        return _error_response(
            ErrorCode.NOT_FOUND,
            "成员关系不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    try:
        payload = MembershipPatchPayload.model_validate_json(request.body)
    except ValidationError as error:
        return _payload_error_response(error)

    changed = _apply_membership_patch(membership, payload)
    if not changed:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "成员关系参数无效。",
            status=HTTPStatus.BAD_REQUEST,
        )
    try:
        with transaction.atomic():
            membership.save(update_fields=["role", "is_active", "updated_at"])
            _record_membership_event(app, actor, "console_app_membership_updated", membership)
    except IntegrityError:
        return _membership_conflict_response()
    return _json_response({"membership": _membership_item(membership, include_id=True)})


def _apply_membership_patch(
    membership: AppMembership,
    payload: MembershipPatchPayload,
) -> bool:
    changed = False
    if payload.role is not None:
        membership.role = payload.role
        changed = True
    if payload.is_active is not None:
        membership.is_active = payload.is_active
        changed = True
    return changed


def _visible_app(actor: ConsoleActor, app_key: str) -> VisibleAppResult:
    app = App.objects.filter(app_key=app_key).first()
    if app is None or not can_view_app(actor, app):
        return _error_response(
            ErrorCode.NOT_FOUND,
            "应用不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    return app


def _manageable_app(request: HttpRequest, app_key: str) -> ManageableAppResult:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    app = App.objects.filter(app_key=app_key).first()
    if app is None or not can_view_app(actor, app):
        return _error_response(
            ErrorCode.NOT_FOUND,
            "应用不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    if not actor.is_superuser:
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有系统管理员可以管理成员关系。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app, actor


def _membership_item(
    membership: AppMembership,
    *,
    include_id: bool = False,
) -> dict[str, JsonValue]:
    item: dict[str, JsonValue] = {
        "user_id": membership.user_id,
        "role": membership.role,
        "is_active": membership.is_active,
    }
    if include_id:
        item["id"] = membership.id
    return item


def _items_response(items: tuple[dict[str, JsonValue], ...]) -> JsonResponse:
    result: list[JsonValue] = []
    result.extend(items)
    return _json_response(list_payload(result))


def _record_membership_event(
    app: App,
    actor: ConsoleActor,
    action: str,
    membership: AppMembership,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor.user_id,
            action=action,
            target_type="app_membership",
            target_id=str(membership.id),
            metadata={
                "app_key": app.app_key,
                "membership_id": membership.id,
                "user_id": membership.user_id,
                "role": membership.role,
                "is_active": membership.is_active,
            },
        ),
    )


def _method_not_allowed() -> JsonResponse:
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        "不支持的请求方法。",
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )


def _payload_error_response(error: ValidationError) -> JsonResponse:
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        "成员关系参数无效。",
        {"errors": str(error)},
        status=HTTPStatus.BAD_REQUEST,
    )


def _membership_conflict_response() -> JsonResponse:
    return _error_response(
        ErrorCode.CONFLICT,
        "成员关系已存在。",
        status=HTTPStatus.CONFLICT,
    )
