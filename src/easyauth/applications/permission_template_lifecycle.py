"""从 App manifest 同步 webhook 生命周期 URL 与交接能力。"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Final

from easyauth.applications.handover_capability import (
    sync_handover_capability_from_manifest,
)
from easyauth.config.net import validate_public_https_url
from easyauth.webhooks.models import AppWebhookConfig

if TYPE_CHECKING:
    from easyauth.applications.models import App
    from easyauth.applications.permission_template_types import AppManifestInput

# webhook 事件 URL 的语义是"接入时从 manifest 读入、控制台可覆盖"(AppWebhookConfig 注释):
# 只有配置从未被控制台管理员改过(updated_by 为空或 manifest)时才回填, 避免覆盖人工设置。
_MANIFEST_ACTOR: Final = "manifest"
_MANIFEST_DNS_TIMEOUT_SECONDS: Final = 5.0
_LIFECYCLE_URL_FIELDS: Final[tuple[str, str]] = ("handover_url", "onboard_url")

__all__ = ["sync_manifest_lifecycle"]


def sync_manifest_lifecycle(
    *,
    app: App,
    template: AppManifestInput,
    downstream_base_url: str | None,
    actor_type: str,
) -> None:
    _sync_webhook_config_from_manifest(
        app=app,
        template=template,
        downstream_base_url=downstream_base_url,
    )
    lifecycle_for_cap = template.lifecycle
    if lifecycle_for_cap is not None:
        # 交接能力必须以 webhook 配置里实际可调用的 URL 为准(与 handover_hook_url 同口径)。
        # 相对路径无法补全时不会落库; 若把相对路径原样交给能力同步, App 会被标成
        # declared, 但创建离职交接任务时因钩子为空而直接失败。
        lifecycle_for_cap = replace(
            lifecycle_for_cap,
            handover_url=_persisted_handover_hook_url(app),
        )
    sync_handover_capability_from_manifest(
        app,
        lifecycle_for_cap,
        actor_id=template.imported_by or _MANIFEST_ACTOR,
        actor_type=actor_type,
    )


def _persisted_handover_hook_url(app: App) -> str:
    # 必须与 easyauth.lifecycle.handover_shared.handover_hook_url 同口径:
    # 只读 enabled=True 的配置行; 无行或未启用视为没有钩子。
    config = AppWebhookConfig.objects.filter(app=app, enabled=True).first()
    if config is None:
        return ""
    return config.handover_url


def _sync_webhook_config_from_manifest(
    *,
    app: App,
    template: AppManifestInput,
    downstream_base_url: str | None,
) -> None:
    locked = _lock_or_create_webhook_config(app, template)
    if locked is None:
        return
    config, config_is_new = locked
    if config.updated_by not in ("", _MANIFEST_ACTOR):
        return
    resolved_urls = _resolve_lifecycle_urls(template, downstream_base_url)
    updates = _validate_lifecycle_urls(config, resolved_urls)
    _apply_manifest_ownership(config, updates, config_is_new=config_is_new)


def _lock_or_create_webhook_config(
    app: App,
    template: AppManifestInput,
) -> tuple[AppWebhookConfig, bool] | None:
    try:
        config = AppWebhookConfig.objects.select_for_update().get(app=app)
    except AppWebhookConfig.DoesNotExist:
        if template.lifecycle is None:
            return None
        return AppWebhookConfig(app=app), True
    return config, False


def _resolve_lifecycle_urls(
    template: AppManifestInput,
    downstream_base_url: str | None,
) -> tuple[str | None, str | None]:
    raw_urls = (
        ("", "")
        if template.lifecycle is None
        else (template.lifecycle.handover_url, template.lifecycle.onboard_url)
    )
    handover_url, onboard_url = raw_urls
    return (
        _resolve_manifest_url(handover_url, downstream_base_url),
        _resolve_manifest_url(onboard_url, downstream_base_url),
    )


def _validate_lifecycle_urls(
    config: AppWebhookConfig,
    resolved_urls: tuple[str | None, str | None],
) -> list[str]:
    updates: list[str] = []
    for field, resolved in zip(_LIFECYCLE_URL_FIELDS, resolved_urls, strict=True):
        if resolved is not None and getattr(config, field) != resolved:
            if resolved:
                _ = validate_public_https_url(
                    resolved,
                    dns_timeout_seconds=_MANIFEST_DNS_TIMEOUT_SECONDS,
                )
            setattr(config, field, resolved)
            updates.append(field)
    return updates


def _apply_manifest_ownership(
    config: AppWebhookConfig,
    updates: list[str],
    *,
    config_is_new: bool,
) -> None:
    if not updates:
        return
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
