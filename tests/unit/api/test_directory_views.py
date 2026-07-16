from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from json import loads
from pathlib import Path
from typing import Any

import pytest
from django.core.cache import cache
from django.test import RequestFactory
from django.utils import timezone

from easyauth.accounts.directory_references import (
    build_department_ref,
    build_dingtalk_user_ref,
)
from easyauth.accounts.models import (
    DingTalkDepartmentMirror,
    DingTalkDirectorySyncState,
    DingTalkUserMirror,
    UserMirror,
)
from easyauth.api.directory_views import (
    directory_departments,
    directory_user_detail,
    directory_user_manager,
    directory_user_subordinates,
    directory_users,
)
from easyauth.applications.models import CAPABILITY_DIRECTORY, App, AppCapability
from easyauth.applications.services import AppPrincipal
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "contract_samples" / "directory"
_CORP_ID = "corp-demo"
_SOURCE = "dingtalk"
_APP_KEY = "easyproject"
_AUTH_HEADER = "Bearer eat_directory_test"
_CACHE_CONTROL = "private, max-age=60"
_EXPECTED_AMBIGUITY_CANDIDATES = 2


def _load_sample(name: str) -> dict[str, Any]:
    return loads((_SAMPLES_DIR / name).read_text(encoding="utf-8"))


def _enable_directory(app: App) -> None:
    _ = AppCapability.objects.create(
        app=app,
        capability=CAPABILITY_DIRECTORY,
        enabled=True,
    )


def _principal(app: App) -> AppPrincipal:
    return AppPrincipal(
        app_id=app.id,
        app_key=app.app_key,
        credential_type="static_token",
        credential_id=101,
        capabilities=frozenset({CAPABILITY_DIRECTORY}),
    )


def _auth(monkeypatch: pytest.MonkeyPatch, app: App) -> None:
    principal = _principal(app)
    monkeypatch.setattr(
        "easyauth.api.directory_views.authenticate_permission_query_token",
        lambda _token: principal,
    )


def _seed_departments() -> None:
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP_ID,
        dept_id="1",
        parent_id="",
        name="杰发科技",
        order=0,
    )
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP_ID,
        dept_id="460001",
        parent_id="1",
        name="研发部",
        order=10,
    )
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP_ID,
        dept_id="470001",
        parent_id="1",
        name="质量委员会",
        order=20,
    )


def _seed_contract_directory(*, with_manager_row: bool = True) -> None:
    _seed_departments()
    _ = DingTalkDirectorySyncState.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP_ID,
        generation=7,
        status="success",
        counters={"users": 3 if with_manager_row else 2, "departments": 3},
        # 上游快照时间只作展示; freshness 使用本地 auto_now 的 last_synced_at。
        finished_at="2020-01-01T00:00:00+00:00",
    )
    if with_manager_row:
        _ = DingTalkUserMirror.objects.create(
            source_slug=_SOURCE,
            corp_id=_CORP_ID,
            user_id="manager8836",
            name="张主管",
            avatar="",
            title="研发经理",
            email="manager@example.com",
            mobile="13800000001",
            employee_number="E0001",
            department_ids=["460001"],
            manager_userid="",
            status="active",
        )
    _ = DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP_ID,
        user_id="user0123",
        name="王小明",
        avatar="https://static-legacy.dingtalk.com/media/xxx.jpg",
        title="后端工程师",
        email="wang@example.com",
        mobile="13800000002",
        employee_number="E0002",
        department_ids=["460001"],
        manager_userid="manager8836",
        status="active",
    )
    _ = DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP_ID,
        user_id="user0456",
        name="李新人",
        avatar="",
        title="测试工程师",
        email="li@example.com",
        mobile="13800000003",
        employee_number="E0003",
        department_ids=["470001", "460001"],
        manager_userid="manager8836",
        status="active",
    )
    _ = UserMirror.objects.create(
        authentik_user_id="f7c31a09e5b24f8d9a1c",
        name="王小明",
        dingtalk_corp_id=_CORP_ID,
        dingtalk_userid="user0123",
        status="active",
    )


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    cache.clear()


