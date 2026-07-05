from __future__ import annotations

from easyauth.applications.dependency_health import redact_summary


def test_redact_strips_redis_url_credentials() -> None:
    # broker 连接错误常内嵌 redis://:password@host, 且不含 "password" 字面子串。
    redacted = redact_summary("ConnectionError: Error connecting to redis://:s3cr3t@cache:6379/0")
    assert "s3cr3t" not in redacted
    assert "redis://cache:6379/0" in redacted


def test_redact_strips_password_containing_unescaped_at_sign() -> None:
    # 口令中含未转义 @ 时, 必须剥离到 userinfo 的最后一个 @, 不能只截到第一个。
    redacted = redact_summary("connect to redis://:p@ss@cache:6379/0 failed")
    assert "p@ss" not in redacted
    assert "ss@cache" not in redacted
    assert "redis://cache:6379/0" in redacted


def test_redact_strips_amqp_and_https_userinfo() -> None:
    redacted = redact_summary("amqp://user:pw@broker/ and https://tok:sec@api.example/status")
    assert "pw" not in redacted
    assert "sec" not in redacted
    assert "amqp://broker/" in redacted
    assert "https://api.example/status" in redacted


def test_redact_masks_bearer_tokens() -> None:
    redacted = redact_summary("Authorization: Bearer ak-abcdef0123456789")
    assert "ak-abcdef0123456789" not in redacted
    assert "Bearer [已隐藏]" in redacted


def test_redact_keeps_benign_summaries_intact() -> None:
    # 不含凭据的摘要不应被破坏 (时间戳里的冒号、普通邮箱等)。
    benign = "同步于 2026-07-05T01:00:00+00:00, users=12, contact user@example.com"
    assert redact_summary(benign) == benign
