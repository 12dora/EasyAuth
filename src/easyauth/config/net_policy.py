"""URL 与主机策略: https 形态、allowlist、公网/环回判定。"""

from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from urllib.parse import quote, urlparse, urlsplit

from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured

from easyauth.config.net_dns import resolve_public_addresses
from easyauth.config.net_errors import UNRESOLVABLE_HOST_MESSAGE, BlockedHostError

if TYPE_CHECKING:
    from collections.abc import Collection
    from urllib.parse import SplitResult

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

INSECURE_URL_MESSAGE = "URL 必须使用 https(仅本地开发允许 http://localhost)。"
INVALID_WEBHOOK_URL_MESSAGE = (
    "Webhook URL 必须是 https:// 公网地址, 且不得包含用户信息、片段或非 443 端口。"
)
WEBHOOK_HOST_NOT_ALLOWED_MESSAGE = "Webhook URL 的域名不在该应用的允许列表中。"
CONTROL_CHARACTER_LIMIT: Final = 0x20
MAX_NETWORK_PORT: Final = 65_535
# 仅全栈 E2E(DEBUG=1)可放行的环回 webhook 主机列表; 默认空=不放行任何主机。
# 生产/非 DEBUG 下读取该变量也必须仍是空集, 见 e2e_allowed_insecure_webhook_hosts。
E2E_ALLOW_INSECURE_WEBHOOK_HOSTS_ENV: Final = "EASYAUTH_E2E_ALLOW_INSECURE_WEBHOOK_HOSTS"
E2E_RUNTIME_SETTINGS_MODULE: Final = "easyauth.config.settings.e2e"

# 仅本机流量允许明文 http 的主机。host.docker.internal 是 Docker 容器访问宿主的
# 专用主机名(容器化部署里 worker/stream 经它访问宿主上的 Authentik/EasyTrade),
# 流量只走本机 docker bridge, 与环回地址同一信任边界。
LOCAL_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})

__all__ = (
    "E2E_ALLOW_INSECURE_WEBHOOK_HOSTS_ENV",
    "E2E_RUNTIME_SETTINGS_MODULE",
    "INSECURE_URL_MESSAGE",
    "INVALID_WEBHOOK_URL_MESSAGE",
    "LOCAL_HTTP_HOSTS",
    "WEBHOOK_HOST_NOT_ALLOWED_MESSAGE",
    "InsecureUrlError",
    "InvalidWebhookUrlError",
    "ValidatedHttpsUrl",
    "assert_public_host",
    "e2e_allowed_insecure_webhook_hosts",
    "is_e2e_insecure_webhook_host",
    "normalize_hostname",
    "parse_https_url",
    "require_secure_url",
    "validate_public_https_url",
)


class InsecureUrlError(ValueError):
    def __init__(self) -> None:
        super().__init__(INSECURE_URL_MESSAGE)


class InvalidWebhookUrlError(ValueError):
    def __init__(self, message: str = INVALID_WEBHOOK_URL_MESSAGE) -> None:
        super().__init__(message)


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
        if (
            not bool(getattr(django_settings, "DEBUG", False))
            or os.environ.get("DJANGO_SETTINGS_MODULE") != E2E_RUNTIME_SETTINGS_MODULE
        ):
            return frozenset()
    except ImproperlyConfigured:
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
    for raw_ip in _resolved_host_ips(hostname):
        if _host_ip_is_blocked(raw_ip, allow_local=allow_local):
            raise BlockedHostError


def _resolved_host_ips(hostname: str) -> tuple[str | int, ...]:
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as error:
        raise BlockedHostError(UNRESOLVABLE_HOST_MESSAGE) from error
    return tuple(addr_info[4][0] for addr_info in addr_infos)


def _host_ip_is_blocked(raw_ip: str | int, *, allow_local: bool) -> bool:
    ip = ipaddress.ip_address(raw_ip)
    if _ip_is_always_blocked(ip):
        return True
    return not allow_local and _ip_is_local_scope(ip)


def _ip_is_always_blocked(ip: IPAddress) -> bool:
    # 链路本地(含 169.254.169.254 云元数据)、多播、保留、未指定地址一律禁止。
    return ip.is_multicast or ip.is_reserved or ip.is_unspecified or ip.is_link_local


def _ip_is_local_scope(ip: IPAddress) -> bool:
    return ip.is_private or ip.is_loopback


def normalize_hostname(hostname: str) -> str:
    try:
        normalized = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise InvalidWebhookUrlError from error
    if not normalized or normalized != hostname.lower():
        # 拒绝尾点等同名异形, 避免 allowlist 与 TLS Host/SNI 采用不同口径。
        raise InvalidWebhookUrlError
    return normalized


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
    # 经本模块全局名查找, 测试替换 easyauth.config.net_policy.resolve_public_addresses 生效。
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
    if port < 1 or port > MAX_NETWORK_PORT:
        raise InvalidWebhookUrlError
    return port, scheme == "http"


def _public_https_scheme_and_port(
    *,
    scheme: str,
    hostname: str,
    port: int | None,
) -> tuple[int, bool]:
    if scheme != "https" or port not in (None, 443):
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