def test_directory_users_list_matches_contract_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    # 列表样例仅含两名成员; 不落库主管行以免多出一条。
    _seed_contract_directory(with_manager_row=False)
    request = RequestFactory().get(
        "/api/v1/apps/easyproject/directory/users",
        HTTP_AUTHORIZATION=_AUTH_HEADER,
    )

    response = directory_users(request, _APP_KEY)

    assert response.status_code == HTTPStatus.OK
    assert response["Cache-Control"] == _CACHE_CONTROL
    assert loads(response.content) == _load_sample("users_list.json")


def test_directory_user_detail_matches_contract_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _seed_contract_directory()
    request = RequestFactory().get(
        "/",
        HTTP_AUTHORIZATION=_AUTH_HEADER,
    )

    response = directory_user_detail(request, _APP_KEY, "f7c31a09e5b24f8d9a1c")

    assert response.status_code == HTTPStatus.OK
    assert response["Cache-Control"] == _CACHE_CONTROL
    assert loads(response.content) == _load_sample("user_detail.json")


def test_directory_user_detail_accepts_dt_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _seed_contract_directory()
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)

    response = directory_user_detail(request, _APP_KEY, "dt:user0123")

    assert response.status_code == HTTPStatus.OK
    payload = loads(response.content)
    assert payload["dingtalk_user_id"] == "user0123"
    assert payload["user_id"] == "f7c31a09e5b24f8d9a1c"


def test_directory_users_include_null_user_id_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _seed_contract_directory()
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)

    response = directory_users(request, _APP_KEY)

    payload = loads(response.content)
    null_by_id = {
        item["dingtalk_user_id"]: item for item in payload["data"] if item["user_id"] is None
    }
    assert "user0456" in null_by_id
    assert null_by_id["user0456"]["name"] == "李新人"
    assert null_by_id["user0456"]["dingtalk_user_id"] == "user0456"


def test_directory_users_include_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _seed_contract_directory()
    _ = DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP_ID,
        user_id="departed01",
        name="已离职",
        email="departed@example.com",
        mobile="13800000004",
        employee_number="E0004",
        department_ids=[],
        status="departed",
        is_tombstone=True,
    )
    default_request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)
    include_request = RequestFactory().get(
        "/",
        {"include_inactive": "true"},
        HTTP_AUTHORIZATION=_AUTH_HEADER,
    )

    default_payload = loads(directory_users(default_request, _APP_KEY).content)
    include_payload = loads(directory_users(include_request, _APP_KEY).content)

    assert all(item["active"] for item in default_payload["data"])
    departed = [
        item for item in include_payload["data"] if item["dingtalk_user_id"] == "departed01"
    ]
    assert len(departed) == 1
    assert departed[0]["active"] is False
    assert departed[0]["status"] == "departed"
    assert departed[0]["user_id"] is None
    assert departed[0]["email"] == "departed@example.com"
    assert departed[0]["mobile"] == "13800000004"
    assert departed[0]["employee_number"] == "E0004"


def test_directory_users_snapshot_pin_accepts_current_and_rejects_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _seed_contract_directory()
    first = directory_users(
        RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER),
        _APP_KEY,
    )
    snapshot_id = loads(first.content)["directory_snapshot"]["snapshot_id"]
    pinned = directory_users(
        RequestFactory().get(
            "/",
            {"page": "2", "snapshot_id": snapshot_id},
            HTTP_AUTHORIZATION=_AUTH_HEADER,
        ),
        _APP_KEY,
    )
    drifted = directory_users(
        RequestFactory().get(
            "/",
            {"page": "2", "snapshot_id": "older-generation"},
            HTTP_AUTHORIZATION=_AUTH_HEADER,
        ),
        _APP_KEY,
    )

    assert pinned.status_code == HTTPStatus.OK
    assert loads(pinned.content)["directory_snapshot"]["snapshot_id"] == snapshot_id
    assert drifted.status_code == HTTPStatus.CONFLICT
    error = loads(drifted.content)["error"]
    assert error["code"] == "CONFLICT"
    assert error["details"] == {
        "reason": "snapshot_mismatch",
        "expected_snapshot_id": "older-generation",
        "actual_snapshot_id": snapshot_id,
    }


