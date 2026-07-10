from __future__ import annotations

from dataclasses import dataclass
from json import JSONDecodeError, dumps, loads
from typing import TYPE_CHECKING, Final, Self, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from easyauth.connectors.base import ConnectorError

if TYPE_CHECKING:
    from types import TracebackType

    from easyauth.applications.ops_models import JsonValue

# NetBird 管理 API 的全部调用点收敛在本模块(方案 §8: API 随版本漂移时只改这里);
# 端点契约以 fork 锁定的基线 tag 为准(姊妹篇 §1/§4), 预创建用户依赖 fork 补丁。
DEFAULT_TIMEOUT_SECONDS: Final = 10.0

USER_ROLE_USER: Final = "user"
USER_ROLE_ADMIN: Final = "admin"
USER_ROLE_OWNER: Final = "owner"


class NetBirdApiError(ConnectorError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code: int | None = status_code


class _ReadableResponse:
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def read(self) -> bytes: ...


@dataclass(frozen=True, slots=True)
class NetBirdUser:
    user_id: str
    name: str
    email: str
    role: str
    is_blocked: bool
    is_service_user: bool
    auto_group_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class NetBirdGroup:
    group_id: str
    name: str


class NetBirdClient:
    def __init__(
        self,
        *,
        api_url: str,
        api_token: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url: str = api_url.rstrip("/")
        self._api_token: str = api_token
        self._timeout_seconds: float = timeout_seconds

    def list_users(self) -> list[NetBirdUser]:
        payload = self._request("GET", "/api/users")
        if not isinstance(payload, list):
            message = "NetBird /api/users 响应必须是 JSON 数组。"
            raise NetBirdApiError(message)
        return [_parse_user(item) for item in payload if isinstance(item, dict)]

    def create_user(
        self,
        *,
        user_id: str,
        name: str,
        email: str,
        auto_group_ids: list[str],
    ) -> None:
        # fork 补丁端点: 以 IdP sub 预创建用户, 首次 OIDC 登录会被原样收养(F8)。
        group_ids: list[JsonValue] = list(auto_group_ids)
        body: dict[str, JsonValue] = {
            "id": user_id,
            "name": name,
            "email": email,
            "role": USER_ROLE_USER,
            "auto_groups": group_ids,
            "is_service_user": False,
        }
        _ = self._request("POST", "/api/users", body=body)

    def update_user(
        self,
        *,
        user_id: str,
        role: str,
        auto_group_ids: list[str],
        is_blocked: bool,
    ) -> None:
        # NetBird 的 PUT 是整体替换语义: role/auto_groups/is_blocked 必须同时携带。
        group_ids: list[JsonValue] = list(auto_group_ids)
        body: dict[str, JsonValue] = {
            "role": role,
            "auto_groups": group_ids,
            "is_blocked": is_blocked,
        }
        _ = self._request("PUT", f"/api/users/{user_id}", body=body)

    def list_groups(self) -> list[NetBirdGroup]:
        payload = self._request("GET", "/api/groups")
        if not isinstance(payload, list):
            message = "NetBird /api/groups 响应必须是 JSON 数组。"
            raise NetBirdApiError(message)
        return [_parse_group(item) for item in payload if isinstance(item, dict)]

    def create_group(self, *, name: str) -> NetBirdGroup:
        payload = self._request("POST", "/api/groups", body={"name": name})
        if not isinstance(payload, dict):
            message = "NetBird 创建组响应必须是 JSON 对象。"
            raise NetBirdApiError(message)
        return _parse_group(payload)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, JsonValue] | None = None,
    ) -> JsonValue:
        url = f"{self._base_url}{path}"
        data = dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Token {self._api_token}",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)  # noqa: S310 - URL 来自控制台超管配置。
        try:
            with cast(
                "_ReadableResponse",
                urlopen(request, timeout=self._timeout_seconds),  # noqa: S310
            ) as response:
                raw = response.read()
        except HTTPError as error:
            message = f"NetBird API {method} {path} 返回 HTTP {error.code}。"
            raise NetBirdApiError(message, status_code=error.code) from error
        except (URLError, TimeoutError) as error:
            message = f"NetBird API 不可达: {error}"
            raise NetBirdApiError(message) from error
        if not raw:
            return None
        try:
            return cast("JsonValue", loads(raw.decode("utf-8")))
        except (JSONDecodeError, UnicodeDecodeError) as error:
            message = f"NetBird API {method} {path} 响应不是有效 JSON。"
            raise NetBirdApiError(message) from error


def _parse_user(item: dict[str, JsonValue]) -> NetBirdUser:
    return NetBirdUser(
        user_id=_string_value(item, "id"),
        name=_string_value(item, "name"),
        email=_string_value(item, "email"),
        role=_string_value(item, "role"),
        is_blocked=item.get("is_blocked") is True,
        is_service_user=item.get("is_service_user") is True,
        auto_group_ids=_string_set(item.get("auto_groups")),
    )


def _string_set(value: JsonValue | None) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(entry for entry in value if isinstance(entry, str))


def _parse_group(item: dict[str, JsonValue]) -> NetBirdGroup:
    return NetBirdGroup(group_id=_string_value(item, "id"), name=_string_value(item, "name"))


def _string_value(item: dict[str, JsonValue], key: str) -> str:
    value = item.get(key)
    return value if isinstance(value, str) else ""
