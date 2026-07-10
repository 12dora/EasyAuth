from __future__ import annotations

import time
from dataclasses import dataclass
from json import JSONDecodeError, dumps, loads
from typing import TYPE_CHECKING, Final, Self, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from easyauth.applications.integration_settings import authentik_runtime_config

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

ADMIN_API_NOT_CONFIGURED_MESSAGE: Final = "Authentik 管理 API 未配置。"
ADMIN_API_UNAVAILABLE_MESSAGE: Final = "Authentik 管理 API 暂不可用。"
USER_NOT_FOUND_MESSAGE: Final = "Authentik 中找不到对应用户。"
_USERS_PAGE_SIZE: Final = 500
_MAX_USER_PAGES: Final = 40
_MAX_SESSION_PAGES: Final = 40
_MAX_RESPONSE_BYTES: Final = 1024 * 1024
_READ_CHUNK_BYTES: Final = 64 * 1024
_TOTAL_OPERATION_SECONDS: Final = 60.0

INVALID_RESPONSE_MESSAGE: Final = "Authentik 管理 API 响应格式无效。"
RESPONSE_TOO_LARGE_MESSAGE: Final = "Authentik 管理 API 响应超过大小上限。"
OPERATION_TIMEOUT_MESSAGE: Final = "Authentik 管理 API 操作超过总时限。"
PAGINATION_LIMIT_MESSAGE: Final = "Authentik 管理 API 分页超过上限。"

type AdminJson = dict[str, object]


class _ReadableResponse:
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def read(self, _amount: int = -1) -> bytes: ...

    def getheader(self, _name: str) -> str | None: ...


class AuthentikAdminError(RuntimeError):
    pass


class AuthentikAdminNotConfiguredError(AuthentikAdminError):
    def __init__(self) -> None:
        super().__init__(ADMIN_API_NOT_CONFIGURED_MESSAGE)


class AuthentikAdminUserNotFoundError(AuthentikAdminError):
    def __init__(self) -> None:
        super().__init__(USER_NOT_FOUND_MESSAGE)


@dataclass(frozen=True, slots=True)
class AccountDisableResult:
    user_pk: int
    deactivated: bool
    revoked_session_count: int


