from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import TYPE_CHECKING, Final, Protocol

import pytest
from django.test import Client

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.applications.services import StaticTokenService
from easyauth.workflows.models import ApprovalInstance, ApprovalTemplate

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

FORM_VALUE: Final = "1000"


class HttpResponseLike(Protocol):
    status_code: int
    content: bytes

    def json(self) -> dict[str, JsonValue]: ...


class _FakeDingTalkClient:
    def create_process_instance(self, **_kwargs: object) -> str:
        return "proc-api-1"


def _app_with_token(app_key: str) -> tuple[App, str]:
    app = App.objects.create(app_key=app_key, name=app_key)
    issue = StaticTokenService.create_token(app=app, name="integration")
    return app, issue.plaintext_token


def _template_and_originator(app: App) -> None:
    _ = ApprovalTemplate.objects.create(
        app=app,
        key="expense",
        name="费用审批",
        dingtalk_process_code="PROC-EXPENSE",
    )
    _ = UserMirror.objects.create(
        authentik_user_id="api-originator",
        dingtalk_userid="api-originator-dt",
    )


def test_app_creates_approval_instance_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 已配置模板与发起人, 应用持静态 token。
    app, token = _app_with_token("api-approval-app")
    _template_and_originator(app)
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: _FakeDingTalkClient(),
    )
    body = dumps(
        {
            "template_key": "expense",
            "originator_user_id": "api-originator",
            "form": {"amount": FORM_VALUE},
            "biz_key": "order-77",
        },
    )

    # When: 同 biz_key 发起两次。
    client = Client()
    first = client.post(
        f"/api/v1/apps/{app.app_key}/approval-instances",
        data=body,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    second = client.post(
        f"/api/v1/apps/{app.app_key}/approval-instances",
        data=body,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    # Then: 首次 201, 重复 200 且返回同一实例; 只落一行。
    first_body = first.json()
    second_body = second.json()
    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.OK
    assert first_body["instance_id"] == second_body["instance_id"]
    assert first_body["status"] == "submitted"
    assert ApprovalInstance.objects.filter(app=app).count() == 1


def test_app_reads_own_instance_and_cannot_read_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 两个应用各自的凭证, 一笔属于 app_a 的实例。
    app_a, token_a = _app_with_token("api-read-app-a")
    _app_b, token_b = _app_with_token("api-read-app-b")
    _template_and_originator(app_a)
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: _FakeDingTalkClient(),
    )
    client = Client()
    created = client.post(
        f"/api/v1/apps/{app_a.app_key}/approval-instances",
        data=dumps(
            {
                "template_key": "expense",
                "originator_user_id": "api-originator",
                "form": {},
                "biz_key": "order-88",
            },
        ),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_a}",
    )
    instance_id = created.json()["instance_id"]
    assert isinstance(instance_id, str)

    # When
    own = client.get(
        f"/api/v1/apps/{app_a.app_key}/approval-instances/{instance_id}",
        HTTP_AUTHORIZATION=f"Bearer {token_a}",
    )
    cross_app = client.get(
        f"/api/v1/apps/{app_a.app_key}/approval-instances/{instance_id}",
        HTTP_AUTHORIZATION=f"Bearer {token_b}",
    )

    # Then: 本应用可读; 他应用凭证被拒(凭证与 URL app_key 不匹配)。
    assert own.status_code == HTTPStatus.OK
    assert own.json()["status"] == "submitted"
    assert cross_app.status_code == HTTPStatus.FORBIDDEN


def test_create_rejects_unknown_template_and_bad_token() -> None:
    # Given
    app, token = _app_with_token("api-invalid-app")
    _ = UserMirror.objects.create(
        authentik_user_id="api-invalid-originator",
        dingtalk_userid="api-invalid-dt",
    )
    client = Client()

    # When
    unknown_template = client.post(
        f"/api/v1/apps/{app.app_key}/approval-instances",
        data=dumps(
            {
                "template_key": "missing",
                "originator_user_id": "api-invalid-originator",
                "form": {},
                "biz_key": "b1",
            },
        ),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    bad_token = client.post(
        f"/api/v1/apps/{app.app_key}/approval-instances",
        data="{}",
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer eat_invalid",
    )

    # Then
    assert unknown_template.status_code == HTTPStatus.NOT_FOUND
    assert bad_token.status_code == HTTPStatus.UNAUTHORIZED
    assert ApprovalInstance.objects.count() == 0
