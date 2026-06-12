from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import Client, override_settings

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror

if TYPE_CHECKING:
    from django.http import HttpRequest

    from easyauth.accounts.auth import OidcClientConfig

pytestmark = pytest.mark.django_db

AUTHENTIK_ISSUER: Final = "https://authentik.example.test/application/o/easyauth/"
AUTHORIZATION_ENDPOINT: Final = "http://127.0.0.1:19000/application/o/authorize/"
CLIENT_ID: Final = "easyauth-portal-client"
REDIRECT_URI: Final = "http://testserver/auth/callback/"
CLIENT_SECRET: Final = "s12-client-secret"  # noqa: S105 - 测试夹具密钥值.
SESSION_KEY: Final = AUTHENTIK_SESSION_KEY
STATE_SESSION_KEY: Final = "easyauth_oidc_state"
NONCE_SESSION_KEY: Final = "easyauth_oidc_nonce"
NEXT_SESSION_KEY: Final = "easyauth_oidc_next"
OIDC_STATE: Final = "s12-state"
OIDC_NONCE: Final = "s12-nonce"
OIDC_CODE: Final = "s12-code"
OIDC_SUBJECT: Final = "s12-authentik-user"


type OidcClaimValue = str | tuple[str, ...] | dict[str, str]
type OidcClaims = dict[str, OidcClaimValue]


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT="",
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
    EASYAUTH_AUTHENTIK_OIDC_SCOPES=("openid", "profile", "email"),
)
def test_s12_login_redirects_to_authentik_authorization_endpoint_with_state_and_nonce() -> None:
    # Given
    client = Client()

    # When
    response = client.get("/auth/login/")

    # Then
    assert response.status_code == HTTPStatus.FOUND
    location = response.headers["Location"]
    parsed = urlsplit(location)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://authentik.example.test/application/o/authorize/"
    )
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["response_type"] == ["code"]
    assert set(query["scope"][0].split()) == {"openid", "profile", "email"}
    assert query["state"][0] == client.session[STATE_SESSION_KEY]
    assert query["nonce"][0] == client.session[NONCE_SESSION_KEY]
    assert query["state"][0]
    assert query["nonce"][0]


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT="",
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI="http://localhost:8001/auth/callback/",
    EASYAUTH_AUTHENTIK_OIDC_SCOPES=("openid", "profile", "email"),
)
def test_s12_login_redirects_to_canonical_auth_host_before_starting_oidc_attempt() -> None:
    client = Client(HTTP_HOST="127.0.0.1:8001")

    response = client.get("/auth/login/?next=/portal/")

    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "http://localhost:8001/auth/login/?next=/portal/"
    assert STATE_SESSION_KEY not in client.session
    assert NONCE_SESSION_KEY not in client.session


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT="",
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI="http://localhost:8000/auth/callback/",
    EASYAUTH_AUTHENTIK_OIDC_SCOPES=("openid", "profile", "email"),
)
def test_s12_login_uses_current_loopback_port_for_oidc_redirect_uri() -> None:
    client = Client(HTTP_HOST="localhost:8001")

    response = client.get("/auth/login/?next=/portal/")

    assert response.status_code == HTTPStatus.FOUND
    location = response.headers["Location"]
    query = parse_qs(urlsplit(location).query)
    assert query["redirect_uri"] == ["http://localhost:8001/auth/callback/"]
    assert query["state"][0] == client.session[STATE_SESSION_KEY]


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT="",
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
    EASYAUTH_AUTHENTIK_OIDC_SCOPES=("openid", "profile", "email"),
)
def test_s12_login_ignores_reauthentication_prompt_to_avoid_replaying_authentik_flow() -> None:
    client = Client()

    response = client.get("/auth/login/?next=/portal/&prompt=login")

    assert response.status_code == HTTPStatus.FOUND
    query = parse_qs(urlsplit(response.headers["Location"]).query)
    assert "prompt" not in query
    assert "max_age" not in query


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT="",
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
    EASYAUTH_AUTHENTIK_OIDC_SCOPES=("openid", "profile", "email"),
)
def test_s12_login_stores_safe_local_next_and_rejects_external_next() -> None:
    # Given
    client = Client()

    # When
    safe_response = client.get("/auth/login/?next=/console/apps/?tab=roles")
    safe_next = cast("str", client.session[NEXT_SESSION_KEY])
    unsafe_response = client.get("/auth/login/?next=https://evil.example.test/console")

    # Then
    assert safe_response.status_code == HTTPStatus.FOUND
    assert unsafe_response.status_code == HTTPStatus.FOUND
    assert safe_next == "/console/apps/?tab=roles"
    assert client.session[NEXT_SESSION_KEY] == "/portal/"


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT=AUTHORIZATION_ENDPOINT,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
    EASYAUTH_AUTHENTIK_OIDC_SCOPES=("openid", "profile", "email"),
)
def test_s12_login_uses_configured_browser_authorization_endpoint() -> None:
    # Given
    client = Client()

    # When
    response = client.get("/auth/login/")

    # Then
    assert response.status_code == HTTPStatus.FOUND
    location = response.headers["Location"]
    parsed = urlsplit(location)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZATION_ENDPOINT


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
def test_s12_callback_binds_session_to_user_mirror_when_claims_are_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    client = Client()
    user = UserMirror.objects.create(authentik_user_id=OIDC_SUBJECT, name="OIDC 用户")
    _seed_oidc_attempt(client)
    _patch_claim_exchange(monkeypatch, _valid_claims())

    # When
    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    # Then
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/portal/"
    assert client.session[SESSION_KEY] == user.authentik_user_id


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
def test_s12_callback_redirects_to_saved_next_and_pops_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    client = Client()
    _ = UserMirror.objects.create(authentik_user_id=OIDC_SUBJECT, name="OIDC 用户")
    _seed_oidc_attempt(client, next_path="/console/apps/?tab=roles")
    _patch_claim_exchange(monkeypatch, _valid_claims())

    # When
    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    # Then
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/console/apps/?tab=roles"
    assert NEXT_SESSION_KEY not in client.session


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
def test_s12_callback_stores_authentik_groups_in_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    _seed_oidc_attempt(client)
    _patch_claim_exchange(
        monkeypatch,
        {**_valid_claims(), "groups": ("EasyAuth Admins", "开发者")},
    )

    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    assert response.status_code == HTTPStatus.FOUND
    assert client.session["easyauth_authentik_groups"] == ["EasyAuth Admins", "开发者"]


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
def test_s12_callback_persists_authentik_profile_picture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    _seed_oidc_attempt(client)
    _patch_claim_exchange(
        monkeypatch,
        {
            **_valid_claims(),
            "name": "真实姓名",
            "picture": "/media/avatars/user.png",
        },
    )

    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    assert response.status_code == HTTPStatus.FOUND
    user = UserMirror.objects.get(authentik_user_id=OIDC_SUBJECT)
    assert user.name == "真实姓名"
    assert user.avatar_url == "/media/avatars/user.png"


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
@pytest.mark.parametrize(
    ("extra_claims", "expected_name"),
    [
        ({"dingtalk": {"name": "钉钉张三"}}, "钉钉张三"),
        ({"dingtalk": {"nick": "钉钉昵称"}}, "钉钉昵称"),
        ({"dingtalk_org": {"name": "组织上下文姓名"}}, "组织上下文姓名"),
    ],
)
def test_s12_callback_uses_dingtalk_name_when_oidc_name_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    extra_claims: OidcClaims,
    expected_name: str,
) -> None:
    client = Client()
    _seed_oidc_attempt(client)
    _patch_claim_exchange(monkeypatch, {**_valid_claims(), **extra_claims})

    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    assert response.status_code == HTTPStatus.FOUND
    user = UserMirror.objects.get(authentik_user_id=OIDC_SUBJECT)
    assert user.name == expected_name


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
def test_s12_callback_clears_existing_picture_when_authentik_picture_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    _ = UserMirror.objects.create(
        authentik_user_id=OIDC_SUBJECT,
        avatar_url="/media/avatars/old.png",
    )
    _seed_oidc_attempt(client)
    _patch_claim_exchange(monkeypatch, _valid_claims())

    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    assert response.status_code == HTTPStatus.FOUND
    user = UserMirror.objects.get(authentik_user_id=OIDC_SUBJECT)
    assert user.avatar_url == ""


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
@pytest.mark.parametrize(
    "unsafe_picture",
    [
        "http://authentik.example.test/avatar.png",
        "javascript:alert(1)",
        "//evil.example.test/avatar.png",
    ],
)
def test_s12_callback_ignores_unsafe_authentik_picture_claim(
    monkeypatch: pytest.MonkeyPatch,
    unsafe_picture: str,
) -> None:
    client = Client()
    _seed_oidc_attempt(client)
    _patch_claim_exchange(monkeypatch, {**_valid_claims(), "picture": unsafe_picture})

    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    assert response.status_code == HTTPStatus.FOUND
    user = UserMirror.objects.get(authentik_user_id=OIDC_SUBJECT)
    assert user.avatar_url == ""


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI="http://localhost:8001/auth/callback/",
)
def test_s12_logout_clears_local_session_and_redirects_to_logged_out_page() -> None:
    client = Client()
    session = client.session
    session[SESSION_KEY] = OIDC_SUBJECT
    session["easyauth_authentik_groups"] = ["EasyAuth Admins"]
    session["unrelated_session_value"] = "must-be-flushed"
    session.save()

    response = client.post("/auth/logout/")

    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/auth/logged-out/?next=%2Fportal%2F"
    assert SESSION_KEY not in client.session
    assert "easyauth_authentik_groups" not in client.session
    assert "unrelated_session_value" not in client.session


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID="",
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
def test_s12_logout_clears_local_session_even_when_oidc_logout_config_is_invalid() -> None:
    client = Client()
    session = client.session
    session[SESSION_KEY] = OIDC_SUBJECT
    session.save()

    response = client.post("/auth/logout/")

    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/auth/logged-out/?next=%2Fportal%2F"
    assert SESSION_KEY not in client.session


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
)
def test_s12_logout_prevents_reuse_of_old_local_session_for_portal() -> None:
    client = Client()
    _ = UserMirror.objects.create(authentik_user_id=OIDC_SUBJECT)
    session = client.session
    session[SESSION_KEY] = OIDC_SUBJECT
    session.save()

    logout_response = client.post("/auth/logout/")
    portal_response = client.get("/portal/")

    assert logout_response.status_code == HTTPStatus.FOUND
    assert portal_response.status_code == HTTPStatus.FOUND
    assert portal_response.headers["Location"] == "/auth/logged-out/?next=%2Fportal%2F"
    assert SESSION_KEY not in client.session


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI="http://localhost:8001/auth/callback/",
)
def test_s12_logout_marks_browser_as_logged_out_until_explicit_login() -> None:
    client = Client(HTTP_HOST="localhost:8001")
    _ = UserMirror.objects.create(authentik_user_id=OIDC_SUBJECT)
    session = client.session
    session[SESSION_KEY] = OIDC_SUBJECT
    session.save()

    logout_response = client.post("/auth/logout/")
    portal_response = client.get("/portal/")
    login_response = client.get("/auth/login/?next=/portal/")

    assert logout_response.status_code == HTTPStatus.FOUND
    assert portal_response.status_code == HTTPStatus.FOUND
    assert portal_response.headers["Location"] == "/auth/logged-out/?next=%2Fportal%2F"
    assert login_response.status_code == HTTPStatus.FOUND
    cleared_cookie = login_response.cookies["easyauth_logged_out"]
    assert cleared_cookie.value == ""
    assert cleared_cookie["max-age"] == 0


