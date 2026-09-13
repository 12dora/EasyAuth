from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from django.db import transaction
from django.utils import timezone

from easyauth.connectors.base import BaseConnector, ConnectorError, ExternalGroup
from easyauth.connectors.models import ConnectorExternalGroup, ConnectorInstance
from easyauth.connectors.registry import get_connector

if TYPE_CHECKING:
    from datetime import datetime

CONNECTOR_NOT_REGISTERED_TEMPLATE: Final = "连接器类型 {key} 未在 EASYAUTH_CONNECTORS 注册。"
EXTERNAL_GROUP_REFRESH_STATUS_RUNNING: Final = "running"
EXTERNAL_GROUP_REFRESH_STATUS_SUCCESS: Final = "success"
EXTERNAL_GROUP_REFRESH_STATUS_FAILED: Final = "failed"
EXTERNAL_GROUP_REFRESH_BULK_BATCH_SIZE: Final = 500


@dataclass(frozen=True, slots=True)
class ExternalGroupRefreshResult:
    active_count: int
    deactivated_count: int
    refreshed_at: datetime


def refresh_external_groups(instance_id: int) -> ExternalGroupRefreshResult:
    instance = ConnectorInstance.objects.select_related("app").filter(id=instance_id).first()
    if instance is None or instance.tombstoned:
        return ExternalGroupRefreshResult(
            active_count=0,
            deactivated_count=0,
            refreshed_at=timezone.now(),
        )
    connector = get_connector(instance.connector_key)
    if connector is None:
        message = CONNECTOR_NOT_REGISTERED_TEMPLATE.format(key=instance.connector_key)
        _mark_instance_external_group_refresh_failed(instance, message)
        raise ConnectorError(message)
    started_at = timezone.now()
    _start_external_group_refresh(instance)
    try:
        active_count, last_cursor = _consume_external_group_pages(
            instance,
            connector,
            started_at,
        )
    except ConnectorError as error:
        _mark_instance_external_group_refresh_failed(instance, str(error))
        raise
    deactivated_count = _finish_external_group_refresh(
        instance,
        started_at=started_at,
        last_cursor=last_cursor,
    )
    return ExternalGroupRefreshResult(
        active_count=active_count,
        deactivated_count=deactivated_count,
        refreshed_at=started_at,
    )


def _start_external_group_refresh(instance: ConnectorInstance) -> None:
    instance.external_groups_refresh_status = EXTERNAL_GROUP_REFRESH_STATUS_RUNNING
    instance.external_groups_refresh_cursor = ""
    instance.save(
        update_fields=[
            "external_groups_refresh_status",
            "external_groups_refresh_cursor",
            "updated_at",
        ]
    )


def _consume_external_group_pages(
    instance: ConnectorInstance,
    connector: BaseConnector,
    started_at: datetime,
) -> tuple[int, str]:
    active_count = 0
    last_cursor = ""
    for page in connector.iter_external_group_pages(instance.config):
        groups = page.groups
        last_cursor = page.cursor
        active_count += len(groups)
        _upsert_external_group_page(
            instance=instance,
            groups=groups,
            seen_at=started_at,
            cursor=last_cursor,
        )
    return active_count, last_cursor


def _finish_external_group_refresh(
    instance: ConnectorInstance,
    *,
    started_at: datetime,
    last_cursor: str,
) -> int:
    with transaction.atomic():
        deactivated_count = ConnectorExternalGroup.objects.filter(
            instance=instance,
            is_active=True,
            last_seen_at__lt=started_at,
        ).update(is_active=False)
        instance.last_error = ""
        instance.external_groups_refresh_status = EXTERNAL_GROUP_REFRESH_STATUS_SUCCESS
        instance.external_groups_refresh_cursor = last_cursor
        instance.external_groups_refreshed_at = started_at
        instance.save(
            update_fields=[
                "last_error",
                "external_groups_refresh_status",
                "external_groups_refresh_cursor",
                "external_groups_refreshed_at",
                "updated_at",
            ]
        )
    return deactivated_count


def _upsert_external_group_page(
    *,
    instance: ConnectorInstance,
    groups: tuple[ExternalGroup, ...],
    seen_at: datetime,
    cursor: str,
) -> None:
    rows = [
        ConnectorExternalGroup(
            instance=instance,
            external_ref=group.ref,
            external_name=group.name,
            is_active=True,
            last_seen_at=seen_at,
        )
        for group in groups
    ]
    with transaction.atomic():
        if rows:
            _ = ConnectorExternalGroup.objects.bulk_create(
                rows,
                batch_size=EXTERNAL_GROUP_REFRESH_BULK_BATCH_SIZE,
                update_conflicts=True,
                update_fields=["external_name", "is_active", "last_seen_at"],
                unique_fields=["instance", "external_ref"],
            )
        _ = ConnectorInstance.objects.filter(id=instance.id).update(
            external_groups_refresh_cursor=cursor,
            updated_at=timezone.now(),
        )
        instance.external_groups_refresh_cursor = cursor


def _mark_instance_external_group_refresh_failed(
    instance: ConnectorInstance,
    message: str,
) -> None:
    instance.last_error = message
    instance.external_groups_refresh_status = EXTERNAL_GROUP_REFRESH_STATUS_FAILED
    instance.save(update_fields=["last_error", "external_groups_refresh_status", "updated_at"])
