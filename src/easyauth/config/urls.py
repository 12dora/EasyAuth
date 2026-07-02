from __future__ import annotations

from django.contrib import admin
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import include, path
from oauth2_provider.views import TokenView

from easyauth.config import error_views


def health(_request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok", content_type="text/plain")


def home(_request: HttpRequest) -> HttpResponseRedirect:
    return HttpResponseRedirect("/portal/")


urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("auth/", include("easyauth.accounts.urls")),
    path("api/v1/", include("easyauth.api.urls")),
    path("console/", include("easyauth.admin_console.urls")),
    path("integrations/dingtalk/", include("easyauth.integrations.dingtalk.urls")),
    path("oauth/token", TokenView.as_view(), name="oauth-token"),
    path("portal/", include("easyauth.portal.urls")),
    path("errors/forbidden/", error_views.forbidden, name="forbidden"),
    path("health/", health, name="health"),
]

handler404 = "easyauth.config.error_views.not_found"
handler403 = "easyauth.config.error_views.forbidden"
