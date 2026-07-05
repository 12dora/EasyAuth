from __future__ import annotations

import json
import time
from http import HTTPStatus
from types import SimpleNamespace
from typing import Final

import pyotp
import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, RequestFactory
from webauthn.helpers import bytes_to_base64url

from easyauth.accounts import local_admin
from easyauth.accounts.auth import (
    AUTHENTIK_GROUPS_SESSION_KEY,
    AUTHENTIK_SESSION_KEY,
    OidcSessionError,
    VerifiedOidcClaims,
    bind_oidc_session,
)
from easyauth.accounts.models import LocalAdminAccount, LocalAdminPasskey, UserMirror
from easyauth.admin_console.identity import actor_from_request
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db

USERNAME: Final = "admin"
GOOD_CREDENTIAL: Final = "correct-horse-battery"
BAD_CREDENTIAL: Final = "wrong-horse"
NEW_CREDENTIAL: Final = "brand-new-horse-battery"
CHANGE_PASSWORD_PATH: Final = "/auth/local/change-password/"  # noqa: S105 - URL 路径, 不是密码值.
LOCAL_ADMIN_SUBJECT: Final = "local-admin:admin"
NEW_SIGN_COUNT: Final = 7
REGISTERED_CREDENTIAL_ID_BYTES: Final = b"\x01\x02\x03\x04"
REGISTERED_PUBLIC_KEY_BYTES: Final = b"\x05\x06\x07\x08"


@pytest.fixture(autouse=True)
def _clear_throttle_cache() -> None:  # pyright: ignore[reportUnusedFunction]
    cache.clear()


def _create_account(
    *,
    username: str = USERNAME,
    totp_secret: str = "",
    must_change_password: bool = False,
) -> LocalAdminAccount:
    # 缺省视为已完成首次改密的账号; 强制改密场景显式传 must_change_password=True。
    account = LocalAdminAccount(
        username=username,
        totp_secret=totp_secret,
        totp_enabled=totp_secret != "",
        must_change_password=must_change_password,
    )
    account.set_password(GOOD_CREDENTIAL)
    account.save()
    return account


def _add_passkey(account: LocalAdminAccount) -> LocalAdminPasskey:
    return LocalAdminPasskey.objects.create(
        account=account,
        credential_id=bytes_to_base64url(b"cred-1"),
        public_key=bytes_to_base64url(b"public-key"),
        sign_count=1,
        name="测试密钥",
    )


def _login(client: Client, *, password: str = GOOD_CREDENTIAL) -> object:
    return client.post("/auth/local/", {"username": USERNAME, "password": password})


def _post_json(client: Client, url: str, payload: dict[str, object]) -> object:
    return client.post(url, data=json.dumps(payload), content_type="application/json")


def _assert_session_bound(client: Client) -> None:
    assert client.session[AUTHENTIK_SESSION_KEY] == LOCAL_ADMIN_SUBJECT
    assert client.session[AUTHENTIK_GROUPS_SESSION_KEY] == ["EasyAuth Admins"]


def test_login_page_renders() -> None:
    # Given
    client = Client()

    # When
    response = client.get("/auth/local/")

    # Then: 统一登录页同时提供工作账号入口与本地账号表单。
    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert "登录 EasyAuth" in html
    assert "或使用本地账号登录" in html


def test_login_rejects_wrong_password_with_generic_error() -> None:
    # Given
    _ = _create_account()
    client = Client()

    # When
    response = _login(client, password=BAD_CREDENTIAL)

    # Then
    assert response.status_code == HTTPStatus.OK
    assert "用户名或密码错误" in response.content.decode()
    assert AUTHENTIK_SESSION_KEY not in client.session
    assert AuditLog.objects.filter(
        event_type="admin_local_login_failed",
        actor_id=USERNAME,
    ).exists()


def test_login_rejects_unknown_username_with_same_error() -> None:
    # Given
    client = Client()

    # When
    response = _login(client)

    # Then
    assert response.status_code == HTTPStatus.OK
    assert "用户名或密码错误" in response.content.decode()


def test_login_rejects_disabled_account() -> None:
    # Given
    account = _create_account()
    account.is_active = False
    account.save(update_fields=["is_active", "updated_at"])
    client = Client()

    # When
    response = _login(client)

    # Then
    assert response.status_code == HTTPStatus.OK
    assert "用户名或密码错误" in response.content.decode()
    assert AUTHENTIK_SESSION_KEY not in client.session


