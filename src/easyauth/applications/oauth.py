from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Final, Protocol, override

from django.db import transaction
from django.utils import timezone
from oauth2_provider.generators import generate_client_secret
from oauth2_provider.models import AccessToken, Application

from easyauth.applications.oauth_models import OAUTH_CLIENT_CREDENTIAL_KIND, OAuthClientBinding
from easyauth.applications.services import AppPrincipal
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from easyauth.applications.models import App
    from easyauth.audit.models import JsonValue

APP_CREDENTIAL_TYPE_OAUTH_CLIENT: Final = OAUTH_CLIENT_CREDENTIAL_KIND
OAUTH_CLIENT_CREATED_EVENT: Final = "oauth_client_created"


@dataclass(frozen=True, slots=True)
class OAuthClientIssue:
    binding_id: int
    oauth_application_id: int
    client_id: str
    client_secret: str


@dataclass(frozen=True, slots=True)
class OAuthClientAuthenticationError(Exception):
    @override
    def __str__(self) -> str:
        return "oauth client access token authentication failed"


@dataclass(frozen=True, slots=True)
class OAuthClientAppDisabledError(Exception):
    app_id: int

    @override
    def __str__(self) -> str:
        return "oauth client app is disabled"


class _AppIdentity(Protocol):
    id: int


class OAuthClientService:
    @staticmethod
    @transaction.atomic
    def create_client(*, app: App, name: str) -> OAuthClientIssue:
        plaintext_secret = generate_client_secret()
        oauth_application = Application(
            name=name,
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_CLIENT_CREDENTIALS,
            client_secret=plaintext_secret,
        )
        oauth_application.full_clean()
        oauth_application.save()
        binding = OAuthClientBinding(
            app=app,
            oauth_application=oauth_application,
            credential_type=APP_CREDENTIAL_TYPE_OAUTH_CLIENT,
            name=name,
        )
        binding.full_clean()
        binding.save()
        _record_oauth_client_event(binding)
        return OAuthClientIssue(
            binding_id=_binding_id(binding),
            oauth_application_id=_oauth_application_id(oauth_application),
            client_id=oauth_application.client_id,
            client_secret=plaintext_secret,
        )

    @staticmethod
    def authenticate_access_token_for_api(plaintext_token: str) -> AppPrincipal:
        return _authenticate_oauth_access_token(plaintext_token)


def _authenticate_oauth_access_token(plaintext_token: str) -> AppPrincipal:
    access_token = _find_access_token(plaintext_token)
    if access_token is None:
        raise OAuthClientAuthenticationError
    oauth_application_id = access_token.application_id
    if oauth_application_id is None:
        raise OAuthClientAuthenticationError

    binding = (
        OAuthClientBinding.objects.select_related("app")
        .filter(
            oauth_application_id=oauth_application_id,
            credential_type=APP_CREDENTIAL_TYPE_OAUTH_CLIENT,
            is_active=True,
        )
        .first()
    )
    if binding is None:
        raise OAuthClientAuthenticationError
    if not binding.app.is_active:
        raise OAuthClientAppDisabledError(app_id=_app_id(binding.app))
    return AppPrincipal(
        app_id=_app_id(binding.app),
        app_key=binding.app.app_key,
        credential_type=binding.credential_type,
        credential_id=_binding_id(binding),
    )


def _find_access_token(plaintext_token: str) -> AccessToken | None:
    return (
        AccessToken.objects.select_related("application")
        .filter(
            token_checksum=_token_checksum(plaintext_token),
            expires__gt=timezone.now(),
        )
        .first()
    )


def _token_checksum(plaintext_token: str) -> str:
    return sha256(plaintext_token.encode("utf-8")).hexdigest()


def _record_oauth_client_event(binding: OAuthClientBinding) -> None:
    metadata: dict[str, JsonValue] = {
        "app_id": _app_id(binding.app),
        "app_key": binding.app.app_key,
        "credential_type": binding.credential_type,
        "oauth_application_id": _oauth_application_id(binding.oauth_application),
    }
    _ = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id="easyauth",
            action=OAUTH_CLIENT_CREATED_EVENT,
            target_type="oauth_client",
            target_id=str(_binding_id(binding)),
            metadata=metadata,
        ),
    )


def _app_id(app: _AppIdentity) -> int:
    return app.id


def _binding_id(binding: OAuthClientBinding) -> int:
    return binding.id


def _oauth_application_id(oauth_application: Application) -> int:
    return oauth_application.id
