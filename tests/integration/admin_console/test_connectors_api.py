from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final, cast

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.accounts.auth import AUTHENTIK_GROUPS_SESSION_KEY, AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppMembership, AuthorizationGroup
from easyauth.connectors.models import ConnectorInstance, ConnectorMapping, ConnectorSyncRun
from tests.unit.connectors.fakes import FakeConnector

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

FAKE_CONNECTOR_PATH: Final = "tests.unit.connectors.fakes.FakeConnector"
OTHER_FAKE_CONNECTOR_PATH: Final = (
    "tests.integration.admin_console.test_connectors_api.OtherFakeConnector"
)


class OtherFakeConnector(FakeConnector):
    key: ClassVar[str] = "other-fake"
    display_name: ClassVar[str] = "Other Fake Connector"


@pytest.fixture(autouse=True)
def register_fake_connector(settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONNECTORS = (FAKE_CONNECTOR_PATH,)
    FakeConnector.reset()


def _logged_in_superuser(username: str) -> Client:
    _ = UserMirror.objects.get_or_create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = username
    session[AUTHENTIK_GROUPS_SESSION_KEY] = ["EasyAuth Admins"]
    session.save()
    return client


def _logged_in_owner(username: str, app: App) -> Client:
    _ = UserMirror.objects.get_or_create(authentik_user_id=username)
    _ = AppMembership.objects.create(app=app, user_id=username, role="owner")
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = username
    session.save()
    return client


def _connectors_url(app_key: str) -> str:
    return f"/console/api/v1/apps/{app_key}/connectors"


def test_create_list_and_redact_secret() -> None:
    # Given
    app = App.objects.create(app_key="conn-api", name="X")
    client = _logged_in_superuser("conn-api-admin")

    # When: 创建实例(带密文字段)。
    created = client.post(
        _connectors_url("conn-api"),
        data={
            "connector_key": "fake",
            "enabled": True,
            "config": {"endpoint": "https://fake.example.com", "token": "s3cret"},
        },
        content_type="application/json",
    )

    # Then
    assert created.status_code == HTTPStatus.CREATED
    body = created.content.decode()
    assert "s3cret" not in body

    listed = client.get(_connectors_url("conn-api"))
    assert listed.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", listed.json())
    types = payload["connector_types"]
    assert isinstance(types, list)
    assert any(
        isinstance(item, dict) and item.get("key") == "fake" and "config_schema" in item
        for item in types
    )
    data = payload["data"]
    assert isinstance(data, list)
    instance_item = cast("dict[str, JsonValue]", data[0])
    config = cast("dict[str, JsonValue]", instance_item["config"])
    assert config["token"] == ""
    assert instance_item["configured_secrets"] == ["token"]
    # 密文静态加密落库。
    instance = ConnectorInstance.objects.get(app=app)
    assert instance.config["token"] == "s3cret"  # noqa: S105 - 测试用假密钥.


def test_list_returns_all_connector_instances(settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONNECTORS = (FAKE_CONNECTOR_PATH, OTHER_FAKE_CONNECTOR_PATH)
    app = App.objects.create(app_key="conn-multiple", name="X")
    first = ConnectorInstance.objects.create(app=app, connector_key="fake")
    second = ConnectorInstance.objects.create(app=app, connector_key="other-fake")
    client = _logged_in_superuser("conn-multiple-admin")

    response = client.get(_connectors_url("conn-multiple"))

    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", response.json())
    data = payload["data"]
    assert isinstance(data, list)
    assert [item["id"] for item in data if isinstance(item, dict)] == [first.id, second.id]


def test_update_keeps_secret_when_blank() -> None:
    # Given: 已配置密文的实例。
    app = App.objects.create(app_key="conn-keep", name="X")
    client = _logged_in_superuser("conn-keep-admin")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake")
    instance.set_config({"endpoint": "https://old.example.com", "token": "keep-me"})
    instance.save()

    # When: 表单回传空密文(读接口从不回显)。
    response = client.put(
        f"{_connectors_url('conn-keep')}/{instance.id}",
        data={
            "enabled": True,
            "config": {"endpoint": "https://new.example.com", "token": ""},
        },
        content_type="application/json",
    )

    # Then: 密文保持, 其余字段更新。
    assert response.status_code == HTTPStatus.OK
    instance.refresh_from_db()
    assert instance.enabled is True
    assert instance.config == {"endpoint": "https://new.example.com", "token": "keep-me"}


def test_config_validation_rejects_missing_required_field() -> None:
    app = App.objects.create(app_key="conn-invalid", name="X")
    _ = app
    client = _logged_in_superuser("conn-invalid-admin")

    response = client.post(
        _connectors_url("conn-invalid"),
        data={"connector_key": "fake", "config": {"token": "t"}},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "endpoint" in response.content.decode()


def test_owner_can_read_status_but_not_write() -> None:
    # Given: 应用负责人(非 superuser)。
    app = App.objects.create(app_key="conn-owner", name="X")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    client = _logged_in_owner("conn-owner-u1", app)

    # Then: 可读状态。
    listed = client.get(_connectors_url("conn-owner"))
    assert listed.status_code == HTTPStatus.OK

    # 不可改配置/映射/测试。
    put_response = client.put(
        f"{_connectors_url('conn-owner')}/{instance.id}",
        data={"enabled": False},
        content_type="application/json",
    )
    assert put_response.status_code == HTTPStatus.FORBIDDEN
    mappings_response = client.put(
        f"{_connectors_url('conn-owner')}/{instance.id}/mappings",
        data={"mappings": []},
        content_type="application/json",
    )
    assert mappings_response.status_code == HTTPStatus.FORBIDDEN
    test_response = client.post(
        f"{_connectors_url('conn-owner')}/test",
        data={"connector_key": "fake", "config": {"endpoint": "https://x"}},
        content_type="application/json",
    )
    assert test_response.status_code == HTTPStatus.FORBIDDEN


def test_non_member_cannot_read() -> None:
    _ = App.objects.create(app_key="conn-stranger", name="X")
    _ = UserMirror.objects.create(authentik_user_id="conn-stranger-u1")
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = "conn-stranger-u1"
    session.save()

    response = client.get(_connectors_url("conn-stranger"))

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_mappings_round_trip() -> None:
    # Given
    app = App.objects.create(app_key="conn-map", name="X")
    group = AuthorizationGroup.objects.create(app=app, key="vpn-users", kind="bundle", name="VPN")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake")
    client = _logged_in_superuser("conn-map-admin")
    url = f"{_connectors_url('conn-map')}/{instance.id}/mappings"
    initial_response = client.get(url)
    initial_revision = cast("dict[str, JsonValue]", initial_response.json())["revision"]
    assert isinstance(initial_revision, str)

    # When: 整表写入。
    put_response = client.put(
        url,
        data={
            "revision": initial_revision,
            "mappings": [
                {
                    "authorization_group_key": "vpn-users",
                    "external_ref": "netbird-vpn",
                    "auto_create": True,
                },
            ],
        },
        content_type="application/json",
    )

    # Then
    assert put_response.status_code == HTTPStatus.OK
    mapping = ConnectorMapping.objects.get(instance=instance)
    assert mapping.authorization_group == group
    assert mapping.external_ref == "netbird-vpn"
    assert mapping.auto_create is True
    put_payload = cast("dict[str, JsonValue]", put_response.json())
    updated_revision = put_payload["revision"]
    assert isinstance(updated_revision, str)
    assert updated_revision != initial_revision

    get_response = client.get(url)
    payload = cast("dict[str, JsonValue]", get_response.json())
    assert payload["data"] == [
        {
            "authorization_group_key": "vpn-users",
            "authorization_group_name": "VPN",
            "external_ref": "netbird-vpn",
            "auto_create": True,
        },
    ]

    # 未知授权组整单拒绝。
    bad_response = client.put(
        url,
        data={
            "revision": updated_revision,
            "mappings": [
                {"authorization_group_key": "ghost", "external_ref": "x", "auto_create": False},
            ],
        },
        content_type="application/json",
    )
    assert bad_response.status_code == HTTPStatus.BAD_REQUEST

    # 旧快照不能覆盖之后的映射, 防止 GET 失败或并发编辑演变为整表清空。
    stale_response = client.put(
        url,
        data={"revision": initial_revision, "mappings": []},
        content_type="application/json",
    )
    assert stale_response.status_code == HTTPStatus.CONFLICT
    assert ConnectorMapping.objects.filter(instance=instance).count() == 1


def test_mappings_replace_requires_authoritative_revision() -> None:
    app = App.objects.create(app_key="conn-map-revision", name="X")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake")
    client = _logged_in_superuser("conn-map-revision-admin")

    response = client.put(
        f"{_connectors_url('conn-map-revision')}/{instance.id}/mappings",
        data={"mappings": []},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_test_endpoint_uses_candidate_config() -> None:
    # Given
    _ = App.objects.create(app_key="conn-test", name="X")
    client = _logged_in_superuser("conn-test-admin")

    # When
    response = client.post(
        f"{_connectors_url('conn-test')}/test",
        data={"connector_key": "fake", "config": {"endpoint": "https://probe"}},
        content_type="application/json",
    )

    # Then: 不落库。
    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", response.json())
    assert payload == {"ok": True, "message": "fake probe"}
    assert ConnectorInstance.objects.count() == 0


def test_manual_reconcile_requires_enabled_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: send_task 不受 eager 模式约束, 拦截入队并断言参数。
    from easyauth.admin_console import connectors_api as api_module  # noqa: PLC0415

    sent: list[tuple[str, tuple[object, ...]]] = []

    class _Recorder:
        @staticmethod
        def send_task(name: str, args: list[object]) -> object:
            sent.append((name, tuple(args)))
            return object()

    monkeypatch.setattr(api_module, "current_app", _Recorder())
    app = App.objects.create(app_key="conn-manual", name="X")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=False)
    client = _logged_in_superuser("conn-manual-admin")
    url = f"{_connectors_url('conn-manual')}/{instance.id}/reconcile"

    # When / Then: 未启用拒绝且不入队。
    disabled_response = client.post(url, content_type="application/json")
    assert disabled_response.status_code == HTTPStatus.BAD_REQUEST
    assert sent == []

    # 启用后接受(202), 以 manual 触发直接入队(绕过去抖)。
    instance.enabled = True
    instance.save(update_fields=["enabled", "updated_at"])
    accepted_response = client.post(url, content_type="application/json")
    assert accepted_response.status_code == HTTPStatus.ACCEPTED
    assert sent == [("easyauth.connectors.reconcile_instance", (instance.id, "manual"))]


def test_external_groups_lists_connector_data() -> None:
    # Given
    app = App.objects.create(app_key="conn-groups", name="X")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    client = _logged_in_superuser("conn-groups-admin")

    # When
    response = client.get(f"{_connectors_url('conn-groups')}/{instance.id}/external-groups")

    # Then
    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["data"] == [{"ref": "fake-group", "name": "Fake Group"}]


def test_sync_runs_use_standard_server_pagination() -> None:
    app = App.objects.create(app_key="conn-runs", name="X")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    client = _logged_in_superuser("conn-runs-admin")
    now = timezone.now()
    page_size = 5
    _ = ConnectorSyncRun.objects.bulk_create(
        ConnectorSyncRun(
            instance=instance,
            trigger="manual",
            started_at=now - timedelta(minutes=index),
            finished_at=now - timedelta(minutes=index) + timedelta(seconds=1),
            status="success",
        )
        for index in range(12)
    )

    response = client.get(
        f"{_connectors_url('conn-runs')}/{instance.id}/sync-runs?page=2&page_size={page_size}",
    )

    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", response.json())
    data = payload["data"]
    assert isinstance(data, list)
    assert len(data) == page_size
    assert payload["pagination"] == {
        "page": 2,
        "page_size": page_size,
        "total_items": 12,
        "total_pages": 3,
    }


def test_duplicate_connector_type_conflicts() -> None:
    # Given
    app = App.objects.create(app_key="conn-dup", name="X")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake")
    _ = instance
    client = _logged_in_superuser("conn-dup-admin")

    # When
    response = client.post(
        _connectors_url("conn-dup"),
        data={"connector_key": "fake", "config": {"endpoint": "https://x"}},
        content_type="application/json",
    )

    # Then
    assert response.status_code == HTTPStatus.CONFLICT


def test_delete_instance() -> None:
    # Given
    app = App.objects.create(app_key="conn-del", name="X")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake")
    client = _logged_in_superuser("conn-del-admin")

    # When
    response = client.delete(f"{_connectors_url('conn-del')}/{instance.id}")

    # Then
    assert response.status_code == HTTPStatus.NO_CONTENT
    assert ConnectorInstance.objects.count() == 0