def test_login_without_second_factor_binds_superuser_session() -> None:
    # Given
    _ = _create_account()
    client = Client()

    # When
    response = _login(client)

    # Then
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/console/"
    _assert_session_bound(client)
    user = UserMirror.objects.get(authentik_user_id=LOCAL_ADMIN_SUBJECT)
    assert user.name == "本地管理员 admin"
    assert user.email == "admin@local.admin"
    request = RequestFactory().get("/console/")
    request.session = client.session
    actor = actor_from_request(request)
    assert actor is not None
    assert actor.is_superuser
    succeeded = AuditLog.objects.get(event_type="admin_local_login_succeeded")
    assert succeeded.actor_type == "local_admin"
    assert succeeded.metadata == {"second_factor": "none"}


def test_login_with_totp_redirects_to_verify_without_binding() -> None:
    # Given
    _ = _create_account(totp_secret=pyotp.random_base32())
    client = Client()

    # When
    login_response = _login(client)
    verify_response = client.get("/auth/local/verify/")

    # Then
    assert login_response.status_code == HTTPStatus.FOUND
    assert login_response.headers["Location"] == "/auth/local/verify/"
    assert AUTHENTIK_SESSION_KEY not in client.session
    assert verify_response.status_code == HTTPStatus.OK
    html = verify_response.content.decode()
    assert "二次验证" in html
    assert "验证并登录" in html


def test_verify_page_redirects_to_login_when_pending_expired() -> None:
    # Given
    _ = _create_account(totp_secret=pyotp.random_base32())
    client = Client()
    _ = _login(client)
    session = client.session
    pending = session[local_admin.PENDING_SESSION_KEY]
    pending["issued_at"] = time.time() - local_admin.PENDING_TTL_SECONDS - 1
    session[local_admin.PENDING_SESSION_KEY] = pending
    session.save()

    # When
    response = client.get("/auth/local/verify/")

    # Then
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/auth/local/"


def test_verify_totp_full_flow() -> None:
    # Given
    otp_key = pyotp.random_base32()
    _ = _create_account(totp_secret=otp_key)
    client = Client()
    _ = _login(client)

    # When
    wrong_response = client.post("/auth/local/verify/totp/", {"code": "000000"})
    right_response = client.post(
        "/auth/local/verify/totp/",
        {"code": pyotp.TOTP(otp_key).now()},
    )

    # Then
    assert wrong_response.status_code == HTTPStatus.OK
    assert "验证码不正确" in wrong_response.content.decode()
    assert AuditLog.objects.filter(
        event_type="admin_local_second_factor_failed",
        actor_id=USERNAME,
    ).exists()
    assert right_response.status_code == HTTPStatus.FOUND
    assert right_response.headers["Location"] == "/console/"
    _assert_session_bound(client)


def test_passkey_begin_returns_options_and_stores_challenge() -> None:
    # Given
    account = _create_account()
    passkey = _add_passkey(account)
    client = Client()
    _ = _login(client)

    # When
    response = _post_json(client, "/auth/local/passkey/begin/", {})

    # Then
    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    options = payload["options"]
    assert isinstance(options["challenge"], str)
    assert options["challenge"] != ""
    allowed_ids = [item["id"] for item in options["allowCredentials"]]
    assert passkey.credential_id in allowed_ids
    assert isinstance(payload["state_token"], str)
    stored = client.session[local_admin.CHALLENGE_SESSION_KEY]
    assert stored["challenge"] == options["challenge"]
    assert stored["state_token"] == payload["state_token"]


def test_passkey_begin_requires_pending_login() -> None:
    # Given
    client = Client()

    # When
    response = _post_json(client, "/auth/local/passkey/begin/", {})

    # Then
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_passkey_complete_binds_session(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    account = _create_account()
    passkey = _add_passkey(account)
    client = Client()
    _ = _login(client)
    begin = _post_json(client, "/auth/local/passkey/begin/", {}).json()
    monkeypatch.setattr(
        local_admin.webauthn,
        "verify_authentication_response",
        lambda **_kwargs: SimpleNamespace(new_sign_count=NEW_SIGN_COUNT),
    )

    # When
    response = _post_json(
        client,
        "/auth/local/passkey/complete/",
        {
            "state_token": begin["state_token"],
            "credential": {"id": passkey.credential_id, "rawId": passkey.credential_id},
        },
    )

    # Then
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"redirect": "/console/"}
    _assert_session_bound(client)
    passkey.refresh_from_db()
    assert passkey.sign_count == NEW_SIGN_COUNT
    assert passkey.last_used_at is not None
    succeeded = AuditLog.objects.get(event_type="admin_local_login_succeeded")
    assert succeeded.metadata == {"second_factor": "passkey"}


