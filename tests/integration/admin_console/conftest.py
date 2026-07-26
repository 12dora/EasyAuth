from __future__ import annotations

import pytest

from tests.integration.admin_console.auth_helpers import (
    install_authentik_authority,
    reset_authentik_authority,
)


@pytest.fixture(autouse=True)
def default_console_group_settings(settings: object) -> None:
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("EasyAuth Admins",)


@pytest.fixture(autouse=True)
def fake_authentik_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_authentik_authority()
    install_authentik_authority(monkeypatch)
