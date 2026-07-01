from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict, override

type PermissionQueryScalar = str | int
type PermissionQueryObject = Mapping[str, PermissionQueryScalar]
type PermissionQueryResponseInputValue = PermissionQueryScalar | list[PermissionQueryObject]
type PermissionQueryResponseInput = Mapping[str, PermissionQueryResponseInputValue]
type SerializerErrors = dict[str, list[str]]

_REQUIRED_ERROR = "required"
_INVALID_ERROR = "invalid"


class PermissionQueryGroupPayload(TypedDict):
    key: str
    kind: str
    name: str


class PermissionQueryGrantPayload(TypedDict):
    permission: str
    scope: str
    source_type: str
    source_key: str


class PermissionQueryResponsePayload(TypedDict):
    user_id: str
    app_key: str
    groups: list[PermissionQueryGroupPayload]
    grants: list[PermissionQueryGrantPayload]
    grant_version: int
    catalog_version: int
    snapshot_version: str
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
    groups: list[PermissionQueryGroupPayload] | None
    grants: list[PermissionQueryGrantPayload] | None
    grant_version: int | None
    catalog_version: int | None
    snapshot_version: str | None
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
        groups=_read_groups(payload, "groups"),
        grants=_read_grants(payload, "grants"),
        grant_version=_read_integer(payload, "grant_version"),
        catalog_version=_read_integer(payload, "catalog_version"),
        snapshot_version=_read_string(payload, "snapshot_version"),
        expires_at=_read_datetime_string(payload, "expires_at"),
    )

    match parsed_fields:
        case _ParsedPermissionQueryFields(
            user_id=str() as parsed_user_id,
            app_key=str() as parsed_app_key,
            groups=list() as parsed_groups,
            grants=list() as parsed_grants,
            grant_version=int() as parsed_grant_version,
            catalog_version=int() as parsed_catalog_version,
            snapshot_version=str() as parsed_snapshot_version,
            expires_at=str() as parsed_expires_at,
        ):
            return _ValidPermissionQueryResponse(
                {
                    "user_id": parsed_user_id,
                    "app_key": parsed_app_key,
                    "groups": parsed_groups,
                    "grants": parsed_grants,
                    "grant_version": parsed_grant_version,
                    "catalog_version": parsed_catalog_version,
                    "snapshot_version": parsed_snapshot_version,
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


def _read_integer(payload: PermissionQueryResponseInput, key: str) -> int | None:
    match payload.get(key):
        case bool():
            return None
        case int() as value:
            return value
        case str() | list() | None:
            return None


def _read_groups(
    payload: PermissionQueryResponseInput,
    key: str,
) -> list[PermissionQueryGroupPayload] | None:
    match payload.get(key):
        case list() as values:
            groups: list[PermissionQueryGroupPayload] = []
            for value in values:
                group = _read_group(value)
                if group is None:
                    return None
                groups.append(group)
            return groups
        case str() | bool() | int() | None:
            return None


def _read_group(value: object) -> PermissionQueryGroupPayload | None:
    if not isinstance(value, Mapping):
        return None
    key = value.get("key")
    kind = value.get("kind")
    name = value.get("name")
    if isinstance(key, str) and isinstance(kind, str) and isinstance(name, str):
        return {"key": key, "kind": kind, "name": name}
    return None


def _read_grants(
    payload: PermissionQueryResponseInput,
    key: str,
) -> list[PermissionQueryGrantPayload] | None:
    match payload.get(key):
        case list() as values:
            grants: list[PermissionQueryGrantPayload] = []
            for value in values:
                grant = _read_grant(value)
                if grant is None:
                    return None
                grants.append(grant)
            return grants
        case str() | bool() | int() | None:
            return None


def _read_grant(value: object) -> PermissionQueryGrantPayload | None:
    if not isinstance(value, Mapping):
        return None
    permission = value.get("permission")
    scope = value.get("scope")
    source_type = value.get("source_type")
    source_key = value.get("source_key")
    if (
        isinstance(permission, str)
        and isinstance(scope, str)
        and isinstance(source_type, str)
        and isinstance(source_key, str)
    ):
        return {
            "permission": permission,
            "scope": scope,
            "source_type": source_type,
            "source_key": source_key,
        }
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
    if fields.groups is None:
        errors["groups"] = [_INVALID_ERROR]
    if fields.grants is None:
        errors["grants"] = [_INVALID_ERROR]
    if fields.grant_version is None:
        errors["grant_version"] = [_REQUIRED_ERROR]
    if fields.catalog_version is None:
        errors["catalog_version"] = [_REQUIRED_ERROR]
    if fields.snapshot_version is None:
        errors["snapshot_version"] = [_REQUIRED_ERROR]
    if fields.expires_at is None:
        errors["expires_at"] = [_INVALID_ERROR]

    return errors