def test_s12_logged_out_page_serves_public_react_shell() -> None:
    client = Client()

    response = client.get("/auth/logged-out/?next=/portal/")

    assert response.status_code == HTTPStatus.OK
    html = response.content.decode()
    assert "已登出" in html
    assert 'data-easyauth-react-shell="portal"' in html
    assert "data-current-user-id" not in html
    assert "authentik SSO" not in html
    assert "旧链接会停在这里" not in html


def test_s12_logged_out_page_does_not_render_external_next_in_shell_html() -> None:
    client = Client()

    response = client.get("/auth/logged-out/?next=https://evil.example.test/portal/")

    assert response.status_code == HTTPStatus.OK
    assert "https://evil.example.test/portal/" not in response.content.decode()


def test_s12_logout_requires_csrf_when_csrf_checks_are_enforced() -> None:
    client = Client(enforce_csrf_checks=True)
    session = client.session
    session[SESSION_KEY] = OIDC_SUBJECT
    session.save()

    response = client.post("/auth/logout/")

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert client.session[SESSION_KEY] == OIDC_SUBJECT


def test_s12_logout_accepts_valid_csrf_token_when_csrf_checks_are_enforced() -> None:
    client = Client(enforce_csrf_checks=True)
    _ = UserMirror.objects.create(authentik_user_id=OIDC_SUBJECT)
    session = client.session
    session[SESSION_KEY] = OIDC_SUBJECT
    session.save()
    _ = client.get("/portal/")
    csrf_token = client.cookies["csrftoken"].value

    response = client.post("/auth/logout/", HTTP_X_CSRFTOKEN=csrf_token)

    assert response.status_code == HTTPStatus.FOUND
    assert SESSION_KEY not in client.session


