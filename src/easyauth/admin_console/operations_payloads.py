from __future__ import annotations

from typing import TYPE_CHECKING, Final

from easyauth.api.datetime_json import datetime_value
from easyauth.applications import health_models

if TYPE_CHECKING:
    from easyauth.access_requests.models import AccessRequest
    from easyauth.api.errors import JsonValue
    from easyauth.applications.dependency_health import DependencyHealthItem

DINGTALK_CALLBACK_PATH: Final = "/integrations/dingtalk/callback"

type JsonObject = dict[str, JsonValue]


def access_request_dingtalk_fields(access_request: AccessRequest) -> JsonObject:
    return {
        "dingtalk_process_instance_id": access_request.dingtalk_process_instance_id,
        "dingtalk_callback_path": DINGTALK_CALLBACK_PATH,
        "dingtalk_callback_status": _callback_status(access_request),
        "dingtalk_callback_received_at": _callback_received_at(access_request),
    }


def health_item(item: DependencyHealthItem) -> JsonObject:
    payload: JsonObject = {
        "component": item.component,
        "status": item.status,
        "last_checked_at": datetime_value(item.last_checked_at),
        "summary": item.summary,
        "error_summary": item.error_summary,
    }
    if item.app_key is not None:
        payload["app_key"] = item.app_key
    return payload


def dependency_health_map_payload(items: tuple[DependencyHealthItem, ...]) -> JsonObject:
    return {item.component: _dependency_component(item) for item in items}


def _dependency_component(item: DependencyHealthItem) -> JsonObject:
    payload: JsonObject = {
        "status": item.status,
        "last_checked_at": datetime_value(item.last_checked_at),
        "summary": item.summary,
        "error_summary": item.error_summary,
    }
    payload.update(_dependency_alias_fields(item))
    return payload


def _dependency_alias_fields(item: DependencyHealthItem) -> JsonObject:
    last_checked_at = datetime_value(item.last_checked_at)
    aliases: dict[str, JsonObject] = {
        health_models.DEPENDENCY_AUTHENTIK: {
            "last_sync_at": last_checked_at,
            "last_sync_result": item.summary,
        },
        health_models.DEPENDENCY_DINGTALK: {
            "last_callback_success_at": last_checked_at,
            "recent_failure_count": 0 if item.status == "healthy" else 1,
        },
        health_models.DEPENDENCY_CELERY: {
            "last_grant_expiration_run_at": last_checked_at,
            "last_processed_count": None,
        },
    }
    fallback: JsonObject = {}
    return aliases.get(item.component, fallback)


def _callback_status(access_request: AccessRequest) -> str | None:
    if access_request.dingtalk_process_instance_id is None:
        return None
    if access_request.status == "submitted":
        return None
    return access_request.status


def _callback_received_at(access_request: AccessRequest) -> str | None:
    if access_request.approved_at is not None:
        return access_request.approved_at.isoformat()
    return datetime_value(access_request.applied_at)
