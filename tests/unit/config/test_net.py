from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING, ClassVar, Final, Self, cast

import pytest

from easyauth.config.net import (
    DNS_RESOLVER_SCRIPT,
    BlockedHostError,
    HttpResponseDeadlineExceededError,
    InsecureUrlError,
    read_urlopen_body_bounded,
    require_secure_url,
    resolve_public_addresses,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

DNS_TIMEOUT_ATTEMPTS: Final = 32
DNS_TOTAL_ATTEMPTS: Final = DNS_TIMEOUT_ATTEMPTS + 1
DNS_PUBLIC_OUTPUT: Final = b'{"ok":["8.8.8.8"]}'


class _FakeResolverProcess:
    instances: ClassVar[list[Self]] = []
    outcomes: ClassVar[list[bytes | BaseException]] = []

    def __init__(self, args: list[str], **kwargs: object) -> None:
        self.args: list[str] = args
        self.stdin: int = cast("int", kwargs["stdin"])
        self.stdout: int = cast("int", kwargs["stdout"])
        self.stderr: int = cast("int", kwargs["stderr"])
        self.env: dict[str, str] = cast("dict[str, str]", kwargs["env"])
        self.close_fds: bool = cast("bool", kwargs["close_fds"])
        self.returncode: int | None = None
        self.terminated: bool = False
        self.killed: bool = False
        self.wait_calls: int = 0
        self.__class__.instances.append(self)

    def communicate(self, *, timeout: float) -> tuple[bytes, bytes]:
        assert timeout > 0
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        self.returncode = 0
        return outcome, b""

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, *, timeout: float) -> int:
        assert timeout > 0
        self.wait_calls += 1
        self.returncode = -15 if self.terminated else -9
        return self.returncode

    @classmethod
    def reset(cls, outcomes: list[bytes | BaseException]) -> None:
        cls.instances = []
        cls.outcomes = outcomes


@pytest.mark.parametrize(
    "url",
    [
        "https://authentik.example.com",
        "http://localhost:19000",
        "http://127.0.0.1:19000",
        # Docker 容器访问宿主的专用主机名: 流量只走本机 bridge, 与环回同一信任边界。
        "http://host.docker.internal:19000",
    ],
)
def test_require_secure_url_allows_https_and_local_http(url: str) -> None:
    require_secure_url(url, allow_local_http=True)


@pytest.mark.parametrize(
    "url",
    [
        "http://authentik.example.com",
        "http://192.168.1.10:19000",
        "http://evil-host.docker.internal.example.com",
    ],
)
def test_require_secure_url_rejects_remote_http(url: str) -> None:
    with pytest.raises(InsecureUrlError):
        require_secure_url(url, allow_local_http=True)


def test_require_secure_url_rejects_local_http_when_not_allowed() -> None:
    with pytest.raises(InsecureUrlError):
        require_secure_url("http://localhost:19000", allow_local_http=False)


def test_dns_resolver_rejects_when_supervised_capacity_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FullCapacity:
        def acquire(self, *, blocking: bool) -> bool:
            assert blocking is False
            return False

        def release(self) -> None:
            raise AssertionError

    monkeypatch.setattr("easyauth.config.net_dns._DNS_RESOLVER_CAPACITY", FullCapacity())

    with pytest.raises(BlockedHostError, match="DNS resolver 队列已满"):
        _ = resolve_public_addresses("hooks.example.com", port=443, timeout_seconds=0.01)


def test_dns_timeouts_terminate_isolated_resolvers_and_release_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[bytes | BaseException] = [
        subprocess.TimeoutExpired(cmd="resolver", timeout=0.01) for _ in range(DNS_TIMEOUT_ATTEMPTS)
    ]
    outcomes.append(DNS_PUBLIC_OUTPUT)
    _FakeResolverProcess.reset(outcomes)

    monkeypatch.setattr("easyauth.config.net_dns.subprocess.Popen", _FakeResolverProcess)

    for _ in range(DNS_TIMEOUT_ATTEMPTS):
        with pytest.raises(BlockedHostError, match="解析超时"):
            _ = resolve_public_addresses("hooks.example.com", port=443, timeout_seconds=0.01)

    result = resolve_public_addresses("hooks.example.com", port=443, timeout_seconds=0.01)

    assert result == ("8.8.8.8",)
    assert len(_FakeResolverProcess.instances) == DNS_TOTAL_ATTEMPTS
    assert (
        sum(process.terminated for process in _FakeResolverProcess.instances)
        == DNS_TIMEOUT_ATTEMPTS
    )
    assert all(process.wait_calls == 1 for process in _FakeResolverProcess.instances[:-1])
    assert _FakeResolverProcess.instances[-1].terminated is False


def test_dns_resolver_uses_daemon_safe_subprocess_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeResolverProcess.reset([DNS_PUBLIC_OUTPUT])

    monkeypatch.setattr("easyauth.config.net_dns.subprocess.Popen", _FakeResolverProcess)

    result = resolve_public_addresses("hooks.example.com", port=443, timeout_seconds=0.01)

    process = _FakeResolverProcess.instances[0]
    assert result == ("8.8.8.8",)
    assert process.args == [
        sys.executable,
        "-I",
        "-c",
        DNS_RESOLVER_SCRIPT,
        "hooks.example.com",
        "443",
    ]
    assert "hooks.example.com" not in process.args[3]
    assert process.stdin == subprocess.DEVNULL
    assert process.stdout == subprocess.PIPE
    assert process.stderr == subprocess.PIPE
    assert process.env == {}
    assert process.close_fds is True


def test_dns_resolver_maps_subprocess_gaierror_to_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeResolverProcess.reset([b'{"gaierror":true}'])

    monkeypatch.setattr("easyauth.config.net_dns.subprocess.Popen", _FakeResolverProcess)

    with pytest.raises(BlockedHostError, match="无法解析"):
        _ = resolve_public_addresses("hooks.example.com", port=443, timeout_seconds=0.01)


class _Readable:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks: Iterator[bytes] = iter(chunks)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = (exc_type, exc, traceback)

    def read(self, amount: int = -1) -> bytes:
        _ = amount
        return next(self._chunks, b"")

    def getheader(self, name: str) -> str | None:
        _ = name
        return None


def test_bounded_read_rejects_slow_chunk_after_read() -> None:
    monotonic_values = iter((0.0, 2.0))

    with pytest.raises(HttpResponseDeadlineExceededError):
        _ = read_urlopen_body_bounded(
            _Readable([b"x"]),
            started_at=0.0,
            total_timeout_seconds=1.0,
            max_response_bytes=16,
            monotonic=lambda: next(monotonic_values),
        )


def test_bounded_read_rejects_slow_eof_after_read() -> None:
    monotonic_values = iter((0.0, 0.1, 0.1, 2.0))

    with pytest.raises(HttpResponseDeadlineExceededError):
        _ = read_urlopen_body_bounded(
            _Readable([b"x", b""]),
            started_at=0.0,
            total_timeout_seconds=1.0,
            max_response_bytes=16,
            monotonic=lambda: next(monotonic_values),
        )
