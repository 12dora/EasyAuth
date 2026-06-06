from __future__ import annotations

from typing import Final

import pytest

from easyauth.applications.models import (
    App,
    Permission,
    PermissionGroup,
    PermissionTemplateVersion,
    Role,
    RolePermission,
)
from easyauth.applications.permission_templates import (
    PermissionTemplateImportError,
    PermissionTemplateInput,
    TemplateFormat,
    TemplateNodeInput,
    apply_permission_template,
    parse_permission_template,
    preview_permission_template,
)
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant

pytestmark = pytest.mark.django_db
FIVE_LEVEL_TEMPLATE_VERSION: Final = 7
PIPELINE_TEMPLATE_YAML: Final = """
version: 1
groups:
  - key: PIPELINE_GROUP
    name: 流水线
    children:
      - key: ALLOW_PIPELINE_CREATE
        name: 创建流水线
        type: permission
"""
PIPELINE_TEMPLATE_JSON: Final = """
{
  "version": 1,
  "groups": [
    {
      "key": "PIPELINE_GROUP",
      "name": "流水线",
      "children": [
        {
          "key": "ALLOW_PIPELINE_CREATE",
          "name": "创建流水线",
          "type": "permission"
        }
      ]
    }
  ]
}
"""


def test_ops1_permission_template_parses_pasted_json_and_yaml() -> None:
    # Given: 应用负责人粘贴 JSON 和 YAML 两种模板格式。
    raw_templates: tuple[tuple[TemplateFormat, str], ...] = (
        ("json", PIPELINE_TEMPLATE_JSON),
        ("yaml", PIPELINE_TEMPLATE_YAML),
    )

    # When: 控制台把原始模板解析为 typed template。
    parsed_templates = tuple(
        parse_permission_template(
            raw_template=raw_template,
            template_format=template_format,
            imported_by="owner-001",
        )
        for template_format, raw_template in raw_templates
    )

    # Then: 两种格式都保留版本、导入人、原文和 group/permission 结构。
    for parsed_template in parsed_templates:
        assert parsed_template.version == 1
        assert parsed_template.imported_by == "owner-001"
        assert parsed_template.source == "paste"
        assert parsed_template.nodes[0].key == "PIPELINE_GROUP"
        assert parsed_template.nodes[0].children[0].key == "ALLOW_PIPELINE_CREATE"


def test_ops1_permission_template_preview_reports_creates_without_writing_database() -> None:
    # Given: 下游应用提供一个包含 group 和 permission 叶子的模板。
    app = App.objects.create(app_key="ops1-template-preview", name="Template Preview")
    template = _pipeline_template(version=1, imported_by="owner-001")

    # When: 应用负责人预览权限模板。
    preview = preview_permission_template(app=app, template=template)

    # Then: 预览返回新增差异, 但不写入模板、分组或 Permission。
    assert [(action.action, action.key) for action in preview.actions] == [
        ("create_group", "PIPELINE_GROUP"),
        ("create_permission", "ALLOW_PIPELINE_CREATE"),
    ]
    assert PermissionGroup.objects.count() == 0
    assert Permission.objects.count() == 0
    assert PermissionTemplateVersion.objects.count() == 0


