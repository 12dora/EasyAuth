from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, Self, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from types import TracebackType

AUTHENTIK_LIVENESS_PATH: Final = "/-/health/live/"
LIVENESS_BASE_URL_MISSING_MESSAGE: Final = "未配置 Authentik base URL, 无法执行存活检查。"


class _StatusResponse(Protocol):
    status: int

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class AuthentikLivenessResult:
    ok: bool
    detail: str


def check_authentik_liveness(*, base_url: str, timeout_seconds: float) -> AuthentikLivenessResult:
    # 请求 Authentik 的 /-/health/live/ 探针, 返回真实存活结果。
    if not base_url:
        return AuthentikLivenessResult(ok=False, detail=LIVENESS_BASE_URL_MISSING_MESSAGE)
    request = Request(  # noqa: S310 - URL 来自本地配置.
        f"{base_url.rstrip('/')}{AUTHENTIK_LIVENESS_PATH}",
        headers={"Accept": "*/*"},
        method="GET",
    )
    try:
        response_context = cast(
            "_StatusResponse",
            urlopen(request, timeout=timeout_seconds),  # noqa: S310 - URL 来自本地配置.
        )
        with response_context as response:
            status_code = response.status
    except HTTPError as error:
        return AuthentikLivenessResult(
            ok=False,
            detail=f"GET {AUTHENTIK_LIVENESS_PATH} 返回 HTTP {error.code}。",
        )
    except (URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", None) or error
        return AuthentikLivenessResult(ok=False, detail=f"无法连接 Authentik: {reason}")
    return AuthentikLivenessResult(
        ok=True,
        detail=f"GET {AUTHENTIK_LIVENESS_PATH} 返回 HTTP {status_code}。",
    )
