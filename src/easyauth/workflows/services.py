from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Literal, cast, override

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.integration_settings import dingtalk_runtime_config
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiClient,
    DingTalkApiError,
    DingTalkApiRequestError,
    DingTalkApiUnavailableError,
    DingTalkFormComponent,
    DingTalkNotConfiguredError,
)
from easyauth.webhooks.delivery import WebhookNotConfiguredError, enqueue_delivery
from easyauth.webhooks.models import (
    WEBHOOK_EVENT_APPROVAL_COMPLETED,
    AppWebhookConfig,
)
from easyauth.workflows.models import (
    APPROVAL_STATUS_CREATED,
    APPROVAL_STATUS_FAILED,
    APPROVAL_STATUS_SUBMITTED,
    APPROVAL_TERMINAL_STATUSES,
    CALLBACK_STATE_APPLIED,
    CALLBACK_STATE_CONFLICT,
    SUBMISSION_STATE_AMBIGUOUS,
    SUBMISSION_STATE_FAILED,
    SUBMISSION_STATE_PENDING,
    SUBMISSION_STATE_SUBMITTED,
    SUBMISSION_STATE_SUBMITTING,
    ApprovalInstance,
    ApprovalTemplate,
    PendingApprovalCallback,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from easyauth.applications.models import App
    from easyauth.applications.ops_models import JsonValue

type ApprovalCreateErrorKind = Literal[
    "conflict",
    "dependency_unavailable",
    "originator_invalid",
    "template_not_found",
    "validation_error",
]

TEMPLATE_NOT_FOUND_MESSAGE: Final = "审批模板不存在或未启用。"
ORIGINATOR_INVALID_MESSAGE: Final = "发起人不存在、已停用或缺少钉钉绑定。"
INSTANCE_STATUS_CONFLICT_MESSAGE: Final = "回调状态与审批实例状态不匹配。"
INSTANCE_NOT_FOUND_MESSAGE: Final = "审批实例不存在。"
FORM_MAPPING_INVALID_MESSAGE: Final = "审批模板 form_mapping 必须是字符串到字符串的映射。"
FORM_SCHEMA_INVALID_MESSAGE: Final = "审批模板 form_schema 或提交的 form 不符合契约。"
IDEMPOTENCY_PAYLOAD_CONFLICT_MESSAGE: Final = "同一 biz_key 已使用不同的发起人或表单载荷。"
RETRY_REQUIRED_MESSAGE: Final = "审批提交失败, 必须显式设置 retry=true 后重试。"
SUBMISSION_AMBIGUOUS_MESSAGE: Final = "钉钉是否已创建审批无法确认, 禁止盲目重试。"
SUBMISSION_IN_PROGRESS_MESSAGE: Final = "审批正在提交, 请勿重复发起。"
RETRY_STATE_CONFLICT_MESSAGE: Final = "只有明确失败的审批实例允许显式重试。"
SUBMISSION_DEADLINE_GRACE_SECONDS: Final = 5


@dataclass(frozen=True, slots=True)
class ApprovalCreateError(Exception):
    kind: ApprovalCreateErrorKind
    message: str

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ApprovalCallbackConflictError(Exception):
    instance_id: str
    status: str

    @override
    def __str__(self) -> str:
        return INSTANCE_STATUS_CONFLICT_MESSAGE


class ApprovalInstanceNotFoundError(LookupError):
    def __init__(self) -> None:
        super().__init__(INSTANCE_NOT_FOUND_MESSAGE)


def create_approval_instance(  # noqa: PLR0913 - 发起审批的完整业务事实, 拆包装反而失真。
    *,
    app: App,
    template_key: str,
    originator_user_id: str,
    form: Mapping[str, JsonValue],
    biz_key: str,
    actor_id: str,
    selected_template: ApprovalTemplate | None = None,
    retry_failed: bool = False,
) -> tuple[ApprovalInstance, bool]:
    """发起一笔钉钉审批; 同 biz_key 幂等返回既有实例。返回 (instance, created)。"""
    template = (
        _active_template(app, template_key)
        if selected_template is None
        else _selected_active_template(app, template_key, selected_template)
    )
    originator = _valid_originator(originator_user_id)
    normalized_form, form_components = _validated_form(template, form)
    payload_hash = _payload_hash(originator_user_id=originator_user_id, form=normalized_form)
    existing = ApprovalInstance.objects.filter(
        app=app,
        template=template,
        biz_key=biz_key,
    ).first()
    if existing is not None:
        _ = recover_stale_submission(existing)

    created = False
    try:
        with transaction.atomic():
            instance = (
                ApprovalInstance.objects.select_for_update()
                .filter(app=app, template=template, biz_key=biz_key)
                .first()
            )
            if instance is None:
                instance = ApprovalInstance.objects.create(
                    app=app,
                    template=template,
                    biz_key=biz_key,
                    originator_user=originator,
                    form_values=normalized_form,
                    payload_hash=payload_hash,
                )
                created = True
            else:
                should_submit = _prepare_existing_instance(
                    instance,
                    payload_hash=payload_hash,
                    retry_failed=retry_failed,
                )
                if not should_submit:
                    return instance, False
    except IntegrityError:
        with transaction.atomic():
            winner = ApprovalInstance.objects.select_for_update().get(
                app=app,
                template=template,
                biz_key=biz_key,
            )
            should_submit = _prepare_existing_instance(
                winner,
                payload_hash=payload_hash,
                retry_failed=retry_failed,
            )
            if not should_submit:
                return winner, False
            instance = winner

    _mark_submitting(instance)
    try:
        process_instance_id = DingTalkApiClient.from_settings().create_process_instance(
            process_code=template.dingtalk_process_code,
            originator_userid=originator.dingtalk_userid,
            form_components=form_components,
        )
    except DingTalkApiError as error:
        ambiguous = _submission_result_is_ambiguous(error)
        _mark_submission_error(instance, error=error, ambiguous=ambiguous)
        _record_instance_event(
            instance,
            action=(
                "approval_instance_submission_ambiguous"
                if ambiguous
                else "approval_instance_create_failed"
            ),
            actor_id=actor_id,
        )
        raise ApprovalCreateError(kind="dependency_unavailable", message=str(error)) from error

    _callback_applied = _mark_submitted(instance, process_instance_id=process_instance_id)
    _record_instance_event(instance, action="approval_instance_submitted", actor_id=actor_id)
    return instance, created


def apply_instance_callback(
    *,
    process_instance_id: str,
    status: str,
) -> ApprovalInstance:
    """钉钉回调推进实例; 无法关联时先持久化, 待提交保存 process ID 后恢复。"""
    missing = False
    conflict: ApprovalCallbackConflictError | None = None
    instance: ApprovalInstance | None = None
    with transaction.atomic():
        instance = (
            ApprovalInstance.objects.select_for_update()
            .select_related("app", "template", "originator_user")
            .filter(dingtalk_process_instance_id=process_instance_id)
            .first()
        )
        callback, _created = PendingApprovalCallback.objects.select_for_update().get_or_create(
            process_instance_id=process_instance_id,
            defaults={"status": status},
        )
        if callback.status != status:
            callback.state = CALLBACK_STATE_CONFLICT
            callback.last_error = INSTANCE_STATUS_CONFLICT_MESSAGE
            callback.save(update_fields=["state", "last_error", "updated_at"])
            conflict = ApprovalCallbackConflictError(
                instance_id=str(instance.id) if instance is not None else "",
                status=callback.status,
            )
        elif instance is None:
            missing = True
        else:
            _changed, conflict = _apply_callback_locked(instance, callback)
            if conflict is None and instance.status in APPROVAL_TERMINAL_STATUSES:
                # 重复回调也补写事件, 且终态与 delivery/outbox 在同一事务提交。
                deliver_completion(instance)
    if conflict is not None:
        raise conflict
    if missing or instance is None:
        raise ApprovalInstanceNotFoundError
    return instance


def _prepare_existing_instance(
    instance: ApprovalInstance,
    *,
    payload_hash: str,
    retry_failed: bool,
) -> bool:
    if instance.payload_hash != payload_hash:
        raise ApprovalCreateError(kind="conflict", message=IDEMPOTENCY_PAYLOAD_CONFLICT_MESSAGE)
    if retry_failed:
        if instance.submission_state != SUBMISSION_STATE_FAILED:
            raise ApprovalCreateError(kind="conflict", message=RETRY_STATE_CONFLICT_MESSAGE)
        instance.status = APPROVAL_STATUS_CREATED
        instance.submission_state = SUBMISSION_STATE_PENDING
        instance.submission_deadline_at = None
        instance.last_error = ""
        instance.save(
            update_fields=[
                "status",
                "submission_state",
                "submission_deadline_at",
                "last_error",
                "updated_at",
            ],
        )
        return True
    if instance.submission_state == SUBMISSION_STATE_SUBMITTED:
        return False
    if instance.submission_state == SUBMISSION_STATE_FAILED:
        raise ApprovalCreateError(kind="conflict", message=RETRY_REQUIRED_MESSAGE)
    if instance.submission_state == SUBMISSION_STATE_AMBIGUOUS:
        raise ApprovalCreateError(kind="conflict", message=SUBMISSION_AMBIGUOUS_MESSAGE)
    raise ApprovalCreateError(kind="conflict", message=SUBMISSION_IN_PROGRESS_MESSAGE)


def _mark_submitting(instance: ApprovalInstance) -> None:
    with transaction.atomic():
        locked = ApprovalInstance.objects.select_for_update().get(id=instance.id)
        if locked.submission_state != SUBMISSION_STATE_PENDING:
            raise ApprovalCreateError(kind="conflict", message=SUBMISSION_IN_PROGRESS_MESSAGE)
        locked.submission_state = SUBMISSION_STATE_SUBMITTING
        timeout_seconds = max(dingtalk_runtime_config().timeout_seconds, 1)
        locked.submission_deadline_at = timezone.now() + timedelta(
            seconds=timeout_seconds + SUBMISSION_DEADLINE_GRACE_SECONDS,
        )
        locked.save(
            update_fields=["submission_state", "submission_deadline_at", "updated_at"],
        )
    instance.submission_state = SUBMISSION_STATE_SUBMITTING
    instance.submission_deadline_at = locked.submission_deadline_at


def _mark_submission_error(
    instance: ApprovalInstance,
    *,
    error: DingTalkApiError,
    ambiguous: bool,
) -> None:
    with transaction.atomic():
        locked = ApprovalInstance.objects.select_for_update().get(id=instance.id)
        locked.submission_state = (
            SUBMISSION_STATE_AMBIGUOUS if ambiguous else SUBMISSION_STATE_FAILED
        )
        locked.status = APPROVAL_STATUS_CREATED if ambiguous else APPROVAL_STATUS_FAILED
        locked.submission_deadline_at = None
        locked.last_error = str(error)
        locked.save(
            update_fields=[
                "submission_state",
                "status",
                "submission_deadline_at",
                "last_error",
                "updated_at",
            ],
        )
    instance.submission_state = locked.submission_state
    instance.status = locked.status
    instance.submission_deadline_at = None
    instance.last_error = locked.last_error


def _submission_result_is_ambiguous(error: DingTalkApiError) -> bool:
    if isinstance(error, DingTalkNotConfiguredError):
        return False
    if isinstance(error, DingTalkApiUnavailableError):
        return True
    return isinstance(error, DingTalkApiRequestError) and error.status_code is None


def _mark_submitted(instance: ApprovalInstance, *, process_instance_id: str) -> bool:
    try:
        with transaction.atomic():
            locked = ApprovalInstance.objects.select_for_update().get(id=instance.id)
            if locked.submission_state != SUBMISSION_STATE_SUBMITTING:
                raise ApprovalCreateError(kind="conflict", message=SUBMISSION_IN_PROGRESS_MESSAGE)
            locked.dingtalk_process_instance_id = process_instance_id
            locked.status = APPROVAL_STATUS_SUBMITTED
            locked.submission_state = SUBMISSION_STATE_SUBMITTED
            locked.submission_deadline_at = None
            locked.last_error = ""
            locked.save(
                update_fields=[
                    "dingtalk_process_instance_id",
                    "status",
                    "submission_state",
                    "submission_deadline_at",
                    "last_error",
                    "updated_at",
                ],
            )
            callback = (
                PendingApprovalCallback.objects.select_for_update()
                .filter(process_instance_id=process_instance_id)
                .first()
            )
            changed = False
            if callback is not None:
                changed, conflict = _apply_callback_locked(locked, callback)
                if conflict is not None:
                    raise conflict
                if changed:
                    deliver_completion(locked)
    except IntegrityError as error:
        message = "钉钉返回了已关联其他审批实例的 process_instance_id。"
        _mark_submission_error(
            instance,
            error=DingTalkApiRequestError(message),
            ambiguous=True,
        )
        raise ApprovalCreateError(kind="conflict", message=message) from error
    instance.dingtalk_process_instance_id = locked.dingtalk_process_instance_id
    instance.status = locked.status
    instance.submission_state = locked.submission_state
    instance.submission_deadline_at = locked.submission_deadline_at
    instance.last_error = locked.last_error
    instance.completed_at = locked.completed_at
    return changed


def recover_stale_submission(instance: ApprovalInstance) -> ApprovalInstance:
    with transaction.atomic():
        locked = ApprovalInstance.objects.select_for_update().get(id=instance.id)
        _mark_stale_submission_ambiguous_locked(locked)
    if locked.submission_state != instance.submission_state:
        instance.submission_state = locked.submission_state
        instance.submission_deadline_at = locked.submission_deadline_at
        instance.last_error = locked.last_error
    return instance


def _mark_stale_submission_ambiguous_locked(instance: ApprovalInstance) -> None:
    if (
        instance.submission_state != SUBMISSION_STATE_SUBMITTING
        or instance.submission_deadline_at is None
        or instance.submission_deadline_at > timezone.now()
    ):
        return
    instance.submission_state = SUBMISSION_STATE_AMBIGUOUS
    instance.submission_deadline_at = None
    instance.last_error = SUBMISSION_AMBIGUOUS_MESSAGE
    instance.save(
        update_fields=[
            "submission_state",
            "submission_deadline_at",
            "last_error",
            "updated_at",
        ],
    )


def _apply_callback_locked(
    instance: ApprovalInstance,
    callback: PendingApprovalCallback,
) -> tuple[bool, ApprovalCallbackConflictError | None]:
    if instance.status == callback.status:
        if callback.state != CALLBACK_STATE_APPLIED:
            callback.state = CALLBACK_STATE_APPLIED
            callback.instance = instance
            callback.applied_at = instance.completed_at or timezone.now()
            callback.last_error = ""
            callback.save(
                update_fields=["state", "instance", "applied_at", "last_error", "updated_at"],
            )
        return False, None
    if instance.status in APPROVAL_TERMINAL_STATUSES:
        callback.state = CALLBACK_STATE_CONFLICT
        callback.instance = instance
        callback.last_error = INSTANCE_STATUS_CONFLICT_MESSAGE
        callback.save(update_fields=["state", "instance", "last_error", "updated_at"])
        return False, ApprovalCallbackConflictError(
            instance_id=str(instance.id),
            status=instance.status,
        )
    instance.status = callback.status
    instance.completed_at = timezone.now()
    instance.save(update_fields=["status", "completed_at", "updated_at"])
    callback.state = CALLBACK_STATE_APPLIED
    callback.instance = instance
    callback.applied_at = instance.completed_at
    callback.last_error = ""
    callback.save(
        update_fields=["state", "instance", "applied_at", "last_error", "updated_at"],
    )
    _record_instance_event(
        instance,
        action=f"approval_instance_{callback.status}",
        actor_id="dingtalk_callback",
    )
    return True, None


def deliver_completion(instance: ApprovalInstance) -> None:
    # 结果经 §5.1 通道推给发起 APP; 未配置 webhook 时保持无关联投递行,
    # delivery_state() 派生为 skipped(APP 侧轮询兜底)。
    with transaction.atomic():
        locked = (
            ApprovalInstance.objects.select_for_update()
            .select_related("app", "template", "originator_user")
            .get(id=instance.id)
        )
        if locked.completion_delivery_id is not None:
            instance.completion_delivery_id = locked.completion_delivery_id
            return
        config = AppWebhookConfig.objects.filter(app=locked.app, enabled=True).first()
        url = config.approval_callback_url if config is not None else ""
        try:
            delivery = enqueue_delivery(
                app=locked.app,
                event_type=WEBHOOK_EVENT_APPROVAL_COMPLETED,
                url=url,
                payload=completion_event_payload(locked),
            )
        except WebhookNotConfiguredError:
            return
        locked.completion_delivery = delivery
        locked.save(update_fields=["completion_delivery", "updated_at"])
        instance.completion_delivery = delivery


def completion_event_payload(instance: ApprovalInstance) -> dict[str, JsonValue]:
    return {
        "instance_id": str(instance.id),
        "template_key": instance.template.key,
        "biz_key": instance.biz_key,
        "status": instance.status,
        "originator_user_id": instance.originator_user.authentik_user_id,
        "completed_at": (
            instance.completed_at.isoformat() if instance.completed_at is not None else None
        ),
    }


def _active_template(app: App, template_key: str) -> ApprovalTemplate:
    # 优先 app 专属模板, 其次平台共用模板。
    template = (
        ApprovalTemplate.objects.filter(app=app, key=template_key, is_active=True).first()
        or ApprovalTemplate.objects.filter(
            app__isnull=True,
            key=template_key,
            is_active=True,
        ).first()
    )
    if template is None:
        raise ApprovalCreateError(kind="template_not_found", message=TEMPLATE_NOT_FOUND_MESSAGE)
    return template


def _selected_active_template(
    app: App,
    template_key: str,
    template: ApprovalTemplate,
) -> ApprovalTemplate:
    if (
        not template.is_active
        or template.key != template_key
        or (template.app_id is not None and template.app_id != app.id)
    ):
        raise ApprovalCreateError(kind="template_not_found", message=TEMPLATE_NOT_FOUND_MESSAGE)
    return template


def _valid_originator(originator_user_id: str) -> UserMirror:
    originator = UserMirror.objects.filter(
        authentik_user_id=originator_user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    # 钉钉 userid 映射只在 EasyAuth(§0.4): 发起审批必须能换算, 否则明确报错。
    if originator is None or not originator.dingtalk_userid:
        raise ApprovalCreateError(kind="originator_invalid", message=ORIGINATOR_INVALID_MESSAGE)
    return originator


def _validated_form(
    template: ApprovalTemplate,
    form: Mapping[str, JsonValue],
) -> tuple[dict[str, JsonValue], tuple[DingTalkFormComponent, ...]]:
    try:
        template.full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as error:
        raise ApprovalCreateError(
            kind="validation_error",
            message=f"{FORM_SCHEMA_INVALID_MESSAGE} {error}",
        ) from error

    schema = cast("dict[str, dict[str, object]]", template.form_schema)
    unknown_fields = set(form) - set(schema)
    if unknown_fields:
        names = "、".join(sorted(unknown_fields))
        raise ApprovalCreateError(
            kind="validation_error",
            message=f"form 包含 form_schema 未声明的字段: {names}。",
        )
    missing_fields = {
        field_name
        for field_name, definition in schema.items()
        if definition.get("required", False) and field_name not in form
    }
    if missing_fields:
        names = "、".join(sorted(missing_fields))
        raise ApprovalCreateError(
            kind="validation_error",
            message=f"form 缺少必填字段: {names}。",
        )

    mapping = cast("dict[str, str]", template.form_mapping)
    normalized: dict[str, JsonValue] = {}
    components: list[DingTalkFormComponent] = []
    for field_name, value in form.items():
        field_type = cast("str", schema[field_name]["type"])
        if not _form_value_matches_type(value, field_type):
            raise ApprovalCreateError(
                kind="validation_error",
                message=f"form 字段 {field_name} 必须是 {field_type} 类型。",
            )
        normalized[field_name] = value
        components.append(
            DingTalkFormComponent(
                name=mapping.get(field_name, field_name),
                value=_dingtalk_form_value(value),
            ),
        )
    return normalized, tuple(components)


def _form_value_matches_type(value: JsonValue, field_type: str) -> bool:
    match field_type:
        case "string":
            return isinstance(value, str)
        case "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        case "number":
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            )
        case "boolean":
            return isinstance(value, bool)
        case _:
            return False


def _dingtalk_form_value(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    raise ApprovalCreateError(kind="validation_error", message=FORM_SCHEMA_INVALID_MESSAGE)


def _payload_hash(*, originator_user_id: str, form: dict[str, JsonValue]) -> str:
    canonical = json.dumps(
        {"originator_user_id": originator_user_id, "form": form},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _record_instance_event(
    instance: ApprovalInstance,
    *,
    action: str,
    actor_id: str,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="app" if actor_id == instance.app.app_key else "system",
            actor_id=actor_id,
            action=action,
            target_type="approval_instance",
            target_id=str(instance.id),
            metadata={
                "app_key": instance.app.app_key,
                "template_key": instance.template.key,
                "biz_key": instance.biz_key,
                "status": instance.status,
                "dingtalk_process_instance_id": instance.dingtalk_process_instance_id,
            },
        ),
    )
