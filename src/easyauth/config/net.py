from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, Self, cast
from urllib.parse import quote, urlparse, urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping
    from types import TracebackType
    from urllib.parse import SplitResult

INSECURE_URL_MESSAGE = "URL 必须使用 https(仅本地开发允许 http://localhost)。"
BLOCKED_HOST_MESSAGE = "目标主机解析到被禁止的内网/环回/保留地址。"
UNRESOLVABLE_HOST_MESSAGE = "目标主机无法解析。"
DNS_RESOLUTION_TIMEOUT_MESSAGE = "目标主机解析超时。"
DNS_RESOLVER_QUEUE_FULL_MESSAGE = "DNS resolver 队列已满。"
HTTP_RESPONSE_TOO_LARGE_MESSAGE = "外部 HTTP 响应超过允许的大小。"
HTTP_RESPONSE_DEADLINE_MESSAGE = "外部 HTTP 响应读取超过总时限。"
HTTP_INVALID_CONTENT_LENGTH_MESSAGE = "外部 HTTP 响应的 Content-Length 无效。"
INVALID_WEBHOOK_URL_MESSAGE = (
    "Webhook URL 必须是 https:// 公网地址, 且不得包含用户信息、片段或非 443 端口。"
)
WEBHOOK_HOST_NOT_ALLOWED_MESSAGE = "Webhook URL 的域名不在该应用的允许列表中。"
CONTROL_CHARACTER_LIMIT: Final = 0x20
IPV6_VERSION: Final = 6
DNS_RESOLVER_MAX_IN_FLIGHT: Final = 32
HTTP_READ_CHUNK_BYTES: Final = 64 * 1024
DNS_RESOLVER_TERMINATE_GRACE_SECONDS: Final = 0.2
DNS_RESOLVER_OUTPUT_MAX_BYTES: Final = 64 * 1024
# 仅全栈 E2E(DEBUG=1)可放行的环回 webhook 主机列表; 默认空=不放行任何主机。
# 生产/非 DEBUG 下读取该变量也必须仍是空集, 见 e2e_allowed_insecure_webhook_hosts。
E2E_ALLOW_INSECURE_WEBHOOK_HOSTS_ENV: Final = "EASYAUTH_E2E_ALLOW_INSECURE_WEBHOOK_HOSTS"
E2E_RUNTIME_SETTINGS_MODULE: Final = "easyauth.config.settings.e2e"
DNS_RESOLVER_SCRIPT: Final = r"""
import json
import socket
import sys

try:
    hostname = sys.argv[1]
    port = int(sys.argv[2])
    infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    addresses = []
    for info in infos[:256]:
        raw_ip = info[4][0]
        if isinstance(raw_ip, str) and raw_ip not in addresses:
            addresses.append(raw_ip)
    print(json.dumps({"ok": addresses}, separators=(",", ":")), flush=True)
except socket.gaierror:
    print(json.dumps({"gaierror": True}, separators=(",", ":")), flush=True)
except Exception:
    print(json.dumps({"error": True}, separators=(",", ":")), flush=True)
"""

# 仅本机流量允许明文 http 的主机。host.docker.internal 是 Docker 容器访问宿主的
# 专用主机名(容器化部署里 worker/stream 经它访问宿主上的 Authentik/EasyTrade),
# 流量只走本机 docker bridge, 与环回地址同一信任边界。
LOCAL_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})


class InsecureUrlError(ValueError):
    def __init__(self) -> None:
        super().__init__(INSECURE_URL_MESSAGE)


class BlockedHostError(ValueError):
    def __init__(self, message: str = BLOCKED_HOST_MESSAGE) -> None:
        super().__init__(message)


class InvalidWebhookUrlError(ValueError):
    def __init__(self, message: str = INVALID_WEBHOOK_URL_MESSAGE) -> None:
        super().__init__(message)


class HttpResponseReadError(RuntimeError):
    pass


class HttpResponseTooLargeError(HttpResponseReadError):
    def __init__(self) -> None:
        super().__init__(HTTP_RESPONSE_TOO_LARGE_MESSAGE)


class HttpResponseDeadlineExceededError(HttpResponseReadError):
    def __init__(self) -> None:
        super().__init__(HTTP_RESPONSE_DEADLINE_MESSAGE)


class InvalidContentLengthError(HttpResponseReadError):
    def __init__(self) -> None:
        super().__init__(HTTP_INVALID_CONTENT_LENGTH_MESSAGE)


