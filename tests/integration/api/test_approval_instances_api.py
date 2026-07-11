from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import TYPE_CHECKING, ClassVar, Final, Protocol

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
    _seq: ClassVar[int] = 0

    def create_process_instance(self, **_kwargs: object) -> str:
        type(self)._seq += 1
        return f"proc-api-{type(self)._seq}"


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
        form_schema={"amount": {"type": "string", "required": False}},
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
    assert first_body["submission_state"] == "submitted"
    assert ApprovalInstance.objects.filter(app=app).count() == 1


def test_app_rejects_same_biz_key_with_different_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, token = _app_with_token("api-approval-conflict")
    _template_and_originator(app)
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: _FakeDingTalkClient(),
    )
    client = Client()
    url = f"/api/v1/apps/{app.app_key}/approval-instances"
    base = {
        "template_key": "expense",
        "originator_user_id": "api-originator",
        "biz_key": "same-key",
    }
    first = client.post(
        url,
        data=dumps({**base, "form": {"amount": "100"}}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    conflict = client.post(
        url,
        data=dumps({**base, "form": {"amount": "200"}}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert first.status_code == HTTPStatus.CREATED
    assert conflict.status_code == HTTPStatus.CONFLICT
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


def test_list_approval_instances_filters_and_scopes_to_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 两个应用各有实例; 列表只暴露本应用, 且支持 status/biz_key 过滤。
    app_a, token_a = _app_with_token("api-list-app-a")
    app_b, token_b = _app_with_token("api-list-app-b")
    _template_and_originator(app_a)
    _ = ApprovalTemplate.objects.create(
        app=app_b,
        key="expense",
        name="费用审批",
        dingtalk_process_code="PROC-B",
        form_schema={},
    )
    monkeypatch.setattr(
        "easyauth.workflows.services.DingTalkApiClient.from_settings",
        lambda: _FakeDingTalkClient(),
    )
    client = Client()
    for biz_key in ("list-1", "list-2"):
        created = client.post(
            f"/api/v1/apps/{app_a.app_key}/approval-instances",
            data=dumps(
                {
                    "template_key": "expense",
                    "originator_user_id": "api-originator",
                    "form": {},
                    "biz_key": biz_key,
                },
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token_a}",
        )
        assert created.status_code == HTTPStatus.CREATED
    other = client.post(
        f"/api/v1/apps/{app_b.app_key}/approval-instances",
        data=dumps(
            {
                "template_key": "expense",
                "originator_user_id": "api-originator",
                "form": {},
                "biz_key": "other-biz",
            },
        ),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token_b}",
    )
    assert other.status_code == HTTPStatus.CREATED

    # When
    listed = client.get(
        f"/api/v1/apps/{app_a.app_key}/approval-instances",
        HTTP_AUTHORIZATION=f"Bearer {token_a}",
    )
    filtered = client.get(
        f"/api/v1/apps/{app_a.app_key}/approval-instances",
        data={"biz_key": "list-1", "status": "submitted", "template_key": "expense"},
        HTTP_AUTHORIZATION=f"Bearer {token_a}",
    )
    mismatched = client.get(
        f"/api/v1/apps/{app_a.app_key}/approval-instances",
        HTTP_AUTHORIZATION=f"Bearer {token_b}",
    )
    unauthenticated = client.get(f"/api/v1/apps/{app_a.app_key}/approval-instances")

    # Then
    body = listed.json()
    assert listed.status_code == HTTPStatus.OK
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 2
    assert body["pagination"]["total_items"] == 2
    biz_keys = {item["biz_key"] for item in body["data"]}
    assert biz_keys == {"list-1", "list-2"}
    assert "other-biz" not in biz_keys
    filtered_body = filtered.json()
    assert filtered.status_code == HTTPStatus.OK
    assert len(filtered_body["data"]) == 1
    assert filtered_body["data"][0]["biz_key"] == "list-1"
    assert mismatched.status_code == HTTPStatus.FORBIDDEN
    assert unauthenticated.status_code == HTTPStatus.UNAUTHORIZED


def test_list_approval_templates_returns_active_app_and_platform_only() -> None:
    # Given: 本应用活跃/停用模板 + 平台模板 + 其他应用模板。
    app, token = _app_with_token("api-templates-app")
    other, _other_token = _app_with_token("api-templates-other")
    _ = ApprovalTemplate.objects.create(
        app=app,
        key="expense",
        name="费用审批",
        dingtalk_process_code="PROC-EXPENSE-SECRET",
        form_schema={"amount": {"type": "string", "required": True}},
        form_mapping={"amount": "金额"},
        is_active=True,
    )
    _ = ApprovalTemplate.objects.create(
        app=app,
        key="inactive",
        name="已停用",
        dingtalk_process_code="PROC-INACTIVE",
        is_active=False,
    )
    _ = ApprovalTemplate.objects.create(
        app=None,
        key="platform-leave",
        name="平台请假",
        dingtalk_process_code="PROC-PLATFORM",
        form_schema={"days": {"type": "integer", "required": True}},
        is_active=True,
    )
    _ = ApprovalTemplate.objects.create(
        app=other,
        key="other-only",
        name="他应用模板",
        dingtalk_process_code="PROC-OTHER",
        is_active=True,
    )
    client = Client()

    # When
    ok = client.get(
        f"/api/v1/apps/{app.app_key}/approval-templates",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    bad = client.get(
        f"/api/v1/apps/{app.app_key}/approval-templates",
        HTTP_AUTHORIZATION="Bearer eat_invalid",
    )
    mismatch = client.get(
        f"/api/v1/apps/{other.app_key}/approval-templates",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    # Then: 只返回本应用 + 平台活跃模板; 不泄露 process_code / form_mapping。
    assert ok.status_code == HTTPStatus.OK
    body = ok.json()
    keys = {item["key"] for item in body["data"]}
    assert keys == {"expense", "platform-leave"}
    for item in body["data"]:
        assert set(item) == {"key", "name", "form_schema", "is_active"}
        assert "dingtalk_process_code" not in item
        assert "form_mapping" not in item
    expense = next(item for item in body["data"] if item["key"] == "expense")
    assert expense["form_schema"] == {"amount": {"type": "string", "required": True}}
    assert bad.status_code == HTTPStatus.UNAUTHORIZED
    assert mismatch.status_code == HTTPStatus.FORBIDDEN
