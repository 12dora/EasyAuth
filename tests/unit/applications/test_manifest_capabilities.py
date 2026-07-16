from __future__ import annotations

from json import dumps
from typing import Any, Final

import pytest

from easyauth.applications.models import App, AppCapability
from easyauth.applications.permission_templates import (
    PermissionTemplateImportError,
    apply_permission_template,
    parse_permission_template,
)

pytestmark = pytest.mark.django_db

APP_KEY: Final = "cap-manifest"


def test_manifest_accepts_top_level_capabilities_section() -> None:
    payload = _manifest_payload(capabilities=["directory", "notify"])

    manifest = parse_permission_template(
        app_key=APP_KEY,
        raw_template=dumps(payload),
        template_format="json",
        imported_by="owner-001",
    )

    assert manifest.capabilities == ("directory", "notify")


def test_manifest_capabilities_dedupe_and_strip() -> None:
    payload = _manifest_payload(capabilities=[" directory ", "notify", "directory"])

    manifest = parse_permission_template(
        app_key=APP_KEY,
        raw_template=dumps(payload),
        template_format="json",
        imported_by="owner-001",
    )

    assert manifest.capabilities == ("directory", "notify")


def test_manifest_capabilities_unknown_values_are_accepted_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = _manifest_payload(capabilities=["directory", "future_capability"])

    with caplog.at_level("WARNING"):
        manifest = parse_permission_template(
            app_key=APP_KEY,
            raw_template=dumps(payload),
            template_format="json",
            imported_by="owner-001",
        )

    assert manifest.capabilities == ("directory", "future_capability")
    assert any("future_capability" in record.message for record in caplog.records)


def test_manifest_capabilities_reject_empty_string() -> None:
    payload = _manifest_payload(capabilities=["directory", ""])

    with pytest.raises(PermissionTemplateImportError) as raised:
        _ = parse_permission_template(
            app_key=APP_KEY,
            raw_template=dumps(payload),
            template_format="json",
            imported_by="owner-001",
        )

    assert raised.value.code == "permission_template_parse_error"


def test_manifest_capabilities_import_has_no_authorization_side_effect() -> None:
    # 申明 ≠ 开通: 导入后 AppCapability 不得自动出现/开启。
    app = App.objects.create(app_key=APP_KEY, name="Cap Manifest")
    payload = _manifest_payload(capabilities=["directory", "notify"])
    manifest = parse_permission_template(
        app_key=APP_KEY,
        raw_template=dumps(payload),
        template_format="json",
        imported_by="owner-001",
    )

    _ = apply_permission_template(app=app, template=manifest)

    assert AppCapability.objects.filter(app=app).count() == 0
    assert manifest.capabilities == ("directory", "notify")


def _manifest_payload(*, capabilities: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "app": {"app_key": APP_KEY, "name": "Cap Manifest", "description": "能力申明"},
        "scopes": [{"key": "SELF", "name": "本人"}],
        "permission_groups": [{"key": "core", "name": "核心"}],
        "permissions": [
            {
                "key": "core.read",
                "name": "查看",
                "group_key": "core",
                "supported_scopes": ["SELF"],
            },
        ],
        "authorization_groups": [
            {
                "key": "viewer",
                "kind": "role",
                "name": "只读",
                "grants": [{"permission": "core.read", "scope": "SELF"}],
            },
        ],
        "approval_rules": [],
    }
    if capabilities is not None:
        payload["capabilities"] = capabilities
    return payload
