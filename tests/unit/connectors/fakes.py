from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from easyauth.connectors.base import (
    BaseConnector,
    ConnectorError,
    ConnectorProbe,
    ExternalGroup,
    ReconcileReport,
)

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.applications.ops_models import JsonValue
    from easyauth.connectors.base import DesiredState
    from easyauth.connectors.models import ConnectorInstance


class FakeConnector(BaseConnector):
    """测试用连接器: 经 EASYAUTH_CONNECTORS 注册, 用类属性注入行为并捕获输入。"""

    key: ClassVar[str] = "fake"
    display_name: ClassVar[str] = "Fake Connector"
    config_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "endpoint": {"type": "string", "title": "Endpoint"},
            "token": {"type": "string", "title": "Token", "x-secret": True},
        },
        "required": ["endpoint"],
    }

    last_desired: ClassVar[DesiredState | None] = None
    next_report: ClassVar[ReconcileReport | None] = None
    next_error_message: ClassVar[str] = ""
    probe_ok: ClassVar[bool] = True
    offboarded_user_ids: ClassVar[list[str]] = []
    offboard_handled: ClassVar[bool] = True
    external_account: ClassVar[str] = ""

    @classmethod
    def reset(cls) -> None:
        cls.last_desired = None
        cls.next_report = None
        cls.next_error_message = ""
        cls.probe_ok = True
        cls.offboarded_user_ids = []
        cls.offboard_handled = True
        cls.external_account = ""

    @override
    def test_connection(self, config: dict[str, JsonValue]) -> ConnectorProbe:
        _ = config
        return ConnectorProbe(ok=type(self).probe_ok, message="fake probe")

    @override
    def list_external_groups(self, config: dict[str, JsonValue]) -> list[ExternalGroup]:
        _ = config
        return [ExternalGroup(ref="fake-group", name="Fake Group")]

    @override
    def external_account_id(self, config: dict[str, JsonValue]) -> str:
        _ = config
        return type(self).external_account

    @override
    def reconcile(self, instance: ConnectorInstance, desired: DesiredState) -> ReconcileReport:
        _ = instance
        cls = type(self)
        cls.last_desired = desired
        if cls.next_error_message:
            raise ConnectorError(cls.next_error_message)
        return cls.next_report or ReconcileReport()

    @override
    def on_user_offboarded(self, instance: ConnectorInstance, user: UserMirror) -> bool:
        _ = instance
        cls = type(self)
        if cls.next_error_message:
            raise ConnectorError(cls.next_error_message)
        cls.offboarded_user_ids.append(user.authentik_user_id)
        return cls.offboard_handled
