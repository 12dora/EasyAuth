from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.grants.inputs import AuthorizationGroupGrantInput, ScopedDirectGrantInput
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from easyauth.grants.operations import replace_memberships
from easyauth.grants.query import resolve_user_permissions
from easyauth.grants.services import GrantService

pytestmark = pytest.mark.django_db


def _catalog() -> tuple[UserMirror, App, Permission, AuthorizationGroup, AccessGrant]:
    user = UserMirror.objects.create(authentik_user_id="source-user", status="active")
    app = App.objects.create(app_key="sources", name="来源")
    AppScope.objects.get_or_create(app=app, key="GLOBAL", defaults={"name": "全局"})
    permission = Permission.objects.create(
        app=app, key="read", name="读取", supported_scopes=["GLOBAL"]
    )
    group = AuthorizationGroup.objects.create(app=app, key="reader", name="读取", kind="role")
    AuthorizationGroupGrant.objects.create(
        authorization_group=group, permission=permission, scope_key="GLOBAL"
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    return user, app, permission, group, grant


def test_replace_and_personal_revoke_preserve_department_memberships() -> None:
    user, app, permission, group, grant = _catalog()
    department_group = AccessGrantGroup.objects.create(
        grant=grant, authorization_group=group, source="department"
    )
    department_direct = AccessGrantPermission.objects.create(
        grant=grant, permission=permission, source="department"
    )
    replace_memberships(
        grant,
        [AuthorizationGroupGrantInput(group, None)],
        [ScopedDirectGrantInput(permission, "GLOBAL", None)],
    )
    replace_memberships(grant, (), [ScopedDirectGrantInput(permission, "GLOBAL", None)])
    assert AccessGrantGroup.objects.filter(pk=department_group.pk).exists()
    assert AccessGrantPermission.objects.filter(pk=department_direct.pk).exists()
    result = GrantService.revoke_user_memberships(
        user=user, app=app, actor_type="user", actor_id="source-user"
    )
    assert result is not None
    assert result.is_current
    assert result.version == 2
    assert not AccessGrantPermission.objects.filter(grant=grant, source="user").exists()
    assert AccessGrantPermission.objects.filter(pk=department_direct.pk).exists()


@pytest.mark.parametrize(
    ("personal_days", "department_days"), [(None, 2), (2, None), (2, 4), (4, 2)]
)
def test_query_merges_duplicate_sources_with_longest_expiry(
    personal_days: int | None,
    department_days: int | None,
) -> None:
    user, app, permission, group, grant = _catalog()
    now = timezone.now()
    expirations = [
        None if days is None else now + timedelta(days=days)
        for days in (personal_days, department_days)
    ]
    expected = None if None in expirations else max(expirations)
    for source, expiry in zip(("user", "department"), expirations, strict=True):
        AccessGrantGroup.objects.create(
            grant=grant, authorization_group=group, source=source, expires_at=expiry
        )
        AccessGrantPermission.objects.create(
            grant=grant, permission=permission, source=source, expires_at=expiry
        )
    snapshot = resolve_user_permissions(user=user, app=app)
    assert len(snapshot.groups) == 1
    assert len(snapshot.grants) == 2
    assert snapshot.groups[0].expires_at == expected
    assert all(item.expires_at == expected for item in snapshot.grants)
