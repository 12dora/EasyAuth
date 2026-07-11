from __future__ import annotations

from dataclasses import dataclass
from json import JSONDecodeError, dumps, loads
from time import monotonic
from typing import TYPE_CHECKING, Final, Protocol, Self, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from easyauth.connectors.base import ConnectorError

if TYPE_CHECKING:
    from types import TracebackType

    from easyauth.applications.ops_models import JsonValue

# NetBird 管理 API 的全部调用点收敛在本模块(方案 §8: API 随版本漂移时只改这里);
# 端点契约以 fork 锁定的基线 tag 为准(姊妹篇 §1/§4), 预创建用户依赖 fork 补丁。
DEFAULT_TIMEOUT_SECONDS: Final = 10.0
DEFAULT_TOTAL_TIMEOUT_SECONDS: Final = 30.0
MAX_RESPONSE_BYTES: Final = 1024 * 1024
RESPONSE_READ_CHUNK_BYTES: Final = 64 * 1024
MAX_TRANSIENT_IDEMPOTENT_ATTEMPTS: Final = 3
TOTAL_TIMEOUT_MESSAGE: Final = "NetBird API 请求超过总时限。"
READ_TOTAL_TIMEOUT_MESSAGE: Final = "NetBird API 响应读取超过总时限。"
INVALID_CONTENT_LENGTH_MESSAGE: Final = "NetBird API Content-Length 无效。"
RESPONSE_TOO_LARGE_MESSAGE: Final = "NetBird API 响应体超过大小上限。"

USER_ROLE_USER: Final = "user"
USER_ROLE_ADMIN: Final = "admin"
USER_ROLE_OWNER: Final = "owner"


