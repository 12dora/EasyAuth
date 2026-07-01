from __future__ import annotations

from json import dumps
from typing import TYPE_CHECKING, Any, Final

import pytest

from easyauth.applications.models import (
    App,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
    PermissionGroup,
    PermissionTemplateVersion,
)
from easyauth.applications.permission_templates import (
    AppManifestInput,
    PermissionTemplateImportError,
    apply_permission_template,
    parse_permission_template,
    preview_permission_template,
)
from easyauth.audit.models import AuditLog

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.django_db

APP_KEY: Final = "ops1-manifest"


def test_ops1_app_manifest_parses_pasted_json_and_yaml() -> None:
    raw_json = dumps(_manifest_payload())
    raw_yaml = """
schema_version: 1
app:
  app_key: ops1-manifest
  name: Ops1
  description: 权限目录
scopes:
  - key: SELF
    name: 本人
permission_groups:
  - key: billing
    name: 账务
permissions:
  - key: billing.read
    name: 查看账务
    group_key: billing
    supported_scopes: [SELF]
authorization_groups:
  - key: accountant
    kind: role
    name: 会计
    grants:
      - permission: billing.read
        scope: SELF
approval_rules:
  - target_type: authorization_group
    target_key: accountant
    approver_userids: [manager-001]
"""

    parsed = [
        parse_permission_template(
            app_key=APP_KEY,
            raw_template=raw_json,
            template_format="json",
            imported_by="owner-001",
        ),
        parse_permission_template(
            app_key=APP_KEY,
            raw_template=raw_yaml,
            template_format="yaml",
            imported_by="owner-001",
        ),
    ]

    for manifest in parsed:
        assert isinstance(manifest, AppManifestInput)
        assert manifest.schema_version == 1
        assert manifest.source == "paste"
        assert manifest.imported_by == "owner-001"
        assert manifest.app.app_key == APP_KEY
        assert manifest.scopes[0].key == "SELF"
        assert manifest.permissions[0].supported_scopes == ("SELF",)
        assert manifest.authorization_groups[0].grants[0].permission == "billing.read"


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (
            lambda manifest: manifest["scopes"].append({"key": "SELF", "name": "重复"}),
            "app_manifest_duplicate_key",
        ),
        (
            lambda manifest: manifest["permissions"][0].update({"group_key": "missing"}),
            "app_manifest_unknown_permission_group",
        ),
        (
            lambda manifest: manifest["permissions"][0].update({"supported_scopes": ["ALL"]}),
            "app_manifest_unknown_scope",
        ),
        (
            lambda manifest: manifest["authorization_groups"][0]["grants"][0].update(
                {"permission": "missing.read"},
            ),
            "app_manifest_unknown_permission",
        ),
        (
            lambda manifest: manifest["authorization_groups"][0]["grants"][0].update(
                {"scope": "MANAGED"},
            ),
            "app_manifest_grant_scope_unsupported",
        ),
        (
            lambda manifest: manifest["approval_rules"][0].update({"target_key": "missing"}),
            "app_manifest_unknown_approval_target",
        ),
    ],
)
def test_ops1_app_manifest_rejects_invalid_references(
    mutator: Callable[[dict[str, Any]], None],
    code: str,
) -> None:
    payload = _manifest_payload()
    mutator(payload)

    with pytest.raises(PermissionTemplateImportError) as raised:
        _ = parse_permission_template(
            app_key=APP_KEY,
            raw_template=dumps(payload),
            template_format="json",
            imported_by="owner-001",
        )

    assert raised.value.code == code


def test_ops1_app_manifest_rejects_path_app_key_mismatch() -> None:
    payload = _manifest_payload()

    with pytest.raises(PermissionTemplateImportError) as raised:
        _ = parse_permission_template(
            app_key="other-app",
            raw_template=dumps(payload),
            template_format="json",
            imported_by="owner-001",
        )

    assert raised.value.code == "app_manifest_app_key_mismatch"


