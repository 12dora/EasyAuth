from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, ClassVar, Final, cast, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.webhooks.models import WebhookDelivery

if TYPE_CHECKING:
    from datetime import date, datetime

    from easyauth.applications.ops_models import JsonValue

APPROVAL_STATUS_CREATED: Final = "created"
APPROVAL_STATUS_SUBMITTED: Final = "submitted"
APPROVAL_STATUS_APPROVED: Final = "approved"
APPROVAL_STATUS_REJECTED: Final = "rejected"
APPROVAL_STATUS_CANCELED: Final = "canceled"
APPROVAL_STATUS_FAILED: Final = "failed"
APPROVAL_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (APPROVAL_STATUS_CREATED, "created"),
    (APPROVAL_STATUS_SUBMITTED, "submitted"),
    (APPROVAL_STATUS_APPROVED, "approved"),
    (APPROVAL_STATUS_REJECTED, "rejected"),
    (APPROVAL_STATUS_CANCELED, "canceled"),
    (APPROVAL_STATUS_FAILED, "failed"),
)
APPROVAL_STATUS_VALUES: Final[tuple[str, ...]] = (
    APPROVAL_STATUS_CREATED,
    APPROVAL_STATUS_SUBMITTED,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
    APPROVAL_STATUS_CANCELED,
    APPROVAL_STATUS_FAILED,
)
# 终态集合: 回调只允许推进到这些状态且不允许回退。
APPROVAL_TERMINAL_STATUSES: Final[tuple[str, ...]] = (
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
    APPROVAL_STATUS_CANCELED,
)

SUBMISSION_STATE_PENDING: Final = "pending"
SUBMISSION_STATE_SUBMITTING: Final = "submitting"
SUBMISSION_STATE_SUBMITTED: Final = "submitted"
SUBMISSION_STATE_AMBIGUOUS: Final = "ambiguous"
SUBMISSION_STATE_FAILED: Final = "failed"
SUBMISSION_STATE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (SUBMISSION_STATE_PENDING, "pending"),
    (SUBMISSION_STATE_SUBMITTING, "submitting"),
    (SUBMISSION_STATE_SUBMITTED, "submitted"),
    (SUBMISSION_STATE_AMBIGUOUS, "ambiguous"),
    (SUBMISSION_STATE_FAILED, "failed"),
)
SUBMISSION_STATE_VALUES: Final[tuple[str, ...]] = tuple(
    value for value, _label in SUBMISSION_STATE_CHOICES
)

CALLBACK_STATE_PENDING: Final = "pending"
CALLBACK_STATE_APPLIED: Final = "applied"
CALLBACK_STATE_CONFLICT: Final = "conflict"
CALLBACK_STATE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (CALLBACK_STATE_PENDING, "pending"),
    (CALLBACK_STATE_APPLIED, "applied"),
    (CALLBACK_STATE_CONFLICT, "conflict"),
)

FORM_FIELD_TYPES: Final[tuple[str, ...]] = ("string", "integer", "number", "boolean")

# 结果投递状态由关联的 WebhookDelivery 行派生; 未配置 webhook 的完成实例
# 视为 skipped, APP 侧以轮询兜底。
DELIVERY_STATE_SKIPPED: Final = "skipped"


class ApprovalTemplate(models.Model):
    # 审批模板只声明业务字段与钉钉表单控件的映射; 流程本身在钉钉后台配置,
    # EasyAuth 不做表单设计器、不做审批流引擎, 只存 process_code 映射。
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int | None]

    app: models.ForeignKey[App | None, App | None] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="approval_templates",
        blank=True,
        null=True,
    )
    key: models.CharField[str, str] = models.CharField(max_length=64)
    name: models.CharField[str, str] = models.CharField(max_length=128)
    dingtalk_process_code: models.CharField[str, str] = models.CharField(max_length=128)
    # 声明 APP 侧提交的业务字段(名称/是否必填等), JSON 配置(§7 决策 3)。
    form_schema: models.JSONField[
        dict[str, JsonValue],
        dict[str, JsonValue],
    ] = models.JSONField(default=dict, blank=True)
    # 业务字段 → 钉钉表单控件名映射: {"业务字段": "钉钉控件名"}。
    form_mapping: models.JSONField[
        dict[str, JsonValue],
        dict[str, JsonValue],
    ] = models.JSONField(default=dict, blank=True)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            # app 为空表示平台共用模板; key 在所属 app(或平台层)内唯一。
            models.UniqueConstraint(
                fields=["app", "key"],
                name="workflows_template_key_unique_per_app",
            ),
            models.UniqueConstraint(
                fields=["key"],
                condition=Q(app__isnull=True),
                name="workflows_template_key_unique_platform",
            ),
        ]
        ordering: ClassVar[list[str]] = ["key"]

    @override
    def __str__(self) -> str:
        scope = self.app.app_key if self.app is not None else "platform"
        return f"{scope}:{self.key}"

    @override
    def clean(self) -> None:
        super().clean()
        if not self.dingtalk_process_code.strip():
            raise ValidationError(
                {"dingtalk_process_code": "Approval template requires a process code."},
            )
        _validate_form_contract(self.form_schema, self.form_mapping)

