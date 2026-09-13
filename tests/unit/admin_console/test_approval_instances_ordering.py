from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol, cast

import pytest
from django.test import Client

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App
from easyauth.webhooks.models import (
    DELIVERY_STATUS_DELIVERED,
    DELIVERY_STATUS_FAILED,
    WebhookDelivery,
)
from easyauth.workflows.models import (
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_CREATED,
    APPROVAL_STATUS_REJECTED,
    ApprovalInstance,
    ApprovalTemplate,
)
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    install_authentik_authority,
    reset_authentik_authority,
)

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

INSTANCES_URL: Final = "/console/api/v1/operations/approval-instances"


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


@pytest.fixture(autouse=True)
def _console_auth(monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)
    reset_authentik_authority()
    install_authentik_authority(monkeypatch)


def test_approval_instances_order_by_biz_key_originator_and_process_id() -> None:
    client = _admin("ord-inst-fields-admin")
    ada = _instance("ord-inst-a", "alpha", "Ada", "aaa", "PROC-AAA")
    cara = _instance("ord-inst-c", "zeta", "Cara", "zzz", "")
    ben = _instance("ord-inst-b", "mu", "Ben", "mmm", "PROC-MMM")

    assert _biz(client, "biz_key") == [ada.biz_key, ben.biz_key, cara.biz_key]
    assert _biz(client, "-biz_key") == [cara.biz_key, ben.biz_key, ada.biz_key]
    assert _biz(client, "originator") == [ada.biz_key, ben.biz_key, cara.biz_key]
    assert _biz(client, "-originator") == [cara.biz_key, ben.biz_key, ada.biz_key]
    assert _biz(client, "dingtalk_process_instance_id") == [ada.biz_key, ben.biz_key, cara.biz_key]
    assert _biz(client, "-dingtalk_process_instance_id") == [
        ben.biz_key,
        ada.biz_key,
        cara.biz_key,
    ]


def test_approval_instances_order_by_delivery_places_missing_last() -> None:
    client = _admin("ord-inst-delivery-admin")
    delivered = _instance("ord-inst-del-a", "onboard", "Ada", "biz-delivered")
    failed = _instance("ord-inst-del-b", "onboard", "Ben", "biz-failed")
    missing = _instance("ord-inst-del-c", "onboard", "Cara", "biz-missing")
    _attach_delivery(delivered, DELIVERY_STATUS_DELIVERED)
    _attach_delivery(failed, DELIVERY_STATUS_FAILED)

    assert _biz(client, "delivery") == [delivered.biz_key, failed.biz_key, missing.biz_key]
    assert _biz(client, "-delivery") == [failed.biz_key, delivered.biz_key, missing.biz_key]


def test_approval_instances_order_by_status_and_app_key() -> None:
    client = _admin("ord-inst-status-admin")
    created = _instance(
        "ord-inst-st-a",
        "tmpl",
        "Ada",
        "biz-created",
        status=APPROVAL_STATUS_CREATED,
    )
    rejected = _instance(
        "ord-inst-st-z",
        "tmpl",
        "Ben",
        "biz-rejected",
        status=APPROVAL_STATUS_REJECTED,
    )
    approved = _instance(
        "ord-inst-st-m",
        "tmpl",
        "Cara",
        "biz-approved",
        status=APPROVAL_STATUS_APPROVED,
    )

    assert _biz(client, "status") == [approved.biz_key, created.biz_key, rejected.biz_key]
    assert _biz(client, "-status") == [rejected.biz_key, created.biz_key, approved.biz_key]
    assert _biz(client, "app_key") == [created.biz_key, approved.biz_key, rejected.biz_key]
    assert _biz(client, "-app_key") == [rejected.biz_key, approved.biz_key, created.biz_key]


def test_approval_instances_reject_unknown_ordering() -> None:
    client = _admin("ord-inst-unknown-admin")
    response = client.get(INSTANCES_URL, {"ordering": "unknown"})
    _assert_unknown(response, "unknown")


def _instance(  # noqa: PLR0913 - 审批实例夹具按排序字段铺开。
    app_key: str,
    template_key: str,
    originator_name: str,
    biz_key: str,
    process_id: str = "",
    *,
    status: str = APPROVAL_STATUS_CREATED,
) -> ApprovalInstance:
    app = App.objects.create(app_key=app_key, name=app_key)
    template = ApprovalTemplate.objects.create(
        app=app,
        key=template_key,
        name=template_key,
        dingtalk_process_code=f"CODE-{app_key}",
    )
    originator = UserMirror.objects.create(
        authentik_user_id=f"{app_key}-origin",
        name=originator_name,
    )
    return ApprovalInstance.objects.create(
        app=app,
        template=template,
        biz_key=biz_key,
        originator_user=originator,
        payload_hash="0" * 64,
        dingtalk_process_instance_id=process_id,
        status=status,
    )


def _attach_delivery(instance: ApprovalInstance, status: str) -> None:
    delivery = WebhookDelivery.objects.create(
        app=instance.app,
        delivery_id=f"del-{instance.biz_key}",
        event_type="approval.completed",
        target_url="https://example.test/hook",
        status=status,
    )
    instance.completion_delivery = delivery
    instance.save(update_fields=["completion_delivery"])


def _admin(username: str) -> Client:
    return authenticate_console_admin(Client(HTTP_HOST="localhost"), username)


def _biz(client: Client, ordering: str) -> list[str]:
    response = client.get(INSTANCES_URL, {"ordering": ordering, "page_size": "20"})
    assert response.status_code == HTTPStatus.OK, response.content
    payload = cast("dict[str, JsonValue]", response.json())
    data = payload["data"]
    assert isinstance(data, list), payload
    keys: list[str] = []
    for item in data:
        assert isinstance(item, dict), payload
        keys.append(str(item["biz_key"]))
    return keys


def _assert_unknown(response: _JsonResponse, value: str) -> None:
    assert response.status_code == HTTPStatus.BAD_REQUEST
    payload = cast("dict[str, JsonValue]", response.json())
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["details"] == {"field": "ordering", "value": value}
