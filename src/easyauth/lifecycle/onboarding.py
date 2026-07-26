from __future__ import annotations

from typing import cast

from django.db import transaction

from easyauth.accounts.models import UserMirror
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.inputs import AuthorizationGroupGrantInput, ScopedDirectGrantInput
from easyauth.grants.models import AccessGrant
from easyauth.lifecycle.core import (
    TRANSFER_TEMPLATE_REVISION_MISSING_MESSAGE,
)
from easyauth.lifecycle.errors import HandoverConflictError
from easyauth.lifecycle.models import OnboardingTemplate, OnboardingTemplateRevisionItem
from easyauth.lifecycle.transfer import merge_into_current_grant, revision_item_expiry


def onboard_user(
    *,
    user: UserMirror,
    template: OnboardingTemplate,
    actor_id: str,
) -> list[AccessGrant]:
    """一键入职: 按模板项批量创建授权(每 APP 一条 current 授权, 复用现有授权服务)。"""
    user_pk = cast("int", user.pk)
    with transaction.atomic():
        user = UserMirror.objects.select_for_update().get(pk=user_pk)
        template = (
            OnboardingTemplate.objects.select_for_update()
            .select_related("current_revision")
            .get(pk=template.id)
        )
        template_revision = template.current_revision
        if template_revision is None:
            raise HandoverConflictError(TRANSFER_TEMPLATE_REVISION_MISSING_MESSAGE)
        grants: list[AccessGrant] = []
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
        _ = list(
            AccessGrant.objects.select_for_update().filter(
                user=user,
                app_id__in=by_app,
                is_current=True,
            ),
        )
        for app_items in by_app.values():
            app = app_items[0].app
            grants.append(
                merge_into_current_grant(
                    user=user,
                    app=app,
                    groups=[
                        AuthorizationGroupGrantInput(
                            authorization_group=i.authorization_group,
                            expires_at=revision_item_expiry(i),
                        )
                        for i in app_items
                        if i.authorization_group is not None
                    ],
                    direct_grants=[
                        ScopedDirectGrantInput(
                            permission=i.permission,
                            scope_key=i.scope_key,
                            expires_at=revision_item_expiry(i),
                        )
                        for i in app_items
                        if i.permission is not None
                    ],
                    actor_id=actor_id,
                ),
            )
        _ = AuditService.record(
            AuditRecord(
                actor_type="admin",
                actor_id=actor_id,
                action="lifecycle_onboarded",
                target_type="user",
                target_id=user.authentik_user_id,
                metadata={
                    "template": template.name,
                    "app_count": len(by_app),
                },
            ),
        )
        return grants
