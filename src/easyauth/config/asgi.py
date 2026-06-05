from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

if "DJANGO_SETTINGS_MODULE" not in os.environ:
    os.environ["DJANGO_SETTINGS_MODULE"] = "easyauth.config.settings.base"

application = get_asgi_application()
