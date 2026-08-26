"""App manifest 同步的共享入口。

自动接入(控制台拉取)与下游主动推送复用同一套版本单调递增 + content_hash
幂等语义, 避免两处冲突判定逻辑漂移。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from easyauth.applications.manifest_hashing import (
    canonical_manifest_hash,
    canonical_manifest_template,
)
from easyauth.applications.models import App, PermissionTemplateVersion
from easyauth.applications.permission_template_lifecycle import sync_manifest_lifecycle
from easyauth.applications.permission_templates import (
    apply_permission_template,
    parse_permission_template,
    parse_template_format,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue


class ManifestVersionConflictError(Exception):
    """schema_version 未递增且内容与已导入版本不一致。"""

    def __init__(self, incoming_version: int, latest_version: int) -> None:
        super().__init__(
            "".join(
                (
                    f"下游 manifest schema_version({incoming_version}) 未超过已导入版本 ",
                    f"({latest_version}) 且内容不一致, 请在下游递增版本后重试。",
                ),
            ),
        )
        self.incoming_version: int = incoming_version
        self.latest_version: int = latest_version


@dataclass(frozen=True, slots=True)
class ManifestSyncOutcome:
    already_up_to_date: bool
    template_version: int


@transaction.atomic
def sync_app_manifest(
    *,
    app: App,
    manifest: dict[str, JsonValue],
    actor_id: str,
    downstream_base_url: str | None = None,
    actor_type: str = "system",
) -> ManifestSyncOutcome:
    """按幂等语义导入 manifest, 并在 App 行锁内完成版本判定。

    可能抛出:
    - ManifestVersionConflictError: 版本未递增且内容不同。
    - PermissionTemplateImportError: 解析/语义校验失败(由调用方映射响应码)。
    """
    locked_app = App.objects.select_for_update().get(pk=app.id)
    canonical_template = canonical_manifest_template(manifest)
    latest = PermissionTemplateVersion.objects.filter(app=locked_app).order_by("-version").first()
    raw_schema_version = manifest["schema_version"]
    if not isinstance(raw_schema_version, int) or isinstance(raw_schema_version, bool):
        msg = "App manifest schema_version 必须是整数。"
        raise TypeError(msg)
    incoming_version = raw_schema_version
    if latest is not None and incoming_version <= latest.version:
        if canonical_manifest_hash(manifest) == latest.content_hash:
            template = parse_permission_template(
                app_key=locked_app.app_key,
                raw_template=canonical_template,
                template_format=parse_template_format("json"),
                imported_by=actor_id,
            )
            sync_manifest_lifecycle(
                app=locked_app,
                template=template,
                downstream_base_url=downstream_base_url,
                actor_type=actor_type,
            )
            return ManifestSyncOutcome(
                already_up_to_date=True,
                template_version=latest.version,
            )
        raise ManifestVersionConflictError(incoming_version, latest.version)
    template = parse_permission_template(
        app_key=locked_app.app_key,
        raw_template=canonical_template,
        template_format=parse_template_format("json"),
        imported_by=actor_id,
    )
    result = apply_permission_template(
        app=locked_app,
        template=template,
        downstream_base_url=downstream_base_url,
        actor_type=actor_type,
    )
    return ManifestSyncOutcome(
        already_up_to_date=False,
        template_version=result.template_version.version,
    )
