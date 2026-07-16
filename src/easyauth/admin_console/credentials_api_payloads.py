from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.applications.models import App, AppCredential, OAuthClientBinding
from easyauth.applications.services import APP_CREDENTIAL_STATIC_KIND

if TYPE_CHECKING:
    from easyauth.admin_console.credentials import OneTimeSecret
    from easyauth.api.errors import JsonValue


def credential_items(app: App) -> list[JsonValue]:
    items: list[JsonValue] = []
    credentials = AppCredential.objects.filter(
        app=app,
        credential_type=APP_CREDENTIAL_STATIC_KIND,
    ).order_by("id")
    bindings = (
        OAuthClientBinding.objects.select_related("oauth_application")
        .filter(app=app)
        .order_by("id")
    )
    items.extend(static_credential_item(credential) for credential in credentials)
    items.extend(oauth_client_item(binding) for binding in bindings)
    return items


def static_credential_item(credential: AppCredential) -> dict[str, JsonValue]:
    capabilities: list[JsonValue] = list(credential.capabilities)
    return {
        "id": credential.id,
        "kind": "static_token",
        "name": credential.name,
        "is_active": credential.is_active,
        "capabilities": capabilities,
    }


def oauth_client_item(binding: OAuthClientBinding) -> dict[str, JsonValue]:
    capabilities: list[JsonValue] = list(binding.capabilities)
    return {
        "id": binding.id,
        "kind": "oauth_client",
        "name": binding.name,
        "is_active": binding.is_active,
        "client_id": binding.oauth_application.client_id,
        "capabilities": capabilities,
    }


def credential_secret_payload(
    credential: dict[str, JsonValue],
    one_time_secret: OneTimeSecret,
) -> dict[str, JsonValue]:
    secret: dict[str, JsonValue] = {
        "kind": one_time_secret.kind,
        one_time_secret.label: one_time_secret.value,
    }
    if one_time_secret.secondary_label:
        secret[one_time_secret.secondary_label] = one_time_secret.secondary_value
    return {"credential": credential, "one_time_secret": secret}
