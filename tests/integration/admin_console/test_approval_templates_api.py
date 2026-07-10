from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.contrib.auth.models import User
from django.test import Client

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.workflows.models import ApprovalInstance, ApprovalTemplate

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-approval-templates-api"


class _FakeDingTalkClient:
    def __init__(self) -> None:
        self.process_codes: list[str] = []

    def create_process_instance(
        self,
        *,
        process_code: str,
        originator_userid: str,
        dept_id: int = -1,
        form_components: tuple[object, ...],
    ) -> str:
        del originator_userid, dept_id, form_components
        self.process_codes.append(process_code)
        return "process-exact-template"


def test_create_rejects_non_string_form_mapping_value() -> None:
    # Given: 管理员创建审批模板, 映射值误传为数字。
    client = _logged_in_superuser("approval-template-create-admin")

    # When
    response = client.post(
        "/console/api/v1/approval-templates",
        data=dumps(
            {
                "key": "expense",
                "name": "费用审批",
                "dingtalk_process_code": "PROC-EXPENSE",
                "form_mapping": {"amount": 123},
            },
        ),
        content_type="application/json",
    )

    # Then: 明确拒绝无效契约, 不保存模板。
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert not ApprovalTemplate.objects.filter(key="expense").exists()


def test_patch_rejects_non_string_form_mapping_value() -> None:
    # Given: 已有合法审批模板。
    client = _logged_in_superuser("approval-template-patch-admin")
    template = ApprovalTemplate.objects.create(
        key="expense-patch",
        name="费用审批",
        dingtalk_process_code="PROC-EXPENSE",
        form_mapping={"amount": "金额"},
    )

    # When: 更新时误传布尔值。
    response = client.patch(
        f"/console/api/v1/approval-templates/{template.id}",
        data=dumps({"form_mapping": {"amount": True}}),
        content_type="application/json",
    )

    # Then: 原有映射保持不变。
    assert response.status_code == HTTPStatus.BAD_REQUEST
    template.refresh_from_db()
    assert template.form_mapping == {"amount": "金额"}


def test_platform_template_test_uses_exact_template_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 平台模板与 App 专属模板使用相同 key, 但 process code 不同。
    client = _logged_in_superuser("approval-template-test-admin")
    app = App.objects.create(app_key="approval-template-app", name="审批测试应用")
    platform_template = ApprovalTemplate.objects.create(
        key="expense-test",
        name="平台费用审批",
        dingtalk_process_code="PROC-PLATFORM",
    )
    _ = ApprovalTemplate.objects.create(
        app=app,
        key=platform_template.key,
        name="应用费用审批",
        dingtalk_process_code="PROC-APP",
    )
    _ = UserMirror.objects.create(
        authentik_user_id="approval-template-originator",
        dingtalk_userid="approval-template-originator-dt",
    )
    fake = _FakeDingTalkClient()
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: fake,
    )

    # When: 按平台模板的精确 ID 发起测试。
    response = client.post(
        f"/console/api/v1/approval-templates/{platform_template.id}/test",
        data=dumps(
            {
                "app_key": app.app_key,
                "originator_user_id": "approval-template-originator",
                "form": {},
            },
        ),
        content_type="application/json",
    )

    # Then: 不被同 key 的 App 专属模板抢占。
    assert response.status_code == HTTPStatus.OK
    instance = ApprovalInstance.objects.get()
    assert instance.template == platform_template
    assert fake.process_codes == ["PROC-PLATFORM"]


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client
