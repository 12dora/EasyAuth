from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    import pytest


def test_manage_loads_env_local_without_overriding_existing_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        """# 本地 authentik 配置
EASYAUTH_AUTHENTIK_OIDC_ISSUER=https://auth.example.test/application/o/easyauth/
EASYAUTH_AUTHENTIK_OIDC_SCOPES="openid profile email"
EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=easyauth-from-file""",
        encoding="utf-8",
    )
    monkeypatch.delenv("EASYAUTH_AUTHENTIK_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("EASYAUTH_AUTHENTIK_OIDC_SCOPES", raising=False)
    monkeypatch.setenv("EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID", "already-set")

    manage = _load_manage_module()

    manage.load_local_env(env_file)

    assert (
        manage.os.environ["EASYAUTH_AUTHENTIK_OIDC_ISSUER"]
        == "https://auth.example.test/application/o/easyauth/"
    )
    assert manage.os.environ["EASYAUTH_AUTHENTIK_OIDC_SCOPES"] == "openid profile email"
    assert manage.os.environ["EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID"] == "already-set"


def _load_manage_module() -> ModuleType:
    manage_path = Path(__file__).resolve().parents[3] / "manage.py"
    spec = importlib.util.spec_from_file_location("easyauth_manage_for_test", manage_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
