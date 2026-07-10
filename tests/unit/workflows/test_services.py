from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from easyauth.accounts.models import USER_STATUS_DEPARTED, UserMirror
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiRequestError,
    DingTalkApiUnavailableError,
)
from easyauth.outbox.models import OutboxEvent
from easyauth.webhooks.models import AppWebhookConfig, WebhookDelivery
from easyauth.workflows.models import (
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_FAILED,
    APPROVAL_STATUS_SUBMITTED,
    CALLBACK_STATE_APPLIED,
    CALLBACK_STATE_PENDING,
    SUBMISSION_STATE_AMBIGUOUS,
    SUBMISSION_STATE_FAILED,
    ApprovalInstance,
    ApprovalTemplate,
    PendingApprovalCallback,
)
from easyauth.workflows.services import (
    ApprovalCreateError,
    ApprovalInstanceNotFoundError,
    apply_instance_callback,
    create_approval_instance,
)

pytestmark = pytest.mark.django_db


class _FakeDingTalkClient:
    created: list[dict[str, object]]

    def __init__(self) -> None:
        self.created = []

    def create_process_instance(
        self,
        *,
        process_code: str,
        originator_userid: str,
        dept_id: int = -1,
        form_components: tuple[object, ...],
    ) -> str:
        self.created.append(
            {
                "process_code": process_code,
                "originator_userid": originator_userid,
                "dept_id": dept_id,
                "form_components": form_components,
            },
        )
        return f"proc-{len(self.created)}"


class _UnavailableDingTalkClient:
    def create_process_instance(self, **_kwargs: object) -> str:
        message = "钉钉 API 暂不可用。"
        raise DingTalkApiUnavailableError(message)


class _RejectedDingTalkClient:
    def create_process_instance(self, **_kwargs: object) -> str:
        message = "钉钉拒绝创建审批。"
        raise DingTalkApiRequestError(message, status_code=400)


def _app_with_template(app_key: str) -> tuple[App, ApprovalTemplate]:
    app = App.objects.create(app_key=app_key, name=app_key)
    template = ApprovalTemplate.objects.create(
        app=app,
        key="expense",
        name="费用审批",
        dingtalk_process_code="PROC-EXPENSE",
        form_schema={
            "amount": {"type": "string", "required": False},
            "备注": {"type": "string", "required": False},
        },
        form_mapping={"amount": "金额"},
    )
    return app, template


def _originator(user_id: str) -> UserMirror:
    return UserMirror.objects.create(
        authentik_user_id=user_id,
        dingtalk_userid=f"{user_id}-dt",
    )


def test_create_approval_instance_submits_with_mapped_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    app, _template = _app_with_template("wf-create-app")
    _ = _originator("wf-create-user")
    fake = _FakeDingTalkClient()
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: fake,
    )

    # When
    instance, created = create_approval_instance(
        app=app,
        template_key="expense",
        originator_user_id="wf-create-user",
        form={"amount": "1000", "备注": "差旅"},
        biz_key="order-1",
        actor_id=app.app_key,
    )

    # Then: 表单按 form_mapping 换名, 未映射字段按原名透传; 实例进入 submitted。
    assert created is True
    assert instance.status == APPROVAL_STATUS_SUBMITTED
    assert instance.dingtalk_process_instance_id == "proc-1"
    call = fake.created[0]
    assert call["process_code"] == "PROC-EXPENSE"
    assert call["originator_userid"] == "wf-create-user-dt"
    component_names = {c.name for c in call["form_components"]}  # type: ignore[union-attr]
    assert component_names == {"金额", "备注"}
    assert AuditLog.objects.filter(event_type="approval_instance_submitted").exists()


def test_create_approval_instance_is_idempotent_per_biz_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 同 biz_key 已发起过一笔。
    app, _template = _app_with_template("wf-idem-app")
    _ = _originator("wf-idem-user")
    fake = _FakeDingTalkClient()
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: fake,
    )
    first, _ = create_approval_instance(
        app=app,
        template_key="expense",
        originator_user_id="wf-idem-user",
        form={},
        biz_key="order-dup",
        actor_id=app.app_key,
    )

    # When: 重复发起。
    second, created = create_approval_instance(
        app=app,
        template_key="expense",
        originator_user_id="wf-idem-user",
        form={},
        biz_key="order-dup",
        actor_id=app.app_key,
    )

    # Then: 只有一个实例, 钉钉只被调用一次。
    assert created is False
    assert second.id == first.id
    assert len(fake.created) == 1
    assert ApprovalInstance.objects.filter(app=app).count() == 1


