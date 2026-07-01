from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Protocol

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, ErrorResponse, JsonValue, build_error_response
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor, can_manage_app
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from collections.abc import Mapping

type WriteContextResult = CatalogWriteContext | JsonResponse
type SaveResult = None | JsonResponse


@dataclass(frozen=True, slots=True)
class CatalogWriteContext:
    app: App
    actor: ConsoleActor


@dataclass(frozen=True, slots=True)
class CatalogEvent:
    app: App
    actor: ConsoleActor
    action: str
    target_type: str
    target_id: str
    metadata: Mapping[str, JsonValue]


class DjangoModel(Protocol):
    def full_clean(self) -> None: ...

    def save(self) -> None: ...


class ResourceIdPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: int = Field(gt=0)


def write_context(request: HttpRequest, app_key: str) -> WriteContextResult:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return error_response(ErrorCode.NOT_FOUND, "App 不存在。", status=HTTPStatus.NOT_FOUND)
    if not can_manage_app(actor, app):
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner 可以写入该 App 权限目录。",
            status=HTTPStatus.FORBIDDEN,
        )
    return CatalogWriteContext(app=app, actor=actor)


def parse_payload[PayloadT: BaseModel](
    request: HttpRequest,
    model_type: type[PayloadT],
    message: str,
) -> PayloadT | JsonResponse:
    try:
        return model_type.model_validate_json(request.body)
    except ValidationError as error:
        return bad_request(message, {"errors": str(error)})


def bad_request(message: str, details: dict[str, JsonValue] | None = None) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        details,
        status=HTTPStatus.BAD_REQUEST,
    )


def conflict_response(message: str) -> JsonResponse:
    return error_response(ErrorCode.CONFLICT, message, status=HTTPStatus.CONFLICT)


def semantic_response(message: str) -> JsonResponse:
    return error_response(
        ErrorCode.SEMANTIC_VALIDATION_ERROR,
        message,
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def method_not_allowed_response() -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        "不支持的请求方法。",
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )


def error_response(
    code: ErrorCode,
    message: str,
    details: dict[str, JsonValue] | None = None,
    *,
    status: HTTPStatus,
) -> JsonResponse:
    return json_response(build_error_response(code, message, details), status=status)


def json_response(
    payload: dict[str, JsonValue] | ErrorResponse,
    *,
    status: HTTPStatus = HTTPStatus.OK,
) -> JsonResponse:
    return JsonResponse(payload, status=status, json_dumps_params={"ensure_ascii": False})


def save_model(model: DjangoModel) -> SaveResult:
    try:
        model.full_clean()
        model.save()
    except DjangoValidationError as error:
        return semantic_response(str(error))
    except IntegrityError:
        return conflict_response("catalog key 已存在。")
    return None


def record_catalog_event(event: CatalogEvent) -> None:
    stored_metadata: dict[str, JsonValue] = {"app_key": event.app.app_key}
    stored_metadata.update(event.metadata)
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=event.actor.user_id,
            action=event.action,
            target_type=event.target_type,
            target_id=event.target_id,
            metadata=stored_metadata,
        ),
    )
