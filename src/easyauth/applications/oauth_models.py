from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, override

from django.core.exceptions import ValidationError
from django.db import models
from oauth2_provider.models import Application

if TYPE_CHECKING:
    from datetime import date, datetime

OAUTH_CLIENT_CREDENTIAL_KIND = "oauth_client"


class _BoundApp(Protocol):
    id: int
    app_key: str
    is_active: bool


class OAuthClientBinding(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    app: models.ForeignKey[_BoundApp, _BoundApp] = models.ForeignKey(
        "applications.App",
        on_delete=models.CASCADE,
        related_name="oauth_client_bindings",
    )
    oauth_application: models.OneToOneField[Application, Application] = models.OneToOneField(
        "oauth2_provider.Application",
        on_delete=models.CASCADE,
        related_name="easyauth_binding",
    )
    credential_type: models.CharField[str, str] = models.CharField(
        max_length=32,
        default=OAUTH_CLIENT_CREDENTIAL_KIND,
    )
    name: models.CharField[str, str] = models.CharField(max_length=128)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    disabled_at: models.DateTimeField[str | date | datetime | None, datetime | None] = (
        models.DateTimeField(blank=True, null=True)
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["app__app_key", "id"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.credential_type}:{self.id}"

    @override
    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.credential_type != OAUTH_CLIENT_CREDENTIAL_KIND:
            errors["credential_type"] = "OAuth client binding credential_type must be oauth_client."
        if self.oauth_application.client_type != Application.CLIENT_CONFIDENTIAL:
            errors["oauth_application"] = "OAuth client must be confidential."
        if self.oauth_application.authorization_grant_type != Application.GRANT_CLIENT_CREDENTIALS:
            errors["oauth_application"] = "OAuth client must use client credentials grant."
        if errors:
            raise ValidationError(errors)