def test_create_approval_instance_marks_ambiguous_when_dingtalk_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    app, _template = _app_with_template("wf-fail-app")
    _ = _originator("wf-fail-user")
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: _UnavailableDingTalkClient(),
    )

    # When / Then: 网络失败无法判断远端是否创建, 必须落 ambiguous 并禁止盲目重试。
    with pytest.raises(ApprovalCreateError) as exc_info:
        _ = create_approval_instance(
            app=app,
            template_key="expense",
            originator_user_id="wf-fail-user",
            form={},
            biz_key="order-fail",
            actor_id=app.app_key,
        )
    instance = ApprovalInstance.objects.get(app=app, biz_key="order-fail")
    assert exc_info.value.kind == "dependency_unavailable"
    assert instance.status != APPROVAL_STATUS_FAILED
    assert instance.submission_state == SUBMISSION_STATE_AMBIGUOUS
    assert instance.last_error != ""


def test_failed_submission_requires_explicit_locked_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _template = _app_with_template("wf-explicit-retry")
    _ = _originator("wf-explicit-retry-user")
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: _RejectedDingTalkClient(),
    )
    with pytest.raises(ApprovalCreateError):
        _ = create_approval_instance(
            app=app,
            template_key="expense",
            originator_user_id="wf-explicit-retry-user",
            form={},
            biz_key="retry-1",
            actor_id=app.app_key,
        )
    failed = ApprovalInstance.objects.get(app=app)
    assert failed.submission_state == SUBMISSION_STATE_FAILED

    with pytest.raises(ApprovalCreateError) as retry_required:
        _ = create_approval_instance(
            app=app,
            template_key="expense",
            originator_user_id="wf-explicit-retry-user",
            form={},
            biz_key="retry-1",
            actor_id=app.app_key,
        )
    assert retry_required.value.kind == "conflict"

    fake = _FakeDingTalkClient()
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: fake,
    )
    retried, created = create_approval_instance(
        app=app,
        template_key="expense",
        originator_user_id="wf-explicit-retry-user",
        form={},
        biz_key="retry-1",
        actor_id=app.app_key,
        retry_failed=True,
    )
    assert created is False
    assert retried.status == APPROVAL_STATUS_SUBMITTED
    assert len(fake.created) == 1


def test_idempotency_key_rejects_different_originator_or_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _template = _app_with_template("wf-payload-hash")
    _ = _originator("wf-payload-user-a")
    _ = _originator("wf-payload-user-b")
    fake = _FakeDingTalkClient()
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: fake,
    )
    _ = create_approval_instance(
        app=app,
        template_key="expense",
        originator_user_id="wf-payload-user-a",
        form={"amount": "100"},
        biz_key="same-key",
        actor_id=app.app_key,
    )

    for originator_user_id, form in (
        ("wf-payload-user-b", {"amount": "100"}),
        ("wf-payload-user-a", {"amount": "200"}),
    ):
        with pytest.raises(ApprovalCreateError) as exc_info:
            _ = create_approval_instance(
                app=app,
                template_key="expense",
                originator_user_id=originator_user_id,
                form=form,
                biz_key="same-key",
                actor_id=app.app_key,
            )
        assert exc_info.value.kind == "conflict"
    assert len(fake.created) == 1


def test_form_schema_rejects_missing_wrong_type_and_unknown_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, template = _app_with_template("wf-form-schema")
    template.form_schema = {
        "amount": {"type": "integer", "required": True},
        "urgent": {"type": "boolean", "required": False},
    }
    template.save(update_fields=["form_schema", "updated_at"])
    _ = _originator("wf-form-schema-user")
    fake = _FakeDingTalkClient()
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: fake,
    )
    invalid_forms = ({}, {"amount": "100"}, {"amount": 100, "unknown": True})
    for index, form in enumerate(invalid_forms):
        with pytest.raises(ApprovalCreateError) as exc_info:
            _ = create_approval_instance(
                app=app,
                template_key="expense",
                originator_user_id="wf-form-schema-user",
                form=form,
                biz_key=f"invalid-{index}",
                actor_id=app.app_key,
            )
        assert exc_info.value.kind == "validation_error"
    assert fake.created == []


