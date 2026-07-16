from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, override

from django.utils import timezone

from easyauth.applications.models import App, AppCredential
from easyauth.applications.oauth import OAuthClientService
from easyauth.applications.oauth_models import OAuthClientBinding
from easyauth.applications.services import (
    APP_CREDENTIAL_STATIC_KIND,
    AppCredentialService,
    StaticTokenService,
)
from easyauth.audit.services import AuditRecord, AuditService

type OneTimeSecretKind = Literal["static_token", "oauth_client"]


@dataclass(frozen=True, slots=True)
class CredentialActor:
    actor_id: str


@dataclass(frozen=True, slots=True)
class OneTimeSecret:
    kind: OneTimeSecretKind
    credential_id: int
    label: str
    value: str
    secondary_label: str = ""
    secondary_value: str = ""


@dataclass(frozen=True, slots=True)
class CredentialOperationError(Exception):
    code: str
    credential_id: int

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.credential_id}"


@dataclass(frozen=True, slots=True)
class CredentialEvent:
    app: App
    actor: CredentialActor
    action: str
    credential_type: str
    credential_id: int
    reason: str = ""
    capabilities: list[str] | None = None


def create_static_token_for_console(
    *,
    app: App,
    name: str,
    actor: CredentialActor,
    capabilities: list[str] | None = None,
) -> OneTimeSecret:
    issue = StaticTokenService.create_token(
        app=app,
        name=name,
        capabilities=capabilities or [],
    )
    _record_credential_event(
        CredentialEvent(
            app=app,
            actor=actor,
            action="console_static_token_created",
            credential_type=APP_CREDENTIAL_STATIC_KIND,
            credential_id=issue.credential_id,
        ),
    )
    return OneTimeSecret(
        kind="static_token",
        credential_id=issue.credential_id,
        label="app_token",
        value=issue.plaintext_token,
    )


def rotate_static_token_for_console(
    *,
    app: App,
    credential_id: int,
    actor: CredentialActor,
) -> OneTimeSecret:
    _ = _static_credential_for_app(app=app, credential_id=credential_id)
    issue = StaticTokenService.rotate_token(credential_id=credential_id)
    _record_credential_event(
        CredentialEvent(
            app=app,
            actor=actor,
            action="console_static_token_rotated",
            credential_type=APP_CREDENTIAL_STATIC_KIND,
            credential_id=issue.credential_id,
        ),
    )
    return OneTimeSecret(
        kind="static_token",
        credential_id=issue.credential_id,
        label="app_token",
        value=issue.plaintext_token,
    )


def disable_static_token_for_console(
    *,
    app: App,
    credential_id: int,
    actor: CredentialActor,
    reason: str = "",
) -> None:
    credential = _static_credential_for_app(app=app, credential_id=credential_id)
    _ = AppCredentialService.disable_static_token(credential)
    _record_credential_event(
        CredentialEvent(
            app=app,
            actor=actor,
            action="console_static_token_disabled",
            credential_type=APP_CREDENTIAL_STATIC_KIND,
            credential_id=credential_id,
            reason=reason,
        ),
    )


def disable_oauth_client_for_console(
    *,
    app: App,
    credential_id: int,
    actor: CredentialActor,
    reason: str = "",
) -> None:
    binding = _oauth_client_for_app(app=app, credential_id=credential_id)
    binding.is_active = False
    binding.disabled_at = timezone.now()
    binding.save(update_fields=["is_active", "disabled_at", "updated_at"])
    _record_credential_event(
        CredentialEvent(
            app=app,
            actor=actor,
            action="console_oauth_client_disabled",
            credential_type="oauth_client",
            credential_id=credential_id,
            reason=reason,
        ),
    )


def create_oauth_client_for_console(
    *,
    app: App,
    name: str,
    actor: CredentialActor,
    capabilities: list[str] | None = None,
) -> OneTimeSecret:
    issue = OAuthClientService.create_client(
        app=app,
        name=name,
        capabilities=capabilities or [],
    )
    _record_credential_event(
        CredentialEvent(
            app=app,
            actor=actor,
            action="console_oauth_client_created",
            credential_type="oauth_client",
            credential_id=issue.binding_id,
        ),
    )
    return OneTimeSecret(
        kind="oauth_client",
        credential_id=issue.binding_id,
        label="client_id",
        value=issue.client_id,
        secondary_label="client_secret",
        secondary_value=issue.client_secret,
    )


def update_credential_capabilities_for_console(
    *,
    app: App,
    credential_type: str,
    credential_id: int,
    capabilities: list[str],
    actor: CredentialActor,
) -> AppCredential | OAuthClientBinding:
    match credential_type:
        case "static-tokens":
            credential: AppCredential | OAuthClientBinding = _static_credential_for_app(
                app=app,
                credential_id=credential_id,
            )
        case "oauth-clients":
            credential = _oauth_client_for_app(app=app, credential_id=credential_id)
        case _:
            raise CredentialOperationError(
                code="credential_not_found",
                credential_id=credential_id,
            )
    credential.capabilities = capabilities
    credential.full_clean()
    credential.save(update_fields=["capabilities", "updated_at"])
    _record_credential_event(
        CredentialEvent(
            app=app,
            actor=actor,
            action="console_credential_capabilities_updated",
            credential_type=credential.credential_type,
            credential_id=credential_id,
            capabilities=capabilities,
        ),
    )
    return credential


def _static_credential_for_app(*, app: App, credential_id: int) -> AppCredential:
    credential = AppCredential.objects.filter(
        app=app,
        id=credential_id,
        credential_type=APP_CREDENTIAL_STATIC_KIND,
    ).first()
    if credential is None:
        raise CredentialOperationError(code="credential_not_found", credential_id=credential_id)
    return credential


def _oauth_client_for_app(*, app: App, credential_id: int) -> OAuthClientBinding:
    binding = OAuthClientBinding.objects.filter(app=app, id=credential_id).first()
    if binding is None:
        raise CredentialOperationError(code="credential_not_found", credential_id=credential_id)
    return binding


def _record_credential_event(event: CredentialEvent) -> None:
    metadata: dict[str, str | int | list[str]] = {
        "app_key": event.app.app_key,
        "credential_type": event.credential_type,
        "credential_id": event.credential_id,
    }
    if event.reason:
        metadata["reason"] = event.reason
    if event.capabilities is not None:
        metadata["capabilities"] = event.capabilities
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=event.actor.actor_id,
            action=event.action,
            target_type="app_credential",
            target_id=str(event.credential_id),
            metadata=metadata,
        ),
    )
