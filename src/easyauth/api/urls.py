from __future__ import annotations

from django.urls import path

from easyauth.api.views import query_user_permissions

urlpatterns = [
    path(
        "apps/<str:app_key>/users/<str:user_id>/permissions",
        query_user_permissions,
        name="query-user-permissions",
    ),
]
