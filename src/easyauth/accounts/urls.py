from __future__ import annotations

from django.urls import path

from easyauth.accounts import views

urlpatterns = [
    path("login/", views.oidc_login, name="oidc-login"),
    path("callback/", views.oidc_callback, name="oidc-callback"),
]
