"""00 §9.1 第三白名单: lifecycle.handover_asset_types 解析钉扎。"""

from __future__ import annotations

from json import dumps

import pytest

from easyauth.applications.permission_templates import (
    PermissionTemplateImportError,
    parse_permission_template,
)

pytestmark = pytest.mark.django_db


def _base_manifest(**lifecycle_extra: object) -> dict[str, object]:
    lifecycle: dict[str, object] = {
        "handover_url": "https://example.test/handover",
        "capabilities": ["handover.v2"],
        "handover_asset_types": [
            {
                "type": "customer",
                "label": "客户",
                "detail_supported": True,
                "releasable": False,
            },
            {
                "type": "order",
                "label": "订单",
                "detail_supported": False,
                "releasable": True,
            },
        ],
    }
    lifecycle.update(lifecycle_extra)
    return {
        "schema_version": 1,
        "app": {"app_key": "life-parse", "name": "Life"},
        "scopes": [{"key": "GLOBAL", "name": "全局"}],
        "permission_groups": [{"key": "core", "name": "核心"}],
        "permissions": [
            {
                "key": "x.view",
                "name": "view",
                "group_key": "core",
                "supported_scopes": ["GLOBAL"],
            },
        ],
        "lifecycle": lifecycle,
    }


def test_parse_lifecycle_handover_asset_types() -> None:
    manifest = parse_permission_template(
        app_key="life-parse",
        raw_template=dumps(_base_manifest()),
        template_format="json",
        imported_by="tester",
    )
    assert manifest.lifecycle is not None
    types = manifest.lifecycle.handover_asset_types
    assert len(types) == 2
    assert types[0].type == "customer"
    assert types[0].label == "客户"
    assert types[0].detail_supported is True
    assert types[0].releasable is False
    assert types[1].type == "order"
    assert types[1].releasable is True


def test_reject_unknown_key_inside_asset_type_item() -> None:
    payload = _base_manifest()
    lifecycle = payload["lifecycle"]
    assert isinstance(lifecycle, dict)
    items = list(lifecycle["handover_asset_types"])  # type: ignore[index]
    first = dict(items[0])  # type: ignore[arg-type]
    first["unknown_field"] = "x"
    lifecycle["handover_asset_types"] = [first, items[1]]
    with pytest.raises(PermissionTemplateImportError):
        _ = parse_permission_template(
            app_key="life-parse",
            raw_template=dumps(payload),
            template_format="json",
            imported_by="tester",
        )


def test_reject_unknown_key_inside_lifecycle() -> None:
    with pytest.raises(PermissionTemplateImportError):
        _ = parse_permission_template(
            app_key="life-parse",
            raw_template=dumps(_base_manifest(extra_flag=True)),
            template_format="json",
            imported_by="tester",
        )
