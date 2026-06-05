from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Final, Literal

from django.utils import timezone

from easyauth.access_requests.models import GRANT_TYPE_PERMANENT
from easyauth.applications.models import App, Role

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import QueryDict

type GrantLifetime = Literal["permanent", "timed"]

DATETIME_LOCAL_FORMAT: Final = "%Y-%m-%dT%H:%M"


@dataclass(frozen=True, slots=True)
class AppOption:
    id_value: str
    name: str


@dataclass(frozen=True, slots=True)
class RoleOption:
    id_value: str
    app_id_value: str
    label: str


@dataclass(frozen=True, slots=True)
class AccessRequestForm:
    app_id_value: str
    role_id_value: str
    grant_type_value: str
    grant_expires_at_value: str
    reason_value: str
    selected_app_value: App | None
    selected_role_value: Role | None
    selected_grant_expires_at_value: datetime | None
    app_errors: tuple[str, ...] = ()
    role_errors: tuple[str, ...] = ()
    grant_type_errors: tuple[str, ...] = ()
    grant_expires_at_errors: tuple[str, ...] = ()
    reason_errors: tuple[str, ...] = ()

    @classmethod
    def empty(cls) -> AccessRequestForm:
        return cls(
            app_id_value="",
            role_id_value="",
            grant_type_value=GRANT_TYPE_PERMANENT,
            grant_expires_at_value="",
            reason_value="",
            selected_app_value=None,
            selected_role_value=None,
            selected_grant_expires_at_value=None,
        )

    @classmethod
    def bind(cls, data: QueryDict) -> AccessRequestForm:
        app_id_value = _query_value(data, "app_id")
        role_id_value = _query_value(data, "role_id")
        grant_type_value = _query_value(data, "grant_type")
        grant_expires_at_value = _query_value(data, "grant_expires_at")
        reason_value = _query_value(data, "reason").strip()

        selected_app = _selected_app(app_id_value)
        selected_role = _selected_role(role_id_value)
        selected_expiration, expiration_parse_errors = _selected_expiration(
            grant_expires_at_value,
        )
        app_errors = _app_errors(selected_app)
        role_errors = _role_errors(selected_app, selected_role)
        grant_type_errors = _grant_type_errors(grant_type_value)
        grant_expires_at_errors = _grant_expires_at_errors(
            grant_type_value,
            selected_expiration,
            expiration_parse_errors,
        )
        reason_errors = _reason_errors(reason_value)

        return cls(
            app_id_value=app_id_value,
            role_id_value=role_id_value,
            grant_type_value=grant_type_value,
            grant_expires_at_value=grant_expires_at_value,
            reason_value=reason_value,
            selected_app_value=selected_app,
            selected_role_value=selected_role,
            selected_grant_expires_at_value=selected_expiration,
            app_errors=app_errors,
            role_errors=role_errors,
            grant_type_errors=grant_type_errors,
            grant_expires_at_errors=grant_expires_at_errors,
            reason_errors=reason_errors,
        )

    def is_valid(self) -> bool:
        return not (
            self.app_errors
            or self.role_errors
            or self.grant_type_errors
            or self.grant_expires_at_errors
            or self.reason_errors
        )

    def with_role_error(self, message: str) -> AccessRequestForm:
        return replace(self, role_errors=(*self.role_errors, message))

    def selected_app(self) -> App:
        if self.selected_app_value is None:
            message = "表单应用字段必须解析为 App。"
            raise TypeError(message)
        return self.selected_app_value

    def selected_role(self) -> Role:
        if self.selected_role_value is None:
            message = "表单角色字段必须解析为 Role。"
            raise TypeError(message)
        return self.selected_role_value

    def selected_lifetime(self) -> GrantLifetime:
        match self.grant_type_value:
            case "permanent":
                return "permanent"
            case "timed":
                return "timed"
            case unsupported:
                message = f"表单授权期限字段不支持: {unsupported}"
                raise TypeError(message)

    def selected_grant_expires_at(self) -> datetime | None:
        return self.selected_grant_expires_at_value

    def selected_reason(self) -> str:
        return self.reason_value


def app_options() -> tuple[AppOption, ...]:
    return tuple(AppOption(id_value=str(app.id), name=app.name) for app in _requestable_apps())


def role_options() -> tuple[RoleOption, ...]:
    return tuple(
        RoleOption(
            id_value=str(role.id),
            app_id_value=str(role.app.id),
            label=f"{role.app.name} / {role.name}",
        )
        for role in _requestable_roles()
    )


def _query_value(data: QueryDict, key: str) -> str:
    value = data.get(key)
    if isinstance(value, str):
        return value
    return ""


def _selected_app(app_id_value: str) -> App | None:
    app_id = _parse_int(app_id_value)
    if app_id is None:
        return None
    return App.objects.filter(id=app_id, is_active=True).first()


def _selected_role(role_id_value: str) -> Role | None:
    role_id = _parse_int(role_id_value)
    if role_id is None:
        return None
    return _requestable_roles().filter(id=role_id).first()


def _selected_expiration(expires_at_value: str) -> tuple[datetime | None, tuple[str, ...]]:
    if expires_at_value == "":
        return None, ()
    try:
        parsed = datetime.strptime(expires_at_value, DATETIME_LOCAL_FORMAT).replace(
            tzinfo=timezone.get_current_timezone(),
        )
    except ValueError:
        return None, ("请输入有效的到期时间。",)
    return parsed, ()


def _parse_int(raw_value: str) -> int | None:
    if raw_value == "":
        return None
    try:
        return int(raw_value)
    except ValueError:
        return None


def _app_errors(app: App | None) -> tuple[str, ...]:
    if app is None:
        return ("请选择可申请的应用。",)
    return ()


def _role_errors(app: App | None, role: Role | None) -> tuple[str, ...]:
    if role is None:
        return ("该角色当前不可申请。",)
    if app is not None and role.app.id != app.id:
        return ("该角色不属于所选应用。",)
    return ()


def _grant_type_errors(grant_type_value: str) -> tuple[str, ...]:
    match grant_type_value:
        case "permanent" | "timed":
            return ()
        case _:
            return ("请选择有效授权期限。",)


def _grant_expires_at_errors(
    grant_type_value: str,
    selected_expiration: datetime | None,
    parse_errors: tuple[str, ...],
) -> tuple[str, ...]:
    if parse_errors:
        return parse_errors
    match grant_type_value:
        case "timed":
            if selected_expiration is None:
                return ("请选择限时授权的到期时间。",)
        case "permanent":
            if selected_expiration is not None:
                return ("长期授权不需要填写过期时间。",)
        case _:
            return ()
    return ()


def _reason_errors(reason: str) -> tuple[str, ...]:
    if reason == "":
        return ("请填写申请原因。",)
    return ()


def _requestable_roles() -> QuerySet[Role]:
    return (
        Role.objects.select_related("app")
        .filter(
            app__is_active=True,
            is_active=True,
            requestable=True,
            approval_rules__is_active=True,
        )
        .distinct()
        .order_by("app__app_key", "key")
    )


def _requestable_apps() -> QuerySet[App]:
    return (
        App.objects.filter(
            is_active=True,
            roles__is_active=True,
            roles__requestable=True,
            roles__approval_rules__is_active=True,
        )
        .distinct()
        .order_by("app_key")
    )
