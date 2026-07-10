from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.access_requests.approvals import access_request_approver_user_ids
from easyauth.api.datetime_json import datetime_value
from easyauth.applications import health_models

if TYPE_CHECKING:
    from easyauth.access_requests.models import AccessRequest
    from easyauth.api.errors import JsonValue
    from easyauth.applications.dependency_health import DependencyHealthItem

type JsonObject = dict[str, JsonValue]


def access_request_decision_fields(access_request: AccessRequest) -> JsonObject:
    # 站内审批闭环(M2)的决定事实: 权限审批不再与钉钉回调有任何关系(§3.0)。
    approver_ids: list[JsonValue] = []
    approver_ids.extend(access_request_approver_user_ids(access_request))
    return {
        "approver_user_ids": approver_ids,
        "decided_by": access_request.decided_by,
        "decision_actor_type": access_request.decision_actor_type,
        "decision_comment": access_request.decision_comment,
        "decided_at": datetime_value(access_request.decided_at),
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
    health_map: JsonObject = {item.component: _dependency_component(item) for item in items}
    return {"health_map": health_map, **health_map}


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
        health_models.DEPENDENCY_AUTHENTIK_DIRECTORY: {
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
