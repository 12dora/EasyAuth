from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from json import JSONDecodeError, loads
from typing import TYPE_CHECKING, Self, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from easyauth.applications.integration_settings import authentik_runtime_config
from easyauth.integrations.authentik.directory_payloads import (
    DingTalkDirectoryDepartment,
    DingTalkDirectoryOrgContext,
    DingTalkDirectoryStatus,
    DingTalkDirectoryUser,
    DingTalkManagedUsers,
    DirectoryJson,
    JsonValue,
    parse_departments,
    parse_managed_users,
    parse_org_context,
    parse_status,
    parse_users,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

DIRECTORY_UNAVAILABLE_MESSAGE = "Authentik 目录 API 暂不可用。"
DIRECTORY_INVALID_JSON_MESSAGE = "Authentik 目录 API 返回了无效 JSON。"
DIRECTORY_INVALID_FORMAT_MESSAGE = "Authentik 目录 API 返回格式无效。"
DIRECTORY_PERMISSION_MESSAGE = "Authentik 目录 API 权限不足。"
DIRECTORY_NOT_FOUND_MESSAGE = "Authentik 目录 API 资源不存在。"


class _ReadableResponse:
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def read(self) -> bytes: ...


class AuthentikDirectoryError(RuntimeError):
    pass


class AuthentikDirectoryPermissionError(AuthentikDirectoryError):
    pass


class AuthentikDirectoryNotFoundError(AuthentikDirectoryError):
    pass


class AuthentikDirectoryUnavailableError(AuthentikDirectoryError):
    pass


@dataclass(frozen=True, slots=True)
class AuthentikDirectoryClient:
    base_url: str
    api_token: str
    source_slug: str
    timeout_seconds: float = 5

    @classmethod
    def from_settings(cls) -> AuthentikDirectoryClient:
        # 生效配置由 integration_settings 解析: 数据库设置优先, 其次环境变量。
        config = authentik_runtime_config()
        return cls(
            base_url=config.base_url,
            api_token=config.api_token,
            source_slug=config.source_slug,
            timeout_seconds=config.timeout_seconds,
        )

    def get_status(self) -> DingTalkDirectoryStatus:
        return parse_status(self._get_json("status/"), source_slug=self.source_slug)

    def iter_departments(self) -> Iterator[DingTalkDirectoryDepartment]:
        for page in self._iter_paginated("departments/"):
            try:
                yield from parse_departments(page, source_slug=self.source_slug)
            except (TypeError, ValueError) as error:
                raise AuthentikDirectoryUnavailableError(
                    DIRECTORY_INVALID_FORMAT_MESSAGE,
                ) from error

    def iter_users(self) -> Iterator[DingTalkDirectoryUser]:
        for page in self._iter_paginated("users/"):
            try:
                yield from parse_users(page, source_slug=self.source_slug)
            except (TypeError, ValueError) as error:
                raise AuthentikDirectoryUnavailableError(
                    DIRECTORY_INVALID_FORMAT_MESSAGE,
                ) from error

    def get_user_org(self, corp_id: str, user_id: str) -> DingTalkDirectoryOrgContext:
        quoted_corp = quote(corp_id, safe="")
        quoted_user = quote(user_id, safe="")
        return parse_org_context(
            self._get_json(f"users/{quoted_corp}/{quoted_user}/org/"),
            source_slug=self.source_slug,
        )

    def get_managed_users(self, corp_id: str, manager_user_id: str) -> DingTalkManagedUsers:
        quoted_corp = quote(corp_id, safe="")
        quoted_manager = quote(manager_user_id, safe="")
        try:
            return parse_managed_users(
                self._get_json(
                    f"managed-users/by-manager/{quoted_corp}/{quoted_manager}/",
                ),
                source_slug=self.source_slug,
            )
        except (TypeError, ValueError) as error:
            raise AuthentikDirectoryUnavailableError(DIRECTORY_INVALID_FORMAT_MESSAGE) from error

    def _iter_paginated(self, suffix: str) -> Iterator[DirectoryJson]:
        page = 1
        while True:
            payload = self._get_json(suffix, query={"page": str(page)})
            yield payload
            next_page = _next_page(payload)
            if next_page is None:
                return
            page = next_page

    def _get_json(self, suffix: str, *, query: dict[str, str] | None = None) -> DirectoryJson:
        query_string = f"?{urlencode(query)}" if query else ""
        request = Request(  # noqa: S310 - URL 来自本地配置.
            (
                f"{self.base_url}/api/v3/sources/oauth/dingtalk-directory/"
                f"{self.source_slug}/{suffix}{query_string}"
            ),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_token}",
            },
            method="GET",
        )
        raw_body = b""
        try:
            response_context = cast(
                "_ReadableResponse",
                urlopen(request, timeout=self.timeout_seconds),  # noqa: S310 - URL 来自本地配置.
            )
            with response_context as response:
                raw_body = response.read()
        except HTTPError as error:
            _raise_http_error(error)
        except URLError as error:
            raise AuthentikDirectoryUnavailableError(DIRECTORY_UNAVAILABLE_MESSAGE) from error

        try:
            parsed = cast("JsonValue", loads(raw_body.decode("utf-8")))
        except (JSONDecodeError, UnicodeDecodeError) as error:
            raise AuthentikDirectoryUnavailableError(DIRECTORY_INVALID_JSON_MESSAGE) from error
        if not isinstance(parsed, dict):
            raise AuthentikDirectoryUnavailableError(DIRECTORY_INVALID_FORMAT_MESSAGE)
        return cast("DirectoryJson", parsed)


def _raise_http_error(error: HTTPError) -> None:
    if error.code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        raise AuthentikDirectoryPermissionError(DIRECTORY_PERMISSION_MESSAGE) from error
    if error.code == HTTPStatus.NOT_FOUND:
        raise AuthentikDirectoryNotFoundError(DIRECTORY_NOT_FOUND_MESSAGE) from error
    raise AuthentikDirectoryUnavailableError(DIRECTORY_UNAVAILABLE_MESSAGE) from error


def _next_page(payload: DirectoryJson) -> int | None:
    pagination = payload.get("pagination")
    if not isinstance(pagination, dict):
        return None
    pagination_mapping = cast("DirectoryJson", pagination)
    next_page = pagination_mapping.get("next")
    return next_page if isinstance(next_page, int) and next_page > 0 else None