class AuthentikAdminClient:
    # 离职禁号编排的执行端(§1.2): 只用 Authentik 标准 API, fork 零改动。
    _base_url: str
    _api_token: str
    _timeout_seconds: float
    _monotonic: Callable[[], float]

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        timeout_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token
        self._timeout_seconds = timeout_seconds
        self._monotonic = monotonic

    @classmethod
    def from_settings(cls) -> AuthentikAdminClient:
        config = authentik_runtime_config()
        if not config.base_url or not config.api_token:
            raise AuthentikAdminNotConfiguredError
        return cls(
            base_url=config.base_url,
            api_token=config.api_token,
            timeout_seconds=config.timeout_seconds,
        )

    def disable_user_and_revoke_sessions(self, authentik_user_uid: str) -> AccountDisableResult:
        """按 uid(OIDC sub)禁用 Authentik 账号并吊销其全部会话。"""
        deadline = self._monotonic() + _TOTAL_OPERATION_SECONDS
        user_pk = self._find_user_pk_by_uid(authentik_user_uid, deadline=deadline)
        _ = self._request_json(
            "PATCH",
            f"/api/v3/core/users/{user_pk}/",
            body={"is_active": False},
            deadline=deadline,
        )
        revoked = self._revoke_sessions(user_pk, deadline=deadline)
        return AccountDisableResult(
            user_pk=user_pk,
            deactivated=True,
            revoked_session_count=revoked,
        )

    def _find_user_pk_by_uid(self, uid: str, *, deadline: float) -> int:
        # uid 是只读散列, core users API 不支持按它过滤; 离职是低频操作,
        # 分页拉取后本地匹配, 避免为此给 fork 加自定义端点。
        page = 1
        while page <= _MAX_USER_PAGES:
            payload = self._request_json(
                "GET",
                "/api/v3/core/users/",
                query={"page": str(page), "page_size": str(_USERS_PAGE_SIZE)},
                deadline=deadline,
            )
            results = payload.get("results")
            if not isinstance(results, list):
                raise AuthentikAdminError(INVALID_RESPONSE_MESSAGE)
            for item in cast("list[object]", results):
                if not isinstance(item, dict):
                    raise AuthentikAdminError(INVALID_RESPONSE_MESSAGE)
                entry = cast("AdminJson", item)
                entry_uid = entry.get("uid")
                entry_pk = entry.get("pk")
                if not isinstance(entry_uid, str) or type(entry_pk) is not int:
                    raise AuthentikAdminError(INVALID_RESPONSE_MESSAGE)
                if entry_uid == uid:
                    return cast("int", entry["pk"])
            pagination = payload.get("pagination")
            if not isinstance(pagination, dict):
                raise AuthentikAdminError(INVALID_RESPONSE_MESSAGE)
            total_pages = cast("AdminJson", pagination).get("total_pages")
            if type(total_pages) is not int or total_pages < 1 or page > total_pages:
                raise AuthentikAdminError(INVALID_RESPONSE_MESSAGE)
            if page == total_pages:
                break
            page += 1
        raise AuthentikAdminUserNotFoundError

    def _revoke_sessions(self, user_pk: int, *, deadline: float) -> int:
        # 先完整物化全部页再开始 DELETE; 分页中途失败时不产生“只撤了一半”的假成功。
        session_uuids: list[str] = []
        seen_uuids: set[str] = set()
        page = 1
        while page <= _MAX_SESSION_PAGES:
            payload = self._request_json(
                "GET",
                "/api/v3/core/authenticated_sessions/",
                query={
                    "user": str(user_pk),
                    "page": str(page),
                    "page_size": str(_USERS_PAGE_SIZE),
                },
                deadline=deadline,
            )
            results, next_page = _session_page(payload, expected_page=page)
            for item in results:
                session_uuid = item.get("uuid")
                if (
                    not isinstance(session_uuid, str)
                    or session_uuid == ""
                    or session_uuid in seen_uuids
                ):
                    raise AuthentikAdminError(INVALID_RESPONSE_MESSAGE)
                seen_uuids.add(session_uuid)
                session_uuids.append(session_uuid)
            if next_page == 0:
                break
            page = next_page
        else:
            raise AuthentikAdminError(PAGINATION_LIMIT_MESSAGE)

        for session_uuid in session_uuids:
            _ = self._request_json(
                "DELETE",
                f"/api/v3/core/authenticated_sessions/{session_uuid}/",
                deadline=deadline,
            )
        return len(session_uuids)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: AdminJson | None = None,
        query: dict[str, str] | None = None,
        deadline: float | None = None,
    ) -> AdminJson:
        effective_deadline = (
            self._monotonic() + _TOTAL_OPERATION_SECONDS if deadline is None else deadline
        )
        remaining = effective_deadline - self._monotonic()
        if remaining <= 0:
            raise AuthentikAdminError(OPERATION_TIMEOUT_MESSAGE)
        url = f"{self._base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_token}",
        }
        data: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = dumps(body).encode("utf-8")
        request = Request(url, data=data, headers=headers, method=method)  # noqa: S310 - base_url 由管理员配置。
        try:
            with cast(
                "_ReadableResponse",
                urlopen(request, timeout=min(self._timeout_seconds, remaining)),  # noqa: S310
            ) as response:
                raw = self._read_response(response, deadline=effective_deadline)
        except HTTPError as error:
            message = f"Authentik 管理 API 请求失败(HTTP {error.code})。"
            raise AuthentikAdminError(message) from error
        except (URLError, TimeoutError) as error:
            raise AuthentikAdminError(ADMIN_API_UNAVAILABLE_MESSAGE) from error
        if not raw and method == "DELETE":
            return {}
        if not raw:
            raise AuthentikAdminError(INVALID_RESPONSE_MESSAGE)
        try:
            parsed = cast("object", loads(raw.decode("utf-8")))
        except (JSONDecodeError, UnicodeDecodeError) as error:
            message = "Authentik 管理 API 响应不是有效 JSON。"
            raise AuthentikAdminError(message) from error
        if not isinstance(parsed, dict):
            raise AuthentikAdminError(INVALID_RESPONSE_MESSAGE)
        return cast("AdminJson", parsed)

    def _read_response(self, response: _ReadableResponse, *, deadline: float) -> bytes:
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError as error:
                raise AuthentikAdminError(INVALID_RESPONSE_MESSAGE) from error
            if declared_length < 0:
                raise AuthentikAdminError(INVALID_RESPONSE_MESSAGE)
            if declared_length > _MAX_RESPONSE_BYTES:
                raise AuthentikAdminError(RESPONSE_TOO_LARGE_MESSAGE)

        chunks: list[bytes] = []
        observed = 0
        while True:
            if self._monotonic() >= deadline:
                raise AuthentikAdminError(OPERATION_TIMEOUT_MESSAGE)
            chunk = response.read(min(_READ_CHUNK_BYTES, _MAX_RESPONSE_BYTES + 1 - observed))
            if not chunk:
                return b"".join(chunks)
            observed += len(chunk)
            if observed > _MAX_RESPONSE_BYTES:
                raise AuthentikAdminError(RESPONSE_TOO_LARGE_MESSAGE)
            chunks.append(chunk)


def _session_page(payload: AdminJson, *, expected_page: int) -> tuple[list[AdminJson], int]:
    results = payload.get("results")
    pagination = payload.get("pagination")
    if not isinstance(results, list) or not isinstance(pagination, dict):
        raise AuthentikAdminError(INVALID_RESPONSE_MESSAGE)
    entries: list[AdminJson] = []
    for item in cast("list[object]", results):
        if not isinstance(item, dict):
            raise AuthentikAdminError(INVALID_RESPONSE_MESSAGE)
        entries.append(cast("AdminJson", item))

    pagination_json = cast("AdminJson", pagination)
    current = pagination_json.get("current")
    next_page = pagination_json.get("next")
    if (
        type(current) is not int
        or current != expected_page
        or type(next_page) is not int
        or next_page < 0
        or (next_page != 0 and next_page != expected_page + 1)
        or (next_page != 0 and not entries)
    ):
        raise AuthentikAdminError(INVALID_RESPONSE_MESSAGE)
    return entries, next_page
