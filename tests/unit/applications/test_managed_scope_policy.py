from __future__ import annotations

from typing import Literal

import pytest
from django.core.exceptions import ValidationError

from easyauth.applications.managed_scope_policy import ManagedScopePolicyService
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    ManagedScopePolicy,
    Permission,
)

pytestmark = pytest.mark.django_db


def test_managed_scope_policy_accepts_app_default_target_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    policy = ManagedScopePolicy(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )

    # When
    policy.full_clean()

    # Then
    assert policy.enabled is True


def test_managed_scope_policy_rejects_unsupported_scope_and_resolver_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    policy = ManagedScopePolicy(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="TEAM",
        resolver="static",
    )

    # When / Then
    with pytest.raises(ValidationError) as error:
        policy.clean()
    assert error.value.message_dict == {
        "scope": ["Managed scope policy scope must be MANAGED_USERS."],
        "resolver": [
            "Managed scope policy resolver must be one of "
            "dingtalk_manager_chain, easyauth_team, union, disabled.",
        ],
    }


def test_managed_scope_policy_rejects_cross_app_grant_target_when_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm", name="CRM")
    erp = App.objects.create(app_key="erp", name="ERP")
    grant = _grant(erp)
    policy = ManagedScopePolicy(
        app=crm,
        target_type="authorization_group_grant",
        target_id=grant.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )

    # When / Then
    with pytest.raises(ValidationError) as error:
        policy.clean()
    assert error.value.message_dict == {
        "target_id": ["Authorization group grant target must belong to the same app."],
    }


def test_effective_policy_uses_app_default_for_app_scope() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    policy = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )

    # When
    effective = ManagedScopePolicyService.get_effective_policy(app=app)

    # Then
    assert effective is not None
    assert effective.policy == policy
    assert effective.source == "app_default"
    assert effective.inherited_from is None
    assert effective.resolver == "dingtalk_manager_chain"


def test_effective_policy_inherits_app_default_when_grant_has_no_override() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    grant = _grant(app)
    policy = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )

    # When
    effective = ManagedScopePolicyService.get_effective_policy(app=app, grant=grant)

    # Then
    assert effective is not None
    assert effective.policy == policy
    assert effective.source == "app_default"
    assert effective.inherited_from == "app_default"


def test_effective_policy_prefers_grant_override_over_app_default() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    grant = _grant(app)
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )
    override = ManagedScopePolicy.objects.create(
        app=app,
        target_type="authorization_group_grant",
        target_id=grant.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )

    # When
    effective = ManagedScopePolicyService.get_effective_policy(app=app, grant=grant)

    # Then
    assert effective is not None
    assert effective.policy == override
    assert effective.source == "authorization_group_grant"
    assert effective.inherited_from is None


@pytest.mark.parametrize(
    ("enabled", "resolver"),
    [
        (False, "dingtalk_manager_chain"),
        (True, "disabled"),
    ],
)
def test_effective_policy_ignores_disabled_app_default_policy(
    enabled: Literal[True, False],
    resolver: str,
) -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver=resolver,
        enabled=enabled,
    )

    # When
    effective = ManagedScopePolicyService.get_effective_policy(app=app)

    # Then
    assert effective is None


@pytest.mark.parametrize(
    ("enabled", "resolver"),
    [
        (False, "dingtalk_manager_chain"),
        (True, "disabled"),
    ],
)
def test_disabled_grant_override_blocks_app_default_inheritance(
    enabled: Literal[True, False],
    resolver: str,
) -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    grant = _grant(app)
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="authorization_group_grant",
        target_id=grant.id,
        scope="MANAGED_USERS",
        resolver=resolver,
        enabled=enabled,
    )

    # When
    effective = ManagedScopePolicyService.get_effective_policy(app=app, grant=grant)

    # Then
    assert effective is None


def _grant(app: App) -> AuthorizationGroupGrant:
    _ = AppScope.objects.create(app=app, key="MANAGED_USERS", name="Managed users")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="MANAGER",
        kind="role",
        name="Manager",
    )
    permission = Permission.objects.create(
        app=app,
        key="orders.read",
        name="Read orders",
        supported_scopes=["MANAGED_USERS"],
    )
    return AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="MANAGED_USERS",
    )
