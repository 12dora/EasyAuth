"""集成描述符: 下游应用向 EasyAuth 暴露的自描述接入契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from easyauth_app_sdk.manifest import validate_manifest

DESCRIPTOR_WELL_KNOWN_PATH: Final = "/.well-known/easyauth-app.json"
DESCRIPTOR_VERSION: Final = 1
SDK_NAME: Final = "easyauth-app-sdk-python"
SDK_VERSION: Final = "0.2.0"


class DescriptorError(ValueError):
    """集成描述符不满足契约。"""


@dataclass(frozen=True)
class AppDescriptor:
    app_key: str
    name: str
    description: str
    manifest: dict[str, Any]


def build_descriptor_payload(*, manifest: dict[str, Any]) -> dict[str, Any]:
    """由 manifest 构建描述符 payload; 应用元数据直接取自 manifest.app, 保证单一事实源。"""
    validated = validate_manifest(manifest)
    app = validated["app"]
    return {
        "descriptor_version": DESCRIPTOR_VERSION,
        "app": {
            "app_key": app["app_key"],
            "name": app["name"],
            "description": app["description"],
        },
        "manifest": validated,
        "sdk": {"name": SDK_NAME, "version": SDK_VERSION},
    }


def parse_descriptor_payload(payload: Any) -> AppDescriptor:
    """解析并校验对端返回的描述符 payload。"""
    if not isinstance(payload, dict):
        raise DescriptorError("描述符必须是 JSON object")
    descriptor_version = payload.get("descriptor_version")
    if descriptor_version != DESCRIPTOR_VERSION:
        raise DescriptorError(f"不支持的 descriptor_version: {descriptor_version!r}")
    app = payload.get("app")
    if not isinstance(app, dict):
        raise DescriptorError("描述符缺少 app 元数据")
    app_key = app.get("app_key")
    name = app.get("name")
    if not isinstance(app_key, str) or not app_key or not isinstance(name, str) or not name:
        raise DescriptorError("app.app_key 与 app.name 必须是非空字符串")
    description = app.get("description")
    if not isinstance(description, str):
        raise DescriptorError("app.description 必须是字符串")
    manifest = validate_manifest(payload.get("manifest"))
    if manifest["app"]["app_key"] != app_key:
        raise DescriptorError("manifest.app.app_key 与描述符 app_key 不一致")
    return AppDescriptor(app_key=app_key, name=name, description=description, manifest=manifest)
