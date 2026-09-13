from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from easyauth.applications.models import App, AppMembership
from easyauth.applications.ops_models import (
    APP_MEMBERSHIP_ROLE_DEVELOPER,
    APP_MEMBERSHIP_ROLE_OWNER,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.models import QuerySet


@dataclass(frozen=True, slots=True)
class ConsoleActor:
    user_id: str
    is_superuser: bool


def can_view_app(actor: ConsoleActor, app: App) -> bool:
    if actor.is_superuser:
        return True
    return AppMembership.objects.filter(
        app=app,
        user_id=actor.user_id,
        role__in=(APP_MEMBERSHIP_ROLE_OWNER, APP_MEMBERSHIP_ROLE_DEVELOPER),
        is_active=True,
    ).exists()


def can_manage_app(actor: ConsoleActor, app: App) -> bool:
    if actor.is_superuser:
        return True
    return _has_active_owner_membership(actor, app)


def can_operate_credentials(actor: ConsoleActor, app: App) -> bool:
    return can_manage_app(actor, app)


def apps_visible_to_actor(actor: ConsoleActor) -> list[App]:
    return list(apps_visible_to_actor_queryset(actor))


def apps_visible_to_actor_queryset(actor: ConsoleActor) -> QuerySet[App]:
    if actor.is_superuser:
        return App.objects.order_by("app_key")
    return (
        App.objects.filter(
            memberships__user_id=actor.user_id,
            memberships__role__in=(APP_MEMBERSHIP_ROLE_OWNER, APP_MEMBERSHIP_ROLE_DEVELOPER),
            memberships__is_active=True,
        )
        .distinct()
        .order_by("app_key")
    )


def member_user_ids_by_app_id(
    app_ids: Iterable[int],
    *,
    role: str,
) -> dict[int, tuple[str, ...]]:
    ids = tuple(app_ids)
    member_ids_by_app_id: dict[int, list[str]] = {app_id: [] for app_id in ids}
    if not ids:
        return {}
    membership_rows = (
        AppMembership.objects.filter(
            app_id__in=ids,
            role=role,
            is_active=True,
        )
        .order_by("app_id", "user_id")
        .values_list("app_id", "user_id")
    )
    for raw_app_id, raw_user_id in cast("Iterable[tuple[object, object]]", membership_rows):
        member_ids_by_app_id.setdefault(cast("int", raw_app_id), []).append(
            cast("str", raw_user_id),
        )
    return {app_id: tuple(user_ids) for app_id, user_ids in member_ids_by_app_id.items()}


def _has_active_owner_membership(actor: ConsoleActor, app: App) -> bool:
    return AppMembership.objects.filter(
        app=app,
        user_id=actor.user_id,
        role=APP_MEMBERSHIP_ROLE_OWNER,
        is_active=True,
    ).exists()
