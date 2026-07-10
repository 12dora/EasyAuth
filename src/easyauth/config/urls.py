from __future__ import annotations

from http import HTTPStatus

import redis
from django.conf import settings
from django.contrib import admin
from django.db import connection
from django.db.utils import DatabaseError
from django.http import HttpRequest, HttpResponseRedirect, JsonResponse
from django.urls import include, path
from oauth2_provider.views import TokenView

from easyauth.config import error_views
from easyauth.config.runtime_health import (
    BEAT_WORKER_HEARTBEAT,
    DIRECTORY_SYNC_SUCCESS,
    GRANT_CLEANUP_SUCCESS,
    STREAM_ACK_HEARTBEAT,
    STREAM_PROCESS_HEARTBEAT,
    Heartbeat,
    read_heartbeat,
)


def health(_request: HttpRequest) -> JsonResponse:
    checks: dict[str, dict[str, bool | float | None]] = {}
    database_ok = _database_ready()
    broker_ok = _broker_ready()
    checks["database"] = {"healthy": database_ok}
    checks["broker"] = {"healthy": broker_ok}

    heartbeat_specs = (
        (BEAT_WORKER_HEARTBEAT, settings.EASYAUTH_HEALTH_BEAT_MAX_AGE_SECONDS),
        (STREAM_PROCESS_HEARTBEAT, settings.EASYAUTH_HEALTH_STREAM_MAX_AGE_SECONDS),
        (STREAM_ACK_HEARTBEAT, settings.EASYAUTH_HEALTH_STREAM_MAX_AGE_SECONDS),
        (
            GRANT_CLEANUP_SUCCESS,
            settings.EASYAUTH_HEALTH_GRANT_CLEANUP_MAX_AGE_SECONDS,
        ),
        (
            DIRECTORY_SYNC_SUCCESS,
            settings.EASYAUTH_HEALTH_DIRECTORY_SYNC_MAX_AGE_SECONDS,
        ),
    )
    heartbeats = {
        name: read_heartbeat(name, max_age_seconds=max_age)
        for name, max_age in heartbeat_specs
    }
    checks.update({name: _heartbeat_payload(item) for name, item in heartbeats.items()})

    required = [database_ok, broker_ok]
    if settings.EASYAUTH_HEALTH_REQUIRE_BACKGROUND:
        required.extend(
            heartbeats[name].healthy
            for name in (
                BEAT_WORKER_HEARTBEAT,
                STREAM_PROCESS_HEARTBEAT,
                GRANT_CLEANUP_SUCCESS,
                DIRECTORY_SYNC_SUCCESS,
            )
        )
    healthy = all(required)
    return JsonResponse(
        {"status": "ok" if healthy else "unhealthy", "checks": checks},
        status=HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE,
    )


def _database_ready() -> bool:
    try:
        with connection.cursor() as cursor:
            _ = cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)
    except DatabaseError:
        return False


def _broker_ready() -> bool:
    try:
        client = redis.Redis.from_url(
            settings.CELERY_BROKER_URL,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        return bool(client.ping())
    except (OSError, ValueError, redis.RedisError):
        return False


def _heartbeat_payload(heartbeat: Heartbeat) -> dict[str, bool | float | None]:
    return {
        "healthy": heartbeat.healthy,
        "age_seconds": heartbeat.age_seconds,
        "max_age_seconds": heartbeat.max_age_seconds,
    }


def home(_request: HttpRequest) -> HttpResponseRedirect:
    return HttpResponseRedirect("/portal/")


urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("auth/", include("easyauth.accounts.urls")),
    path("api/v1/", include("easyauth.api.urls")),
    path("console/", include("easyauth.admin_console.urls")),
    path("integrations/dingtalk/", include("easyauth.integrations.dingtalk.urls")),
    path("oauth/token", TokenView.as_view(), name="oauth-token"),
    path("portal/", include("easyauth.portal.urls")),
    path("errors/forbidden/", error_views.forbidden, name="forbidden"),
    path("health/", health, name="health"),
]

handler404 = "easyauth.config.error_views.not_found"
handler403 = "easyauth.config.error_views.forbidden"
