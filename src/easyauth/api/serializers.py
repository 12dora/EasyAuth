from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict, override

type PermissionQueryResponseInputValue = str | int | list[str]
type PermissionQueryResponseInput = Mapping[str, PermissionQueryResponseInputValue]
type SerializerErrors = dict[str, list[str]]

_REQUIRED_ERROR = "required"
_INVALID_ERROR = "invalid"


class PermissionQueryResponsePayload(TypedDict):
    user_id: str
    app_key: str
    roles: list[str]
    permissions: list[str]
    version: int
    expires_at: str


@dataclass(frozen=True, slots=True)
class SerializerDataAccessError(RuntimeError):
    errors: SerializerErrors

    @override
    def __str__(self) -> str:
        return "serializer data is unavailable because input is invalid"


@dataclass(frozen=True, slots=True)
class _ValidPermissionQueryResponse:
    payload: PermissionQueryResponsePayload


@dataclass(frozen=True, slots=True)
class _InvalidPermissionQueryResponse:
    errors: SerializerErrors


@dataclass(frozen=True, slots=True)
class _ParsedPermissionQueryFields:
    user_id: str | None
    app_key: str | None
    roles: list[str] | None
    permissions: list[str] | None
    version: int | None
    expires_at: str | None


type _PermissionQueryResponseParseResult = (
    _ValidPermissionQueryResponse | _InvalidPermissionQueryResponse
)


@dataclass(frozen=True, slots=True, init=False)
class PermissionQueryResponseSerializer:
    initial_data: PermissionQueryResponseInput

    def __init__(self, data: PermissionQueryResponseInput) -> None:
        object.__setattr__(self, "initial_data", data)

    def is_valid(self) -> bool:
        match _parse_permission_query_response(self.initial_data):
            case _ValidPermissionQueryResponse():
                return True
            case _InvalidPermissionQueryResponse():
                return False

    @property
    def data(self) -> PermissionQueryResponsePayload:
        match _parse_permission_query_response(self.initial_data):
            case _ValidPermissionQueryResponse(payload=payload):
                return payload
            case _InvalidPermissionQueryResponse(errors=errors):
                raise SerializerDataAccessError(errors)

    @property
    def errors(self) -> SerializerErrors:
        match _parse_permission_query_response(self.initial_data):
            case _ValidPermissionQueryResponse():
                return {}
            case _InvalidPermissionQueryResponse(errors=errors):
                return errors


def _parse_permission_query_response(
    payload: PermissionQueryResponseInput,
) -> _PermissionQueryResponseParseResult:
    parsed_fields = _ParsedPermissionQueryFields(
        user_id=_read_string(payload, "user_id"),
        app_key=_read_string(payload, "app_key"),
        roles=_read_string_list(payload, "roles"),
        permissions=_read_string_list(payload, "permissions"),
        version=_read_integer(payload, "version"),
        expires_at=_read_datetime_string(payload, "expires_at"),
    )

    match parsed_fields:
        case _ParsedPermissionQueryFields(
            user_id=str() as parsed_user_id,
            app_key=str() as parsed_app_key,
            roles=list() as parsed_roles,
            permissions=list() as parsed_permissions,
            version=int() as parsed_version,
            expires_at=str() as parsed_expires_at,
        ):
            return _ValidPermissionQueryResponse(
                {
                    "user_id": parsed_user_id,
                    "app_key": parsed_app_key,
                    "roles": parsed_roles,
                    "permissions": parsed_permissions,
                    "version": parsed_version,
                    "expires_at": parsed_expires_at,
                },
            )
        case _:
            return _InvalidPermissionQueryResponse(
                _collect_permission_query_errors(parsed_fields),
            )


def _read_string(payload: PermissionQueryResponseInput, key: str) -> str | None:
    match payload.get(key):
        case str() as value:
            return value
        case bool() | int() | list() | None:
            return None


def _read_string_list(payload: PermissionQueryResponseInput, key: str) -> list[str] | None:
    match payload.get(key):
        case list() as values:
            return list(values)
        case str() | bool() | int() | None:
            return None


def _read_integer(payload: PermissionQueryResponseInput, key: str) -> int | None:
    match payload.get(key):
        case bool():
            return None
        case int() as value:
            return value
        case str() | list() | None:
            return None


def _read_datetime_string(payload: PermissionQueryResponseInput, key: str) -> str | None:
    value = _read_string(payload, key)
    if value is None:
        return None

    try:
        parsed_value = datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed_value.tzinfo is None:
        return None

    return value


def _collect_permission_query_errors(fields: _ParsedPermissionQueryFields) -> SerializerErrors:
    errors: SerializerErrors = {}

    if fields.user_id is None:
        errors["user_id"] = [_REQUIRED_ERROR]
    if fields.app_key is None:
        errors["app_key"] = [_REQUIRED_ERROR]
    if fields.roles is None:
        errors["roles"] = [_INVALID_ERROR]
    if fields.permissions is None:
        errors["permissions"] = [_INVALID_ERROR]
    if fields.version is None:
        errors["version"] = [_REQUIRED_ERROR]
    if fields.expires_at is None:
        errors["expires_at"] = [_INVALID_ERROR]

    return errors
