from __future__ import annotations

from django.urls import path

from easyauth.admin_console import views

PAGE_URLPATTERNS = [
    path("operations", views.console_operations, name="console-operations-no-slash"),
    path("operations/", views.console_operations, name="console-operations"),
    path("operations/<path:_path>", views.console_operations, name="console-operations-path"),
    path("settings", views.console_home, name="console-settings"),
    path("settings/", views.console_home, name="console-settings-slash"),
    path("apps/new", views.console_home, name="console-app-new"),
    path("apps/new/", views.console_home, name="console-app-new-slash"),
    path("teams", views.console_home, name="console-teams-page"),
    path("teams/", views.console_home, name="console-teams-page-slash"),
    path("teams/<path:_path>", views.console_operations, name="console-teams-path"),
    path("people", views.console_home, name="console-people"),
    path("people/", views.console_home, name="console-people-slash"),
    path(
        "lifecycle/handover-tasks",
        views.console_home,
        name="console-handover-tasks",
    ),
    path(
        "lifecycle/handover-tasks/",
        views.console_home,
        name="console-handover-tasks-slash",
    ),
    path(
        "lifecycle/handover-tasks/<path:_path>",
        views.console_operations,
        name="console-handover-tasks-path",
    ),
    path(
        "lifecycle/onboarding",
        views.console_home,
        name="console-lifecycle-onboarding",
    ),
    path(
        "lifecycle/onboarding/",
        views.console_home,
        name="console-lifecycle-onboarding-slash",
    ),
    path(
        "approval-templates",
        views.console_home,
        name="console-approval-templates-page",
    ),
    path(
        "approval-templates/",
        views.console_home,
        name="console-approval-templates-page-slash",
    ),
    path("apps/<str:app_key>", views.app_detail, name="app-detail-no-slash"),
    path("apps/<str:app_key>/", views.app_detail, name="app-detail"),
]