def test_early_callback_is_persisted_and_applied_after_process_id_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _template = _app_with_template("wf-early-callback")
    _ = _originator("wf-early-callback-user")
    with pytest.raises(ApprovalInstanceNotFoundError):
        _ = apply_instance_callback(process_instance_id="proc-early", status="approved")
    pending = PendingApprovalCallback.objects.get(process_instance_id="proc-early")
    assert pending.state == CALLBACK_STATE_PENDING

    class _EarlyCallbackClient:
        def create_process_instance(self, **_kwargs: object) -> str:
            return "proc-early"

    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: _EarlyCallbackClient(),
    )
    instance, _created = create_approval_instance(
        app=app,
        template_key="expense",
        originator_user_id="wf-early-callback-user",
        form={},
        biz_key="early-1",
        actor_id=app.app_key,
    )
    pending.refresh_from_db()
    assert instance.status == APPROVAL_STATUS_APPROVED
    assert pending.state == CALLBACK_STATE_APPLIED
    assert pending.instance == instance


def test_completion_and_unique_delivery_event_are_repaired_idempotently() -> None:
    app, template = _app_with_template("wf-completion-outbox")
    originator = _originator("wf-completion-user")
    _ = AppWebhookConfig.objects.create(
        app=app,
        secret="whsec_test",  # noqa: S106 - 测试专用 Webhook 密钥。
        approval_callback_url="https://app.example.com/hook",
    )
    instance = ApprovalInstance.objects.create(
        app=app,
        template=template,
        biz_key="completion-1",
        originator_user=originator,
        dingtalk_process_instance_id="proc-completion-1",
        status=APPROVAL_STATUS_SUBMITTED,
        submission_state="submitted",
        payload_hash="1" * 64,
    )

    _ = apply_instance_callback(process_instance_id="proc-completion-1", status="approved")
    _ = apply_instance_callback(process_instance_id="proc-completion-1", status="approved")

    instance.refresh_from_db()
    assert instance.completion_delivery_id is not None
    delivery = WebhookDelivery.objects.get(id=instance.completion_delivery_id)
    assert WebhookDelivery.objects.filter(app=app).count() == 1
    assert OutboxEvent.objects.filter(
        event_key=f"webhook-delivery:{delivery.delivery_id}:{delivery.generation}",
    ).count() == 1


def test_stale_submitting_command_recovers_to_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _template = _app_with_template("wf-stale-submission")
    _ = _originator("wf-stale-submission-user")
    fake = _FakeDingTalkClient()
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: fake,
    )
    instance, _created = create_approval_instance(
        app=app,
        template_key="expense",
        originator_user_id="wf-stale-submission-user",
        form={},
        biz_key="stale-1",
        actor_id=app.app_key,
    )
    _ = ApprovalInstance.objects.filter(id=instance.id).update(
        dingtalk_process_instance_id="",
        status="created",
        submission_state="submitting",
        submission_deadline_at=timezone.now() - timedelta(seconds=1),
    )

    with pytest.raises(ApprovalCreateError) as exc_info:
        _ = create_approval_instance(
            app=app,
            template_key="expense",
            originator_user_id="wf-stale-submission-user",
            form={},
            biz_key="stale-1",
            actor_id=app.app_key,
        )
    instance.refresh_from_db()
    assert exc_info.value.kind == "conflict"
    assert instance.submission_state == SUBMISSION_STATE_AMBIGUOUS