def _valid_claims() -> OidcClaims:
    return {
        "iss": AUTHENTIK_ISSUER,
        "aud": CLIENT_ID,
        "sub": OIDC_SUBJECT,
        "nonce": OIDC_NONCE,
    }


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
@pytest.mark.parametrize(
    ("claims", "error_text"),
    [
        ({**_valid_claims(), "iss": "https://evil.example.test/application/o/easyauth/"}, "issuer"),
        ({**_valid_claims(), "aud": "other-client"}, "audience"),
        ({**_valid_claims(), "sub": ""}, "subject"),
    ],
)
def test_s12_callback_rejects_invalid_claims_without_writing_session(
    monkeypatch: pytest.MonkeyPatch,
    claims: OidcClaims,
    error_text: str,
) -> None:
    # Given
    client = Client()
    _seed_oidc_attempt(client)
    _patch_claim_exchange(monkeypatch, claims)

    # When
    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    # Then
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert error_text in response.content.decode()
    assert SESSION_KEY not in client.session
    assert STATE_SESSION_KEY not in client.session
    assert NONCE_SESSION_KEY not in client.session


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
def test_s12_callback_rejects_multiple_audiences_without_authorized_party(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    client = Client()
    _seed_oidc_attempt(client)
    _patch_claim_exchange(monkeypatch, {**_valid_claims(), "aud": (CLIENT_ID, "other-client")})

    # When
    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state={OIDC_STATE}")

    # Then
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "azp" in response.content.decode()


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER=AUTHENTIK_ISSUER,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID=CLIENT_ID,
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET=CLIENT_SECRET,
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI=REDIRECT_URI,
)
def test_s12_callback_rejects_state_mismatch_and_clears_login_attempt() -> None:
    # Given
    client = Client()
    _seed_oidc_attempt(client)

    # When
    response = client.get(f"/auth/callback/?code={OIDC_CODE}&state=wrong-state")

    # Then
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "state" in response.content.decode()
    assert SESSION_KEY not in client.session
    assert STATE_SESSION_KEY not in client.session
    assert NONCE_SESSION_KEY not in client.session


def _seed_oidc_attempt(client: Client, *, next_path: str = "/portal/") -> None:
    session = client.session
    session[STATE_SESSION_KEY] = OIDC_STATE
    session[NONCE_SESSION_KEY] = OIDC_NONCE
    session[NEXT_SESSION_KEY] = next_path
    session.save()


def _patch_claim_exchange(monkeypatch: pytest.MonkeyPatch, claims: OidcClaims) -> None:
    def exchange_claims(
        _request: HttpRequest,
        _code: str,
        _config: OidcClientConfig,
    ) -> OidcClaims:
        return claims

    monkeypatch.setattr(
        "easyauth.accounts.views.exchange_authorization_code_for_claims",
        exchange_claims,
    )
