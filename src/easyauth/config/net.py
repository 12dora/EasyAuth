from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

INSECURE_URL_MESSAGE = "URL 必须使用 https(仅本地开发允许 http://localhost)。"
BLOCKED_HOST_MESSAGE = "目标主机解析到被禁止的内网/环回/保留地址。"
UNRESOLVABLE_HOST_MESSAGE = "目标主机无法解析。"

# 仅本地开发允许明文 http 的主机。
LOCAL_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class InsecureUrlError(ValueError):
    def __init__(self) -> None:
        super().__init__(INSECURE_URL_MESSAGE)


class BlockedHostError(ValueError):
    def __init__(self, message: str = BLOCKED_HOST_MESSAGE) -> None:
        super().__init__(message)


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
