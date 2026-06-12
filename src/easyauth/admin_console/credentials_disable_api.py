from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.credentials import (
    CredentialActor,
    CredentialOperationError,
    disable_oauth_client_for_console,
    disable_static_token_for_console,
)
from easyauth.admin_console.credentials_api import credential_write_context
from easyauth.admin_console.credentials_api_payloads import (
    oauth_client_item,
    static_credential_item,
)
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import App, AppCredential, OAuthClientBinding
from easyauth.applications.ownership import ConsoleActor


class CredentialDisablePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    reason: str = Field(default="", max_length=1000)


def console_static_token_disable(
    request: HttpRequest,
    app_key: str,
    credential_id: int,
) -> JsonResponse:
    return console_credential_disable(request, app_key, "static-tokens", credential_id)


def console_credential_disable(
    request: HttpRequest,
    app_key: str,
    credential_type: str,
    credential_id: int,
) -> JsonResponse:
    if request.method != "POST":
        return _method_not_allowed_response()

    match credential_write_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response

    match _disable_payload(request):
        case CredentialDisablePayload() as payload:
            return _disable_credential(app, actor, credential_type, credential_id, payload.reason)
        case JsonResponse() as response:
            return response


def _disable_credential(
    app: App,
    actor: ConsoleActor,
    credential_type: str,
    credential_id: int,
    reason: str,
) -> JsonResponse:
    credential_actor = CredentialActor(actor_id=actor.user_id)
    try:
        match credential_type:
            case "static-tokens":
                disable_static_token_for_console(
                    app=app,
                    credential_id=credential_id,
                    actor=credential_actor,
                    reason=reason,
                )
                credential = AppCredential.objects.get(id=credential_id)
                return _json_response({"credential": static_credential_item(credential)})
            case "oauth-clients":
                disable_oauth_client_for_console(
                    app=app,
                    credential_id=credential_id,
                    actor=credential_actor,
                    reason=reason,
                )
                binding = OAuthClientBinding.objects.select_related("oauth_application").get(
                    id=credential_id,
                )
                return _json_response({"credential": oauth_client_item(binding)})
            case _:
                return _not_found_response()
    except CredentialOperationError:
        return _not_found_response()


def _disable_payload(request: HttpRequest) -> CredentialDisablePayload | JsonResponse:
    if not request.body:
        return CredentialDisablePayload()
    try:
        return CredentialDisablePayload.model_validate_json(request.body)
    except ValidationError as error:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "凭据禁用参数无效。",
            {"errors": str(error)},
            status=HTTPStatus.BAD_REQUEST,
        )


def _method_not_allowed_response() -> JsonResponse:
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        "不支持的请求方法。",
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )


def _not_found_response() -> JsonResponse:
    return _error_response(
        ErrorCode.NOT_FOUND,
        "凭据不存在。",
        status=HTTPStatus.NOT_FOUND,
    )