def test_passkey_complete_rejects_wrong_state_token() -> None:
    # Given
    account = _create_account()
    passkey = _add_passkey(account)
    client = Client()
    _ = _login(client)
    _ = _post_json(client, "/auth/local/passkey/begin/", {})

    # When
    response = _post_json(
        client,
        "/auth/local/passkey/complete/",
        {
            "state_token": "forged",
            "credential": {"id": passkey.credential_id, "rawId": passkey.credential_id},
        },
    )

    # Then
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert AUTHENTIK_SESSION_KEY not in client.session
    assert AuditLog.objects.filter(
        event_type="admin_local_second_factor_failed",
        actor_id=USERNAME,
    ).exists()


def test_login_is_throttled_after_repeated_failures() -> None:
    # Given
    _ = _create_account()
    client = Client()
    for _attempt in range(local_admin.LOGIN_FAILURE_LIMIT):
        _ = _login(client, password=BAD_CREDENTIAL)

    # When
    response = _login(client)

    # Then
    assert response.status_code == HTTPStatus.OK
    assert "尝试次数过多" in response.content.decode()
    assert AUTHENTIK_SESSION_KEY not in client.session


def test_security_page_is_hidden_for_anonymous_visitors() -> None:
    # Given
    client = Client()

    # When
    response = client.get("/auth/local/security/")

    # Then
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_security_page_is_hidden_for_non_local_admin_sessions() -> None:
    # Given: 普通 OIDC 会话(subject 不带 local-admin: 前缀)。
    _ = UserMirror.objects.create(authentik_user_id="oidc-user")
    client = Client()
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = "oidc-user"
    session.save()

    # When
    response = client.get("/auth/local/security/")

    # Then
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_security_page_renders_for_local_admin() -> None:
    # Given
    _ = _create_account()
    client = Client()
    _ = _login(client)

    # When
    response = client.get("/auth/local/security/")

    # Then
    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert "安全设置" in html
    assert "开始绑定验证器" in html
    assert "注册通行密钥" in html
    assert "修改密码" in html


def test_change_password_page_requires_local_admin_session() -> None:
    # Given: 匿名浏览器。
    client = Client()

    # When
    response = client.get(CHANGE_PASSWORD_PATH)

    # Then: 无本地管理员会话时跳回登录页。
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/auth/local/"


def test_forced_password_change_gates_portal_and_console() -> None:
    # Given: 带强制改密标记的本地管理员完成登录。
    _ = _create_account(must_change_password=True)
    client = Client()
    _ = _login(client)

    # When: 分别访问门户、控制台页面和控制台 API。
    portal = client.get("/portal/")
    console = client.get("/console/")
    console_api = client.get("/console/api/v1/apps")
    change_page = client.get(CHANGE_PASSWORD_PATH)

    # Then: 全部 302 到改密页; 改密页自身可正常打开。
    assert portal.status_code == HTTPStatus.FOUND
    assert portal.headers["Location"].startswith(CHANGE_PASSWORD_PATH)
    assert console.status_code == HTTPStatus.FOUND
    assert console.headers["Location"].startswith(CHANGE_PASSWORD_PATH)
    assert console_api.status_code == HTTPStatus.FOUND
    assert console_api.headers["Location"].startswith(CHANGE_PASSWORD_PATH)
    assert change_page.status_code == HTTPStatus.OK
    assert "修改密码" in change_page.content.decode()


def test_forced_password_change_allows_logout() -> None:
    # Given: 带强制改密标记的本地管理员完成登录。
    _ = _create_account(must_change_password=True)
    client = Client()
    _ = _login(client)

    # When: 走统一登出。
    response = client.post("/auth/logout/")

    # Then: 登出链路不被强制改密拦截。
    assert response.status_code == HTTPStatus.FOUND
    assert AUTHENTIK_SESSION_KEY not in client.session


