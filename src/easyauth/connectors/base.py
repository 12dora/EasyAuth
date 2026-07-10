from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Mapping

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.ops_models import JsonValue
    from easyauth.connectors.models import ConnectorInstance

# ADR-003: 连接器是授权事实的只读投影——它把 GrantService 已产生的事实物化到
# 外部执行点, 绝不反向产生或修改授权; 幂等全量对账是正确性的唯一依据。

RECONCILE_STATUS_SUCCESS = "success"
RECONCILE_STATUS_PARTIAL = "partial"


class ConnectorError(RuntimeError):
    """连接器与外部系统交互失败(网络/凭据/契约), 由框架捕获记入运行审计。"""


@dataclass(frozen=True, slots=True)
class ConnectorProbe:
    ok: bool
    message: str = ""


@dataclass(frozen=True, slots=True)
class ExternalGroup:
    # ref 是映射表 external_ref 使用的稳定标识(NetBird 取组名), name 用于展示。
    ref: str
    name: str


@dataclass(frozen=True, slots=True)
class DesiredUserProfile:
    # 预创建外部用户所需的最小画像, 来自 UserMirror。
    user_id: str
    name: str
    email: str


@dataclass(frozen=True, slots=True)
class DesiredState:
    # authentik_user_id → 应持有的外部组 ref 集合(仅映射表管理的组)。
    user_groups: Mapping[str, frozenset[str]]
    profiles: Mapping[str, DesiredUserProfile]
    # 映射表管理的全部外部组 ref: 对账只增删该集合内的组, 范围外不触碰。
    managed_group_refs: frozenset[str]
    # 其中允许在外部系统缺失时自动创建的子集。
    auto_create_group_refs: frozenset[str]


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    status: str = RECONCILE_STATUS_SUCCESS
    stats: dict[str, int] = field(default_factory=dict)
    # 外部系统存在但 desired 中没有的用户(逆序用户), Phase 2 钉钉引导消息的数据口。
    ungranted_user_ids: tuple[str, ...] = ()
    error: str = ""


class BaseConnector(ABC):
    key: ClassVar[str]
    display_name: ClassVar[str]
    # JSON Schema 子集(string/boolean/number/enum); "x-secret": true 标记加密字段,
    # 前端渲染密码框、后端读接口只回显占位。
    config_schema: ClassVar[dict[str, JsonValue]]

    @abstractmethod
    def test_connection(self, config: dict[str, JsonValue]) -> ConnectorProbe: ...

    @abstractmethod
    def list_external_groups(self, config: dict[str, JsonValue]) -> list[ExternalGroup]: ...

    @abstractmethod
    def reconcile(self, instance: ConnectorInstance, desired: DesiredState) -> ReconcileReport: ...

    def external_account_id(self, config: dict[str, JsonValue]) -> str:
        """探测外部租户的不可变 ID; 不具备租户概念的连接器返回空串。"""
        _ = config
        return ""

    def validate_config(self, config: dict[str, JsonValue]) -> list[str]:
        """返回配置问题列表(空表 = 通过); 子类可追加连接器特有校验。"""
        return validate_config_against_schema(self.config_schema, config)

    def on_user_offboarded(self, instance: ConnectorInstance, user: UserMirror) -> bool:
        """离职快路径; 返回 False 表示未处理, 框架回退为触发一次完整对账。"""
        _ = (instance, user)
        return False


def secret_field_names(schema: dict[str, JsonValue]) -> frozenset[str]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return frozenset()
    return frozenset(
        name
        for name, spec in properties.items()
        if isinstance(spec, dict) and spec.get("x-secret") is True
    )


def validate_config_against_schema(
    schema: dict[str, JsonValue],
    config: dict[str, JsonValue],
) -> list[str]:
    # 轻量校验(v1 只覆盖 required 与标量类型), 足够挡住控制台的手误输入;
    # 不引入完整 JSON Schema 校验器依赖。
    problems: list[str] = []
    properties = schema.get("properties")
    property_specs = properties if isinstance(properties, dict) else {}
    required = schema.get("required")
    required_names = [name for name in required if isinstance(name, str)] if isinstance(
        required,
        list,
    ) else []
    for name in required_names:
        value = config.get(name)
        if value is None or value == "":
            problems.append(f"缺少必填配置项 {name}。")
    for name, value in config.items():
        spec = property_specs.get(name)
        if not isinstance(spec, dict):
            problems.append(f"未知配置项 {name}。")
            continue
        problems.extend(_type_problems(name, spec, value))
    return problems


def _type_problems(name: str, spec: dict[str, JsonValue], value: JsonValue) -> list[str]:
    if value is None:
        return []
    expected = spec.get("type")
    enum_values = spec.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        return [f"配置项 {name} 不在允许的取值内。"]
    match expected:
        case "string" if not isinstance(value, str):
            return [f"配置项 {name} 必须是字符串。"]
        case "boolean" if not isinstance(value, bool):
            return [f"配置项 {name} 必须是布尔值。"]
        case "number" if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"配置项 {name} 必须是数字。"]
        case _:
            return []
