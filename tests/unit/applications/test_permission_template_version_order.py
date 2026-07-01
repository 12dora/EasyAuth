from __future__ import annotations

import pytest

from easyauth.applications.models import App, Permission, PermissionGroup, PermissionTemplateVersion
from easyauth.applications.permission_template_types import (
    AppManifestAppInput,
    AppManifestAuthorizationGroupInput,
    AppManifestGrantInput,
    AppManifestInput,
    AppManifestPermissionGroupInput,
    AppManifestPermissionInput,
    AppManifestScopeInput,
    PermissionTemplateImportError,
)
from easyauth.applications.permission_templates import (
    apply_permission_template,
)

pytestmark = pytest.mark.django_db


def test_permission_template_import_rejects_lower_version_after_newer_version() -> None:
    # Given: App 已经成功导入 v3 权限模板。
    app = App.objects.create(app_key="ops1-template-version-lower", name="Version Lower")
    _ = apply_permission_template(
        app=app,
        template=_pipeline_template(
            version=3,
            group_name="Pipeline",
            permission_name="Create pipeline",
        ),
    )
    older_template = _pipeline_template(
        version=2,
        group_name="Changed Pipeline",
        permission_name="Changed permission",
    )

    # When / Then: 更低版本导入被拒绝, 且不会回写既有权限目录。
    with pytest.raises(PermissionTemplateImportError) as raised:
        _ = apply_permission_template(app=app, template=older_template)
    assert raised.value.code == "permission_template_version_not_increasing"
    assert raised.value.subject == "2<=3"
    assert PermissionGroup.objects.get(app=app, key="PIPELINE_GROUP").name == "Pipeline"
    assert Permission.objects.get(app=app, key="ALLOW_PIPELINE_CREATE").name == "Create pipeline"
    assert PermissionTemplateVersion.objects.filter(app=app).count() == 1


def _pipeline_template(
    *,
    version: int,
    group_name: str,
    permission_name: str,
) -> AppManifestInput:
    return AppManifestInput(
        schema_version=version,
        source="paste",
        imported_by="owner-001",
        raw_template="pipeline-template",
        app=AppManifestAppInput(
            app_key="ops1-template-version-lower",
            name="Version Lower",
        ),
        scopes=(AppManifestScopeInput(key="GLOBAL", name="Global"),),
        permission_groups=(
            AppManifestPermissionGroupInput(
                key="PIPELINE_GROUP",
                name=group_name,
            ),
        ),
        permissions=(
            AppManifestPermissionInput(
                key="ALLOW_PIPELINE_CREATE",
                name=permission_name,
                group_key="PIPELINE_GROUP",
                supported_scopes=("GLOBAL",),
            ),
        ),
        authorization_groups=(
            AppManifestAuthorizationGroupInput(
                key="operator",
                kind="role",
                name="Operator",
                grants=(
                    AppManifestGrantInput(
                        permission="ALLOW_PIPELINE_CREATE",
                        scope="GLOBAL",
                    ),
                ),
            ),
        ),
        approval_rules=(),
    )
