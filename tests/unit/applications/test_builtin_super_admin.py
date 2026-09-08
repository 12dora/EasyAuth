from __future__ import annotations

from json import dumps
from typing import Any, Final

import pytest
from django.utils import timezone

from easyauth.applications.builtin_authorization_groups import (
    BUILTIN_SUPER_ADMIN_DESCRIPTION,
    BUILTIN_SUPER_ADMIN_DESCRIPTION_EN,
    BUILTIN_SUPER_ADMIN_KIND,
    BUILTIN_SUPER_ADMIN_NAME,
    BUILTIN_SUPER_ADMIN_NAME_EN,
    RESERVED_AUTHORIZATION_GROUP_REASON,
    ensure_builtin_super_admin,
)
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.applications.models.constants import BUILTIN_SUPER_ADMIN_GROUP_KEY
from easyauth.applications.permission_templates import (
    AppManifestInput,
    PermissionTemplateImportError,
    apply_permission_template,
    parse_permission_template,
)

pytestmark = pytest.mark.django_db

APP_KEY: Final = "builtin-super-admin"


def test_ensure_builtin_super_admin_creates_empty_group_for_fresh_app() -> None:
    app = App.objects.create(app_key=f"{APP_KEY}-fresh", name="Fresh")

    group = ensure_builtin_super_admin(app)
    again = ensure_builtin_super_admin(app)

    assert group.id == again.id
    assert group.key == BUILTIN_SUPER_ADMIN_GROUP_KEY
    assert group.kind == BUILTIN_SUPER_ADMIN_KIND
    assert group.name == BUILTIN_SUPER_ADMIN_NAME
    assert group.name_en == BUILTIN_SUPER_ADMIN_NAME_EN
    assert group.description == BUILTIN_SUPER_ADMIN_DESCRIPTION
    assert group.description_en == BUILTIN_SUPER_ADMIN_DESCRIPTION_EN
    assert group.requestable is False
    assert group.is_active is True
    assert AuthorizationGroup.objects.filter(app=app).count() == 1
    assert AuthorizationGroupGrant.objects.filter(authorization_group=group).count() == 0


def test_ensure_builtin_super_admin_resyncs_grants_when_catalog_changes() -> None:
    app = App.objects.create(app_key=f"{APP_KEY}-resync", name="Resync")
    group = ensure_builtin_super_admin(app)
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    team_scope = AppScope.objects.create(app=app, key="TEAM", name="团队")
    read = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="查看发票",
        supported_scopes=["GLOBAL", "TEAM"],
    )
    write = Permission.objects.create(
        app=app,
        key="invoice.write",
        name="开具发票",
        supported_scopes=["GLOBAL"],
    )

    _ = ensure_builtin_super_admin(app)
    assert _active_grant_pairs(group) == {
        (read.id, "GLOBAL"),
        (read.id, "TEAM"),
        (write.id, "GLOBAL"),
    }

    team_scope.is_active = False
    team_scope.save(update_fields=["is_active", "updated_at"])
    write.is_active = False
    write.deprecated_at = timezone.now()
    write.save(update_fields=["is_active", "deprecated_at", "updated_at"])
    extra_scope = AppScope.objects.create(app=app, key="SELF", name="本人")
    extra = Permission.objects.create(
        app=app,
        key="invoice.export",
        name="导出发票",
        supported_scopes=["SELF"],
    )

    _ = ensure_builtin_super_admin(app)
    assert _active_grant_pairs(group) == {
        (read.id, "GLOBAL"),
        (extra.id, extra_scope.key),
    }
    assert AuthorizationGroupGrant.objects.filter(
        authorization_group=group,
        permission=read,
        scope_key="TEAM",
        is_active=False,
    ).exists()
    assert AuthorizationGroupGrant.objects.filter(
        authorization_group=group,
        permission=write,
        scope_key="GLOBAL",
        is_active=False,
    ).exists()


