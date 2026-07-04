from __future__ import annotations

from django.urls import path

from easyauth.accounts import local_admin_views, views

urlpatterns = [
    path("logged-out/", views.logged_out, name="logged-out"),
    path("login/", views.oidc_login, name="oidc-login"),
    path("callback/", views.oidc_callback, name="oidc-callback"),
    path("logout/", views.logout, name="logout"),
    path("local/", local_admin_views.login_page, name="local-admin-login"),
    path("local/verify/", local_admin_views.verify_page, name="local-admin-verify"),
    path("local/verify/totp/", local_admin_views.verify_totp, name="local-admin-verify-totp"),
    path("local/passkey/begin/", local_admin_views.passkey_begin, name="local-admin-passkey-begin"),
    path(
        "local/passkey/complete/",
        local_admin_views.passkey_complete,
        name="local-admin-passkey-complete",
    ),
    path(
        "local/change-password/",
        local_admin_views.change_password_page,
        name="local-admin-change-password",
    ),
    path("local/security/", local_admin_views.security_page, name="local-admin-security"),
    path(
        "local/security/totp/begin/",
        local_admin_views.totp_begin,
        name="local-admin-totp-begin",
    ),
    path(
        "local/security/totp/confirm/",
        local_admin_views.totp_confirm,
        name="local-admin-totp-confirm",
    ),
    path(
        "local/security/totp/disable/",
        local_admin_views.totp_disable,
        name="local-admin-totp-disable",
    ),
    path(
        "local/security/passkey/register/begin/",
        local_admin_views.passkey_register_begin,
        name="local-admin-passkey-register-begin",
    ),
    path(
        "local/security/passkey/register/complete/",
        local_admin_views.passkey_register_complete,
        name="local-admin-passkey-register-complete",
    ),
    path(
        "local/security/passkey/<int:passkey_id>/delete/",
        local_admin_views.passkey_delete,
        name="local-admin-passkey-delete",
    ),
]
