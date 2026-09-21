from __future__ import annotations

from typing import TYPE_CHECKING, Self

from easyauth.integrations.authentik import liveness as liveness_module
from easyauth.integrations.authentik.liveness import check_authentik_liveness

if TYPE_CHECKING:
    import pytest


class _Response:
    status: int = 200

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_liveness_counts_internal_authentik_other(monkeypatch: pytest.MonkeyPatch) -> None:
    keys: list[str] = []
    monkeypatch.setattr(
        liveness_module,
        "record_usage",
        lambda key, *_args, **_kwargs: keys.append(str(key)),
        raising=False,
    )
    monkeypatch.setattr(liveness_module, "urlopen", lambda *_args, **_kwargs: _Response())
    result = check_authentik_liveness(
        base_url="https://authentik.test",
        timeout_seconds=1,
    )
    assert result.ok is True
    assert keys == ["internal_authentik_other"]


def test_liveness_missing_base_url_does_not_count(monkeypatch: pytest.MonkeyPatch) -> None:
    keys: list[str] = []
    monkeypatch.setattr(
        liveness_module,
        "record_usage",
        lambda key, *_args, **_kwargs: keys.append(str(key)),
        raising=False,
    )
    result = check_authentik_liveness(base_url="", timeout_seconds=1)
    assert result.ok is False
    assert keys == []