def test_directory_users_rejects_generation_change_during_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _seed_contract_directory()
    snapshots = iter(
        [
            {"snapshot_id": "generation-7"},
            {"snapshot_id": "generation-8"},
        ],
    )
    monkeypatch.setattr(
        "easyauth.api.directory_views.build_directory_snapshot",
        lambda: next(snapshots),
    )

    response = directory_users(
        RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER),
        _APP_KEY,
    )

    assert response.status_code == HTTPStatus.CONFLICT
    assert loads(response.content)["error"]["details"] == {
        "reason": "snapshot_changed",
        "expected_snapshot_id": "generation-7",
        "actual_snapshot_id": "generation-8",
    }


def test_directory_snapshot_reports_multi_corp_stale_missing_and_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    stale_state = DingTalkDirectorySyncState.objects.create(
        source_slug=_SOURCE,
        corp_id="corp-stale",
        generation=3,
        status="success",
        finished_at="2000-01-01T00:00:00+00:00",
    )
    DingTalkDirectorySyncState.objects.filter(pk=stale_state.pk).update(
        last_synced_at=timezone.now() - timedelta(seconds=601),
    )
    _ = DingTalkDirectorySyncState.objects.create(
        source_slug=_SOURCE,
        corp_id="corp-error",
        generation=4,
        status="error",
        error="上游失败",
        finished_at="2020-01-01T00:00:00+00:00",
    )
    _ = DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id="corp-missing",
        user_id="orphan-user",
        status="disabled",
    )

    response = directory_departments(
        RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER),
        _APP_KEY,
    )

    assert response.status_code == HTTPStatus.OK
    snapshot = loads(response.content)["directory_snapshot"]
    by_corp = {item["corp_id"]: item for item in snapshot["snapshots"]}
    assert by_corp["corp-stale"]["stale"] is True
    assert by_corp["corp-error"]["status"] == "error"
    assert by_corp["corp-error"]["stale"] is True
    assert by_corp["corp-missing"]["status"] == "missing"
    assert by_corp["corp-missing"]["generation"] == -1
    assert snapshot["stale"] is True
    assert snapshot["complete"] is False
    assert snapshot["authoritative"] is False


def test_directory_user_manager_matches_contract_and_reason_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _seed_contract_directory()
    ok_request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)
    missing_request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)
    no_manager_request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)

    ok = directory_user_manager(ok_request, _APP_KEY, "dt:user0123")
    missing = directory_user_manager(missing_request, _APP_KEY, "dt:no-such-user")
    no_manager = directory_user_manager(no_manager_request, _APP_KEY, "dt:manager8836")

    assert ok.status_code == HTTPStatus.OK
    assert loads(ok.content) == _load_sample("user_manager.json")
    assert missing.status_code == HTTPStatus.NOT_FOUND
    assert loads(missing.content)["error"]["details"]["reason"] == "user_not_found"
    assert no_manager.status_code == HTTPStatus.NOT_FOUND
    assert loads(no_manager.content)["error"]["details"]["reason"] == "no_manager"


def test_directory_user_subordinates_matches_contract_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _seed_contract_directory()
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)

    response = directory_user_subordinates(request, _APP_KEY, "dt:manager8836")

    assert response.status_code == HTTPStatus.OK
    assert loads(response.content) == _load_sample("user_subordinates.json")


def test_directory_departments_matches_contract_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _seed_contract_directory()
    # 契约样例只含根与研发部两行; 质量委员会在 seed 中但样例对照过滤后比对核心两行。
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)

    response = directory_departments(request, _APP_KEY)

    assert response.status_code == HTTPStatus.OK
    assert response["Cache-Control"] == _CACHE_CONTROL
    payload = loads(response.content)
    sample = _load_sample("departments_list.json")
    sample_ids = {item["department_id"] for item in sample["data"]}
    filtered = {
        "data": [item for item in payload["data"] if item["department_id"] in sample_ids],
        "directory_snapshot": payload["directory_snapshot"],
    }
    assert filtered == sample