def test_ops1_permission_template_import_supports_five_group_levels() -> None:
    # Given: 模板包含 5 层 group 和一个 permission 叶子节点。
    app = App.objects.create(app_key="ops1-template-depth", name="Template Depth")
    template = PermissionTemplateInput(
        version=FIVE_LEVEL_TEMPLATE_VERSION,
        source="paste",
        imported_by="owner-001",
        raw_template="five-depth-template",
        nodes=(
            _group(
                "G1",
                "Level 1",
                _group(
                    "G2",
                    "Level 2",
                    _group(
                        "G3",
                        "Level 3",
                        _group(
                            "G4",
                            "Level 4",
                            _group(
                                "G5",
                                "Level 5",
                                _permission("ALLOW_PIPELINE_CREATE", "Create pipeline"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    # When: 应用负责人确认导入。
    result = apply_permission_template(app=app, template=template)

    # Then: 分组深度、Permission 归属和审计记录都被保存, 但不会创建授权事实。
    permission = Permission.objects.get(app=app, key="ALLOW_PIPELINE_CREATE")
    assert result.template_version.version == FIVE_LEVEL_TEMPLATE_VERSION
    assert permission.group is not None
    assert permission.group.key == "G5"
    assert list(PermissionGroup.objects.filter(app=app).values_list("key", "depth")) == [
        ("G1", 1),
        ("G2", 2),
        ("G3", 3),
        ("G4", 4),
        ("G5", 5),
    ]
    assert AuditLog.objects.get(event_type="permission_template_imported").target_id == str(
        result.template_version.id,
    )
    assert AccessGrant.objects.count() == 0


def test_ops1_permission_template_rejects_duplicate_keys_without_partial_writes() -> None:
    # Given: 模板中两个兄弟 group 使用同一个 key。
    app = App.objects.create(app_key="ops1-template-duplicate", name="Template Duplicate")
    template = PermissionTemplateInput(
        version=1,
        source="paste",
        imported_by="owner-001",
        raw_template="duplicate-template",
        nodes=(
            _group("PIPELINE_GROUP", "Pipeline A"),
            _group("PIPELINE_GROUP", "Pipeline B"),
        ),
    )

    # When / Then: 导入被拒绝, 且不产生部分写入。
    with pytest.raises(PermissionTemplateImportError) as raised:
        _ = apply_permission_template(app=app, template=template)
    assert raised.value.code == "permission_template_duplicate_key"
    assert PermissionGroup.objects.count() == 0
    assert PermissionTemplateVersion.objects.count() == 0


def test_ops1_permission_template_rejects_cycles_before_duplicate_key_errors() -> None:
    # Given: 一个 group key 出现在自己的后代路径中。
    app = App.objects.create(app_key="ops1-template-cycle", name="Template Cycle")
    template = PermissionTemplateInput(
        version=1,
        source="paste",
        imported_by="owner-001",
        raw_template="cycle-template",
        nodes=(_group("A", "A", _group("B", "B", _group("A", "A again"))),),
    )

    # When / Then: 服务按环检测拒绝模板。
    with pytest.raises(PermissionTemplateImportError) as raised:
        _ = preview_permission_template(app=app, template=template)
    assert raised.value.code == "permission_template_cycle"


def test_ops1_permission_template_deprecates_missing_permission_without_deleting_history() -> None:
    # Given: App 里已有被 RolePermission 引用的历史 Permission, 新模板不再包含它。
    app = App.objects.create(app_key="ops1-template-deprecate", name="Template Deprecate")
    role = Role.objects.create(app=app, key="operator", name="Operator")
    legacy = Permission.objects.create(app=app, key="ALLOW_LEGACY", name="Legacy")
    _ = RolePermission.objects.create(role=role, permission=legacy)
    template = _pipeline_template(version=2, imported_by="owner-001")

    # When: 应用负责人确认导入新模板。
    _ = apply_permission_template(app=app, template=template)

    # Then: 历史 Permission 只被 inactive/deprecated, 引用关系仍保留。
    legacy.refresh_from_db()
    assert legacy.is_active is False
    assert legacy.deprecated_at is not None
    assert legacy.deprecated_reason == "permission template missing"
    assert RolePermission.objects.filter(role=role, permission=legacy).exists() is True


def test_ops1_permission_template_rejects_duplicate_version_without_partial_writes() -> None:
    # Given: App 已导入 v1 模板, 后续用户又提交同版本但改名的模板。
    app = App.objects.create(app_key="ops1-template-version-duplicate", name="Version Duplicate")
    _ = apply_permission_template(
        app=app,
        template=_pipeline_template(version=1, imported_by="owner-001"),
    )
    duplicate_template = PermissionTemplateInput(
        version=1,
        source="paste",
        imported_by="owner-001",
        raw_template="duplicate-version-template",
        nodes=(
            _group(
                "PIPELINE_GROUP",
                "Changed Pipeline",
                _permission("ALLOW_PIPELINE_CREATE", "Changed permission"),
            ),
        ),
    )

    # When / Then: 同版本导入被拒绝, 既有 group/permission 不被部分改写。
    with pytest.raises(PermissionTemplateImportError) as raised:
        _ = apply_permission_template(app=app, template=duplicate_template)
    assert raised.value.code == "permission_template_version_duplicate"
    assert PermissionGroup.objects.get(app=app, key="PIPELINE_GROUP").name == "Pipeline"
    assert Permission.objects.get(app=app, key="ALLOW_PIPELINE_CREATE").name == "Create pipeline"
    assert PermissionTemplateVersion.objects.filter(app=app).count() == 1


def test_ops1_permission_template_preview_is_isolated_by_app_when_keys_overlap() -> None:
    # Given: 其他 App 已有相同 key 的 group 和 permission。
    target_app = App.objects.create(app_key="ops1-template-target-app", name="Target")
    other_app = App.objects.create(app_key="ops1-template-other-app", name="Other")
    other_group = PermissionGroup.objects.create(
        app=other_app,
        key="PIPELINE_GROUP",
        name="Other Pipeline",
    )
    _ = Permission.objects.create(
        app=other_app,
        group=other_group,
        key="ALLOW_PIPELINE_CREATE",
        name="Other Permission",
    )

    # When: target App 预览同 key 模板。
    preview = preview_permission_template(
        app=target_app,
        template=_pipeline_template(version=1, imported_by="owner-001"),
    )

    # Then: 差异只按 target App 计算, 不复用或更新其他 App 的对象。
    assert [(action.action, action.key) for action in preview.actions] == [
        ("create_group", "PIPELINE_GROUP"),
        ("create_permission", "ALLOW_PIPELINE_CREATE"),
    ]
    assert PermissionGroup.objects.filter(app=target_app).count() == 0
    assert Permission.objects.filter(app=target_app).count() == 0


def _pipeline_template(*, version: int, imported_by: str) -> PermissionTemplateInput:
    return PermissionTemplateInput(
        version=version,
        source="paste",
        imported_by=imported_by,
        raw_template="pipeline-template",
        nodes=(
            _group(
                "PIPELINE_GROUP",
                "Pipeline",
                _permission("ALLOW_PIPELINE_CREATE", "Create pipeline"),
            ),
        ),
    )


def _group(key: str, name: str, *children: TemplateNodeInput) -> TemplateNodeInput:
    return TemplateNodeInput(key=key, name=name, node_type="group", children=children)


def _permission(key: str, name: str) -> TemplateNodeInput:
    return TemplateNodeInput(key=key, name=name, node_type="permission")
