from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override

if TYPE_CHECKING:
    from django.http import QueryDict

from easyauth.admin_console.configuration import (
    ApprovalRuleCreateMutation,
    ConsoleMutationActor,
    RolePermissionMutation,
    create_approval_rule,
    create_permission,
    create_role,
    set_role_permission,
)
from easyauth.applications.models import App, Permission, Role

CONFIGURATION_FORM_ERROR_MESSAGE: Final = "表单参数无效"


@dataclass(frozen=True, slots=True)
class ConsoleConfigurationFormError(Exception):
    message: str = CONFIGURATION_FORM_ERROR_MESSAGE

    @override
    def __str__(self) -> str:
        return self.message


def handle_configuration_form_post(
    *,
    post: QueryDict,
    actor_id: str,
    app: App,
    action: str,
) -> None:
    mutation_actor = ConsoleMutationActor(actor_id=actor_id)
    match action:
        case "set_role_permission":
            set_role_permission(
                RolePermissionMutation(
                    app=app,
                    role=_role_for_app(post, "role_id", app),
                    permission=_permission_for_app(post, "permission_id", app),
                    enabled=post.get("enabled") == "on",
                    actor=mutation_actor,
                ),
            )
        case "create_role":
            _ = create_role(
                app=app,
                key=post.get("role_key", "").strip(),
                name=post.get("role_name", "").strip(),
                requestable=post.get("requestable") == "on",
                actor=mutation_actor,
            )
        case "create_permission":
            _ = create_permission(
                app=app,
                key=post.get("permission_key", "").strip(),
                name=post.get("permission_name", "").strip(),
                actor=mutation_actor,
            )
        case "create_approval_rule":
            _ = create_approval_rule(
                ApprovalRuleCreateMutation(
                    app=app,
                    role=_role_for_app(post, "approval_role_id", app),
                    permission=None,
                    approver_userids=_approver_userids(post.get("approver_userids", "")),
                    is_active=True,
                    actor=mutation_actor,
                ),
            )
        case _:
            return


def _post_int(post: QueryDict, key: str) -> int:
    try:
        return int(post.get(key, "0"))
    except ValueError as error:
        raise ConsoleConfigurationFormError from error


def _role_for_app(post: QueryDict, key: str, app: App) -> Role:
    try:
        return Role.objects.get(id=_post_int(post, key), app=app)
    except Role.DoesNotExist as error:
        raise ConsoleConfigurationFormError from error


def _permission_for_app(post: QueryDict, key: str, app: App) -> Permission:
    try:
        return Permission.objects.get(id=_post_int(post, key), app=app)
    except Permission.DoesNotExist as error:
        raise ConsoleConfigurationFormError from error


def _approver_userids(raw_value: str) -> tuple[str, ...]:
    return tuple(userid.strip() for userid in raw_value.split(",") if userid.strip())
