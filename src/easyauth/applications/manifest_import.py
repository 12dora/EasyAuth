"""App manifest 同步的共享入口: 自动接入(控制台拉取)与下游主动推送复用同一套
版本单调递增 + content_hash 幂等语义, 避免两处冲突判定逻辑漂移。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from easyauth.applications.models import PermissionTemplateVersion
from easyauth.applications.permission_templates import (
    apply_permission_template,
    parse_permission_template,
    parse_template_format,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue
    from easyauth.applications.models import App


class ManifestVersionConflictError(Exception):
    """schema_version 未递增且内容与已导入版本不一致。"""

    def __init__(self, incoming_version: int, latest_version: int) -> None:
        super().__init__(
            f"下游 manifest schema_version({incoming_version}) 未超过已导入版本"
            f"({latest_version}) 且内容不一致, 请在下游递增版本后重试。",
        )
        self.incoming_version = incoming_version
        self.latest_version = latest_version


@dataclass(frozen=True, slots=True)
class ManifestSyncOutcome:
    already_up_to_date: bool
    template_version: int


def canonical_manifest_template(manifest: dict[str, JsonValue]) -> str:
    # 固定的规范化序列化保证同内容重复接入可以按 content_hash 幂等判定。
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)


def sync_app_manifest(
    *,
    app: App,
    manifest: dict[str, JsonValue],
    actor_id: str,
    downstream_base_url: str | None = None,
) -> ManifestSyncOutcome:
    """按幂等语义导入 manifest; 调用方需持有事务(与 App 创建同一原子域)。

    可能抛出:
    - ManifestVersionConflictError: 版本未递增且内容不同。
    - PermissionTemplateImportError: 解析/语义校验失败(由调用方映射响应码)。
    """
    canonical_template = canonical_manifest_template(manifest)
    latest = PermissionTemplateVersion.objects.filter(app=app).order_by("-version").first()
    incoming_version = int(manifest["schema_version"])  # 调用方已校验为 >=1 的 int
    if latest is not None and incoming_version <= latest.version:
        if sha256(canonical_template.encode("utf-8")).hexdigest() == latest.content_hash:
            return ManifestSyncOutcome(
                already_up_to_date=True,
                template_version=latest.version,
            )
        raise ManifestVersionConflictError(incoming_version, latest.version)
    template = parse_permission_template(
        app_key=app.app_key,
        raw_template=canonical_template,
        template_format=parse_template_format("json"),
        imported_by=actor_id,
    )
    result = apply_permission_template(
        app=app,
        template=template,
        downstream_base_url=downstream_base_url,
    )
    return ManifestSyncOutcome(
        already_up_to_date=False,
        template_version=result.template_version.version,
    )
