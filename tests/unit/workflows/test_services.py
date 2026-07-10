from __future__ import annotations

import pytest

from easyauth.accounts.models import USER_STATUS_DEPARTED, UserMirror
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.integrations.dingtalk.api_client import DingTalkApiUnavailableError
from easyauth.workflows.models import (
    APPROVAL_STATUS_FAILED,
    APPROVAL_STATUS_SUBMITTED,
    ApprovalInstance,
    ApprovalTemplate,
)
from easyauth.workflows.services import (
    ApprovalCreateError,
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


def _app_with_template(app_key: str) -> tuple[App, ApprovalTemplate]:
    app = App.objects.create(app_key=app_key, name=app_key)
    template = ApprovalTemplate.objects.create(
        app=app,
        key="expense",
        name="费用审批",
        dingtalk_process_code="PROC-EXPENSE",
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


def test_create_approval_instance_marks_failed_when_dingtalk_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    app, _template = _app_with_template("wf-fail-app")
    _ = _originator("wf-fail-user")
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: _UnavailableDingTalkClient(),
    )

    # When / Then: 钉钉不可用时实例落 failed 并保留错误, 调用方收到明确错误。
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
    assert instance.status == APPROVAL_STATUS_FAILED
    assert instance.last_error != ""


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
