from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    import pytest


class ManageModule(Protocol):
    load_local_env: Callable[[Path], None]


def test_manage_loads_env_local_without_overriding_existing_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env.local"
    _ = env_file.write_text(
        """# 本地 authentik 配置
EASYAUTH_AUTHENTIK_OIDC_ISSUER=https://auth.example.test/application/o/easyauth/
EASYAUTH_AUTHENTIK_OIDC_SCOPES="openid profile email"
EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=easyauth-from-file""",
        encoding="utf-8",
    )
    monkeypatch.delenv("EASYAUTH_AUTHENTIK_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("EASYAUTH_AUTHENTIK_OIDC_SCOPES", raising=False)
    monkeypatch.setenv("EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID", "already-set")

    manage = cast("ManageModule", cast("object", _load_manage_module()))

    manage.load_local_env(env_file)

    assert (
        os.environ["EASYAUTH_AUTHENTIK_OIDC_ISSUER"]
        == "https://auth.example.test/application/o/easyauth/"
    )
    assert os.environ["EASYAUTH_AUTHENTIK_OIDC_SCOPES"] == "openid profile email"
    assert os.environ["EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID"] == "already-set"
    assert manage.load_local_env.__module__ == "easyauth.config.local_env"


def _load_manage_module() -> ModuleType:
    manage_path = Path(__file__).resolve().parents[3] / "manage.py"
    spec = importlib.util.spec_from_file_location("easyauth_manage_for_test", manage_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
