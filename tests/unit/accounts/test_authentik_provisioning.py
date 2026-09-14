from __future__ import annotations

from io import StringIO
from typing import TYPE_CHECKING, cast, final
from urllib.error import URLError

import pytest
from django.core.cache import cache
from django.core.management import call_command

from easyauth.accounts.authentik_provisioning import (
    USER_PROVISION_UNAVAILABLE_MESSAGE,
    MirrorAuthentikUsersResult,
    ProvisionKind,
    UserProvisionUnavailableError,
    authentik_payload_from_core_user,
    ensure_user_mirror_for_permission_query,
    mirror_missing_authentik_users,
    provision_user_from_authentik,
)
from easyauth.accounts.models import UserMirror
from easyauth.integrations.authentik.admin_client import (
    ADMIN_API_UNAVAILABLE_MESSAGE,
    AuthentikAdminError,
    AuthentikAdminNotConfiguredError,
    AuthentikAdminUserNotFoundError,
)
from easyauth.integrations.authentik.directory_sync_types import AuthentikDirectorySyncResult
from easyauth.integrations.authentik.payloads import AuthentikPayloadError
from easyauth.tasks import authentik as authentik_tasks

if TYPE_CHECKING:
    from collections.abc import Iterator

    from easyauth.integrations.authentik.admin_client import AdminJson, AuthentikAdminClient

pytestmark = pytest.mark.django_db

_SUB = "fdac7e94-a7ab-4311-9b57-436f3a35f3cb"
_CORP_ID = "dingtalk-corp"
_USER_ID = "user-chenning"
_SOURCE_SLUG = "dingtalk"
_MISS_CACHE_KEY = f"authentik-provision-miss:{_SUB}"
_UNAVAILABLE_CACHE_KEY = "authentik-provision-unavailable"


