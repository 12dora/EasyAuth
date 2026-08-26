"""权限模板存储门面: 显式再导出 catalog / diff / records 的公共符号。"""

from easyauth.applications.permission_template_catalog import upsert_manifest
from easyauth.applications.permission_template_diff import template_actions
from easyauth.applications.permission_template_records import (
    PERMISSION_TEMPLATE_IMPORTED_EVENT,
    bump_manifest_catalog_version,
    export_manifest,
    record_import_event,
    record_template_version,
)

__all__ = [
    "PERMISSION_TEMPLATE_IMPORTED_EVENT",
    "bump_manifest_catalog_version",
    "export_manifest",
    "record_import_event",
    "record_template_version",
    "template_actions",
    "upsert_manifest",
]
