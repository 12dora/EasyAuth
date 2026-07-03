from __future__ import annotations

from json import dumps
from typing import TYPE_CHECKING, Any, Final

import pytest
from pydantic import TypeAdapter

from easyauth.api.errors import JsonValue
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
    export_manifest,
    parse_permission_template,
    preview_permission_template,
)
from easyauth.audit.models import AuditLog

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.django_db

APP_KEY: Final = "ops1-manifest"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


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
                {"scope": "MANAGED_USERS"},
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
        ("create_scope", "MANAGED_USERS"),
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


def test_app_manifest_bilingual_fields_import_export_roundtrip() -> None:
    app = App.objects.create(app_key=APP_KEY, name="Ops1")
    manifest = parse_permission_template(
        app_key=APP_KEY,
        raw_template=dumps(_bilingual_manifest_payload()),
        template_format="json",
        imported_by="owner-001",
    )

    _ = apply_permission_template(app=app, template=manifest)

    scope = AppScope.objects.get(app=app, key="SELF")
    group = PermissionGroup.objects.get(app=app, key="billing")
    permission = Permission.objects.get(app=app, key="billing.read")
    auth_group = AuthorizationGroup.objects.get(app=app, key="accountant")
    assert (scope.name_en, scope.description_en) == ("Self", "Only the requester")
    assert (group.name_en, group.description_en) == ("Billing", "Billing domain")
    assert (permission.name_en, permission.description_en) == (
        "Read billing",
        "Read billing records",
    )
    assert (auth_group.name_en, auth_group.description_en) == ("Accountant", "Accountant role")

    exported = _exported_manifest(app)
    exported_scopes = _exported_items_by_key(exported, "scopes")
    assert exported_scopes["SELF"]["name_en"] == "Self"
    assert exported_scopes["SELF"]["description_en"] == "Only the requester"
    # 未维护英文文案的条目不输出双语键, 保持导出干净。
    assert "name_en" not in exported_scopes["MANAGED_USERS"]
    assert "description_en" not in exported_scopes["MANAGED_USERS"]
    assert _exported_items_by_key(exported, "permission_groups")["billing"]["name_en"] == "Billing"
    assert (
        _exported_items_by_key(exported, "permissions")["billing.read"]["name_en"] == "Read billing"
    )
    assert (
        _exported_items_by_key(exported, "authorization_groups")["accountant"]["name_en"]
        == "Accountant"
    )

    replay = parse_permission_template(
        app_key=APP_KEY,
        raw_template=dumps(export_manifest(app)),
        template_format="json",
        imported_by="owner-001",
    )
    assert preview_permission_template(app=app, template=replay).actions == ()


def test_app_manifest_without_bilingual_fields_imports_with_empty_defaults() -> None:
    app = App.objects.create(app_key=APP_KEY, name="Ops1")

    _ = apply_permission_template(app=app, template=_parsed_manifest())

    scope = AppScope.objects.get(app=app, key="SELF")
    group = PermissionGroup.objects.get(app=app, key="billing")
    permission = Permission.objects.get(app=app, key="billing.read")
    auth_group = AuthorizationGroup.objects.get(app=app, key="accountant")
    assert (scope.name_en, scope.description_en) == ("", "")
    assert (group.name_en, group.description_en) == ("", "")
    assert (permission.name_en, permission.description_en) == ("", "")
    assert (auth_group.name_en, auth_group.description_en) == ("", "")
    exported = _exported_manifest(app)
    scopes = _exported_items_by_key(exported, "scopes")
    permissions = _exported_items_by_key(exported, "permissions")
    assert all("name_en" not in item for item in scopes.values())
    assert all("description_en" not in item for item in permissions.values())


def test_app_manifest_reimport_overwrites_bilingual_fields() -> None:
    app = App.objects.create(app_key=APP_KEY, name="Ops1")
    first_payload = _bilingual_manifest_payload()
    first = parse_permission_template(
        app_key=APP_KEY,
        raw_template=dumps(first_payload),
        template_format="json",
        imported_by="owner-001",
    )
    _ = apply_permission_template(app=app, template=first)

    second_payload = _manifest_payload()
    second_payload["schema_version"] = 2
    second = parse_permission_template(
        app_key=APP_KEY,
        raw_template=dumps(second_payload),
        template_format="json",
        imported_by="owner-001",
    )
    preview = preview_permission_template(app=app, template=second)
    _ = apply_permission_template(app=app, template=second)

    preview_keys = [(action.action, action.key) for action in preview.actions]
    assert ("update_scope", "SELF") in preview_keys
    scope = AppScope.objects.get(app=app, key="SELF")
    assert (scope.name_en, scope.description_en) == ("", "")


def _exported_manifest(app: App) -> dict[str, JsonValue]:
    exported = JSON_VALUE_ADAPTER.validate_python(export_manifest(app))
    assert isinstance(exported, dict)
    return exported


def _exported_items_by_key(
    exported: dict[str, JsonValue],
    section: str,
) -> dict[str, dict[str, JsonValue]]:
    raw_items = exported[section]
    assert isinstance(raw_items, list)
    items: dict[str, dict[str, JsonValue]] = {}
    for item in raw_items:
        assert isinstance(item, dict)
        key = item["key"]
        assert isinstance(key, str)
        items[key] = item
    return items


def _bilingual_manifest_payload() -> dict[str, object]:
    payload: dict[str, object] = _manifest_payload()
    payload["scopes"] = [
        {
            "key": "SELF",
            "name": "本人",
            "name_en": "Self",
            "description": "",
            "description_en": "Only the requester",
            "display_order": 10,
        },
        {
            "key": "MANAGED_USERS",
            "name": "管理用户范围",
            "description": "",
            "display_order": 20,
        },
    ]
    payload["permission_groups"] = [
        {
            "key": "billing",
            "name": "账务",
            "name_en": "Billing",
            "description_en": "Billing domain",
            "display_order": 10,
        },
    ]
    payload["permissions"] = [
        {
            "key": "billing.read",
            "name": "查看账务",
            "name_en": "Read billing",
            "description": "",
            "description_en": "Read billing records",
            "group_key": "billing",
            "supported_scopes": ["SELF"],
            "risk_level": "standard",
        },
    ]
    payload["authorization_groups"] = [
        {
            "key": "accountant",
            "kind": "role",
            "name": "会计",
            "name_en": "Accountant",
            "description": "",
            "description_en": "Accountant role",
            "requestable": True,
            "is_active": True,
            "grants": [{"permission": "billing.read", "scope": "SELF"}],
        },
    ]
    return payload


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
            {
                "key": "MANAGED_USERS",
                "name": "管理用户范围",
                "description": "",
                "display_order": 20,
            },
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