def test_change_password_happy_path_clears_flag_and_unblocks_navigation() -> None:
    # Given: 带强制改密标记的本地管理员完成登录。
    account = _create_account(must_change_password=True)
    client = Client()
    _ = _login(client)

    # When: 提交合法的改密表单。
    response = client.post(
        CHANGE_PASSWORD_PATH,
        {
            "current_password": GOOD_CREDENTIAL,
            "new_password": NEW_CREDENTIAL,
            "confirm_password": NEW_CREDENTIAL,
        },
    )

    # Then: 密码更新、标记清除、审计落盘, 后续访问不再被拦截。
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/portal/"
    account.refresh_from_db()
    assert account.check_password(NEW_CREDENTIAL)
    assert not account.must_change_password
    assert AuditLog.objects.filter(
        event_type="admin_local_password_changed",
        actor_id=USERNAME,
    ).exists()
    console = client.get("/console/")
    assert console.status_code == HTTPStatus.OK
    assert 'data-easyauth-react-shell="console"' in console.content.decode()


def test_change_password_rejects_wrong_current_password() -> None:
    # Given
    account = _create_account()
    client = Client()
    _ = _login(client)

    # When: 当前密码填错。
    response = client.post(
        CHANGE_PASSWORD_PATH,
        {
            "current_password": BAD_CREDENTIAL,
            "new_password": NEW_CREDENTIAL,
            "confirm_password": NEW_CREDENTIAL,
        },
    )

    # Then: 密码不变, 返回错误提示并写失败审计。
    assert response.status_code == HTTPStatus.OK
    assert "当前密码不正确" in response.content.decode()
    account.refresh_from_db()
    assert account.check_password(GOOD_CREDENTIAL)
    assert AuditLog.objects.filter(
        event_type="admin_local_password_change_failed",
        actor_id=USERNAME,
    ).exists()


@pytest.mark.parametrize(
    ("new_password", "confirm_password", "message"),
    [
        ("short", "short", "新密码长度至少 8 位"),
        (GOOD_CREDENTIAL, GOOD_CREDENTIAL, "新密码不能与当前密码相同"),
        (NEW_CREDENTIAL, NEW_CREDENTIAL + "-typo", "两次输入的新密码不一致"),
    ],
)
def test_change_password_rejects_invalid_new_password(
    new_password: str,
    confirm_password: str,
    message: str,
) -> None:
    # Given
    account = _create_account()
    client = Client()
    _ = _login(client)

    # When
    response = client.post(
        CHANGE_PASSWORD_PATH,
        {
            "current_password": GOOD_CREDENTIAL,
            "new_password": new_password,
            "confirm_password": confirm_password,
        },
    )

    # Then
    assert response.status_code == HTTPStatus.OK
    assert message in response.content.decode()
    account.refresh_from_db()
    assert account.check_password(GOOD_CREDENTIAL)


def test_change_password_ignores_unsafe_next_path() -> None:
    # Given
    _ = _create_account()
    client = Client()
    _ = _login(client)

    # When: next 指向外部地址。
    response = client.post(
        CHANGE_PASSWORD_PATH,
        {
            "current_password": GOOD_CREDENTIAL,
            "new_password": NEW_CREDENTIAL,
            "confirm_password": NEW_CREDENTIAL,
            "next": "https://evil.example.test/portal/",
        },
    )

    # Then: 回退到默认站内路径。
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/portal/"


def test_totp_enable_and_disable_flow() -> None:
    # Given
    account = _create_account()
    client = Client()
    _ = _login(client)

    # When
    begin_response = client.post("/auth/local/security/totp/begin/")
    setup_page = client.get("/auth/local/security/")
    otp_key = client.session[local_admin.TOTP_SETUP_SESSION_KEY]["secret"]
    wrong_confirm = client.post("/auth/local/security/totp/confirm/", {"code": "000000"})
    confirm_response = client.post(
        "/auth/local/security/totp/confirm/",
        {"code": pyotp.TOTP(otp_key).now()},
    )

    # Then
    assert begin_response.status_code == HTTPStatus.FOUND
    setup_html = setup_page.content.decode()
    assert "data:image/svg+xml;base64," in setup_html
    assert otp_key in setup_html
    assert wrong_confirm.headers["Location"] == "/auth/local/security/?error=totp_confirm"
    assert confirm_response.headers["Location"] == "/auth/local/security/?notice=totp_enabled"
    account.refresh_from_db()
    assert account.totp_enabled
    assert account.totp_secret == otp_key
    assert AuditLog.objects.filter(event_type="admin_local_totp_enabled").exists()

    # When
    # 绑定确认会消费当前 timestep, 停用需用下一 timestep 的验证码(模拟绑定后隔一段时间再停用)。
    disable_response = client.post(
        "/auth/local/security/totp/disable/",
        {
            "code": pyotp.TOTP(otp_key).at(time.time() + 30),
            "current_password": GOOD_CREDENTIAL,
        },
    )

    # Then
    assert disable_response.headers["Location"] == "/auth/local/security/?notice=totp_disabled"
    account.refresh_from_db()
    assert not account.totp_enabled
    assert account.totp_secret == ""
    assert AuditLog.objects.filter(event_type="admin_local_totp_disabled").exists()


