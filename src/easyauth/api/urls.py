from __future__ import annotations

from django.urls import path

from easyauth.api.approval_views import (
    app_approval_instance_detail,
    app_approval_instances,
    app_approval_templates,
)
from easyauth.api.directory_views import (
    directory_departments,
    directory_user_detail,
    directory_user_manager,
    directory_user_subordinates,
    directory_users,
)
from easyauth.api.manifest_sync_views import app_manifest_sync
from easyauth.api.notify_views import notify_message_detail, notify_messages_create
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
    path(
        "apps/<str:app_key>/approval-templates",
        app_approval_templates,
        name="app-approval-templates",
    ),
    path(
        "apps/<str:app_key>/directory/users",
        directory_users,
        name="app-directory-users",
    ),
    path(
        "apps/<str:app_key>/directory/users/<str:user_ref>/manager",
        directory_user_manager,
        name="app-directory-user-manager",
    ),
    path(
        "apps/<str:app_key>/directory/users/<str:user_ref>/subordinates",
        directory_user_subordinates,
        name="app-directory-user-subordinates",
    ),
    path(
        "apps/<str:app_key>/directory/users/<str:user_ref>",
        directory_user_detail,
        name="app-directory-user-detail",
    ),
    path(
        "apps/<str:app_key>/directory/departments",
        directory_departments,
        name="app-directory-departments",
    ),
    path(
        "apps/<str:app_key>/notify/messages",
        notify_messages_create,
        name="app-notify-messages-create",
    ),
    path(
        "apps/<str:app_key>/notify/messages/<str:message_id>",
        notify_message_detail,
        name="app-notify-message-detail",
    ),
]
