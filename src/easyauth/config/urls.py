from __future__ import annotations

from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.urls import include, path
from oauth2_provider.views import TokenView


def health(_request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("auth/", include("easyauth.accounts.urls")),
    path("api/v1/", include("easyauth.api.urls")),
    path("oauth/token", TokenView.as_view(), name="oauth-token"),
    path("portal/", include("easyauth.portal.urls")),
    path("health/", health, name="health"),
]