class HeaderReadableResponse(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def read(self, amount: int = -1) -> bytes: ...

    def getheader(self, name: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ValidatedHttpsUrl:
    hostname: str
    port: int
    request_target: str
    addresses: tuple[str, ...]
    # E2E 窄门: 仅当主机在 EASYAUTH_E2E_ALLOW_INSECURE_WEBHOOK_HOSTS 且 DEBUG 时为 True。
    # 生产路径恒为 False; transport 据此决定是否走明文 HTTP 连接。
    allow_insecure_http: bool = False


def e2e_allowed_insecure_webhook_hosts() -> frozenset[str]:
    """返回当前进程允许的 E2E 明文 webhook 主机集合。

    仅在 ``settings.DEBUG is True`` 且环境变量
    ``EASYAUTH_E2E_ALLOW_INSECURE_WEBHOOK_HOSTS`` 非空时生效; 其它情况一律空集。
    默认路径(未设环境变量或 DEBUG=false)不得放宽任何公网 https 校验。
    """
    try:
        from django.conf import settings as django_settings

        if (
            not bool(getattr(django_settings, "DEBUG", False))
            or os.environ.get("DJANGO_SETTINGS_MODULE") != E2E_RUNTIME_SETTINGS_MODULE
        ):
            return frozenset()
    except Exception:
        # Django 尚未配置时不允许任何 E2E 放宽(单元测试未 setup 时走严格路径)。
        return frozenset()
    raw = os.environ.get(E2E_ALLOW_INSECURE_WEBHOOK_HOSTS_ENV, "").strip()
    if not raw:
        return frozenset()
    hosts: set[str] = set()
    for part in raw.split(","):
        host = part.strip().lower().rstrip(".")
        if host:
            hosts.add(host)
    return frozenset(hosts)


def is_e2e_insecure_webhook_host(hostname: str) -> bool:
    if not hostname:
        return False
    try:
        normalized = normalize_hostname(hostname)
    except InvalidWebhookUrlError:
        return False
    return normalized in e2e_allowed_insecure_webhook_hosts()


def require_secure_url(url: str, *, allow_local_http: bool) -> None:
    # https 一律放行; http 只在显式允许且主机是本地环回时放行, 否则快速失败。
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme == "https":
        return
    if scheme == "http" and allow_local_http and host in LOCAL_HTTP_HOSTS:
        return
    raise InsecureUrlError


def assert_public_host(hostname: str, *, allow_local: bool) -> None:
    # 解析主机并拒绝内网/环回/链路本地/保留/多播地址, 防止 SSRF 打内网与云元数据端点。
    if not hostname:
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE)
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as error:
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE) from error
    for addr_info in addr_infos:
        raw_ip = addr_info[4][0]
        ip = ipaddress.ip_address(raw_ip)
        # 链路本地(含 169.254.169.254 云元数据)、多播、保留、未指定地址一律禁止。
        blocked = ip.is_multicast or ip.is_reserved or ip.is_unspecified or ip.is_link_local
        if not allow_local:
            blocked = blocked or ip.is_private or ip.is_loopback
        if blocked:
            raise BlockedHostError


def normalize_hostname(hostname: str) -> str:
    try:
        normalized = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise InvalidWebhookUrlError from error
    if not normalized or normalized != hostname.lower():
        # 拒绝尾点等同名异形, 避免 allowlist 与 TLS Host/SNI 采用不同口径。
        raise InvalidWebhookUrlError
    return normalized


type SocketAddress = tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes]
type AddressInfo = tuple[socket.AddressFamily, socket.SocketKind, int, str, SocketAddress]

_DNS_RESOLVER_CAPACITY = threading.BoundedSemaphore(DNS_RESOLVER_MAX_IN_FLIGHT)


def resolve_public_addresses(
    hostname: str,
    *,
    port: int,
    timeout_seconds: float | None = None,
) -> tuple[str, ...]:
    if not hostname:
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE)
    addr_infos = _resolve_addresses(hostname, port=port, timeout_seconds=timeout_seconds)
    addresses: list[str] = []
    for addr_info in addr_infos:
        raw_ip = addr_info[4][0]
        if not isinstance(raw_ip, str):
            raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE)
        ip = ipaddress.ip_address(raw_ip)
        # is_global 同时排除私网、环回、链路本地、保留、组播、未指定及共享地址。
        if not ip.is_global:
            raise BlockedHostError
        canonical = str(ip)
        if canonical not in addresses:
            addresses.append(canonical)
    if not addresses:
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE)
    return tuple(addresses)


def _resolve_addresses(
    hostname: str,
    *,
    port: int,
    timeout_seconds: float | None,
) -> tuple[AddressInfo, ...]:
    if timeout_seconds is None:
        try:
            return tuple(socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM))
        except socket.gaierror as error:
            raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE) from error

    if not _DNS_RESOLVER_CAPACITY.acquire(blocking=False):
        raise BlockedHostError(DNS_RESOLVER_QUEUE_FULL_MESSAGE)
    try:
        return _resolve_addresses_subprocess(
            hostname=hostname,
            port=port,
            timeout_seconds=timeout_seconds,
        )
    finally:
        _DNS_RESOLVER_CAPACITY.release()


