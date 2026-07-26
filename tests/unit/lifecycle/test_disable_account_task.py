from __future__ import annotations

from typing import Protocol, cast, final

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.audit.models import AuditLog
from easyauth.integrations.authentik.admin_client import (
    AuthentikAdminNotConfiguredError,
    AuthentikAdminPaginationLimitError,
    AuthentikAdminUserNotFoundError,
)
from easyauth.tasks import lifecycle as task_module

pytestmark = pytest.mark.django_db


@final
class _FailingDisableClient:
    _error: Exception

    def __init__(self, error: Exception) -> None:
        self._error = error

    def disable_user_and_revoke_sessions(self, _authentik_user_id: str) -> object:
        raise self._error


class _DisableAccountTask(Protocol):
    def run(self, user_mirror_id: int) -> str: ...


@pytest.mark.parametrize(
    ("error", "detail"),
    [
        (AuthentikAdminNotConfiguredError(), "authentik_admin_not_configured"),
        (AuthentikAdminPaginationLimitError(), "authentik_admin_pagination_limit"),
        (AuthentikAdminUserNotFoundError(), "authentik_user_not_found"),
    ],
)
def test_disable_account_task_records_failure_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    detail: str,
) -> None:
    user = UserMirror.objects.create(authentik_user_id="ak-disabled-user")
    monkeypatch.setattr(
        "easyauth.tasks.lifecycle.AuthentikAdminClient.from_settings",
        lambda: _FailingDisableClient(error),
    )

    task = cast("_DisableAccountTask", task_module.disable_departed_account_task)
    user_id = cast("int", user.pk)

    with pytest.raises(type(error)):
        _ = task.run(user_id)

    audit = AuditLog.objects.get(event_type="lifecycle_account_disable_failed")
    assert audit.target_id == "ak-disabled-user"
    assert audit.metadata == {"detail": detail}
