from __future__ import annotations

import hashlib
import json

from django.utils import timezone

from easyauth.api.errors import JsonValue
from easyauth.connectors.base import BaseConnector, secret_field_names
from easyauth.connectors.models import (
    ConnectorConfigError,
    ConnectorInstance,
    ConnectorMapping,
    ConnectorSyncRun,
)
from easyauth.connectors.registry import available_connectors, get_connector

type JsonObject = dict[str, JsonValue]

TOMBSTONE_MAPPING_SERIALIZE_ERROR = "tombstone mapping cannot be serialized"


def connector_types() -> list[BaseConnector]:
    return list(available_connectors().values())


def connector_type_item(connector: BaseConnector) -> JsonObject:
    return {
        "key": connector.key,
        "display_name": connector.display_name,
        "config_schema": dict(connector.config_schema),
    }


def instance_item(instance: ConnectorInstance) -> JsonObject:
    connector = get_connector(instance.connector_key)
    redacted, config_error, configured_secrets = _project_config(instance, connector)
    return {
        "id": instance.id,
        "connector_key": instance.connector_key,
        "display_name": connector.display_name if connector else instance.connector_key,
        "enabled": instance.enabled,
        "config": redacted,
        "config_error": config_error,
        "configured_secrets": configured_secrets,
        "reconcile_interval_seconds": instance.reconcile_interval_seconds,
        "last_reconcile_at": (
            instance.last_reconcile_at.isoformat() if instance.last_reconcile_at else None
        ),
        "last_status": instance.last_status,
        "last_error": instance.last_error,
        "consecutive_failures": instance.consecutive_failures,
        "external_account_id": instance.external_account_id,
        "external_groups_refresh": _external_groups_refresh_item(instance),
        "reconcile_state": reconcile_state_item(instance),
        "updated_by": instance.updated_by,
        "updated_at": instance.updated_at.isoformat(),
    }


def _project_config(
    instance: ConnectorInstance,
    connector: BaseConnector | None,
) -> tuple[JsonObject, JsonObject | None, list[JsonValue]]:
    secrets: frozenset[str] = (
        secret_field_names(connector.config_schema) if connector else frozenset()
    )
    config_error: ConnectorConfigError | None = None
    try:
        config = instance.config
    except ConnectorConfigError as error:
        config_error = error
        config = {}
    redacted: JsonObject = {key: ("" if key in secrets else value) for key, value in config.items()}
    projected_error: JsonObject | None = (
        {"kind": config_error.kind, "message": str(config_error)}
        if config_error is not None
        else None
    )
    configured_secrets: list[JsonValue] = []
    configured_secrets.extend(sorted(key for key in secrets if config.get(key)))
    return redacted, projected_error, configured_secrets


def _external_groups_refresh_item(instance: ConnectorInstance) -> JsonObject:
    return {
        "status": instance.external_groups_refresh_status,
        "cursor": instance.external_groups_refresh_cursor,
        "refreshed_at": (
            instance.external_groups_refreshed_at.isoformat()
            if instance.external_groups_refreshed_at
            else None
        ),
    }


def reconcile_state_item(instance: ConnectorInstance) -> JsonObject:
    now = timezone.now()
    lease_active = (
        instance.reconcile_lease_token is not None
        and instance.reconcile_lease_expires_at is not None
        and instance.reconcile_lease_expires_at > now
    )
    if lease_active:
        status = "running"
    elif instance.reconcile_worker_queued:
        status = "queued"
    elif instance.reconcile_dirty:
        status = "dirty"
    else:
        status = "idle"
    return {
        "status": status,
        "generation": instance.reconcile_generation,
        "reconciled_generation": instance.reconciled_generation,
        "dirty": instance.reconcile_dirty,
        "pending_trigger": instance.reconcile_pending_trigger,
        "worker_queued": instance.reconcile_worker_queued,
        "worker_queued_at": (
            instance.reconcile_worker_queued_at.isoformat()
            if instance.reconcile_worker_queued_at
            else None
        ),
        "lease_active": lease_active,
        "lease_expires_at": (
            instance.reconcile_lease_expires_at.isoformat()
            if instance.reconcile_lease_expires_at
            else None
        ),
    }


def mapping_item(mapping: ConnectorMapping) -> JsonObject:
    if mapping.authorization_group is None:
        raise ValueError(TOMBSTONE_MAPPING_SERIALIZE_ERROR)
    return {
        "authorization_group_key": mapping.authorization_group.key,
        "authorization_group_name": mapping.authorization_group.name,
        "external_ref": mapping.external_ref,
        "auto_create": mapping.auto_create,
    }


def mapping_revision(mappings: list[ConnectorMapping]) -> str:
    canonical = [
        {
            "authorization_group_key": mapping.authorization_group.key,
            "external_ref": mapping.external_ref,
            "auto_create": mapping.auto_create,
        }
        for mapping in mappings
        if mapping.authorization_group is not None and not mapping.tombstoned
    ]
    serialized = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def sync_run_item(run: ConnectorSyncRun) -> JsonObject:
    return {
        "id": run.id,
        "trigger": run.trigger,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat(),
        "stats": dict(run.stats),
        "error": run.error,
    }


def merge_secret_fields(
    connector: BaseConnector,
    config: dict[str, JsonValue],
    stored: ConnectorInstance | None,
) -> dict[str, JsonValue]:
    # 读接口不回显密文, 表单原样提交会带回空串; 空值密文回填已存值。
    if stored is None:
        return config
    stored_config = stored.config
    for name in secret_field_names(connector.config_schema):
        incoming = config.get(name)
        if (incoming is None or incoming == "") and stored_config.get(name):
            config[name] = stored_config[name]
    return config


def instance_audit_metadata(instance: ConnectorInstance) -> JsonObject:
    # 审计记录不得包含 token/secret 明文。
    return {
        "app_key": instance.app.app_key,
        "connector_key": instance.connector_key,
        "instance_id": instance.id,
        "enabled": instance.enabled,
        "reconcile_interval_seconds": instance.reconcile_interval_seconds,
    }
