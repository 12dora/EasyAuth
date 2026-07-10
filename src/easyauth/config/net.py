from __future__ import annotations

import ipaddress
import queue
import socket
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from urllib.parse import urlparse, urlsplit

if TYPE_CHECKING:
    from collections.abc import Collection

INSECURE_URL_MESSAGE = "URL 必须使用 https(仅本地开发允许 http://localhost)。"
BLOCKED_HOST_MESSAGE = "目标主机解析到被禁止的内网/环回/保留地址。"
UNRESOLVABLE_HOST_MESSAGE = "目标主机无法解析。"
DNS_RESOLUTION_TIMEOUT_MESSAGE = "目标主机解析超时。"
INVALID_WEBHOOK_URL_MESSAGE = (
    "Webhook URL 必须是 https:// 公网地址, 且不得包含用户信息、片段或非 443 端口。"
)
WEBHOOK_HOST_NOT_ALLOWED_MESSAGE = "Webhook URL 的域名不在该应用的允许列表中。"
CONTROL_CHARACTER_LIMIT: Final = 0x20

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


@dataclass(frozen=True, slots=True)
class ValidatedHttpsUrl:
    hostname: str
    port: int
    request_target: str
    addresses: tuple[str, ...]


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

    results: queue.Queue[tuple[AddressInfo, ...] | Exception] = queue.Queue(maxsize=1)

    def resolve() -> None:
        try:
            result = tuple(socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM))
        except Exception as error:  # noqa: BLE001 - 跨线程原样传回解析异常。
            results.put(error)
        else:
            results.put(result)

    threading.Thread(target=resolve, daemon=True, name="webhook-dns-resolver").start()
    try:
        result = results.get(timeout=timeout_seconds)
    except queue.Empty as error:
        raise BlockedHostError(DNS_RESOLUTION_TIMEOUT_MESSAGE) from error
    if isinstance(result, Exception):
        if isinstance(result, socket.gaierror):
            raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE) from result
        raise result
    return result


def validate_public_https_url(
    url: str,
    *,
    allowed_hosts: Collection[str] | None = None,
    dns_timeout_seconds: float | None = None,
) -> ValidatedHttpsUrl:
    parsed_url = parse_https_url(url, allowed_hosts=allowed_hosts)
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
    )


def parse_https_url(
    url: str,
    *,
    allowed_hosts: Collection[str] | None = None,
) -> ValidatedHttpsUrl:
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
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port not in (None, 443)
    ):
        raise InvalidWebhookUrlError
    hostname = normalize_hostname(parsed.hostname)
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and not literal_ip.is_global:
        raise BlockedHostError
    if allowed_hosts is not None:
        normalized_allowed_hosts = {normalize_hostname(host) for host in allowed_hosts}
        if hostname not in normalized_allowed_hosts:
            raise InvalidWebhookUrlError(WEBHOOK_HOST_NOT_ALLOWED_MESSAGE)
    path = parsed.path or "/"
    request_target = f"{path}?{parsed.query}" if parsed.query else path
    return ValidatedHttpsUrl(
        hostname=hostname,
        port=443,
        request_target=request_target,
        addresses=(),
    )
