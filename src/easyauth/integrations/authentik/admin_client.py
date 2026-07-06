from __future__ import annotations

from dataclasses import dataclass
from json import JSONDecodeError, dumps, loads
from typing import TYPE_CHECKING, Final, Self, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from easyauth.applications.integration_settings import authentik_runtime_config

if TYPE_CHECKING:
    from types import TracebackType

ADMIN_API_NOT_CONFIGURED_MESSAGE: Final = "Authentik 管理 API 未配置。"
ADMIN_API_UNAVAILABLE_MESSAGE: Final = "Authentik 管理 API 暂不可用。"
USER_NOT_FOUND_MESSAGE: Final = "Authentik 中找不到对应用户。"
_USERS_PAGE_SIZE: Final = 500
_MAX_USER_PAGES: Final = 40

type AdminJson = dict[str, object]


class _ReadableResponse:
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def read(self) -> bytes: ...


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

    def __init__(self, *, base_url: str, api_token: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token
        self._timeout_seconds = timeout_seconds

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
        user_pk = self._find_user_pk_by_uid(authentik_user_uid)
        _ = self._request_json(
            "PATCH",
            f"/api/v3/core/users/{user_pk}/",
            body={"is_active": False},
        )
        revoked = self._revoke_sessions(user_pk)
        return AccountDisableResult(
            user_pk=user_pk,
            deactivated=True,
            revoked_session_count=revoked,
        )

    def _find_user_pk_by_uid(self, uid: str) -> int:
        # uid 是只读散列, core users API 不支持按它过滤; 离职是低频操作,
        # 分页拉取后本地匹配, 避免为此给 fork 加自定义端点。
        page = 1
        while page <= _MAX_USER_PAGES:
            payload = self._request_json(
                "GET",
                "/api/v3/core/users/",
                query={"page": str(page), "page_size": str(_USERS_PAGE_SIZE)},
            )
            results = payload.get("results")
            if not isinstance(results, list):
                message = "Authentik 用户列表响应格式无效。"
                raise AuthentikAdminError(message)
            for item in cast("list[object]", results):
                if not isinstance(item, dict):
                    continue
                entry = cast("AdminJson", item)
                if entry.get("uid") == uid and isinstance(entry.get("pk"), int):
                    return cast("int", entry["pk"])
            pagination = payload.get("pagination")
            if isinstance(pagination, dict):
                total_pages = cast("AdminJson", pagination).get("total_pages")
                if isinstance(total_pages, int) and page >= total_pages:
                    break
            elif len(cast("list[object]", results)) < _USERS_PAGE_SIZE:
                break
            page += 1
        raise AuthentikAdminUserNotFoundError

    def _revoke_sessions(self, user_pk: int) -> int:
        payload = self._request_json(
            "GET",
            "/api/v3/core/authenticated_sessions/",
            query={"user": str(user_pk), "page_size": str(_USERS_PAGE_SIZE)},
        )
        results = payload.get("results")
        if not isinstance(results, list):
            return 0
        revoked = 0
        for item in cast("list[object]", results):
            if not isinstance(item, dict):
                continue
            session_uuid = cast("AdminJson", item).get("uuid")
            if not isinstance(session_uuid, str):
                continue
            _ = self._request_json(
                "DELETE",
                f"/api/v3/core/authenticated_sessions/{session_uuid}/",
            )
            revoked += 1
        return revoked

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: AdminJson | None = None,
        query: dict[str, str] | None = None,
    ) -> AdminJson:
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
                urlopen(request, timeout=self._timeout_seconds),  # noqa: S310
            ) as response:
                raw = response.read()
        except HTTPError as error:
            message = f"Authentik 管理 API 请求失败(HTTP {error.code})。"
            raise AuthentikAdminError(message) from error
        except (URLError, TimeoutError) as error:
            raise AuthentikAdminError(ADMIN_API_UNAVAILABLE_MESSAGE) from error
        if not raw:
            return {}
        try:
            parsed = cast("object", loads(raw.decode("utf-8")))
        except (JSONDecodeError, UnicodeDecodeError) as error:
            message = "Authentik 管理 API 响应不是有效 JSON。"
            raise AuthentikAdminError(message) from error
        if not isinstance(parsed, dict):
            return {}
        return cast("AdminJson", parsed)
