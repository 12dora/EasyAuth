"""公网 DNS 解析: 并发闸、隔离子进程与地址过滤。"""

from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
import sys
import threading
from typing import TYPE_CHECKING, Final, cast

from easyauth.config.net_errors import UNRESOLVABLE_HOST_MESSAGE, BlockedHostError

if TYPE_CHECKING:
    from collections.abc import Mapping

DNS_RESOLUTION_TIMEOUT_MESSAGE = "目标主机解析超时。"
DNS_RESOLVER_QUEUE_FULL_MESSAGE = "DNS resolver 队列已满。"
DNS_RESOLVER_MAX_IN_FLIGHT: Final = 32
IPV6_VERSION: Final = 6
DNS_RESOLVER_TERMINATE_GRACE_SECONDS: Final = 0.2
DNS_RESOLVER_OUTPUT_MAX_BYTES: Final = 64 * 1024
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

type SocketAddress = tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes]
type AddressInfo = tuple[socket.AddressFamily, socket.SocketKind, int, str, SocketAddress]

__all__ = (
    "DNS_RESOLUTION_TIMEOUT_MESSAGE",
    "DNS_RESOLVER_MAX_IN_FLIGHT",
    "DNS_RESOLVER_QUEUE_FULL_MESSAGE",
    "DNS_RESOLVER_SCRIPT",
    "resolve_public_addresses",
)

# 测试通过 easyauth.config.net_dns._DNS_RESOLVER_CAPACITY 替换并发闸。
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
    socket_address: SocketAddress = (raw_ip, 0, 0, 0) if family == socket.AF_INET6 else (raw_ip, 0)
    return (family, socket.SOCK_STREAM, 0, "", socket_address)