def test_directory_departments_parent_id_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _seed_contract_directory()
    request = RequestFactory().get(
        "/",
        {"parent_id": "1"},
        HTTP_AUTHORIZATION=_AUTH_HEADER,
    )
    missing_parent = RequestFactory().get(
        "/",
        {"parent_id": "no-such"},
        HTTP_AUTHORIZATION=_AUTH_HEADER,
    )

    children = loads(directory_departments(request, _APP_KEY).content)
    empty = loads(directory_departments(missing_parent, _APP_KEY).content)

    assert [item["department_id"] for item in children["data"]] == ["460001", "470001"]
    assert empty["data"] == []


def test_directory_capability_disabled_returns_explicit_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _auth(monkeypatch, app)
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)

    response = directory_users(request, _APP_KEY)

    assert response.status_code == HTTPStatus.FORBIDDEN
    payload = loads(response.content)
    assert payload["error"]["code"] == "PERMISSION_DENIED"
    assert payload["error"]["message"] == "应用未开通目录能力。"


def test_directory_credential_capability_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    principal = AppPrincipal(
        app_id=app.id,
        app_key=app.app_key,
        credential_type="static_token",
        credential_id=102,
    )

    def authenticate(_token: str) -> AppPrincipal:
        return principal

    monkeypatch.setattr(
        "easyauth.api.directory_views.authenticate_permission_query_token",
        authenticate,
    )
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)

    response = directory_users(request, _APP_KEY)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert loads(response.content)["error"]["code"] == "PERMISSION_DENIED"


def test_directory_rate_limit_returns_429_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    monkeypatch.setattr(
        "easyauth.api.directory_views.rate_limit_exceeded",
        lambda *_args, **_kwargs: True,
    )
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)

    response = directory_users(request, _APP_KEY)

    assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert response["Retry-After"] == "60"
    assert loads(response.content)["error"]["code"] == "THROTTLED"


def test_directory_removed_from_dingtalk_still_detailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _ = UserMirror.objects.create(
        authentik_user_id="ak-removed",
        name="历史用户",
        dingtalk_corp_id=_CORP_ID,
        dingtalk_userid="gone-user",
        status="departed",
    )
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)

    response = directory_user_detail(request, _APP_KEY, "ak-removed")

    assert response.status_code == HTTPStatus.OK
    payload = loads(response.content)
    assert payload["user_id"] == "ak-removed"
    assert payload["user_ref"] == "ak-removed"
    assert payload["active"] is False
    assert payload["departments"] == []
    assert payload["manager"] is None