class ApprovalInstance(models.Model):
    if TYPE_CHECKING:
        app_id: ClassVar[int]
        template_id: ClassVar[int]

    id: models.UUIDField[uuid.UUID, uuid.UUID] = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="approval_instances",
    )
    template: models.ForeignKey[ApprovalTemplate, ApprovalTemplate] = models.ForeignKey(
        ApprovalTemplate,
        on_delete=models.PROTECT,
        related_name="instances",
    )
    # APP 内幂等键: 同 (app, template, biz_key) 重复发起只产生一个实例。
    biz_key: models.CharField[str, str] = models.CharField(max_length=128)
    originator_user: models.ForeignKey[UserMirror, UserMirror] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
        related_name="originated_approval_instances",
    )
    dingtalk_process_instance_id: models.CharField[str, str] = models.CharField(
        max_length=128,
        blank=True,
        db_index=True,
    )
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=APPROVAL_STATUS_CHOICES,
        default=APPROVAL_STATUS_CREATED,
    )
    form_values: models.JSONField[
        dict[str, JsonValue],
        dict[str, JsonValue],
    ] = models.JSONField(default=dict, blank=True)
    payload_hash: models.CharField[str, str] = models.CharField(max_length=64)
    provider_correlation_key: models.UUIDField[uuid.UUID, uuid.UUID] = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
    )
    submission_state: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=SUBMISSION_STATE_CHOICES,
        default=SUBMISSION_STATE_PENDING,
    )
    submission_deadline_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    completion_delivery: models.ForeignKey[
        WebhookDelivery | None,
        WebhookDelivery | None,
    ] = models.ForeignKey(
        WebhookDelivery,
        on_delete=models.SET_NULL,
        related_name="approval_instances",
        blank=True,
        null=True,
    )
    last_error: models.TextField[str, str] = models.TextField(blank=True)
    completed_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["app", "template", "biz_key"],
                name="workflows_instance_biz_key_unique",
            ),
            models.CheckConstraint(
                condition=Q(status__in=APPROVAL_STATUS_VALUES),
                name="workflows_instance_status_supported",
            ),
            models.CheckConstraint(
                condition=Q(submission_state__in=SUBMISSION_STATE_VALUES),
                name="workflows_submission_state_supported",
            ),
            models.UniqueConstraint(
                fields=["dingtalk_process_instance_id"],
                condition=~Q(dingtalk_process_instance_id=""),
                name="workflows_process_instance_id_unique_nonempty",
            ),
        ]
        ordering: ClassVar[list[str]] = ["-created_at"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.template.key}:{self.biz_key}"

    def delivery_state(self) -> str:
        if self.completion_delivery is not None:
            return self.completion_delivery.status
        if self.status in APPROVAL_TERMINAL_STATUSES:
            return DELIVERY_STATE_SKIPPED
        return ""


class PendingApprovalCallback(models.Model):
    if TYPE_CHECKING:
        instance_id: ClassVar[uuid.UUID | None]

    process_instance_id: models.CharField[str, str] = models.CharField(
        max_length=128,
        unique=True,
    )
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=tuple((value, value) for value in APPROVAL_TERMINAL_STATUSES),
    )
    state: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=CALLBACK_STATE_CHOICES,
        default=CALLBACK_STATE_PENDING,
    )
    instance: models.ForeignKey[ApprovalInstance | None, ApprovalInstance | None] = (
        models.ForeignKey(
            ApprovalInstance,
            on_delete=models.PROTECT,
            related_name="callback_events",
            blank=True,
            null=True,
        )
    )
    last_error: models.TextField[str, str] = models.TextField(blank=True)
    received_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    applied_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["received_at"]

    @override
    def __str__(self) -> str:
        return f"{self.process_instance_id}:{self.status}:{self.state}"


def _validate_form_contract(schema_value: object, mapping_value: object) -> None:
    errors: dict[str, list[str]] = {}
    schema_fields, schema_errors = _validate_form_schema(schema_value)
    mapping_errors = _validate_form_mapping(mapping_value, schema_fields=schema_fields)
    if schema_errors:
        errors["form_schema"] = schema_errors
    if mapping_errors:
        errors["form_mapping"] = mapping_errors
    if errors:
        raise ValidationError(errors)


def _validate_form_schema(schema_value: object) -> tuple[set[str], list[str]]:
    schema_fields: set[str] = set()
    if not isinstance(schema_value, dict):
        return schema_fields, ["form_schema 必须是字段名到字段定义的映射。"]
    schema_errors: list[str] = []
    for field_name, definition_value in cast("dict[object, object]", schema_value).items():
        if not isinstance(field_name, str) or not field_name.strip():
            schema_errors.append("form_schema 字段名必须是非空字符串。")
            continue
        schema_fields.add(field_name)
        if not isinstance(definition_value, dict):
            schema_errors.append(f"字段 {field_name} 的定义必须是对象。")
            continue
        definition = cast("dict[object, object]", definition_value)
        if set(definition) - {"type", "required"}:
            schema_errors.append(f"字段 {field_name} 包含未知配置项。")
        if definition.get("type") not in FORM_FIELD_TYPES:
            schema_errors.append(
                f"字段 {field_name} 的 type 必须是 string、integer、number 或 boolean。",
            )
        if not isinstance(definition.get("required", False), bool):
            schema_errors.append(f"字段 {field_name} 的 required 必须是布尔值。")
    return schema_fields, schema_errors


def _validate_form_mapping(mapping_value: object, *, schema_fields: set[str]) -> list[str]:
    if not isinstance(mapping_value, dict):
        return ["form_mapping 必须是字符串到字符串的映射。"]
    mapping_errors: list[str] = []
    for field_name, component_name in cast("dict[object, object]", mapping_value).items():
        if not isinstance(field_name, str) or not field_name.strip():
            mapping_errors.append("form_mapping 字段名必须是非空字符串。")
            continue
        if not isinstance(component_name, str) or not component_name.strip():
            mapping_errors.append(f"字段 {field_name} 的钉钉控件名必须是非空字符串。")
        if field_name not in schema_fields:
            mapping_errors.append(f"form_mapping 字段 {field_name} 未在 form_schema 中声明。")
    return mapping_errors
