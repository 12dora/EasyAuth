from __future__ import annotations

from json import dumps
from typing import cast

import pytest
from django.core.exceptions import ValidationError

from easyauth.applications.configuration import (
    CONFIGURATION_STATUS_BLOCKING,
    configuration_readiness_for_app,
)
from easyauth.applications.models import (
    App,
    AppMembership,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.applications.permission_templates import (
    AppManifestInput,
    PermissionTemplateImportError,
    apply_permission_template,
    parse_permission_template,
)
from easyauth.applications.services import StaticTokenService

pytestmark = pytest.mark.django_db


def test_active_grant_rejects_inactive_scope_when_cleaned() -> None:
    app, group, permission = _grant_catalog()
    _ = AppScope.objects.create(app=app, key="LEGACY", name="历史", is_active=False)
    grant = AuthorizationGroupGrant(
        authorization_group=group,
        permission=permission,
        scope_key="LEGACY",
    )

    with pytest.raises(ValidationError) as raised:
        grant.full_clean()

    assert raised.value.message_dict == {
        "scope_key": ["Active grant must reference an active app scope."],
    }


def test_inactive_grant_allows_inactive_scope_removed_from_permission() -> None:
    app, group, permission = _grant_catalog()
    _ = AppScope.objects.create(app=app, key="LEGACY", name="历史", is_active=False)
    grant = AuthorizationGroupGrant(
        authorization_group=group,
        permission=permission,
        scope_key="LEGACY",
        is_active=False,
    )

    grant.full_clean()


def test_manifest_parser_rejects_active_grant_for_inactive_scope() -> None:
    payload = _manifest_payload(version=1, scope_key="LEGACY")
    payload["scopes"] = [
        {"key": "LEGACY", "name": "历史", "is_active": False},
        {"key": "CURRENT", "name": "当前"},
    ]

    with pytest.raises(PermissionTemplateImportError) as raised:
        _ = _parse_manifest(payload)

    assert raised.value.code == "app_manifest_grant_scope_inactive"


def test_manifest_parser_allows_inactive_grant_for_inactive_unsupported_scope() -> None:
    payload = _manifest_payload(version=1, scope_key="LEGACY", grant_active=False)
    payload["scopes"] = [
        {"key": "LEGACY", "name": "历史", "is_active": False},
        {"key": "CURRENT", "name": "当前"},
    ]
    permissions = cast("list[dict[str, object]]", payload["permissions"])
    permissions[0]["supported_scopes"] = ["CURRENT"]

    manifest = _parse_manifest(payload)

    assert manifest.authorization_groups[0].grants[0].is_active is False


def test_manifest_scope_shrink_deactivates_old_grant() -> None:
    app = App.objects.create(app_key="scope-grant", name="Scope Grant")
    initial = _manifest_payload(version=1, scope_key="LEGACY")
    _ = apply_permission_template(app=app, template=_parse_manifest(initial))
    updated = _manifest_payload(version=2, scope_key="CURRENT")

    _ = apply_permission_template(app=app, template=_parse_manifest(updated))

    permission = Permission.objects.get(app=app, key="invoice.read")
    grants = {
        grant.scope_key: grant.is_active
        for grant in AuthorizationGroupGrant.objects.filter(
            authorization_group__app=app,
        )
    }
    assert permission.supported_scopes == ["CURRENT"]
    assert AppScope.objects.get(app=app, key="LEGACY").is_active is False
    assert grants == {"CURRENT": True, "LEGACY": False}


def test_readiness_blocks_active_grant_for_inactive_scope() -> None:
    app, group, permission = _grant_catalog(app_key="inactive-scope-readiness")
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key=scope.key,
    )
    _ = AppMembership.objects.create(app=app, user_id="owner-001", role="owner")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    _ = StaticTokenService.create_token(app=app, name="readiness token")
    scope.is_active = False
    scope.save(update_fields=["is_active", "updated_at"])

    readiness = configuration_readiness_for_app(app)

    assert readiness.status == CONFIGURATION_STATUS_BLOCKING
    assert [issue.code for issue in readiness.issues] == [
        "authorization_group_grant_scope_inactive",
    ]
    assert readiness.issues[0].subject == "accountant:invoice.read:GLOBAL"


def _grant_catalog(
    *,
    app_key: str = "scope-grant-model",
) -> tuple[App, AuthorizationGroup, Permission]:
    app = App.objects.create(app_key=app_key, name="Scope Grant")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="查看发票",
        supported_scopes=["GLOBAL"],
    )
    group = AuthorizationGroup.objects.create(
        app=app,
        key="accountant",
        kind="role",
        name="会计",
    )
    return app, group, permission


def _parse_manifest(payload: dict[str, object]) -> AppManifestInput:
    return parse_permission_template(
        app_key="scope-grant",
        raw_template=dumps(payload),
        template_format="json",
        imported_by="owner-001",
    )


def _manifest_payload(
    *,
    version: int,
    scope_key: str,
    grant_active: bool = True,
) -> dict[str, object]:
    return {
        "schema_version": version,
        "app": {"app_key": "scope-grant", "name": "Scope Grant"},
        "scopes": [{"key": scope_key, "name": scope_key}],
        "permission_groups": [{"key": "billing", "name": "账务"}],
        "permissions": [
            {
                "key": "invoice.read",
                "name": "查看发票",
                "group_key": "billing",
                "supported_scopes": [scope_key],
            },
        ],
        "authorization_groups": [
            {
                "key": "accountant",
                "kind": "role",
                "name": "会计",
                "grants": [
                    {
                        "permission": "invoice.read",
                        "scope": scope_key,
                        "is_active": grant_active,
                    },
                ],
            },
        ],
    }
