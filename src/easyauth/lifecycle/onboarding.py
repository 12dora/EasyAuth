from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.db import transaction

from easyauth.accounts.models import UserMirror
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.inputs import AuthorizationGroupGrantInput, ScopedDirectGrantInput
from easyauth.grants.models import AccessGrant
from easyauth.lifecycle.core import (
    TRANSFER_TEMPLATE_REVISION_MISSING_MESSAGE,
)
from easyauth.lifecycle.errors import HandoverConflictError
from easyauth.lifecycle.models import (
    OnboardingTemplate,
    OnboardingTemplateRevision,
    OnboardingTemplateRevisionItem,
)
from easyauth.lifecycle.transfer import merge_into_current_grant, revision_item_expiry

if TYPE_CHECKING:
    from collections.abc import Iterable


def onboard_user(
    *,
    user: UserMirror,
    template: OnboardingTemplate,
    actor_id: str,
) -> list[AccessGrant]:
    """一键入职: 按模板项批量创建授权(每 APP 一条 current 授权, 复用现有授权服务)。"""
    with transaction.atomic():
        user, template, template_revision = _lock_onboarding_inputs(user=user, template=template)
        by_app = _group_revision_items_by_app(template_revision)
        _lock_current_grants(user=user, app_ids=by_app)
        grants: list[AccessGrant] = []
        for app_items in by_app.values():
            groups, direct_grants = _grant_inputs_for_app(app_items)
            grants.append(
                merge_into_current_grant(
                    user=user,
                    app=app_items[0].app,
                    groups=groups,
                    direct_grants=direct_grants,
                    actor_id=actor_id,
                ),
            )
        _record_onboarding_event(
            user=user,
            template=template,
            actor_id=actor_id,
            app_count=len(by_app),
        )
        return grants


def _lock_onboarding_inputs(
    *,
    user: UserMirror,
    template: OnboardingTemplate,
) -> tuple[UserMirror, OnboardingTemplate, OnboardingTemplateRevision]:
    locked_user = UserMirror.objects.select_for_update().get(pk=cast("int", user.pk))
    locked_template = (
        OnboardingTemplate.objects.select_for_update(of=("self",))
        .select_related("current_revision")
        .get(pk=template.id)
    )
    template_revision = locked_template.current_revision
    if template_revision is None:
        raise HandoverConflictError(TRANSFER_TEMPLATE_REVISION_MISSING_MESSAGE)
    return locked_user, locked_template, template_revision


def _group_revision_items_by_app(
    template_revision: OnboardingTemplateRevision,
) -> dict[int, list[OnboardingTemplateRevisionItem]]:
    items = list(
        OnboardingTemplateRevisionItem.objects.select_related(
            "app",
            "authorization_group",
            "permission",
        ).filter(revision=template_revision, app__is_active=True),
    )
    by_app: dict[int, list[OnboardingTemplateRevisionItem]] = {}
    for item in items:
        by_app.setdefault(item.app_id, []).append(item)
    return by_app


def _lock_current_grants(*, user: UserMirror, app_ids: Iterable[int]) -> None:
    _ = list(
        AccessGrant.objects.select_for_update().filter(
            user=user,
            app_id__in=app_ids,
            is_current=True,
        ),
    )


def _grant_inputs_for_app(
    app_items: list[OnboardingTemplateRevisionItem],
) -> tuple[list[AuthorizationGroupGrantInput], list[ScopedDirectGrantInput]]:
    groups = [
        AuthorizationGroupGrantInput(
            authorization_group=item.authorization_group,
            expires_at=revision_item_expiry(item),
        )
        for item in app_items
        if item.authorization_group is not None
    ]
    direct_grants = [
        ScopedDirectGrantInput(
            permission=item.permission,
            scope_key=item.scope_key,
            expires_at=revision_item_expiry(item),
        )
        for item in app_items
        if item.permission is not None
    ]
    return groups, direct_grants


def _record_onboarding_event(
    *,
    user: UserMirror,
    template: OnboardingTemplate,
    actor_id: str,
    app_count: int,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action="lifecycle_onboarded",
            target_type="user",
            target_id=user.authentik_user_id,
            metadata={
                "template": template.name,
                "app_count": app_count,
            },
        ),
    )
