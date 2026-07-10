from __future__ import annotations

from django.db import transaction

from easyauth.applications.models import App, PermissionTemplateVersion
from easyauth.applications.permission_template_flattening import flatten_template
from easyauth.applications.permission_template_parsing import (
    TemplateFormat,
    parse_permission_template,
    parse_template_format,
)
from easyauth.applications.permission_template_storage import (
    bump_manifest_catalog_version,
    export_manifest,
    record_import_event,
    record_template_version,
    template_actions,
    upsert_manifest,
)
from easyauth.applications.permission_template_types import (
    AppManifestInput,
    PermissionTemplateImportError,
    PermissionTemplateImportResult,
    PermissionTemplateInput,
    PermissionTemplatePreview,
    TemplateAction,
)
from easyauth.config.net import validate_public_https_url

__all__ = [
    "AppManifestInput",
    "PermissionTemplateImportError",
    "PermissionTemplateImportResult",
    "PermissionTemplateInput",
    "PermissionTemplatePreview",
    "TemplateAction",
    "TemplateFormat",
    "apply_permission_template",
    "export_manifest",
    "parse_permission_template",
    "parse_template_format",
    "preview_permission_template",
]


def preview_permission_template(
    *,
    app: App,
    template: AppManifestInput,
) -> PermissionTemplatePreview:
    flattened = flatten_template(template)
    return PermissionTemplatePreview(actions=template_actions(app, flattened))


@transaction.atomic
def apply_permission_template(
    *,
    app: App,
    template: AppManifestInput,
    downstream_base_url: str | None = None,
) -> PermissionTemplateImportResult:
    # 锁住 App 行串行化同一 App 的并发导入; 版本检查和写入在同一把锁内完成,
    # 消除"两个导入都读到 latest=1 然后交错落库"的 TOCTOU。
    locked_app = App.objects.select_for_update().get(pk=app.pk)
    _reject_duplicate_template_version(app=locked_app, version=template.schema_version)
    flattened = flatten_template(template)
    actions = template_actions(locked_app, flattened)
    upsert_manifest(locked_app, template)
    template_version = record_template_version(locked_app, template, actions)
    record_import_event(locked_app, template, template_version, actions)
    bump_manifest_catalog_version(locked_app, template, actions)
    _sync_webhook_config_from_manifest(
        app=locked_app,
        template=template,
        downstream_base_url=downstream_base_url,
    )
    return PermissionTemplateImportResult(template_version=template_version, actions=actions)


# webhook 事件 URL 的语义是"接入时从 manifest 读入、控制台可覆盖"(AppWebhookConfig 注释):
# 只有配置从未被控制台管理员改过(updated_by 为空或 manifest)时才回填, 避免覆盖人工设置。
_MANIFEST_ACTOR = "manifest"
_MANIFEST_DNS_TIMEOUT_SECONDS = 5.0


def _sync_webhook_config_from_manifest(
    *,
    app: App,
    template: AppManifestInput,
    downstream_base_url: str | None,
) -> None:
    from easyauth.webhooks.models import AppWebhookConfig  # noqa: PLC0415

    try:
        config = AppWebhookConfig.objects.get(app=app)
        config_is_new = False
    except AppWebhookConfig.DoesNotExist:
        if template.lifecycle is None:
            return
        config = AppWebhookConfig(app=app)
        config_is_new = True
    if config.updated_by not in ("", _MANIFEST_ACTOR):
        return
    lifecycle_urls = (
        ("", "")
        if template.lifecycle is None
        else (template.lifecycle.handover_url, template.lifecycle.onboard_url)
    )
    updates: list[str] = []
    for field, raw_url in zip(("handover_url", "onboard_url"), lifecycle_urls, strict=True):
        resolved = _resolve_manifest_url(raw_url, downstream_base_url)
        if resolved is not None and getattr(config, field) != resolved:
            if resolved:
                _ = validate_public_https_url(
                    resolved,
                    dns_timeout_seconds=_MANIFEST_DNS_TIMEOUT_SECONDS,
                )
            setattr(config, field, resolved)
            updates.append(field)
    if updates:
        config.updated_by = _MANIFEST_ACTOR
        if config_is_new:
            config.save()
        else:
            config.save(update_fields=[*updates, "updated_by", "updated_at"])


def _resolve_manifest_url(raw_url: str, downstream_base_url: str | None) -> str | None:
    # 绝对 http(s) URL 原样使用; 以 / 开头的站内路径需要下游 base_url(仅自动接入具备)。
    if not raw_url:
        return ""
    if raw_url.startswith(("http://", "https://")):
        return raw_url
    if raw_url.startswith("/") and downstream_base_url:
        return f"{downstream_base_url.rstrip('/')}{raw_url}"
    return None


def _reject_duplicate_template_version(*, app: App, version: int) -> None:
    latest_template = (
        PermissionTemplateVersion.objects.filter(app=app).order_by("-version").first()
    )
    if latest_template is None or version > latest_template.version:
        return
    if version < latest_template.version:
        raise PermissionTemplateImportError(
            code="permission_template_version_not_increasing",
            message="App manifest 版本必须大于当前最新版本。",
            subject=f"{version}<={latest_template.version}",
        )
    raise PermissionTemplateImportError(
        code="permission_template_version_duplicate",
        message="App manifest 版本已存在。",
        subject=str(version),
    )
