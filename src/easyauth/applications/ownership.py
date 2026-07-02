from __future__ import annotations

from dataclasses import dataclass

from easyauth.applications.models import App, AppMembership
from easyauth.applications.ops_models import (
    APP_MEMBERSHIP_ROLE_DEVELOPER,
    APP_MEMBERSHIP_ROLE_OWNER,
)


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
    _ = actor
    return list(App.objects.order_by("app_key"))


def _has_active_owner_membership(actor: ConsoleActor, app: App) -> bool:
    return AppMembership.objects.filter(
        app=app,
        user_id=actor.user_id,
        role=APP_MEMBERSHIP_ROLE_OWNER,
        is_active=True,
    ).exists()