@final
class _FakeAdminClient:
    def __init__(
        self,
        *,
        entry: AdminJson | None = None,
        users: tuple[AdminJson, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.entry = entry
        self.users = users
        self.error = error
        self.get_user_calls = 0

    def get_user_by_uuid(self, sub: str) -> AdminJson:
        self.get_user_calls += 1
        if self.error is not None:
            raise self.error
        assert self.entry is not None
        assert sub == self.entry["uuid"]
        return self.entry

    def iter_active_users(self) -> Iterator[AdminJson]:
        return iter(self.users)


def _eligible_core_user(*, uuid: str = _SUB, name: str = "陈柠") -> AdminJson:
    return {
        "pk": 7,
        "username": "17371695448201074",
        "name": name,
        "is_active": True,
        "email": "",
        "uid": "hash-not-sub",
        "uuid": uuid,
        "type": "internal",
        "attributes": {
            "dingtalk": {
                "name": name,
                "nick": name,
                "title": "",
                "avatar": "",
                "corp_id": _CORP_ID,
                "user_id": _USER_ID,
                "union_id": "",
                "job_number": "",
                "source_slug": _SOURCE_SLUG,
                "dept_id_list": [990739069],
            },
            "dingtalk_sources": {"ignored": True},
            "goauthentik.io/user/sources": ["钉钉登录"],
        },
    }


def _service_account_entry(*, uuid: str = "akadmin-uuid") -> AdminJson:
    return {
        "pk": 1,
        "name": "akadmin",
        "is_active": True,
        "uuid": uuid,
        "attributes": {},
    }


def _patch_admin_client(monkeypatch: pytest.MonkeyPatch, client: _FakeAdminClient) -> None:
    monkeypatch.setattr(
        "easyauth.accounts.authentik_provisioning.AuthentikAdminClient.from_settings",
        lambda: client,
    )


def test_authentik_payload_from_core_user_keeps_understood_fields_and_omits_empty() -> None:
    payload = authentik_payload_from_core_user(_eligible_core_user())

    assert payload["context"] == {"sub": _SUB}
    assert payload["is_active"] is True
    user = payload["user"]
    assert isinstance(user, dict)
    assert user["name"] == "陈柠"
    assert "email" not in user
    attributes = user["attributes"]
    assert isinstance(attributes, dict)
    assert set(attributes) == {"dingtalk"}
    dingtalk = attributes["dingtalk"]
    assert isinstance(dingtalk, dict)
    assert dingtalk["corp_id"] == _CORP_ID
    assert dingtalk["user_id"] == _USER_ID
    assert dingtalk["source_slug"] == _SOURCE_SLUG


def test_authentik_payload_from_core_user_copies_top_level_avatar() -> None:
    entry = _eligible_core_user()
    entry["avatar"] = "https://static-legacy.dingtalk.com/media/core.jpg"

    payload = authentik_payload_from_core_user(entry)

    user = payload["user"]
    assert isinstance(user, dict)
    attributes = user["attributes"]
    assert isinstance(attributes, dict)
    assert attributes["avatar"] == "https://static-legacy.dingtalk.com/media/core.jpg"


def test_authentik_payload_from_core_user_rejects_missing_uuid() -> None:
    entry = _eligible_core_user()
    del entry["uuid"]

    with pytest.raises(AuthentikPayloadError, match="uuid"):
        _ = authentik_payload_from_core_user(entry)


def test_provision_user_creates_mirror_from_directory_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache.clear()
    client = _FakeAdminClient(entry=_eligible_core_user())
    _patch_admin_client(monkeypatch, client)

    outcome = provision_user_from_authentik(_SUB)

    assert outcome.kind is ProvisionKind.CREATED
    user = outcome.user
    assert user is not None
    assert user.authentik_user_id == _SUB
    assert user.name == "陈柠"
    assert user.dingtalk_source_slug == _SOURCE_SLUG
    assert user.dingtalk_corp_id == _CORP_ID
    assert user.dingtalk_userid == _USER_ID
    assert cache.get(_MISS_CACHE_KEY) is None
    assert UserMirror.objects.filter(authentik_user_id=_SUB).count() == 1


def test_provision_user_returns_existing_mirror_without_calling_authentik(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = UserMirror.objects.create(authentik_user_id=_SUB, name="已有")
    client = _FakeAdminClient(entry=_eligible_core_user())
    _patch_admin_client(monkeypatch, client)

    outcome = provision_user_from_authentik(_SUB)

    assert outcome.kind is ProvisionKind.EXISTING
    assert outcome.user is not None
    assert outcome.user.pk == existing.pk
    assert client.get_user_calls == 0


def test_provision_user_skips_entries_without_dingtalk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache.clear()
    client = _FakeAdminClient(entry=_service_account_entry(uuid=_SUB))
    _patch_admin_client(monkeypatch, client)

    outcome = provision_user_from_authentik(_SUB)

    assert outcome.kind is ProvisionKind.NOT_ELIGIBLE
    assert outcome.user is None
    assert not UserMirror.objects.filter(authentik_user_id=_SUB).exists()
    assert cache.get(_MISS_CACHE_KEY) == 1
    assert client.get_user_calls == 1
    assert provision_user_from_authentik(_SUB).kind is ProvisionKind.NOT_FOUND
    assert client.get_user_calls == 1


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (AuthentikAdminNotConfiguredError(), ProvisionKind.NOT_ELIGIBLE),
        (AuthentikAdminUserNotFoundError(), ProvisionKind.NOT_FOUND),
    ],
)
def test_provision_user_negative_caches_definite_admin_answers(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    kind: ProvisionKind,
) -> None:
    cache.clear()
    client = _FakeAdminClient(error=error)
    _patch_admin_client(monkeypatch, client)

    with caplog.at_level("WARNING"):
        outcome = provision_user_from_authentik(_SUB)

    assert outcome.kind is kind
    assert outcome.user is None
    assert cache.get(_MISS_CACHE_KEY) == 1
    assert cache.get(_UNAVAILABLE_CACHE_KEY) is None
    assert _SUB in caplog.text
    assert client.get_user_calls == 1
    assert provision_user_from_authentik(_SUB).kind is ProvisionKind.NOT_FOUND
    assert client.get_user_calls == 1


@pytest.mark.parametrize(
    "error",
    [
        AuthentikAdminError(ADMIN_API_UNAVAILABLE_MESSAGE),
        AuthentikAdminError("Authentik 管理 API 请求失败(HTTP 503)。"),
        URLError("timed out"),
        TimeoutError(),
    ],
)
def test_provision_user_marks_transient_admin_failure_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    cache.clear()
    client = _FakeAdminClient(error=error)
    _patch_admin_client(monkeypatch, client)

    with caplog.at_level("WARNING"):
        outcome = provision_user_from_authentik(_SUB)

    assert outcome.kind is ProvisionKind.UNAVAILABLE
    assert cache.get(_MISS_CACHE_KEY) is None
    assert cache.get(_UNAVAILABLE_CACHE_KEY) == 1
    assert _SUB in caplog.text
    assert client.get_user_calls == 1
    assert provision_user_from_authentik("other-unknown-sub").kind is ProvisionKind.UNAVAILABLE
    assert client.get_user_calls == 1


def test_ensure_user_mirror_raises_unavailable_for_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache.clear()
    client = _FakeAdminClient(error=URLError("timed out"))
    _patch_admin_client(monkeypatch, client)

    with pytest.raises(UserProvisionUnavailableError, match=USER_PROVISION_UNAVAILABLE_MESSAGE):
        _ = ensure_user_mirror_for_permission_query(_SUB)


def test_provision_user_invalid_payload_is_negative_cached_not_raised(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache.clear()
    client = _FakeAdminClient(
        entry={
            "uuid": _SUB,
            "is_active": True,
            "attributes": {"dingtalk": "not-object"},
        },
    )
    _patch_admin_client(monkeypatch, client)

    with caplog.at_level("ERROR"):
        outcome = provision_user_from_authentik(_SUB)

    assert outcome.kind is ProvisionKind.INVALID
    assert outcome.user is None
    assert cache.get(_MISS_CACHE_KEY) == 1
    assert "not-object" in caplog.text or "dingtalk" in caplog.text
    assert not UserMirror.objects.filter(authentik_user_id=_SUB).exists()


def test_provision_user_skips_incomplete_dingtalk_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache.clear()
    entry = _eligible_core_user()
    attributes = entry["attributes"]
    assert isinstance(attributes, dict)
    dingtalk = attributes["dingtalk"]
    assert isinstance(dingtalk, dict)
    dingtalk["source_slug"] = ""
    client = _FakeAdminClient(entry=entry)
    _patch_admin_client(monkeypatch, client)

    outcome = provision_user_from_authentik(_SUB)

    assert outcome.kind is ProvisionKind.NOT_ELIGIBLE
    assert cache.get(_MISS_CACHE_KEY) == 1
    assert not UserMirror.objects.filter(authentik_user_id=_SUB).exists()


def test_provision_user_invalid_when_dingtalk_person_already_mirrored(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache.clear()
    _ = UserMirror.objects.create(
        authentik_user_id="older-authentik-uuid",
        name="旧镜像",
        dingtalk_source_slug=_SOURCE_SLUG,
        dingtalk_corp_id=_CORP_ID,
        dingtalk_userid=_USER_ID,
    )
    client = _FakeAdminClient(entry=_eligible_core_user())
    _patch_admin_client(monkeypatch, client)

    with caplog.at_level("ERROR"):
        outcome = provision_user_from_authentik(_SUB)

    assert outcome.kind is ProvisionKind.INVALID
    assert cache.get(_MISS_CACHE_KEY) == 1
    assert _SUB in caplog.text
    assert not UserMirror.objects.filter(authentik_user_id=_SUB).exists()


def test_mirror_missing_authentik_users_creates_only_new_directory_users() -> None:
    existing_uuid = "11111111-1111-1111-1111-111111111111"
    _ = UserMirror.objects.create(
        authentik_user_id=existing_uuid,
        name="旧名",
        dingtalk_source_slug=_SOURCE_SLUG,
        dingtalk_corp_id=_CORP_ID,
        dingtalk_userid="already-bound",
    )
    client = _FakeAdminClient(
        users=(
            _eligible_core_user(uuid=existing_uuid, name="新名不应覆盖"),
            _eligible_core_user(),
            _service_account_entry(),
        ),
    )

    result = mirror_missing_authentik_users(cast("AuthentikAdminClient", client))

    assert result == MirrorAuthentikUsersResult(
        scanned=3,
        created=1,
        skipped_no_directory_identity=1,
        skipped_existing=1,
    )
    created = UserMirror.objects.get(authentik_user_id=_SUB)
    assert created.dingtalk_userid == _USER_ID
    existing = UserMirror.objects.get(authentik_user_id=existing_uuid)
    assert existing.name == "旧名"
    assert existing.dingtalk_userid == "already-bound"


def test_mirror_missing_rechecks_existence_before_upsert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _empty_then_create(*args: object, **kwargs: object) -> list[str]:
        del args, kwargs
        if not UserMirror.objects.filter(authentik_user_id=_SUB).exists():
            _ = UserMirror.objects.create(
                authentik_user_id=_SUB,
                name="旧名",
                dingtalk_source_slug=_SOURCE_SLUG,
                dingtalk_corp_id=_CORP_ID,
                dingtalk_userid=_USER_ID,
            )
        return []

    monkeypatch.setattr(UserMirror.objects, "values_list", _empty_then_create)
    client = _FakeAdminClient(users=(_eligible_core_user(name="新名不应覆盖"),))

    result = mirror_missing_authentik_users(cast("AuthentikAdminClient", client))

    assert result.created == 0
    assert result.skipped_existing == 1
    assert UserMirror.objects.get(authentik_user_id=_SUB).name == "旧名"


def test_sync_dingtalk_directory_task_mirrors_before_directory_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    monkeypatch.setattr(
        "easyauth.tasks.authentik.AuthentikDirectoryClient.from_settings",
        lambda: object(),
    )

    def _sync(_client: object) -> AuthentikDirectorySyncResult:
        order.append("sync")
        return AuthentikDirectorySyncResult(
            department_count=1,
            user_count=2,
            org_context_count=2,
            sync_state_count=1,
        )

    monkeypatch.setattr("easyauth.tasks.authentik.sync_authentik_dingtalk_directory", _sync)
    monkeypatch.setattr(
        "easyauth.tasks.authentik.AuthentikAdminClient.from_settings",
        lambda: object(),
    )

    def _mirror(_client: object) -> MirrorAuthentikUsersResult:
        order.append("mirror")
        return MirrorAuthentikUsersResult(
            scanned=4,
            created=1,
            skipped_no_directory_identity=1,
            skipped_existing=2,
        )

    monkeypatch.setattr("easyauth.tasks.authentik.mirror_missing_authentik_users", _mirror)

    result = authentik_tasks.sync_dingtalk_directory_task.run()

    assert order == ["mirror", "sync"]
    assert result["user_count"] == 2
    assert result["scanned"] == 4
    assert result["created"] == 1
    assert result["skipped_no_directory_identity"] == 1
    assert result["skipped_existing"] == 2


def test_sync_dingtalk_directory_task_continues_when_mirror_scan_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    order: list[str] = []
    monkeypatch.setattr(
        "easyauth.tasks.authentik.AuthentikDirectoryClient.from_settings",
        lambda: object(),
    )

    def _sync(_client: object) -> AuthentikDirectorySyncResult:
        order.append("sync")
        return AuthentikDirectorySyncResult(
            department_count=1,
            user_count=2,
            org_context_count=2,
            sync_state_count=1,
        )

    monkeypatch.setattr("easyauth.tasks.authentik.sync_authentik_dingtalk_directory", _sync)
    monkeypatch.setattr(
        "easyauth.tasks.authentik.AuthentikAdminClient.from_settings",
        lambda: object(),
    )

    def _fail_mirror(_client: object) -> MirrorAuthentikUsersResult:
        order.append("mirror")
        raise AuthentikAdminError(ADMIN_API_UNAVAILABLE_MESSAGE)

    monkeypatch.setattr("easyauth.tasks.authentik.mirror_missing_authentik_users", _fail_mirror)

    with caplog.at_level("WARNING"):
        result = authentik_tasks.sync_dingtalk_directory_task.run()

    assert order == ["mirror", "sync"]
    assert result["user_count"] == 2
    assert "scanned" not in result
    assert "补齐失败" in caplog.text


def test_sync_dingtalk_directory_task_skips_mirror_when_admin_not_configured(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "easyauth.tasks.authentik.AuthentikDirectoryClient.from_settings",
        lambda: object(),
    )
    monkeypatch.setattr(
        "easyauth.tasks.authentik.sync_authentik_dingtalk_directory",
        lambda _client: AuthentikDirectorySyncResult(
            department_count=0,
            user_count=0,
            org_context_count=0,
            sync_state_count=0,
        ),
    )

    def _not_configured() -> AuthentikAdminClient:
        raise AuthentikAdminNotConfiguredError

    monkeypatch.setattr(
        "easyauth.tasks.authentik.AuthentikAdminClient.from_settings",
        _not_configured,
    )

    with caplog.at_level("WARNING"):
        result = authentik_tasks.sync_dingtalk_directory_task.run()

    assert "scanned" not in result
    assert "跳过 UserMirror 补齐" in caplog.text


def test_mirror_authentik_users_command_prints_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "easyauth.accounts.management.commands.mirror_authentik_users.AuthentikAdminClient.from_settings",
        lambda: object(),
    )
    monkeypatch.setattr(
        "easyauth.accounts.management.commands.mirror_authentik_users.mirror_missing_authentik_users",
        lambda _client: MirrorAuthentikUsersResult(
            scanned=3,
            created=1,
            skipped_no_directory_identity=1,
            skipped_existing=1,
        ),
    )
    output = StringIO()

    call_command("mirror_authentik_users", stdout=output)

    text = output.getvalue()
    assert "scanned=3" in text
    assert "created=1" in text
    assert "skipped_no_directory_identity=1" in text
    assert "skipped_existing=1" in text