def test_passkey_registration_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    _ = _create_account()
    client = Client()
    _ = _login(client)
    begin = _post_json(client, "/auth/local/security/passkey/register/begin/", {}).json()
    monkeypatch.setattr(
        local_admin.webauthn,
        "verify_registration_response",
        lambda **_kwargs: SimpleNamespace(
            credential_id=REGISTERED_CREDENTIAL_ID_BYTES,
            credential_public_key=REGISTERED_PUBLIC_KEY_BYTES,
            sign_count=0,
        ),
    )

    # When
    response = _post_json(
        client,
        "/auth/local/security/passkey/register/complete/",
        {
            "state_token": begin["state_token"],
            "name": "MacBook Touch ID",
            "current_password": GOOD_CREDENTIAL,
            "credential": {
                "id": "reg-cred",
                "rawId": "reg-cred",
                "response": {"transports": ["internal"]},
            },
        },
    )

    # Then
    assert begin["options"]["user"]["name"] == USERNAME
    assert response.status_code == HTTPStatus.OK
    passkey = LocalAdminPasskey.objects.get(
        credential_id=bytes_to_base64url(REGISTERED_CREDENTIAL_ID_BYTES),
    )
    assert passkey.public_key == bytes_to_base64url(REGISTERED_PUBLIC_KEY_BYTES)
    assert passkey.name == "MacBook Touch ID"
    assert passkey.transports == ["internal"]
    assert AuditLog.objects.filter(event_type="admin_local_passkey_registered").exists()


def test_passkey_delete_removes_credential() -> None:
    # Given
    account = _create_account()
    client = Client()
    _ = _login(client)
    passkey = _add_passkey(account)

    # When
    response = client.post(
        f"/auth/local/security/passkey/{passkey.pk}/delete/",
        {"current_password": GOOD_CREDENTIAL},
    )

    # Then
    assert response.status_code == HTTPStatus.FOUND
    assert not LocalAdminPasskey.objects.filter(pk=passkey.pk).exists()
    assert AuditLog.objects.filter(event_type="admin_local_passkey_removed").exists()


def test_create_local_admin_command_is_idempotent() -> None:
    # Given / When
    call_command("create_local_admin", USERNAME, "--password", GOOD_CREDENTIAL)
    account = LocalAdminAccount.objects.get(username=USERNAME)

    # Then
    assert account.check_password(GOOD_CREDENTIAL)
    with pytest.raises(CommandError, match="已存在"):
        call_command("create_local_admin", USERNAME, "--password", BAD_CREDENTIAL)
    assert LocalAdminAccount.objects.count() == 1

    # When
    call_command("create_local_admin", USERNAME, "--password", NEW_CREDENTIAL, "--update")

    # Then
    account.refresh_from_db()
    assert account.check_password(NEW_CREDENTIAL)


def test_create_local_admin_command_rejects_weak_password() -> None:
    # Given / When / Then: 弱口令(过短)被口令策略拒绝, 不建号。
    with pytest.raises(CommandError, match="at least 12 characters"):
        call_command("create_local_admin", USERNAME, "--password", BAD_CREDENTIAL)
    assert not LocalAdminAccount.objects.filter(username=USERNAME).exists()


def test_create_local_admin_command_controls_forced_password_change() -> None:
    # Given / When: 新建账号(缺省强制改密)。
    call_command("create_local_admin", USERNAME, "--password", GOOD_CREDENTIAL)
    account = LocalAdminAccount.objects.get(username=USERNAME)

    # Then
    assert account.must_change_password

    # When: 显式关闭强制改密后重置密码。
    call_command(
        "create_local_admin",
        USERNAME,
        "--password",
        GOOD_CREDENTIAL,
        "--update",
        "--no-force-password-change",
    )

    # Then
    account.refresh_from_db()
    assert not account.must_change_password

    # When: 常规 --update 重置密码。
    call_command("create_local_admin", USERNAME, "--password", NEW_CREDENTIAL, "--update")

    # Then: 重置后重新要求改密。
    account.refresh_from_db()
    assert account.must_change_password


