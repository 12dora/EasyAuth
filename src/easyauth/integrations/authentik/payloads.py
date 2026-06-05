from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, TypedDict, override

from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    USER_STATUS_DEPARTED,
    USER_STATUS_DISABLED,
)

type AuthentikPayloadValue = (
    None
    | bool
    | int
    | float
    | str
    | dict[str, "AuthentikPayloadValue"]
    | list["AuthentikPayloadValue"]
)
type AuthentikPayloadInput = dict[str, AuthentikPayloadValue]
type UserStatus = Literal["active", "disabled", "departed"]

AUTHENTIK_STATUS_INACTIVE: Final = "inactive"
SUPPORTED_STATUS_VALUES: Final[frozenset[str]] = frozenset(
    {USER_STATUS_ACTIVE, USER_STATUS_DISABLED, USER_STATUS_DEPARTED, AUTHENTIK_STATUS_INACTIVE},
)
SUBJECT_FIELD: Final = "subject"
IS_ACTIVE_FIELD: Final = "is_active"
STATUS_FIELD: Final = "status"
SUBJECT_REQUIRED_REASON: Final = "is required"
SUBJECT_CONFLICT_REASON: Final = "conflicting subject fields"
IS_ACTIVE_BOOLEAN_REASON: Final = "must be a boolean"


class AuthentikAttributes(TypedDict, total=False):
    uid: str
    department: str
    status: str


class AuthentikPayloadSection(TypedDict, total=False):
    uid: str
    name: str
    email: str
    sub: str
    attributes: AuthentikAttributes


@dataclass(frozen=True, slots=True)
class AuthentikPayloadError(ValueError):
    field: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"Invalid Authentik payload {self.field}: {self.reason}"


@dataclass(frozen=True, slots=True)
class AuthentikUserProfile:
    authentik_user_id: str
    name: str
    email: str
    department: str
    status: UserStatus


def parse_authentik_payload(payload: AuthentikPayloadInput) -> AuthentikUserProfile:
    user = _optional_section(payload, "user")
    context = _optional_section(payload, "context")
    user_attributes = _optional_attributes(user)
    context_attributes = _optional_attributes(context)
    subject = _parse_subject(user, context, context_attributes)
    status = _parse_status(payload, user_attributes)
    return AuthentikUserProfile(
        authentik_user_id=subject,
        name=_first_string(user, context, "name"),
        email=_first_string(user, context, "email"),
        department=_first_attribute_string(user_attributes, context_attributes, "department"),
        status=status,
    )


def _optional_section(
    payload: AuthentikPayloadInput,
    key: Literal["user", "context"],
) -> AuthentikPayloadSection:
    value = payload.get(key)
    match value:
        case None:
            return {}
        case dict() as section:
            return _parse_section(section, key)
        case _:
            raise AuthentikPayloadError(key, "must be an object")


def _parse_section(
    section: dict[str, AuthentikPayloadValue],
    key: Literal["user", "context"],
) -> AuthentikPayloadSection:
    parsed: AuthentikPayloadSection = {}
    for field in ("uid", "name", "email", "sub"):
        if field in section:
            parsed[field] = _required_string(section[field], f"{key}.{field}")
    if "attributes" in section:
        parsed["attributes"] = _parse_attributes(section["attributes"], f"{key}.attributes")
    return parsed


def _optional_attributes(section: AuthentikPayloadSection) -> AuthentikAttributes:
    return section.get("attributes", {})


def _parse_attributes(
    value: AuthentikPayloadValue,
    field_name: str,
) -> AuthentikAttributes:
    match value:
        case dict() as attributes:
            parsed: AuthentikAttributes = {}
            for field in ("uid", "department", "status"):
                if field in attributes:
                    parsed[field] = _required_string(attributes[field], f"{field_name}.{field}")
            return parsed
        case _:
            raise AuthentikPayloadError(field_name, "must be an object")


def _parse_subject(
    user: AuthentikPayloadSection,
    context: AuthentikPayloadSection,
    context_attributes: AuthentikAttributes,
) -> str:
    candidates = (
        user.get("uid", ""),
        context.get("sub", ""),
        context_attributes.get("uid", ""),
    )
    populated = tuple(candidate for candidate in candidates if candidate != "")
    if not populated:
        raise AuthentikPayloadError(SUBJECT_FIELD, SUBJECT_REQUIRED_REASON)
    if len(frozenset(populated)) > 1:
        raise AuthentikPayloadError(SUBJECT_FIELD, SUBJECT_CONFLICT_REASON)
    return populated[0]


def _parse_status(
    payload: AuthentikPayloadInput,
    user_attributes: AuthentikAttributes,
) -> UserStatus:
    explicit_status = _optional_string(payload, "status") or user_attributes.get("status", "")
    if explicit_status:
        return _supported_status(explicit_status)

    is_active = payload.get("is_active", True)
    match is_active:
        case bool() as active:
            return USER_STATUS_ACTIVE if active else USER_STATUS_DISABLED
        case _:
            raise AuthentikPayloadError(IS_ACTIVE_FIELD, IS_ACTIVE_BOOLEAN_REASON)


def _supported_status(status: str) -> UserStatus:
    if status not in SUPPORTED_STATUS_VALUES:
        raise AuthentikPayloadError(STATUS_FIELD, _unsupported_status_reason(status))
    match status:
        case "active":
            return USER_STATUS_ACTIVE
        case "disabled" | "inactive":
            return USER_STATUS_DISABLED
        case "departed":
            return USER_STATUS_DEPARTED
        case unsupported:
            raise AuthentikPayloadError(STATUS_FIELD, _unsupported_status_reason(unsupported))


def _unsupported_status_reason(status: str) -> str:
    return f"unsupported status: {status}"


def _optional_string(payload: AuthentikPayloadInput, key: str) -> str:
    value = payload.get(key)
    match value:
        case None:
            return ""
        case str() as string_value:
            return string_value
        case _:
            raise AuthentikPayloadError(key, "must be a string")


def _required_string(value: AuthentikPayloadValue, field_name: str) -> str:
    match value:
        case str() as string_value:
            if string_value == "":
                raise AuthentikPayloadError(field_name, "must not be empty")
            return string_value
        case _:
            raise AuthentikPayloadError(field_name, "must be a string")


def _first_string(
    user: AuthentikPayloadSection,
    context: AuthentikPayloadSection,
    field: Literal["name", "email"],
) -> str:
    return user.get(field, "") or context.get(field, "")


def _first_attribute_string(
    user_attributes: AuthentikAttributes,
    context_attributes: AuthentikAttributes,
    field: Literal["department"],
) -> str:
    return user_attributes.get(field, "") or context_attributes.get(field, "")
