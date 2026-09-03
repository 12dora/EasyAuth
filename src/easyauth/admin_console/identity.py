from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import DatabaseError

from easyauth.accounts.auth import (
    AUTHENTIK_SESSION_KEY,
    clear_auth_session,
)
from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX, current_local_admin
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.ownership import ConsoleActor
from easyauth.integrations.authentik.admin_client import (
    AuthentikAdminClient,
    AuthentikAdminError,
)

if TYPE_CHECKING:
    from django.http import HttpRequest


def actor_from_request(request: HttpRequest) -> ConsoleActor | None:
    authentik_user_id = _session_string(request, AUTHENTIK_SESSION_KEY)
    if authentik_user_id == "":
        return None

    if authentik_user_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        return _local_admin_actor(request, authentik_user_id)
    return _oidc_actor(request, authentik_user_id)


def _local_admin_actor(request: HttpRequest, authentik_user_id: str) -> ConsoleActor | None:
    try:
        account = current_local_admin(request)
    except DatabaseError:
        return None
    if account is None:
        _clear_console_session(request)
        return None
    user = _active_user(authentik_user_id)
    if user is None:
        _clear_console_session(request)
        return None
    return ConsoleActor(user_id=user.authentik_user_id, is_superuser=True)


def _oidc_actor(request: HttpRequest, authentik_user_id: str) -> ConsoleActor | None:
    user = _active_user(authentik_user_id)
    if user is None:
        _clear_console_session(request)
        return None
    # is_superuser 由本地 is_console_admin 与 Authentik 超管组取并集, 见 _is_console_superuser。
    return ConsoleActor(
        user_id=user.authentik_user_id,
        is_superuser=_is_console_superuser(request, user),
    )


def _active_user(authentik_user_id: str) -> UserMirror | None:
    try:
        return UserMirror.objects.filter(
            authentik_user_id=authentik_user_id,
            status=USER_STATUS_ACTIVE,
        ).first()
    except DatabaseError:
        return None


def _is_console_superuser(request: HttpRequest, user: UserMirror) -> bool:
    # 控制台管理员 = UserMirror.is_console_admin 或 Authentik 超管组。
    # 本地标志是 EasyAuth 内授予/撤销的唯一落库位; Authentik 组用于引导首位管理员
    # (bootstrap) 以及组同步仍生效时的来源。Authentik 管理 API 失败只表示
    # 「不是组超管」, 本地标志仍须生效: 它是本库数据, 不依赖外部 API。
    del request
    # 本地标志为真时短路: 不必再打 Authentik 管理 API。门户每次渲染壳层都会走到这里,
    # web 只有 4 个同步 worker, 省掉这次出站 HTTP 就是省掉一次可能的阻塞。
    if user.is_console_admin:
        return True
    group_superuser = False
    try:
        authority_groups = frozenset(
            _string_values(
                AuthentikAdminClient.from_settings().user_group_names_by_uid(
                    user.authentik_user_id,
                )
            ),
        )
        configured_groups = frozenset(
            _string_values(_setting_value("EASYAUTH_CONSOLE_SUPERUSER_GROUPS")),
        )
        group_superuser = bool(
            configured_groups and not configured_groups.isdisjoint(authority_groups),
        )
    except AuthentikAdminError:
        group_superuser = False
    return group_superuser


def _clear_console_session(request: HttpRequest) -> None:
    clear_auth_session(request)


def _session_string(request: HttpRequest, key: str) -> str:
    match request.session.get(key):
        case str() as value:
            return value
        case _:
            return ""


def _setting_value(name: str) -> object:
    return getattr(settings, name, ())


def _string_values(value: object) -> tuple[str, ...]:
    match value:
        case str() as text:
            return tuple(part for part in text.split() if part)
        case Iterable() as values:
            return tuple(item for item in values if isinstance(item, str) and item)
        case _:
            return ()