class NetBirdApiError(ConnectorError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code: int | None = status_code


class _Headers(Protocol):
    def get(self, name: str) -> str | None: ...


class _ReadableResponse(Protocol):
    headers: _Headers

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def read(self, _amount: int = -1) -> bytes: ...


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
        total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url: str = api_url.rstrip("/")
        self._api_token: str = api_token
        self._timeout_seconds: float = timeout_seconds
        self._total_timeout_seconds: float = total_timeout_seconds

    def list_users(self) -> list[NetBirdUser]:
        payload = self._request("GET", "/api/users")
        if not isinstance(payload, list):
            message = "NetBird /api/users 响应必须是 JSON 数组。"
            raise NetBirdApiError(message)
        users = [_parse_user(item) for item in payload]
        _assert_unique_ids([user.user_id for user in users], label="users")
        return users

    def get_account_id(self) -> str:
        payload = self._request("GET", "/api/accounts")
        if not isinstance(payload, list) or len(payload) != 1:
            message = "NetBird /api/accounts 必须返回唯一账户。"
            raise NetBirdApiError(message)
        account = payload[0]
        if not isinstance(account, dict):
            message = "NetBird /api/accounts 响应账户必须是 JSON 对象。"
            raise NetBirdApiError(message)
        account_id = _required_string(account, "id", label="accounts")
        return account_id

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
        groups = [_parse_group(item) for item in payload]
        _assert_unique_ids([group.group_id for group in groups], label="groups")
        return groups

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
        deadline = monotonic() + self._total_timeout_seconds
        max_attempts = (
            MAX_TRANSIENT_IDEMPOTENT_ATTEMPTS if method in {"GET", "PUT"} else 1
        )
        raw = b""
        for attempt in range(max_attempts):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise NetBirdApiError(TOTAL_TIMEOUT_MESSAGE)
            try:
                with cast(
                    "_ReadableResponse",
                    urlopen(  # noqa: S310
                        request,
                        timeout=min(self._timeout_seconds, remaining),
                    ),
                ) as response:
                    raw = _read_bounded(response, deadline=deadline)
                break
            except HTTPError as error:
                message = f"NetBird API {method} {path} 返回 HTTP {error.code}。"
                raise NetBirdApiError(message, status_code=error.code) from error
            except (URLError, TimeoutError) as error:
                if attempt + 1 < max_attempts and monotonic() < deadline:
                    continue
                message = f"NetBird API 不可达: {error}"
                raise NetBirdApiError(message) from error
        if not raw:
            return None
        try:
            return cast("JsonValue", loads(raw.decode("utf-8")))
        except (JSONDecodeError, UnicodeDecodeError) as error:
            message = f"NetBird API {method} {path} 响应不是有效 JSON。"
            raise NetBirdApiError(message) from error


def _read_bounded(response: _ReadableResponse, *, deadline: float) -> bytes:
    headers = response.headers
    content_length_value = headers.get("Content-Length")
    if content_length_value is not None:
        try:
            content_length = int(content_length_value)
        except (TypeError, ValueError) as error:
            raise NetBirdApiError(INVALID_CONTENT_LENGTH_MESSAGE) from error
        if content_length < 0 or content_length > MAX_RESPONSE_BYTES:
            raise NetBirdApiError(RESPONSE_TOO_LARGE_MESSAGE)
    chunks: list[bytes] = []
    total = 0
    while True:
        if monotonic() >= deadline:
            raise NetBirdApiError(READ_TOTAL_TIMEOUT_MESSAGE)
        chunk = response.read(min(RESPONSE_READ_CHUNK_BYTES, MAX_RESPONSE_BYTES + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise NetBirdApiError(RESPONSE_TOO_LARGE_MESSAGE)
        chunks.append(chunk)
    return b"".join(chunks)


_KNOWN_USER_ROLES: Final = frozenset({USER_ROLE_USER, USER_ROLE_ADMIN, USER_ROLE_OWNER})


def _parse_user(item: JsonValue) -> NetBirdUser:
    if not isinstance(item, dict):
        message = "NetBird /api/users 数组元素必须是 JSON 对象。"
        raise NetBirdApiError(message)
    user_id = _required_string(item, "id", label="users")
    role = _required_string(item, "role", label="users")
    if role not in _KNOWN_USER_ROLES:
        message = f"NetBird /api/users 返回未知 role: {role}。"
        raise NetBirdApiError(message)
    is_blocked = _required_bool(item, "is_blocked", label="users")
    is_service_user = _required_bool(item, "is_service_user", label="users")
    return NetBirdUser(
        user_id=user_id,
        name=_optional_string(item, "name"),
        email=_optional_string(item, "email"),
        role=role,
        is_blocked=is_blocked,
        is_service_user=is_service_user,
        auto_group_ids=_required_string_set(item.get("auto_groups"), label="users.auto_groups"),
    )


def _parse_group(item: JsonValue) -> NetBirdGroup:
    if not isinstance(item, dict):
        message = "NetBird /api/groups 数组元素必须是 JSON 对象。"
        raise NetBirdApiError(message)
    return NetBirdGroup(
        group_id=_required_string(item, "id", label="groups"),
        name=_required_string(item, "name", label="groups"),
    )


def _required_string(item: dict[str, JsonValue], key: str, *, label: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        message = f"NetBird /api/{label} 元素缺少有效字段 {key}。"
        raise NetBirdApiError(message)
    return value


def _optional_string(item: dict[str, JsonValue], key: str) -> str:
    value = item.get(key)
    return value if isinstance(value, str) else ""


def _required_bool(item: dict[str, JsonValue], key: str, *, label: str) -> bool:
    value = item.get(key)
    if not isinstance(value, bool):
        message = f"NetBird /api/{label} 元素字段 {key} 必须是布尔值。"
        raise NetBirdApiError(message)
    return value


def _required_string_set(value: JsonValue | None, *, label: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, list):
        message = f"NetBird {label} 必须是字符串数组。"
        raise NetBirdApiError(message)
    result: set[str] = set()
    for entry in value:
        if not isinstance(entry, str) or not entry:
            message = f"NetBird {label} 只能包含非空字符串。"
            raise NetBirdApiError(message)
        result.add(entry)
    return frozenset(result)


def _assert_unique_ids(ids: list[str], *, label: str) -> None:
    if len(ids) != len(set(ids)):
        message = f"NetBird /api/{label} 响应包含重复 ID。"
        raise NetBirdApiError(message)
