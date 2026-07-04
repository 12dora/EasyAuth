from __future__ import annotations

from typing import Final

from easyauth.applications.ops_models import (
    TEMPLATE_SOURCE_MANUAL,
    TEMPLATE_SOURCE_PASTE,
    TEMPLATE_SOURCE_UPLOAD,
)
from easyauth.applications.permission_template_types import (
    AppManifestInput,
    FlattenedTemplate,
    PermissionTemplateImportError,
)

# 256KB: 防滥用边界。真实应用(EasyTrade 163 权限点)的规范化 manifest
# (sort_keys + indent=2)已超过旧值 64KB,2026-07-04 自动接入实测触顶后上调。
PERMISSION_TEMPLATE_MAX_RAW_LENGTH: Final = 262144


def flatten_template(template: AppManifestInput) -> FlattenedTemplate:
    _validate_template_boundary(template)
    return FlattenedTemplate(manifest=template)


def _validate_template_boundary(template: AppManifestInput) -> None:
    if template.schema_version < 1:
        _raise_template_error("permission_template_version_invalid", str(template.schema_version))
    supported_sources = {TEMPLATE_SOURCE_UPLOAD, TEMPLATE_SOURCE_PASTE, TEMPLATE_SOURCE_MANUAL}
    if template.source not in supported_sources:
        _raise_template_error("permission_template_source_invalid", template.source)
    if len(template.raw_template) > PERMISSION_TEMPLATE_MAX_RAW_LENGTH:
        _raise_template_error("permission_template_too_large", str(len(template.raw_template)))


def _raise_template_error(code: str, subject: str) -> None:
    raise PermissionTemplateImportError(
        code=code,
        message="App manifest 不符合导入约束。",
        subject=subject,
    )
