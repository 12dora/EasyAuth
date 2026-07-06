from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, override

from django.db import IntegrityError, transaction
from django.utils import timezone

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiClient,
    DingTalkApiError,
    DingTalkFormComponent,
)
from easyauth.webhooks.delivery import WebhookNotConfiguredError, enqueue_delivery
from easyauth.webhooks.models import (
    WEBHOOK_EVENT_APPROVAL_COMPLETED,
    AppWebhookConfig,
)
from easyauth.workflows.models import (
    APPROVAL_STATUS_FAILED,
    APPROVAL_STATUS_SUBMITTED,
    APPROVAL_TERMINAL_STATUSES,
    ApprovalInstance,
    ApprovalTemplate,
)

if TYPE_CHECKING:
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
    form: dict[str, str],
    biz_key: str,
    actor_id: str,
) -> tuple[ApprovalInstance, bool]:
    """发起一笔钉钉审批; 同 biz_key 幂等返回既有实例。返回 (instance, created)。"""
    template = _active_template(app, template_key)
    originator = _valid_originator(originator_user_id)
    form_components = _mapped_form_components(template, form)

    existing = ApprovalInstance.objects.filter(
        app=app,
        template=template,
        biz_key=biz_key,
    ).first()
    if existing is not None:
        return existing, False

    # 先调钉钉再落库会在网络抖动时丢实例号; 先落 created 行、拿到实例号后再翻 submitted,
    # 失败翻 failed 并保留 last_error, 同 biz_key 的重试可走人工/重发路径。
    try:
        with transaction.atomic():
            instance = ApprovalInstance.objects.create(
                app=app,
                template=template,
                biz_key=biz_key,
                originator_user=originator,
                form_values=dict(form),
            )
    except IntegrityError:
        # 并发同 biz_key 双写: 唯一约束落败方读回胜出行。
        winner = ApprovalInstance.objects.filter(
            app=app,
            template=template,
            biz_key=biz_key,
        ).first()
        if winner is None:
            raise
        return winner, False

    try:
        process_instance_id = DingTalkApiClient.from_settings().create_process_instance(
            process_code=template.dingtalk_process_code,
            originator_userid=originator.dingtalk_userid,
            form_components=form_components,
        )
    except DingTalkApiError as error:
        instance.status = APPROVAL_STATUS_FAILED
        instance.last_error = str(error)
        instance.save(update_fields=["status", "last_error", "updated_at"])
        _record_instance_event(
            instance,
            action="approval_instance_create_failed",
            actor_id=actor_id,
        )
        raise ApprovalCreateError(kind="dependency_unavailable", message=str(error)) from error

    instance.dingtalk_process_instance_id = process_instance_id
    instance.status = APPROVAL_STATUS_SUBMITTED
    instance.save(update_fields=["dingtalk_process_instance_id", "status", "updated_at"])
    _record_instance_event(instance, action="approval_instance_submitted", actor_id=actor_id)
    return instance, True


def apply_instance_callback(
    *,
    process_instance_id: str,
    status: str,
) -> ApprovalInstance:
    """钉钉回调推进审批实例状态; 幂等, 终态冲突显式报错。"""
    with transaction.atomic():
        instance = (
            ApprovalInstance.objects.select_for_update()
            .select_related("app", "template", "originator_user")
            .filter(dingtalk_process_instance_id=process_instance_id)
            .first()
        )
        if instance is None:
            raise ApprovalInstanceNotFoundError
        if instance.status == status:
            return instance
        if instance.status in APPROVAL_TERMINAL_STATUSES:
            raise ApprovalCallbackConflictError(
                instance_id=str(instance.id),
                status=instance.status,
            )
        instance.status = status
        instance.completed_at = timezone.now()
        instance.save(update_fields=["status", "completed_at", "updated_at"])
        _record_instance_event(
            instance,
            action=f"approval_instance_{status}",
            actor_id="dingtalk_callback",
        )
    deliver_completion(instance)
    return instance


def deliver_completion(instance: ApprovalInstance) -> None:
    # 结果经 §5.1 通道推给发起 APP; 未配置 webhook 时保持无关联投递行,
    # delivery_state() 派生为 skipped(APP 侧轮询兜底)。
    config = AppWebhookConfig.objects.filter(app=instance.app, enabled=True).first()
    url = config.approval_callback_url if config is not None else ""
    try:
        delivery = enqueue_delivery(
            app=instance.app,
            event_type=WEBHOOK_EVENT_APPROVAL_COMPLETED,
            url=url,
            payload=completion_event_payload(instance),
        )
    except WebhookNotConfiguredError:
        return
    instance.completion_delivery = delivery
    instance.save(update_fields=["completion_delivery", "updated_at"])


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


def _valid_originator(originator_user_id: str) -> UserMirror:
    originator = UserMirror.objects.filter(
        authentik_user_id=originator_user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    # 钉钉 userid 映射只在 EasyAuth(§0.4): 发起审批必须能换算, 否则明确报错。
    if originator is None or not originator.dingtalk_userid:
        raise ApprovalCreateError(kind="originator_invalid", message=ORIGINATOR_INVALID_MESSAGE)
    return originator


def _mapped_form_components(
    template: ApprovalTemplate,
    form: dict[str, str],
) -> tuple[DingTalkFormComponent, ...]:
    components: list[DingTalkFormComponent] = []
    for field_name, value in form.items():
        mapped = template.form_mapping.get(field_name)
        component_name = mapped if isinstance(mapped, str) and mapped else field_name
        components.append(DingTalkFormComponent(name=component_name, value=value))
    return tuple(components)


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
