from __future__ import annotations

from django.urls import path

from easyauth.accounts import views

urlpatterns = [
    path("dev-login/", views.dev_login, name="dev-login"),
    path("logged-out/", views.logged_out, name="logged-out"),
    path("login/", views.oidc_login, name="oidc-login"),
    path("callback/", views.oidc_callback, name="oidc-callback"),
    path("logout/", views.logout, name="logout"),
]
