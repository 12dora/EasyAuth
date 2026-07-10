from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.admin_console.api_payloads import paginated_list_payload
from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.operation_filters import (
    OperationFilterValidationError,
    operation_filter_error_response,
    paginate_queryset,
)
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode
from easyauth.api.pagination import pagination_item
from easyauth.applications.models import App, AuthorizationGroup, Permission
from easyauth.lifecycle.models import (
    HANDOVER_KIND_VALUES,
    TASK_STATUS_VALUES,
    HandoverAppAction,
    HandoverGrantItem,
    HandoverTask,
    HandoverTeamItem,
    OnboardingTemplate,
    OnboardingTemplateItem,
    TransferPlan,
)
from easyauth.lifecycle.services import (
    HandoverConflictError,
    HandoverError,
    apply_team_item,
    build_transfer_grant_diff,
    cancel_task,
    confirm_transfer_grant_diff,
    delete_task,
    ensure_handover_task,
    execute_action,
    onboard_user,
    poll_async_action,
    preview_action,
    refresh_task_status,
    retry_action,
    skip_action,
    start_offboarding,
    update_action_receiver,
)
from easyauth.webhooks.hooks import HookCallError

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue
    from easyauth.api.pagination import Pagination

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


class ActionReceiverPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    app_key: str = Field(min_length=1, max_length=64)
    to_user_id: str | None = Field(default=None, max_length=128)
    release_to_pool: bool = False


class HandoverTaskPatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    cancel: bool = False
    app_actions: list[ActionReceiverPayload] = Field(default_factory=list)


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


