from __future__ import annotations

from django.urls import path

from easyauth.api.approval_views import (
    app_approval_instance_detail,
    app_approval_instances,
)
from easyauth.api.manifest_sync_views import app_manifest_sync
from easyauth.api.views import query_user_permissions

urlpatterns = [
    path(
        "apps/<str:app_key>/users/<str:user_id>/permissions",
        query_user_permissions,
        name="query-user-permissions",
    ),
    path(
        "apps/<str:app_key>/manifest-sync",
        app_manifest_sync,
        name="app-manifest-sync",
    ),
    path(
        "apps/<str:app_key>/approval-instances",
        app_approval_instances,
        name="app-approval-instances",
    ),
    path(
        "apps/<str:app_key>/approval-instances/<str:instance_id>",
        app_approval_instance_detail,
        name="app-approval-instance-detail",
    ),
]
