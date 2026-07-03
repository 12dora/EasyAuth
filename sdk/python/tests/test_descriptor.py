from __future__ import annotations

import json

import pytest
from easyauth_app_sdk import (
    DESCRIPTOR_VERSION,
    DescriptorError,
    ManifestValidationError,
    build_descriptor_payload,
    descriptor_http_response,
    parse_descriptor_payload,
    validate_manifest,
)


def _manifest() -> dict:
    return {
        "schema_version": 3,
        "app": {
            "app_key": "demoapp",
            "name": "Demo App",
            "description": "演示应用",
            "is_active": True,
        },
        "scopes": [],
        "permission_groups": [],
        "permissions": [
            {
                "key": "demo.item.view",
                "name": "查看演示对象",
                "name_en": "View Demo Item",
                "description": "",
                "group_key": "demo.item",
                "supported_scopes": ["SELF"],
                "risk_level": "standard",
                "is_active": True,
            },
        ],
        "authorization_groups": [],
        "approval_rules": [],
    }


def test_build_and_parse_descriptor_roundtrip() -> None:
    payload = build_descriptor_payload(manifest=_manifest())

    assert payload["descriptor_version"] == DESCRIPTOR_VERSION
    assert payload["app"]["app_key"] == "demoapp"

    descriptor = parse_descriptor_payload(payload)
    assert descriptor.app_key == "demoapp"
    assert descriptor.manifest["schema_version"] == 3


def test_validate_manifest_rejects_missing_permission_name() -> None:
    manifest = _manifest()
    manifest["permissions"][0]["name"] = ""

    with pytest.raises(ManifestValidationError, match="name"):
        validate_manifest(manifest)


def test_parse_descriptor_rejects_app_key_mismatch() -> None:
    payload = build_descriptor_payload(manifest=_manifest())
    payload["app"]["app_key"] = "otherapp"

    with pytest.raises(DescriptorError, match="app_key"):
        parse_descriptor_payload(payload)


def test_descriptor_http_response_serves_payload() -> None:
    status_code, headers, body = descriptor_http_response(_manifest)

    assert status_code == 200
    assert headers["Content-Type"].startswith("application/json")
    payload = json.loads(body.decode("utf-8"))
    assert payload["manifest"]["app"]["app_key"] == "demoapp"


def test_descriptor_http_response_enforces_token() -> None:
    status_code, _headers, body = descriptor_http_response(
        _manifest,
        authorization=None,
        required_token="shared-secret",
    )
    assert status_code == 401
    assert json.loads(body.decode("utf-8"))["error"]["code"] == "descriptor_unauthorized"

    ok_status, _headers, _body = descriptor_http_response(
        _manifest,
        authorization="Bearer shared-secret",
        required_token="shared-secret",
    )
    assert ok_status == 200