def _resolve_addresses_subprocess(
    *,
    hostname: str,
    port: int,
    timeout_seconds: float,
) -> tuple[AddressInfo, ...]:
    process = subprocess.Popen(  # noqa: S603 - 固定解释器和脚本, 主机名只作为 argv 传入.
        [sys.executable, "-I", "-c", DNS_RESOLVER_SCRIPT, hostname, str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={},
        close_fds=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        _terminate_resolver_subprocess(process)
        raise BlockedHostError(DNS_RESOLUTION_TIMEOUT_MESSAGE) from error
    if len(stdout) > DNS_RESOLVER_OUTPUT_MAX_BYTES or len(stderr) > DNS_RESOLVER_OUTPUT_MAX_BYTES:
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE)
    if process.returncode != 0:
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE)
    return _parse_resolver_output(stdout)


def _terminate_resolver_subprocess(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        _ = process.wait(timeout=DNS_RESOLVER_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            process.kill()
        _ = process.wait(timeout=DNS_RESOLVER_TERMINATE_GRACE_SECONDS)


def _parse_resolver_output(stdout: bytes) -> tuple[AddressInfo, ...]:
    try:
        payload = cast("object", json.loads(stdout.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE) from error
    if not isinstance(payload, dict):
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE)
    payload_mapping = cast("Mapping[str, object]", payload)
    if payload_mapping.get("gaierror") is True:
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE)
    if payload_mapping.get("error") is True:
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE)
    addresses = payload_mapping.get("ok")
    if not isinstance(addresses, list):
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE)
    addr_infos: list[AddressInfo] = []
    for raw_ip in cast("list[object]", addresses):
        if not isinstance(raw_ip, str):
            raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE)
        addr_infos.append(_address_info_for_ip(raw_ip))
    return tuple(addr_infos)


def _address_info_for_ip(raw_ip: str) -> AddressInfo:
    ip = ipaddress.ip_address(raw_ip)
    family = socket.AF_INET6 if ip.version == IPV6_VERSION else socket.AF_INET
    socket_address: SocketAddress = (
        (raw_ip, 0, 0, 0) if family == socket.AF_INET6 else (raw_ip, 0)
    )
    return (family, socket.SOCK_STREAM, 0, "", socket_address)


def validate_public_https_url(
    url: str,
    *,
    allowed_hosts: Collection[str] | None = None,
    dns_timeout_seconds: float | None = None,
) -> ValidatedHttpsUrl:
    parsed_url = parse_https_url(url, allowed_hosts=allowed_hosts)
    if parsed_url.allow_insecure_http:
        # E2E 窄门: 不做公网 DNS 解析; 字面 IP 直接钉住, 主机名仅允许环回解析。
        addresses = _e2e_resolve_addresses(parsed_url.hostname, port=parsed_url.port)
        return ValidatedHttpsUrl(
            hostname=parsed_url.hostname,
            port=parsed_url.port,
            request_target=parsed_url.request_target,
            addresses=addresses,
            allow_insecure_http=True,
        )
    if dns_timeout_seconds is None:
        addresses = resolve_public_addresses(parsed_url.hostname, port=parsed_url.port)
    else:
        addresses = resolve_public_addresses(
            parsed_url.hostname,
            port=parsed_url.port,
            timeout_seconds=dns_timeout_seconds,
        )
    return ValidatedHttpsUrl(
        hostname=parsed_url.hostname,
        port=parsed_url.port,
        request_target=parsed_url.request_target,
        addresses=addresses,
        allow_insecure_http=False,
    )


def parse_https_url(
    url: str,
    *,
    allowed_hosts: Collection[str] | None = None,
) -> ValidatedHttpsUrl:
    parsed, raw_hostname, declared_port = _split_webhook_url(url)
    hostname = normalize_hostname(raw_hostname)
    port, allow_insecure_http = _resolve_scheme_and_port(
        scheme=parsed.scheme.lower(),
        hostname=hostname,
        declared_port=declared_port,
    )
    _reject_host_not_allowed(hostname, allowed_hosts=allowed_hosts)
    return ValidatedHttpsUrl(
        hostname=hostname,
        port=port,
        request_target=_request_target(parsed),
        addresses=(),
        allow_insecure_http=allow_insecure_http,
    )


def _split_webhook_url(url: str) -> tuple[SplitResult, str, int | None]:
    """拆出 URL 各部件并拒绝空白/控制字符、userinfo、fragment 与无主机名的形态。"""
    if not url or any(
        character.isspace() or ord(character) < CONTROL_CHARACTER_LIMIT for character in url
    ):
        raise InvalidWebhookUrlError
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise InvalidWebhookUrlError from error
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise InvalidWebhookUrlError
    return parsed, parsed.hostname, port


