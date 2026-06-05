from __future__ import annotations

from django.urls import path

from easyauth.portal.views import portal_home

urlpatterns = [
    path("", portal_home, name="portal-home"),
]