def test_create_local_admin_command_rejects_invalid_username() -> None:
    # When / Then
    with pytest.raises(CommandError):
        call_command("create_local_admin", "Bad User!", "--password", GOOD_CREDENTIAL)
    assert not LocalAdminAccount.objects.exists()


def test_totp_login_rejects_replayed_code() -> None:
    # Given: 启用了 TOTP 的账号, 用一个验证码完成首次二次验证。
    secret = pyotp.random_base32()
    _ = _create_account(totp_secret=secret)
    code = pyotp.TOTP(secret).now()
    first = Client()
    _ = _login(first)
    first_verify = first.post("/auth/local/verify/totp/", {"code": code})
    assert first_verify.status_code == HTTPStatus.FOUND
    assert first.session[AUTHENTIK_SESSION_KEY] == LOCAL_ADMIN_SUBJECT

    # When: 另一个会话用同一个验证码重放。
    second = Client()
    _ = _login(second)
    replay = second.post("/auth/local/verify/totp/", {"code": code})

    # Then: 一次性消费拒绝重放, 第二个会话未被绑定。
    assert replay.status_code == HTTPStatus.OK
    assert AUTHENTIK_SESSION_KEY not in second.session


def test_totp_disable_requires_current_password() -> None:
    # Given: 已登录且启用了 TOTP 的本地管理员。
    secret = pyotp.random_base32()
    account = _create_account(totp_secret=secret)
    client = Client()
    _ = _login(client)
    _ = client.post("/auth/local/verify/totp/", {"code": pyotp.TOTP(secret).now()})

    # When: 用错误的当前密码尝试停用 TOTP。
    response = client.post(
        "/auth/local/security/totp/disable/",
        {"code": pyotp.TOTP(secret).now(), "current_password": BAD_CREDENTIAL},
    )

    # Then: step-up 失败, TOTP 仍启用。
    assert "error=totp_disable" in response.headers["Location"]
    account.refresh_from_db()
    assert account.totp_enabled is True


def test_change_password_rejects_weak_new_password() -> None:
    # Given: 已登录本地管理员。
    account = _create_account()
    client = Client()
    _ = _login(client)

    # When: 新密码过短, 不满足口令策略。
    response = client.post(
        CHANGE_PASSWORD_PATH,
        {
            "current_password": GOOD_CREDENTIAL,
            "new_password": "short",
            "confirm_password": "short",
        },
    )

    # Then: 密码不变, 返回错误。
    assert response.status_code == HTTPStatus.OK
    account.refresh_from_db()
    assert account.check_password(GOOD_CREDENTIAL)


def test_current_local_admin_requires_session_flag() -> None:
    # Given: 一个本地管理员账号, 以及一个只有 local-admin: 前缀 subject 但缺少专用标志的会话。
    _ = _create_account()
    without_flag = SimpleNamespace(session={AUTHENTIK_SESSION_KEY: LOCAL_ADMIN_SUBJECT})
    with_flag = SimpleNamespace(
        session={
            AUTHENTIK_SESSION_KEY: LOCAL_ADMIN_SUBJECT,
            local_admin.LOCAL_ADMIN_SESSION_FLAG: True,
        },
    )

    # Then: 缺少标志时冒认失败, 带标志时才解析出账号。
    assert local_admin.current_local_admin(without_flag) is None
    assert local_admin.current_local_admin(with_flag) is not None


def test_bind_oidc_session_rejects_reserved_local_admin_subject() -> None:
    request = RequestFactory().get("/auth/callback/")
    request.session = SessionStore()

    # OIDC 登录路径不得绑定 local-admin: 命名空间的 subject。
    with pytest.raises(OidcSessionError):
        _ = bind_oidc_session(
            request,
            VerifiedOidcClaims(
                subject="local-admin:admin",
                name="伪装",
                email="e@example.com",
                groups=("EasyAuth Admins",),
            ),
        )


def test_console_actor_none_when_local_admin_deactivated() -> None:
    # Given: 本地管理员登录并绑定控制台会话。
    account = _create_account()
    client = Client()
    _ = _login(client)
    request = RequestFactory().get("/console/")
    request.session = client.session
    assert actor_from_request(request) is not None

    # When: 停用该本地管理员账号。
    account.is_active = False
    account.save(update_fields=["is_active"])

    # Then: 已有控制台会话立即失效。
    assert actor_from_request(request) is None