def _resolve_scheme_and_port(
    *,
    scheme: str,
    hostname: str,
    declared_port: int | None,
) -> tuple[int, bool]:
    """返回 (最终端口, 是否允许明文 http)。E2E 放行名单是唯一的明文窄门。"""
    if hostname in e2e_allowed_insecure_webhook_hosts():
        return _e2e_scheme_and_port(scheme=scheme, declared_port=declared_port)
    return _public_https_scheme_and_port(scheme=scheme, hostname=hostname, port=declared_port)


def _e2e_scheme_and_port(*, scheme: str, declared_port: int | None) -> tuple[int, bool]:
    # E2E-only: 允许 http/https + 任意端口 + 环回字面 IP; 仍拒绝 userinfo/fragment。
    if scheme not in {"http", "https"}:
        raise InvalidWebhookUrlError
    port = declared_port
    if port is None:
        port = 80 if scheme == "http" else 443
    if port < 1 or port > 65535:
        raise InvalidWebhookUrlError
    return port, scheme == "http"


def _public_https_scheme_and_port(
    *,
    scheme: str,
    hostname: str,
    port: int | None,
) -> tuple[int, bool]:
    if (
        scheme != "https"
        or port not in (None, 443)
    ):
        raise InvalidWebhookUrlError
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and not literal_ip.is_global:
        raise BlockedHostError
    return 443, False


def _reject_host_not_allowed(hostname: str, *, allowed_hosts: Collection[str] | None) -> None:
    if allowed_hosts is None:
        return
    normalized_allowed_hosts = {normalize_hostname(host) for host in allowed_hosts}
    if hostname not in normalized_allowed_hosts:
        raise InvalidWebhookUrlError(WEBHOOK_HOST_NOT_ALLOWED_MESSAGE)


def _request_target(parsed: SplitResult) -> str:
    path = _request_target_path(parsed.path or "/")
    query = _request_target_query(parsed.query)
    return f"{path}?{query}" if query else path


def _e2e_resolve_addresses(hostname: str, *, port: int) -> tuple[str, ...]:
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if not literal_ip.is_loopback:
            raise BlockedHostError
        return (str(literal_ip),)
    # 仅解析到环回; 禁止 E2E 放行主机名再解析到公网或其它内网。
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE) from error
    addresses: list[str] = []
    for info in infos:
        raw_ip = info[4][0]
        if not isinstance(raw_ip, str):
            continue
        ip = ipaddress.ip_address(raw_ip)
        if not ip.is_loopback:
            raise BlockedHostError
        canonical = str(ip)
        if canonical not in addresses:
            addresses.append(canonical)
    if not addresses:
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE)
    return tuple(addresses)


def _request_target_path(path: str) -> str:
    return quote(path, safe="/!$&'()*+,;=:@%~-._")


def _request_target_query(query: str) -> str:
    return quote(query, safe="/?!$&'()*+,;=:@%~-._")


def read_urlopen_body_bounded(
    response: HeaderReadableResponse,
    *,
    started_at: float,
    total_timeout_seconds: float,
    max_response_bytes: int,
    monotonic: Callable[[], float] = time.monotonic,
) -> bytes:
    content_length = response.getheader("Content-Length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise InvalidContentLengthError from error
        if declared_length < 0:
            raise InvalidContentLengthError
        if declared_length > max_response_bytes:
            raise HttpResponseTooLargeError

    chunks: list[bytes] = []
    observed = 0
    while True:
        remaining = _remaining_response_deadline_seconds(
            started_at=started_at,
            total_timeout_seconds=total_timeout_seconds,
            monotonic=monotonic,
        )
        _set_response_socket_timeout(response, remaining)
        chunk = response.read(min(HTTP_READ_CHUNK_BYTES, max_response_bytes + 1 - observed))
        _ = _remaining_response_deadline_seconds(
            started_at=started_at,
            total_timeout_seconds=total_timeout_seconds,
            monotonic=monotonic,
        )
        if not chunk:
            return b"".join(chunks)
        observed += len(chunk)
        if observed > max_response_bytes:
            raise HttpResponseTooLargeError
        chunks.append(chunk)


def _remaining_response_deadline_seconds(
    *,
    started_at: float,
    total_timeout_seconds: float,
    monotonic: Callable[[], float],
) -> float:
    remaining = total_timeout_seconds - (monotonic() - started_at)
    if remaining <= 0:
        raise HttpResponseDeadlineExceededError
    return remaining


def _set_response_socket_timeout(response: object, timeout_seconds: float) -> None:
    socket_candidate = _response_socket_candidate(response)
    if isinstance(socket_candidate, socket.socket):
        socket_candidate.settimeout(timeout_seconds)


def _response_socket_candidate(response: object) -> object | None:
    current: object | None = response
    for attribute in ("fp", "raw", "_sock"):
        current = getattr(current, attribute, None)
        if current is None:
            return None
    return current
