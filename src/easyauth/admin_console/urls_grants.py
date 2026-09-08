from __future__ import annotations

from django.urls import path

from easyauth.admin_console.department_grants_api import (
    console_department_grant_policies,
    console_department_grant_policy,
    console_departments_tree,
)
from easyauth.admin_console.direct_grants_api import (
    console_direct_grants,
    console_user_app_current_grant,
)
from easyauth.admin_console.grant_catalog_api import console_grant_catalog

GRANT_URLPATTERNS = [
    path("api/v1/grant-catalog", console_grant_catalog, name="console-grant-catalog"),
    path("api/v1/direct-grants", console_direct_grants, name="console-direct-grants"),
    path(
        "api/v1/users/<str:user_id>/apps/<str:app_key>/current-grant",
        console_user_app_current_grant,
        name="console-user-app-current-grant",
    ),
    path("api/v1/departments/tree", console_departments_tree, name="console-departments-tree"),
    path(
        "api/v1/departments/<str:dept_id>/grant-policies",
        console_department_grant_policies,
        name="console-department-grant-policies",
    ),
    path(
        "api/v1/department-grant-policies/<int:policy_id>",
        console_department_grant_policy,
        name="console-department-grant-policy",
    ),
]