def lifecycle_handover_tasks(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        queryset = HandoverTask.objects.select_related("subject_user").order_by(
            "-created_at",
            "-id",
        )
        status = request.GET.get("status", "").strip()
        if status in TASK_STATUS_VALUES:
            queryset = queryset.filter(status=status)
        kind = request.GET.get("kind", "").strip()
        if kind in HANDOVER_KIND_VALUES:
            queryset = queryset.filter(kind=kind)
        try:
            page = paginate_queryset(queryset, request.GET)
        except OperationFilterValidationError as exc:
            return operation_filter_error_response(exc)
        items: list[JsonValue] = [_task_item(task) for task in page.items]
        return json_response(
            paginated_list_payload(
                items=items,
                pagination=pagination_item(cast("Pagination", cast("object", page))),
            ),
        )
    if request.method == "POST":
        return _create_task(request, actor_id)
    return method_not_allowed_response()


def lifecycle_handover_task_detail(  # noqa: PLR0911 - HTTP 分支在入口显式返回。
    request: HttpRequest,
    task_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    task = _task_or_none(task_id)
    if task is None:
        return _not_found("交接单不存在。")
    if request.method == "GET":
        return json_response({"handover_task": _task_detail(task)})
    if request.method == "PATCH":
        return _patch_task(request, task, actor_id)
    if request.method == "DELETE":
        try:
            delete_task(task, actor_id=actor_id)
        except HandoverConflictError as error:
            return error_response(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
                str(error),
                status=HTTPStatus.CONFLICT,
            )
        return json_response({"deleted": True})
    return method_not_allowed_response()


def lifecycle_grant_items(  # noqa: C901, PLR0911, PLR0912 - HTTP 校验失败需逐项返回明确响应。
    request: HttpRequest,
    task_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    task = _task_or_none(task_id)
    if task is None:
        return _not_found("交接单不存在。")
    if request.method == "GET":
        items: list[JsonValue] = [
            _grant_item(item)
            for item in HandoverGrantItem.objects.select_related(
                "app",
                "authorization_group",
                "permission",
            ).filter(task=task)
        ]
        return json_response({"data": items})
    if request.method == "PATCH":
        try:
            payload = GrantItemsPatchPayload.model_validate_json(request.body)
        except ValidationError as exc:
            return _validation_error("勾选参数无效。", {"errors": str(exc)})
        selection = {entry.id: entry.selected for entry in payload.items}
        if len(selection) != len(payload.items):
            return _validation_error("同一授权快照项不能重复提交。")
        with transaction.atomic():
            locked_task = HandoverTask.objects.select_for_update().get(pk=task.id)
            if locked_task.status not in {"pending", "in_progress"}:
                return error_response(
                    ErrorCode.SEMANTIC_VALIDATION_ERROR,
                    "交接单不在进行中状态。",
                    status=HTTPStatus.CONFLICT,
                )
            editable = list(
                HandoverGrantItem.objects.select_for_update().filter(
                    task=locked_task,
                    id__in=selection,
                    status="pending",
                ),
            )
            if len(editable) != len(selection):
                return error_response(
                    ErrorCode.SEMANTIC_VALIDATION_ERROR,
                    "授权快照项不存在或已处理。",
                    status=HTTPStatus.CONFLICT,
                )
            changed_app_ids: set[int] = set()
            for item in editable:
                selected = selection[item.id]
                if item.selected == selected:
                    continue
                item.selected = selected
                item.save(update_fields=["selected"])
                changed_app_ids.add(item.app_id)
            if changed_app_ids:
                actions = HandoverAppAction.objects.select_for_update().filter(
                    task=locked_task,
                    app_id__in=changed_app_ids,
                    status="previewed",
                )
                for action in actions:
                    action.status = "pending"
                    action.preview_payload = {}
                    action.last_error = ""
                    action.save(
                        update_fields=["status", "preview_payload", "last_error", "updated_at"],
                    )
        return lifecycle_grant_items_readback(task)
    return method_not_allowed_response()


def lifecycle_grant_items_readback(task: HandoverTask) -> JsonResponse:
    items: list[JsonValue] = [
        _grant_item(item)
        for item in HandoverGrantItem.objects.select_related(
            "app",
            "authorization_group",
            "permission",
        ).filter(task=task)
    ]
    return json_response({"data": items})


def lifecycle_action_operation(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    operation: str,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    task = _task_or_none(task_id)
    if task is None:
        return _not_found("交接单不存在。")
    action = (
        HandoverAppAction.objects.select_related("app", "task", "task__subject_user", "to_user")
        .filter(task=task, app__app_key=app_key)
        .first()
    )
    if action is None:
        return _not_found("交接单中不存在该应用。")
    return _run_action_operation(action, operation=operation, actor_id=actor_id)


def _run_action_operation(
    action: HandoverAppAction,
    *,
    operation: str,
    actor_id: str,
) -> JsonResponse:
    try:
        if operation == "preview":
            action = preview_action(action)
        elif operation == "retry" and action.status == "async_pending":
            action = poll_async_action(action)
        elif operation == "execute":
            action = execute_action(action)
        elif operation == "retry":
            action = retry_action(action)
        elif operation == "skip":
            action = skip_action(action, actor_id=actor_id)
        else:
            return _validation_error("操作必须为 preview、execute、retry 或 skip。")
    except HandoverConflictError as error:
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.CONFLICT,
        )
    except (HandoverError, HookCallError) as error:
        return _validation_error(str(error))
    return json_response({"app_action": _action_item(action)})


def lifecycle_team_item_detail(
    request: HttpRequest,
    task_id: int,
    item_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "PATCH":
        return method_not_allowed_response()
    task = _task_or_none(task_id)
    if task is None:
        return _not_found("交接单不存在。")
    item = (
        HandoverTeamItem.objects.select_related("team", "task", "task__subject_user")
        .filter(task=task, id=item_id)
        .first()
    )
    if item is None:
        return _not_found("交接单中不存在该团队。")
    return _apply_team_item_request(request, item, actor_id=actor_id)


def _apply_team_item_request(
    request: HttpRequest,
    item: HandoverTeamItem,
    *,
    actor_id: str,
) -> JsonResponse:
    try:
        payload = TeamItemPatchPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("团队交接参数无效。", {"errors": str(exc)})
    to_user = None
    if payload.to_user_id:
        to_user = _active_user_or_none(payload.to_user_id)
        if to_user is None:
            return _validation_error("接收人不存在或已停用。")
    try:
        item = apply_team_item(
            item=item,
            action=payload.action,
            to_user=to_user,
            actor_id=actor_id,
        )
    except HandoverConflictError as error:
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.CONFLICT,
        )
    except HandoverError as error:
        return _validation_error(str(error))
    _ = refresh_task_status(item.task)
    return json_response({"team_item": _team_item(item)})


def lifecycle_grant_diff(  # noqa: PLR0911 - HTTP 分支在入口显式返回。
    request: HttpRequest,
    task_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    task = _task_or_none(task_id)
    if task is None:
        return _not_found("交接单不存在。")
    try:
        payload = GrantDiffBuildPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("差异参数无效。", {"errors": str(exc)})
    template = OnboardingTemplate.objects.filter(id=payload.template_id, is_active=True).first()
    if template is None:
        return _not_found("岗位模板不存在或未启用。")
    try:
        plan = build_transfer_grant_diff(task=task, template=template)
    except HandoverConflictError as error:
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.CONFLICT,
        )
    return json_response({"transfer_plan": _plan_item(plan)})


def lifecycle_grant_diff_confirm(  # noqa: PLR0911 - HTTP 分支在入口显式返回。
    request: HttpRequest,
    task_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    task = _task_or_none(task_id)
    if task is None:
        return _not_found("交接单不存在。")
    try:
        payload = GrantDiffConfirmPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("确认参数无效。", {"errors": str(exc)})
    try:
        plan = confirm_transfer_grant_diff(
            task=task,
            revoke_keys=payload.revoke_keys,
            add_keys=payload.add_keys,
            plan_revision=payload.plan_revision,
            actor_id=actor_id,
        )
    except HandoverConflictError as error:
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.CONFLICT,
        )
    except HandoverError as error:
        return _validation_error(str(error))
    return json_response({"transfer_plan": _plan_item(plan)})


def lifecycle_onboarding_templates(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        templates = OnboardingTemplate.objects.order_by("name")
        items: list[JsonValue] = [_template_item(t) for t in templates]
        return json_response({"data": items})
    if request.method == "POST":
        return _write_template(request, template=None)
    return method_not_allowed_response()


class OnboardingTemplateStatusPayload(BaseModel):
    # 列表操作列的启停切换: body 只含 is_active, 用于与「完整模板写入」区分。
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    is_active: bool


def lifecycle_onboarding_template_detail(  # noqa: PLR0911 - HTTP 分支在入口显式返回。
    request: HttpRequest,
    template_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    template = OnboardingTemplate.objects.filter(id=template_id).first()
    if template is None:
        return _not_found("岗位模板不存在。")
    if request.method == "GET":
        return json_response({"onboarding_template": _template_item(template)})
    if request.method == "PATCH":
        # 仅含 is_active 的请求 = 列表操作列的启停切换, 轻量更新不重建模板项; 其余走完整模板写入。
        try:
            status = OnboardingTemplateStatusPayload.model_validate_json(request.body)
        except ValidationError:
            return _write_template(request, template=template)
        template.is_active = status.is_active
        template.save()
        return json_response({"onboarding_template": _template_item(template)})
    if request.method == "DELETE":
        # 硬删除岗位模板: 关联的模板项(items)按 CASCADE 一并清除。
        _ = template.delete()
        return json_response({"deleted": True})
    return method_not_allowed_response()


def lifecycle_onboard(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    try:
        payload = OnboardPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("入职参数无效。", {"errors": str(exc)})
    user = _active_user_or_none(payload.user_id)
    if user is None:
        return _validation_error("用户不存在或已停用。")
    template = OnboardingTemplate.objects.filter(id=payload.template_id, is_active=True).first()
    if template is None:
        return _not_found("岗位模板不存在或未启用。")
    grants = onboard_user(user=user, template=template, actor_id=actor_id)
    return json_response(
        {
            "user_id": user.authentik_user_id,
            "template": template.name,
            "granted_app_count": len(grants),
        },
    )


def _create_task(request: HttpRequest, actor_id: str) -> JsonResponse:
    try:
        payload = HandoverTaskCreatePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("建单参数无效。", {"errors": str(exc)})
    if payload.kind not in HANDOVER_KIND_VALUES:
        return _validation_error("交接类型必须为 offboard 或 transfer。")
    subject = UserMirror.objects.filter(authentik_user_id=payload.user_id).first()
    if subject is None:
        return _validation_error("人员不存在。")
    if subject.authentik_user_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        return _validation_error("系统内置管理员不参与离职/转岗交接。")
    if payload.kind == "offboard":
        # 手动离职建单: 在职员工提前交接时不禁号; 已离职人员补单则补齐立即项。
        if subject.status == USER_STATUS_ACTIVE:
            task, created = ensure_handover_task(
                subject=subject,
                kind=payload.kind,
                created_by=actor_id,
                reason=payload.reason,
            )
        else:
            result = start_offboarding(subject, created_by=actor_id)
            task, created = result.task, result.created
    else:
        task, created = ensure_handover_task(
            subject=subject,
            kind=payload.kind,
            created_by=actor_id,
            reason=payload.reason,
        )
    status = HTTPStatus.CREATED if created else HTTPStatus.OK
    return json_response({"handover_task": _task_detail(task)}, status=status)


def _patch_task(request: HttpRequest, task: HandoverTask, actor_id: str) -> JsonResponse:
    try:
        payload = HandoverTaskPatchPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("交接单参数无效。", {"errors": str(exc)})
    if payload.cancel:
        try:
            task = cancel_task(task, actor_id=actor_id)
        except HandoverConflictError as error:
            return error_response(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
                str(error),
                status=HTTPStatus.CONFLICT,
            )
        return json_response({"handover_task": _task_detail(task)})
    return _patch_receiver_batch(task, payload.app_actions)


def _patch_receiver_batch(
    task: HandoverTask,
    entries: list[ActionReceiverPayload],
) -> JsonResponse:
    try:
        with transaction.atomic():
            locked_task = HandoverTask.objects.select_for_update().get(id=task.id)
            entries_by_app = {entry.app_key: entry for entry in entries}
            if len(entries_by_app) != len(entries):
                return _validation_error("同一应用不能重复指定接收人。")

            actions = tuple(
                HandoverAppAction.objects.select_for_update()
                .select_related("task", "app")
                .filter(task=locked_task, app__app_key__in=entries_by_app)
            )
            actions_by_app = {action.app.app_key: action for action in actions}
            missing_apps = entries_by_app.keys() - actions_by_app.keys()
            if missing_apps:
                return _validation_error(f"交接单中不存在应用 {sorted(missing_apps)[0]}。")

            receiver_ids = {entry.to_user_id for entry in entries if entry.to_user_id}
            receivers = {
                user.authentik_user_id: user
                for user in UserMirror.objects.filter(
                    authentik_user_id__in=receiver_ids,
                    status=USER_STATUS_ACTIVE,
                )
            }
            if receiver_ids - receivers.keys():
                return _validation_error("接收人不存在或已停用。")

            for app_key, entry in entries_by_app.items():
                policy: JsonObject = (
                    {"unowned_strategy": "release_to_pool"} if entry.release_to_pool else {}
                )
                _ = update_action_receiver(
                    action=actions_by_app[app_key],
                    to_user=receivers.get(entry.to_user_id or ""),
                    policy=policy,
                )
    except HandoverConflictError as error:
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.CONFLICT,
        )
    except HandoverError as error:
        return _validation_error(str(error))
    refreshed_task = _task_or_none(task.id) or task
    return json_response({"handover_task": _task_detail(refreshed_task)})


def _write_template(
    request: HttpRequest,
    *,
    template: OnboardingTemplate | None,
) -> JsonResponse:
    try:
        payload = TemplatePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _validation_error("模板参数无效。", {"errors": str(exc)})
    if (
        OnboardingTemplate.objects.filter(name=payload.name)
        .exclude(id=template.id if template is not None else None)
        .exists()
    ):
        return _validation_error("同名模板已存在。")
    resolved_items: list[OnboardingTemplateItem] = []
    for entry in payload.items:
        item = _resolve_template_item(entry)
        if isinstance(item, JsonResponse):
            return item
        try:
            item.full_clean(exclude={"template"})
        except DjangoValidationError as exc:
            return _validation_error("模板项参数无效。", {"errors": str(exc)})
        resolved_items.append(item)
    with transaction.atomic():
        if template is None:
            template = OnboardingTemplate.objects.create(
                name=payload.name,
                description=payload.description,
                is_active=payload.is_active,
            )
        else:
            template = OnboardingTemplate.objects.select_for_update().get(pk=template.id)
            template.name = payload.name
            template.description = payload.description
            template.is_active = payload.is_active
            template.save()
            _ = OnboardingTemplateItem.objects.filter(template=template).delete()
        for item in resolved_items:
            item.template = template
            item.save()
    return json_response({"onboarding_template": _template_item(template)})


def _resolve_template_item(entry: TemplateItemPayload) -> OnboardingTemplateItem | JsonResponse:
    app = App.objects.filter(app_key=entry.app_key, is_active=True).first()
    if app is None:
        return _validation_error(f"应用 {entry.app_key} 不存在或未启用。")
    if bool(entry.authorization_group_key) == bool(entry.permission_key):
        return _validation_error("模板项必须且只能指定授权组或权限之一。")
    group = None
    permission = None
    if entry.authorization_group_key:
        group = AuthorizationGroup.objects.filter(
            app=app,
            key=entry.authorization_group_key,
        ).first()
        if group is None:
            return _validation_error(f"授权组 {entry.authorization_group_key} 不存在。")
    elif entry.permission_key:
        permission = Permission.objects.filter(app=app, key=entry.permission_key).first()
        if permission is None:
            return _validation_error(f"权限 {entry.permission_key} 不存在。")
    else:
        return _validation_error("模板项必须指定授权组或权限。")
    return OnboardingTemplateItem(
        app=app,
        authorization_group=group,
        permission=permission,
        scope_key=entry.scope_key,
        grant_type=entry.grant_type,
        duration_days=entry.duration_days,
    )


def _task_or_none(task_id: int) -> HandoverTask | None:
    return HandoverTask.objects.select_related("subject_user").filter(id=task_id).first()


def _active_user_or_none(user_id: str) -> UserMirror | None:
    # 内置本地管理员不是员工, 不能作为交接接收人等生命周期对象。
    return (
        UserMirror.objects.filter(
            authentik_user_id=user_id,
            status=USER_STATUS_ACTIVE,
        )
        .exclude(authentik_user_id__startswith=LOCAL_ADMIN_SUBJECT_PREFIX)
        .first()
    )


def _task_item(task: HandoverTask) -> JsonObject:
    subject = task.subject_user
    return {
        "id": task.id,
        "kind": task.kind,
        "status": task.status,
        "subject": {
            "user_id": subject.authentik_user_id,
            "name": subject.name,
            "email": subject.email,
            "department": subject.department,
            "status": subject.status,
        },
        "reason": task.reason,
        "created_by": task.created_by,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


def _task_detail(task: HandoverTask) -> JsonObject:
    item = _task_item(task)
    actions: list[JsonValue] = [
        _action_item(action)
        for action in HandoverAppAction.objects.select_related("app", "to_user").filter(
            task=task,
        )
    ]
    team_items: list[JsonValue] = [
        _team_item(entry)
        for entry in HandoverTeamItem.objects.select_related("team", "to_user").filter(task=task)
    ]
    item["app_actions"] = actions
    item["team_items"] = team_items
    plan = TransferPlan.objects.select_related("new_template").filter(task=task).first()
    item["transfer_plan"] = _plan_item(plan) if plan is not None else None
    return item


def _action_item(action: HandoverAppAction) -> JsonObject:
    to_user = action.to_user
    return {
        "id": action.id,
        "app_key": action.app_key_snapshot,
        "app_name": action.app_name_snapshot,
        "app_catalog_version": action.app_catalog_version_snapshot,
        "status": action.status,
        "to_user": (
            {"user_id": to_user.authentik_user_id, "name": to_user.name}
            if to_user is not None
            else None
        ),
        "policy": action.policy,
        "preview_payload": action.preview_payload,
        "result_payload": action.result_payload,
        "async_status_url": action.async_status_url,
        "async_poll_attempts": action.async_poll_attempts,
        "attempts": action.attempts,
        "last_error": action.last_error,
    }


def _team_item(entry: HandoverTeamItem) -> JsonObject:
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


def _grant_item(item: HandoverGrantItem) -> JsonObject:
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


def _plan_item(plan: TransferPlan) -> JsonObject:
    template = plan.new_template
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
        "grant_diff": grant_diff,
        "revision": plan.revision,
        "confirmed_at": datetime_value(plan.confirmed_at),
    }


def _template_item(template: OnboardingTemplate) -> JsonObject:
    items: list[JsonValue] = []
    template_items = OnboardingTemplateItem.objects.select_related(
        "app",
        "authorization_group",
        "permission",
    ).filter(template=template)
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
        "items": items,
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
    }


def _validation_error(message: str, details: JsonObject | None = None) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        details,
        status=HTTPStatus.BAD_REQUEST,
    )


def _not_found(message: str) -> JsonResponse:
    return error_response(ErrorCode.NOT_FOUND, message, status=HTTPStatus.NOT_FOUND)