def test_nonempty_process_instance_id_is_unique() -> None:
    app, template = _app_with_template("wf-process-id-unique")
    originator = _originator("wf-process-id-unique-user")
    _ = ApprovalInstance.objects.create(
        app=app,
        template=template,
        biz_key="unique-1",
        originator_user=originator,
        dingtalk_process_instance_id="proc-unique",
        status=APPROVAL_STATUS_SUBMITTED,
        submission_state="submitted",
        payload_hash="1" * 64,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        _ = ApprovalInstance.objects.create(
            app=app,
            template=template,
            biz_key="unique-2",
            originator_user=originator,
            dingtalk_process_instance_id="proc-unique",
            status=APPROVAL_STATUS_SUBMITTED,
            submission_state="submitted",
            payload_hash="2" * 64,
        )


def test_create_approval_instance_validates_template_and_originator() -> None:
    # Given
    app, _template = _app_with_template("wf-validate-app")
    _ = UserMirror.objects.create(authentik_user_id="wf-no-dingtalk")
    _ = UserMirror.objects.create(
        authentik_user_id="wf-departed",
        dingtalk_userid="wf-departed-dt",
        status=USER_STATUS_DEPARTED,
    )

    # When / Then: 模板不存在、缺钉钉绑定、离职发起人都被明确拒绝。
    with pytest.raises(ApprovalCreateError) as missing_template:
        _ = create_approval_instance(
            app=app,
            template_key="missing",
            originator_user_id="wf-no-dingtalk",
            form={},
            biz_key="b1",
            actor_id=app.app_key,
        )
    with pytest.raises(ApprovalCreateError) as no_binding:
        _ = create_approval_instance(
            app=app,
            template_key="expense",
            originator_user_id="wf-no-dingtalk",
            form={},
            biz_key="b2",
            actor_id=app.app_key,
        )
    with pytest.raises(ApprovalCreateError) as departed:
        _ = create_approval_instance(
            app=app,
            template_key="expense",
            originator_user_id="wf-departed",
            form={},
            biz_key="b3",
            actor_id=app.app_key,
        )
    assert missing_template.value.kind == "template_not_found"
    assert no_binding.value.kind == "originator_invalid"
    assert departed.value.kind == "originator_invalid"
    assert ApprovalInstance.objects.count() == 0


def test_platform_template_is_shared_across_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: 平台共用模板(app 为空)。
    app = App.objects.create(app_key="wf-platform-app", name="Platform App")
    _ = ApprovalTemplate.objects.create(
        app=None,
        key="generic",
        name="通用审批",
        dingtalk_process_code="PROC-GENERIC",
    )
    _ = _originator("wf-platform-user")
    fake = _FakeDingTalkClient()
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: fake,
    )

    # When
    instance, created = create_approval_instance(
        app=app,
        template_key="generic",
        originator_user_id="wf-platform-user",
        form={},
        biz_key="p1",
        actor_id=app.app_key,
    )

    # Then
    assert created is True
    assert instance.template.app is None
    assert instance.app.app_key == "wf-platform-app"


def test_selected_platform_template_is_not_replaced_by_app_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 同 key 同时存在平台模板和 APP 专属模板。
    app = App.objects.create(app_key="wf-selected-platform", name="Selected Platform")
    platform_template = ApprovalTemplate.objects.create(
        app=None,
        key="same-key",
        name="平台模板",
        dingtalk_process_code="PROC-PLATFORM",
    )
    _ = ApprovalTemplate.objects.create(
        app=app,
        key="same-key",
        name="APP 模板",
        dingtalk_process_code="PROC-APP",
    )
    _ = _originator("wf-selected-platform-user")
    fake = _FakeDingTalkClient()
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: fake,
    )

    # When: 控制台明确指定平台模板发起测试。
    instance, created = create_approval_instance(
        app=app,
        template_key=platform_template.key,
        originator_user_id="wf-selected-platform-user",
        form={},
        biz_key="selected-platform",
        actor_id="console:test-admin",
        selected_template=platform_template,
    )

    # Then: 使用精确指定的平台模板, 不按 key 重新解析为 APP 模板。
    assert created is True
    assert instance.template_id == platform_template.id
    assert fake.created[0]["process_code"] == "PROC-PLATFORM"


def test_create_approval_instance_rejects_non_string_form_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 数据库中存在旧的非法映射值。
    app, template = _app_with_template("wf-invalid-mapping")
    template.form_mapping = {"amount": 1}
    template.save(update_fields=["form_mapping", "updated_at"])
    _ = _originator("wf-invalid-mapping-user")
    fake = _FakeDingTalkClient()
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: fake,
    )

    # When / Then: 运行时快速失败, 不静默退回原字段名。
    with pytest.raises(ApprovalCreateError) as exc_info:
        _ = create_approval_instance(
            app=app,
            template_key=template.key,
            originator_user_id="wf-invalid-mapping-user",
            form={"amount": "100"},
            biz_key="invalid-mapping",
            actor_id=app.app_key,
        )
    assert exc_info.value.kind == "validation_error"
    assert fake.created == []
    assert ApprovalInstance.objects.filter(app=app).count() == 0
