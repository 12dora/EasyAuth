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
        "scopes": [{"key": "SELF", "name": "本人"}],
        "permission_groups": [{"key": "demo.item", "name": "演示对象"}],
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


def test_validate_manifest_rejects_empty_scopes() -> None:
    # 与 EasyAuth 导入管线一致: 空 scopes 必须被 SDK 提前拦截, 而不是通过后被服务端拒绝。
    manifest = _manifest()
    manifest["scopes"] = []

    with pytest.raises(ManifestValidationError, match="scopes"):
        validate_manifest(manifest)


def test_validate_manifest_rejects_unknown_supported_scope() -> None:
    # permission.supported_scopes 必须是已声明 scope 的子集(服务端 parsing 同款交叉校验)。
    manifest = _manifest()
    manifest["permissions"][0]["supported_scopes"] = ["UNDECLARED"]

    with pytest.raises(ManifestValidationError, match="未声明的 scope"):
        validate_manifest(manifest)


def test_validate_manifest_accepts_lifecycle_and_webhook_sections() -> None:
    manifest = _manifest()
    manifest["lifecycle"] = {
        "handover_url": "/api/v1/easyauth/lifecycle/handover",
        "onboard_url": None,
        "capabilities": ["preview", "reassign"],
    }
    manifest["webhook"] = {"signing": "hmac-sha256"}

    validated = validate_manifest(manifest)

    assert validated["lifecycle"]["capabilities"] == ["preview", "reassign"]
    assert validated["webhook"]["signing"] == "hmac-sha256"


def test_validate_manifest_accepts_top_level_platform_capabilities() -> None:
    manifest = _manifest()
    manifest["capabilities"] = ["directory", "notify"]

    validated = validate_manifest(manifest)

    assert validated["capabilities"] == ["directory", "notify"]


def test_validate_manifest_rejects_capabilities_not_array() -> None:
    manifest = _manifest()
    manifest["capabilities"] = "directory"
    with pytest.raises(ManifestValidationError, match="capabilities 必须是字符串数组"):
        validate_manifest(manifest)


def test_validate_manifest_rejects_capabilities_empty_string() -> None:
    manifest = _manifest()
    manifest["capabilities"] = ["directory", ""]
    with pytest.raises(ManifestValidationError, match="非空字符串"):
        validate_manifest(manifest)


def test_validate_manifest_rejects_capabilities_outside_whitelist() -> None:
    manifest = _manifest()
    manifest["capabilities"] = ["directory", "future_capability"]
    with pytest.raises(ManifestValidationError, match="取值必须是"):
        validate_manifest(manifest)


def test_validate_manifest_rejects_capabilities_duplicates() -> None:
    manifest = _manifest()
    manifest["capabilities"] = ["directory", "notify", "directory"]
    with pytest.raises(ManifestValidationError, match="重复值"):
        validate_manifest(manifest)


def test_descriptor_roundtrip_preserves_lifecycle_and_webhook_sections() -> None:
    # 描述符 build/parse 必须原样携带 lifecycle/webhook 节, EasyAuth 侧据此发现交接端点。
    manifest = _manifest()
    manifest["lifecycle"] = {"handover_url": "/hooks/handover", "capabilities": ["preview"]}
    manifest["webhook"] = {"signing": "hmac-sha256"}

    payload = build_descriptor_payload(manifest=manifest)
    descriptor = parse_descriptor_payload(payload)

    assert descriptor.manifest["lifecycle"] == manifest["lifecycle"]
    assert descriptor.manifest["webhook"] == manifest["webhook"]


def test_validate_manifest_rejects_bad_lifecycle_and_webhook_types() -> None:
    manifest = _manifest()
    manifest["lifecycle"] = {"handover_url": 123}
    with pytest.raises(ManifestValidationError, match="handover_url"):
        validate_manifest(manifest)

    manifest["lifecycle"] = {"capabilities": "preview"}
    with pytest.raises(ManifestValidationError, match="capabilities"):
        validate_manifest(manifest)

    manifest["lifecycle"] = {"capabilities": ["preview"]}
    manifest["webhook"] = {"signing": 1}
    with pytest.raises(ManifestValidationError, match="signing"):
        validate_manifest(manifest)


def test_validate_manifest_rejects_duplicate_keys_and_unknown_grants() -> None:
    manifest = _manifest()
    manifest["scopes"].append({"key": "SELF", "name": "重复"})
    with pytest.raises(ManifestValidationError, match="重复 key"):
        validate_manifest(manifest)

    manifest = _manifest()
    manifest["authorization_groups"] = [
        {
            "key": "reader",
            "kind": "role",
            "name": "只读",
            "grants": [
                {"permission": "demo.item.view", "scope": "SELF"},
                {"permission": "demo.item.view", "scope": "SELF"},
            ],
        }
    ]
    with pytest.raises(ManifestValidationError, match="重复 grant"):
        validate_manifest(manifest)

    manifest = _manifest()
    manifest["authorization_groups"] = [
        {
            "key": "reader",
            "kind": "bundle",
            "name": "只读",
            "grants": [{"permission": "missing.perm", "scope": "SELF"}],
        }
    ]
    with pytest.raises(ManifestValidationError, match="未知权限"):
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

    # 前缀正确但不完整的 token 必须被拒(不因短路而放行)。
    wrong_status, _h, _b = descriptor_http_response(
        _manifest,
        authorization="Bearer shared",
        required_token="shared-secret",
    )
    assert wrong_status == 401


def test_descriptor_http_response_supports_token_validator() -> None:
    seen: list[str | None] = []

    def validator(token: str | None) -> bool:
        seen.append(token)
        return token == "db-managed-key"  # noqa: S105 - 测试用假密钥.

    denied_status, _h, _b = descriptor_http_response(
        _manifest,
        authorization="Bearer wrong",
        token_validator=validator,
    )
    ok_status, _h2, _b2 = descriptor_http_response(
        _manifest,
        authorization="Bearer db-managed-key",
        token_validator=validator,
    )
    missing_status, _h3, _b3 = descriptor_http_response(
        _manifest,
        authorization=None,
        token_validator=validator,
    )

    assert denied_status == 401
    assert ok_status == 200
    assert missing_status == 401
    assert seen == ["wrong", "db-managed-key", None]
