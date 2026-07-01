from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, TypedDict, cast, override

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
    dingtalk: AuthentikDingTalkAttributes
    dingtalk_org: AuthentikDingTalkOrgAttributes


class AuthentikDingTalkAttributes(TypedDict, total=False):
    corp_id: str
    user_id: str
    union_id: str
    job_number: str
    name: str
    nick: str


class AuthentikDingTalkOrgAttributes(TypedDict, total=False):
    department: str
    manager_userid: str
    name: str


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
    dingtalk_corp_id: str = ""
    dingtalk_userid: str = ""
    dingtalk_union_id: str = ""
    employee_number: str = ""
    manager_userid: str = ""


def parse_authentik_payload(payload: AuthentikPayloadInput) -> AuthentikUserProfile:
    user = _optional_section(payload, "user")
    context = _optional_section(payload, "context")
    user_attributes = _optional_attributes(user)
    context_attributes = _optional_attributes(context)
    subject = _parse_subject(user, context, context_attributes)
    status = _parse_status(payload, user_attributes)
    dingtalk = _first_dingtalk_attributes(user_attributes, context_attributes)
    dingtalk_org = _first_dingtalk_org_attributes(user_attributes, context_attributes)
    return AuthentikUserProfile(
        authentik_user_id=subject,
        name=_first_string(user, context, "name") or _dingtalk_display_name(dingtalk, dingtalk_org),
        email=_first_string(user, context, "email"),
        department=dingtalk_org.get(
            "department",
            _first_attribute_string(user_attributes, context_attributes, "department"),
        ),
        status=status,
        dingtalk_corp_id=dingtalk.get("corp_id", ""),
        dingtalk_userid=dingtalk.get("user_id", ""),
        dingtalk_union_id=dingtalk.get("union_id", ""),
        employee_number=dingtalk.get("job_number", ""),
        manager_userid=dingtalk_org.get("manager_userid", ""),
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
            if "dingtalk" in attributes:
                parsed["dingtalk"] = _parse_dingtalk(
                    attributes["dingtalk"],
                    f"{field_name}.dingtalk",
                )
            if "dingtalk_org" in attributes:
                parsed["dingtalk_org"] = _parse_dingtalk_org(
                    attributes["dingtalk_org"],
                    f"{field_name}.dingtalk_org",
                )
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


def _parse_dingtalk(
    value: AuthentikPayloadValue,
    field_name: str,
) -> AuthentikDingTalkAttributes:
    match value:
        case dict() as attributes:
            parsed: AuthentikDingTalkAttributes = {}
            for field in ("corp_id", "user_id", "union_id", "job_number", "name", "nick"):
                if field in attributes:
                    parsed[field] = _required_string(attributes[field], f"{field_name}.{field}")
            return parsed
        case _:
            raise AuthentikPayloadError(field_name, "must be an object")


def _parse_dingtalk_org(
    value: AuthentikPayloadValue,
    field_name: str,
) -> AuthentikDingTalkOrgAttributes:
    match value:
        case dict() as attributes:
            org_attributes = cast("dict[str, AuthentikPayloadValue]", attributes)
            return {
                "department": _first_department_name(org_attributes.get("departments")),
                "manager_userid": _manager_user_id(org_attributes.get("manager")),
                "name": _optional_mapping_string(org_attributes, "name"),
            }
        case _:
            raise AuthentikPayloadError(field_name, "must be an object")


def _first_department_name(value: object) -> str:
    if not isinstance(value, list):
        return ""
    departments = cast("list[object]", value)
    for item in departments:
        if isinstance(item, dict):
            department = cast("dict[str, AuthentikPayloadValue]", item)
            name = department.get("name")
            if isinstance(name, str) and name:
                return name
    return ""


def _manager_user_id(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    manager = cast("dict[str, AuthentikPayloadValue]", value)
    user_id = manager.get("user_id")
    return user_id if isinstance(user_id, str) else ""


def _first_dingtalk_attributes(
    user_attributes: AuthentikAttributes,
    context_attributes: AuthentikAttributes,
) -> AuthentikDingTalkAttributes:
    return user_attributes.get("dingtalk", {}) or context_attributes.get("dingtalk", {})


def _first_dingtalk_org_attributes(
    user_attributes: AuthentikAttributes,
    context_attributes: AuthentikAttributes,
) -> AuthentikDingTalkOrgAttributes:
    return user_attributes.get("dingtalk_org", {}) or context_attributes.get("dingtalk_org", {})


def _dingtalk_display_name(
    dingtalk: AuthentikDingTalkAttributes,
    dingtalk_org: AuthentikDingTalkOrgAttributes,
) -> str:
    return dingtalk.get("name", "") or dingtalk.get("nick", "") or dingtalk_org.get("name", "")


def _optional_mapping_string(mapping: dict[str, AuthentikPayloadValue], key: str) -> str:
    value = mapping.get(key)
    return value if isinstance(value, str) else ""
