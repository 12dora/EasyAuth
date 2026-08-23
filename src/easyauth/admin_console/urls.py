from __future__ import annotations

from easyauth.admin_console.urls_catalog import CATALOG_URLPATTERNS
from easyauth.admin_console.urls_core import CORE_URLPATTERNS
from easyauth.admin_console.urls_integrations import INTEGRATION_URLPATTERNS
from easyauth.admin_console.urls_lifecycle import LIFECYCLE_URLPATTERNS
from easyauth.admin_console.urls_management import MANAGEMENT_URLPATTERNS
from easyauth.admin_console.urls_pages import PAGE_URLPATTERNS

app_name = "admin_console"

urlpatterns = [
    *CORE_URLPATTERNS,
    *LIFECYCLE_URLPATTERNS,
    *MANAGEMENT_URLPATTERNS,
    *INTEGRATION_URLPATTERNS,
    *CATALOG_URLPATTERNS,
    *PAGE_URLPATTERNS,
]