def test_directory_removed_dt_ref_still_detailable_via_user_mirror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dt: 引用已从钉钉目录移除的用户: 经 UserMirror 兜底返回 200 active:false。"""
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _ = UserMirror.objects.create(
        authentik_user_id="ak-removed-dt",
        name="历史用户 DT",
        dingtalk_corp_id=_CORP_ID,
        dingtalk_userid="gone-via-dt",
        status="departed",
    )
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)

    response = directory_user_detail(request, _APP_KEY, "dt:gone-via-dt")

    assert response.status_code == HTTPStatus.OK
    payload = loads(response.content)
    assert payload["user_id"] == "ak-removed-dt"
    assert payload["dingtalk_user_id"] == "gone-via-dt"
    assert payload["active"] is False
    assert payload["departments"] == []
    assert payload["manager"] is None


def test_directory_users_filter_by_department_and_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _seed_contract_directory()
    by_dept = RequestFactory().get(
        "/",
        {"department_id": "470001"},
        HTTP_AUTHORIZATION=_AUTH_HEADER,
    )
    by_manager = RequestFactory().get(
        "/",
        {"manager_id": "dt:manager8836"},
        HTTP_AUTHORIZATION=_AUTH_HEADER,
    )
    by_q = RequestFactory().get(
        "/",
        {"q": "王小"},
        HTTP_AUTHORIZATION=_AUTH_HEADER,
    )

    dept_payload = loads(directory_users(by_dept, _APP_KEY).content)
    manager_payload = loads(directory_users(by_manager, _APP_KEY).content)
    q_payload = loads(directory_users(by_q, _APP_KEY).content)

    assert [item["dingtalk_user_id"] for item in dept_payload["data"]] == ["user0456"]
    assert {item["dingtalk_user_id"] for item in manager_payload["data"]} == {
        "user0123",
        "user0456",
    }
    assert [item["dingtalk_user_id"] for item in q_payload["data"]] == ["user0123"]


def test_multi_corp_scoped_refs_prevent_cross_corp_user_and_relationship_mix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    for corp_id, suffix in (("corp-a", "甲"), ("corp-b", "乙")):
        _ = DingTalkDepartmentMirror.objects.create(
            source_slug=_SOURCE,
            corp_id=corp_id,
            dept_id="shared-dept",
            name=f"共享部门{suffix}",
        )
        _ = DingTalkUserMirror.objects.create(
            source_slug=_SOURCE,
            corp_id=corp_id,
            user_id="shared-manager",
            name=f"主管{suffix}",
            department_ids=["shared-dept"],
            status="active",
        )
        _ = DingTalkUserMirror.objects.create(
            source_slug=_SOURCE,
            corp_id=corp_id,
            user_id="shared-user",
            name="相同姓名",
            department_ids=["shared-dept"],
            manager_userid="shared-manager",
            status="active",
        )
    _ = DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id="corp-a",
        user_id="unique-user",
        name="旧引用唯一用户",
        status="active",
    )
    user_a_ref = build_dingtalk_user_ref(
        source_slug=_SOURCE,
        corp_id="corp-a",
        user_id="shared-user",
    )
    manager_a_ref = build_dingtalk_user_ref(
        source_slug=_SOURCE,
        corp_id="corp-a",
        user_id="shared-manager",
    )
    dept_a_ref = build_department_ref(
        source_slug=_SOURCE,
        corp_id="corp-a",
        department_id="shared-dept",
    )

    ambiguous_detail = directory_user_detail(
        RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER),
        _APP_KEY,
        "dt:shared-user",
    )
    scoped_detail = directory_user_detail(
        RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER),
        _APP_KEY,
        user_a_ref,
    )
    scoped_manager = directory_user_manager(
        RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER),
        _APP_KEY,
        user_a_ref,
    )
    scoped_subordinates = directory_user_subordinates(
        RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER),
        _APP_KEY,
        manager_a_ref,
    )
    ambiguous_department = directory_users(
        RequestFactory().get(
            "/",
            {"department_id": "shared-dept"},
            HTTP_AUTHORIZATION=_AUTH_HEADER,
        ),
        _APP_KEY,
    )
    scoped_department = directory_users(
        RequestFactory().get(
            "/",
            {"department_id": dept_a_ref},
            HTTP_AUTHORIZATION=_AUTH_HEADER,
        ),
        _APP_KEY,
    )
    ambiguous_manager = directory_users(
        RequestFactory().get(
            "/",
            {"manager_id": "dt:shared-manager"},
            HTTP_AUTHORIZATION=_AUTH_HEADER,
        ),
        _APP_KEY,
    )
    scoped_manager_filter = directory_users(
        RequestFactory().get(
            "/",
            {"manager_id": manager_a_ref},
            HTTP_AUTHORIZATION=_AUTH_HEADER,
        ),
        _APP_KEY,
    )
    legacy_unique = directory_user_detail(
        RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER),
        _APP_KEY,
        "dt:unique-user",
    )
    malformed_scoped = directory_user_detail(
        RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER),
        _APP_KEY,
        "dt:v1:not-enough-parts",
    )

    assert ambiguous_detail.status_code == HTTPStatus.CONFLICT
    ambiguity = loads(ambiguous_detail.content)["error"]
    assert ambiguity["details"]["reason"] == "ambiguous_user_ref"
    assert len(ambiguity["details"]["candidate_refs"]) == _EXPECTED_AMBIGUITY_CANDIDATES
    assert loads(scoped_detail.content)["corp_id"] == "corp-a"
    assert loads(scoped_detail.content)["user_ref"] == user_a_ref
    assert loads(scoped_manager.content)["corp_id"] == "corp-a"
    assert {item["corp_id"] for item in loads(scoped_subordinates.content)["data"]} == {
        "corp-a",
    }
    assert ambiguous_department.status_code == HTTPStatus.CONFLICT
    assert loads(ambiguous_department.content)["error"]["details"]["reason"] == (
        "ambiguous_department_ref"
    )
    assert {item["corp_id"] for item in loads(scoped_department.content)["data"]} == {
        "corp-a",
    }
    assert ambiguous_manager.status_code == HTTPStatus.CONFLICT
    assert {item["corp_id"] for item in loads(scoped_manager_filter.content)["data"]} == {
        "corp-a",
    }
    assert legacy_unique.status_code == HTTPStatus.OK
    assert loads(legacy_unique.content)["corp_id"] == "corp-a"
    assert malformed_scoped.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert loads(malformed_scoped.content)["error"]["details"]["reason"] == (
        "invalid_directory_ref"
    )


def test_multi_corp_user_pagination_has_scope_stable_tail_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    for corp_id in ("corp-b", "corp-a"):
        _ = DingTalkUserMirror.objects.create(
            source_slug=_SOURCE,
            corp_id=corp_id,
            user_id="same-user-id",
            name="相同姓名",
            status="active",
        )

    response = directory_users(
        RequestFactory().get(
            "/",
            {"page_size": "1"},
            HTTP_AUTHORIZATION=_AUTH_HEADER,
        ),
        _APP_KEY,
    )
    snapshot_id = loads(response.content)["directory_snapshot"]["snapshot_id"]
    second = directory_users(
        RequestFactory().get(
            "/",
            {"page": "2", "page_size": "1", "snapshot_id": snapshot_id},
            HTTP_AUTHORIZATION=_AUTH_HEADER,
        ),
        _APP_KEY,
    )

    assert loads(response.content)["data"][0]["corp_id"] == "corp-a"
    assert loads(second.content)["data"][0]["corp_id"] == "corp-b"


def test_directory_list_audit_stays_in_cache_within_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _seed_contract_directory()
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)

    _ = directory_users(request, _APP_KEY)
    _ = directory_users(request, _APP_KEY)

    # 小时内仅 cache 累计, 不写 AuditLog(AuditLog 只追加, 翻转时再落库)。
    assert AuditLog.objects.filter(event_type="app_directory_queried").count() == 0


def test_directory_list_audit_flushes_call_count_on_hour_flip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key=_APP_KEY, name="EasyProject")
    _enable_directory(app)
    _auth(monkeypatch, app)
    _seed_contract_directory()
    request = RequestFactory().get("/", HTTP_AUTHORIZATION=_AUTH_HEADER)
    first_hour = timezone.datetime(2026, 7, 16, 10, 15, tzinfo=timezone.get_current_timezone())
    second_hour = timezone.datetime(2026, 7, 16, 11, 5, tzinfo=timezone.get_current_timezone())
    clock = {"now": first_hour}

    def _fake_now() -> timezone.datetime:
        return clock["now"]

    monkeypatch.setattr("easyauth.api.directory_views.timezone.now", _fake_now)

    calls_in_first_hour = 2
    for _ in range(calls_in_first_hour):
        _ = directory_users(request, _APP_KEY)
    assert AuditLog.objects.filter(event_type="app_directory_queried").count() == 0

    clock["now"] = second_hour
    _ = directory_users(request, _APP_KEY)

    audits = AuditLog.objects.filter(event_type="app_directory_queried")
    assert audits.count() == 1
    metadata = audits.get().metadata
    assert metadata["endpoint"] == "users"
    assert metadata["call_count"] == calls_in_first_hour
    assert metadata["hour_bucket"] == "2026071610"