def test_ops1_app_manifest_preview_reports_manifest_diff_without_writing_database() -> None:
    app = App.objects.create(app_key=APP_KEY, name="旧名称")
    manifest = _parsed_manifest()

    preview = preview_permission_template(app=app, template=manifest)

    assert [(action.action, action.key) for action in preview.actions] == [
        ("update_app", APP_KEY),
        ("create_scope", "SELF"),
        ("create_scope", "MANAGED"),
        ("create_permission_group", "billing"),
        ("create_permission", "billing.read"),
        ("create_authorization_group", "accountant"),
        ("create_approval_rule", "authorization_group:accountant"),
    ]
    assert AppScope.objects.filter(app=app).count() == 0
    assert PermissionGroup.objects.filter(app=app).count() == 0
    assert Permission.objects.filter(app=app).count() == 0
    assert AuthorizationGroup.objects.filter(app=app).count() == 0
    assert PermissionTemplateVersion.objects.filter(app=app).count() == 0


def test_ops1_app_manifest_import_writes_catalog_and_bumps_version() -> None:
    initial_catalog_version: Final = 3
    app = App.objects.create(
        app_key=APP_KEY,
        name="旧名称",
        catalog_version=initial_catalog_version,
    )
    manifest = _parsed_manifest()

    result = apply_permission_template(app=app, template=manifest)

    app.refresh_from_db()
    permission = Permission.objects.get(app=app, key="billing.read")
    auth_group = AuthorizationGroup.objects.get(app=app, key="accountant")
    grant = AuthorizationGroupGrant.objects.get(authorization_group=auth_group)
    rule = ApprovalRule.objects.get(app=app)

    assert app.name == "Ops1"
    assert app.description == "权限目录"
    assert app.catalog_version == initial_catalog_version + 1
    assert AppScope.objects.get(app=app, key="SELF").name == "本人"
    assert permission.group == PermissionGroup.objects.get(app=app, key="billing")
    assert permission.supported_scopes == ["SELF"]
    assert grant.permission == permission
    assert grant.scope_key == "SELF"
    assert rule.authorization_group == auth_group
    assert rule.role is None
    assert result.template_version.version == 1
    assert result.template_version.import_summary["manifest_schema_version"] == 1
    assert AuditLog.objects.filter(event_type="app_manifest_imported").exists()


def test_ops1_app_manifest_import_deactivates_missing_objects_without_hard_delete() -> None:
    app = App.objects.create(app_key=APP_KEY, name="Ops1")
    scope = AppScope.objects.create(app=app, key="LEGACY", name="历史")
    group = PermissionGroup.objects.create(app=app, key="legacy", name="历史")
    permission = Permission.objects.create(
        app=app,
        group=group,
        key="legacy.read",
        name="历史权限",
        supported_scopes=["LEGACY"],
    )
    auth_group = AuthorizationGroup.objects.create(
        app=app,
        key="legacy-role",
        kind="role",
        name="历史角色",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=auth_group,
        permission=permission,
        scope_key=scope.key,
    )

    _ = apply_permission_template(app=app, template=_parsed_manifest())

    scope.refresh_from_db()
    group.refresh_from_db()
    permission.refresh_from_db()
    auth_group.refresh_from_db()
    assert scope.is_active is False
    assert group.is_active is False
    assert permission.is_active is False
    assert permission.deprecated_at is not None
    assert auth_group.is_active is False
    assert AuthorizationGroupGrant.objects.filter(authorization_group=auth_group).exists()


def _parsed_manifest() -> AppManifestInput:
    return parse_permission_template(
        app_key=APP_KEY,
        raw_template=dumps(_manifest_payload()),
        template_format="json",
        imported_by="owner-001",
    )


def _manifest_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "app": {
            "app_key": APP_KEY,
            "name": "Ops1",
            "description": "权限目录",
        },
        "scopes": [
            {"key": "SELF", "name": "本人", "description": "", "display_order": 10},
            {"key": "MANAGED", "name": "管理范围", "description": "", "display_order": 20},
        ],
        "permission_groups": [
            {"key": "billing", "name": "账务", "display_order": 10},
        ],
        "permissions": [
            {
                "key": "billing.read",
                "name": "查看账务",
                "description": "",
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
                "description": "",
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