def test_manifest_import_cannot_remove_or_declare_super_admin() -> None:
    app = App.objects.create(app_key=APP_KEY, name="旧名称")
    first = _parsed_manifest(schema_version=1)
    _ = apply_permission_template(app=app, template=first)

    group = AuthorizationGroup.objects.get(app=app, key=BUILTIN_SUPER_ADMIN_GROUP_KEY)
    billing = Permission.objects.get(app=app, key="billing.read")
    assert group.is_active is True
    assert group.requestable is False
    assert _active_grant_pairs(group) == {(billing.id, "SELF")}

    second_payload = _manifest_payload(schema_version=2)
    second_payload["permissions"] = [
        {
            "key": "billing.read",
            "name": "查看账务",
            "group_key": "billing",
            "supported_scopes": ["SELF", "TEAM"],
            "risk_level": "standard",
        },
        {
            "key": "billing.write",
            "name": "登记账务",
            "group_key": "billing",
            "supported_scopes": ["SELF"],
            "risk_level": "standard",
        },
    ]
    second_payload["scopes"].append({"key": "TEAM", "name": "团队", "display_order": 30})
    second = parse_permission_template(
        app_key=APP_KEY,
        raw_template=dumps(second_payload),
        template_format="json",
        imported_by="owner-001",
    )
    _ = apply_permission_template(app=app, template=second)

    group.refresh_from_db()
    write = Permission.objects.get(app=app, key="billing.write")
    assert group.is_active is True
    assert group.key == BUILTIN_SUPER_ADMIN_GROUP_KEY
    assert _active_grant_pairs(group) == {
        (billing.id, "SELF"),
        (billing.id, "TEAM"),
        (write.id, "SELF"),
    }

    declared = _manifest_payload(schema_version=3)
    declared["authorization_groups"].append(
        {
            "key": BUILTIN_SUPER_ADMIN_GROUP_KEY,
            "kind": "role",
            "name": "伪造超管",
            "grants": [{"permission": "billing.read", "scope": "SELF"}],
        },
    )
    template = parse_permission_template(
        app_key=APP_KEY,
        raw_template=dumps(declared),
        template_format="json",
        imported_by="owner-001",
    )
    with pytest.raises(PermissionTemplateImportError) as raised:
        _ = apply_permission_template(app=app, template=template)
    assert raised.value.code == RESERVED_AUTHORIZATION_GROUP_REASON
    assert raised.value.subject == BUILTIN_SUPER_ADMIN_GROUP_KEY
    group.refresh_from_db()
    assert group.name == BUILTIN_SUPER_ADMIN_NAME
    assert group.is_active is True


def _active_grant_pairs(group: AuthorizationGroup) -> set[tuple[int, str]]:
    return {
        (grant.permission_id, grant.scope_key)
        for grant in AuthorizationGroupGrant.objects.filter(
            authorization_group=group,
            is_active=True,
        )
    }


def _parsed_manifest(*, schema_version: int) -> AppManifestInput:
    return parse_permission_template(
        app_key=APP_KEY,
        raw_template=dumps(_manifest_payload(schema_version=schema_version)),
        template_format="json",
        imported_by="owner-001",
    )


def _manifest_payload(*, schema_version: int) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "app": {
            "app_key": APP_KEY,
            "name": "Ops1",
            "description": "权限目录",
        },
        "scopes": [
            {"key": "SELF", "name": "本人", "display_order": 10},
        ],
        "permission_groups": [
            {"key": "billing", "name": "账务", "display_order": 10},
        ],
        "permissions": [
            {
                "key": "billing.read",
                "name": "查看账务",
                "group_key": "billing",
                "supported_scopes": ["SELF"],
                "risk_level": "standard",
            },
        ],
        "authorization_groups": [
            {
                "key": "accountant",
                "kind": "role",
                "name": "会计",
                "requestable": True,
                "is_active": True,
                "grants": [{"permission": "billing.read", "scope": "SELF"}],
            },
        ],
        "approval_rules": [
            {
                "target_type": "authorization_group",
                "target_key": "accountant",
                "approver_userids": ["manager-001"],
                "is_active": True,
            },
        ],
    }
