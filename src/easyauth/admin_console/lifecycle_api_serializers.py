"""集中定义生命周期控制台 API 的请求体, 查询辅助与响应序列化。"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.admin_console.api_responses import error_response
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode
from easyauth.lifecycle.models import (
    HandoverGrantItem,
    HandoverTask,
    HandoverTeamItem,
    OnboardingTemplate,
    OnboardingTemplateRevisionItem,
    TransferPlan,
)

if TYPE_CHECKING:
    from django.http import JsonResponse

    from easyauth.api.errors import JsonValue

type JsonObject = dict[str, "JsonValue"]


class HandoverTaskCreatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    kind: str = Field(max_length=16)
    user_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(default="", max_length=2000)


class HandoverTaskPatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    # 01 §6.3: app_actions 字段整体删除, 只保留 cancel。
    cancel: bool = False


class SkipReasonPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    reason: str = Field(min_length=1, max_length=2000)


class ExecuteConfirmPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    confirm_version: int = Field(ge=0)


class GrantItemSelectionPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    id: int
    selected: bool


class GrantItemsPatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    items: list[GrantItemSelectionPayload] = Field(min_length=1)


class TeamItemPatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    action: str = Field(max_length=16)
    to_user_id: str | None = Field(default=None, max_length=128)


class GrantDiffBuildPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    template_id: int


class GrantDiffConfirmPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    revoke_keys: list[str] = Field(default_factory=list)
    add_keys: list[str] = Field(default_factory=list)
    plan_revision: int = Field(ge=1)


class TemplateItemPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    app_key: str = Field(min_length=1, max_length=64)
    authorization_group_key: str = Field(default="", max_length=64)
    permission_key: str = Field(default="", max_length=128)
    scope_key: str = Field(default="", max_length=64)
    grant_type: str = Field(default="permanent", max_length=16)
    duration_days: int | None = Field(default=None, ge=1, le=3650)


class TemplatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    is_active: bool = True
    items: list[TemplateItemPayload] = Field(default_factory=list)


class OnboardPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    user_id: str = Field(min_length=1, max_length=128)
    template_id: int


class OnboardingTemplateStatusPayload(BaseModel):
    # 列表操作列的启停切换: body 只含 is_active, 用于与「完整模板写入」区分。
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    is_active: bool


def task_or_none(task_id: int) -> HandoverTask | None:
    return HandoverTask.objects.select_related("subject_user").filter(id=task_id).first()


def active_user_or_none(user_id: str) -> UserMirror | None:
    # 内置本地管理员不是员工, 不能作为交接接收人等生命周期对象。
    return (
        UserMirror.objects.filter(
            authentik_user_id=user_id,
            status=USER_STATUS_ACTIVE,
        )
        .exclude(authentik_user_id__startswith=LOCAL_ADMIN_SUBJECT_PREFIX)
        .first()
    )


def team_item(entry: HandoverTeamItem) -> JsonObject:
    to_user = entry.to_user
    return {
        "id": entry.id,
        "team_id": entry.team_id,
        "team_name": entry.team.name,
        "action": entry.action,
        "status": entry.status,
        "to_user": (
            {"user_id": to_user.authentik_user_id, "name": to_user.name}
            if to_user is not None
            else None
        ),
    }


def grant_item(item: HandoverGrantItem) -> JsonObject:
    return {
        "id": item.id,
        "app_key": item.app_key_snapshot,
        "app_catalog_version": item.app_catalog_version_snapshot,
        "kind": item.target_kind_snapshot,
        "key": item.target_key_snapshot,
        "name": item.target_name_snapshot,
        "scope_key": item.scope_key,
        "grant_type": item.grant_type,
        "grant_expires_at": datetime_value(item.grant_expires_at),
        "selected": item.selected,
        "status": item.status,
    }


def plan_item(plan: TransferPlan) -> JsonObject:
    template = plan.new_template
    template_revision = plan.new_template_revision
    grant_diff = dict(plan.grant_diff)
    if plan.confirmed_at is not None:
        confirmed_by_name = {
            "revoke": set(plan.confirmed_revoke_keys),
            "add": set(plan.confirmed_add_keys),
        }
        for name, confirmed_keys in confirmed_by_name.items():
            entries = grant_diff.get(name)
            if not isinstance(entries, list):
                continue
            serialized: list[JsonValue] = [
                {**entry, "selected": entry.get("key") in confirmed_keys}
                for entry in entries
                if isinstance(entry, dict)
            ]
            grant_diff[name] = serialized
    return {
        "template_id": template.id if template is not None else None,
        "template_name": template.name if template is not None else "",
        "template_revision_id": template_revision.id if template_revision is not None else None,
        "template_revision": template_revision.revision if template_revision is not None else None,
        "grant_diff": grant_diff,
        "revision": plan.revision,
        "confirmed_at": datetime_value(plan.confirmed_at),
    }


def template_item(template: OnboardingTemplate) -> JsonObject:
    items: list[JsonValue] = []
    revision = template.current_revision
    if revision is None:
        template_items: tuple[OnboardingTemplateRevisionItem, ...] = ()
    else:
        template_items = tuple(
            getattr(
                revision,
                "_prefetched_items",
                OnboardingTemplateRevisionItem.objects.select_related(
                    "app",
                    "authorization_group",
                    "permission",
                ).filter(revision=revision),
            ),
        )
    for item in template_items:
        if item.authorization_group is not None:
            kind = "group"
            key = item.authorization_group.key
            name = item.authorization_group.name
        else:
            permission = item.permission
            kind = "permission"
            key = permission.key if permission is not None else ""
            name = permission.name if permission is not None else ""
        items.append(
            {
                "id": item.id,
                "app_key": item.app.app_key,
                "kind": kind,
                "key": key,
                "name": name,
                "scope_key": item.scope_key,
                "grant_type": item.grant_type,
                "duration_days": item.duration_days,
            },
        )
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "is_active": template.is_active,
        "current_revision_id": revision.id if revision is not None else None,
        "current_revision": revision.revision if revision is not None else None,
        "items": items,
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
    }


def validation_error(message: str, details: JsonObject | None = None) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        details,
        status=HTTPStatus.BAD_REQUEST,
    )


def not_found(message: str) -> JsonResponse:
    return error_response(ErrorCode.NOT_FOUND, message, status=HTTPStatus.NOT_FOUND)
