from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

from easyauth.config.local_env import load_local_env

load_local_env()
if "DJANGO_SETTINGS_MODULE" not in os.environ:
    os.environ["DJANGO_SETTINGS_MODULE"] = "easyauth.config.settings.base"

application = get_wsgi_application()
