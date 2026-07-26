from __future__ import annotations

from http import HTTPStatus
from typing import Protocol, cast
from urllib.parse import urlparse

import redis
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.utils import DatabaseError
from django.http import HttpRequest, HttpResponseRedirect, JsonResponse
from django.urls import include, path
from oauth2_provider.views import TokenView

from easyauth.admin_console.authz import require_superuser
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


class RedisHealthClient(Protocol):
    def ping(self) -> bool: ...


def health(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


def readiness(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case JsonResponse() as response:
            return response
        case str():
            pass
    checks: dict[str, dict[str, bool | float | None]] = {}
    database_ok = _database_ready()
    broker_ok = _broker_ready()
    checks["database"] = {"healthy": database_ok}
    checks["broker"] = {"healthy": broker_ok}

    heartbeat_specs = (
        (BEAT_WORKER_HEARTBEAT, _setting_float("EASYAUTH_HEALTH_BEAT_MAX_AGE_SECONDS")),
        (
            STREAM_PROCESS_HEARTBEAT,
            _setting_float("EASYAUTH_HEALTH_STREAM_MAX_AGE_SECONDS"),
        ),
        (STREAM_ACK_HEARTBEAT, _setting_float("EASYAUTH_HEALTH_STREAM_MAX_AGE_SECONDS")),
        (
            GRANT_CLEANUP_SUCCESS,
            _setting_float("EASYAUTH_HEALTH_GRANT_CLEANUP_MAX_AGE_SECONDS"),
        ),
        (
            DIRECTORY_SYNC_SUCCESS,
            _setting_float("EASYAUTH_HEALTH_DIRECTORY_SYNC_MAX_AGE_SECONDS"),
        ),
    )
    heartbeats = {
        name: read_heartbeat(name, max_age_seconds=max_age)
        for name, max_age in heartbeat_specs
    }
    checks.update({name: _heartbeat_payload(item) for name, item in heartbeats.items()})

    required = [database_ok, broker_ok]
    if _setting_bool("EASYAUTH_HEALTH_REQUIRE_BACKGROUND"):
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
            _ = cast("object", cursor.execute("SELECT 1"))
            return True
    except DatabaseError:
        return False


def _broker_ready() -> bool:
    try:
        client = _redis_client_from_url(
            _setting_str("CELERY_BROKER_URL"),
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        return _redis_ping(client)
    except (OSError, ValueError, redis.RedisError):
        return False


def _redis_client_from_url(
    broker_url: str,
    *,
    socket_connect_timeout: float,
    socket_timeout: float,
) -> redis.Redis:
    parsed = urlparse(broker_url)
    if parsed.scheme not in {"redis", "rediss"}:
        msg = "CELERY_BROKER_URL must use redis or rediss scheme for readiness checks"
        raise ValueError(msg)
    if parsed.hostname is None:
        msg = "CELERY_BROKER_URL must include a hostname for readiness checks"
        raise ValueError(msg)
    db = int(parsed.path.lstrip("/") or "0")
    return redis.Redis(
        host=parsed.hostname,
        port=parsed.port or 6379,
        db=db,
        password=parsed.password,
        ssl=parsed.scheme == "rediss",
        socket_connect_timeout=socket_connect_timeout,
        socket_timeout=socket_timeout,
    )


def _redis_ping(client: redis.Redis) -> bool:
    ping = cast("RedisHealthClient", cast("object", client)).ping
    return ping() is True


def _setting_float(name: str) -> float:
    value = cast("object", getattr(settings, name))
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{name} must be a number"
        raise ImproperlyConfigured(msg)
    return float(value)


def _setting_bool(name: str) -> bool:
    value = cast("object", getattr(settings, name))
    if not isinstance(value, bool):
        msg = f"{name} must be a boolean"
        raise ImproperlyConfigured(msg)
    return value


def _setting_str(name: str) -> str:
    value = cast("object", getattr(settings, name))
    if not isinstance(value, str):
        msg = f"{name} must be a string"
        raise ImproperlyConfigured(msg)
    return value


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
    path("auth/", include("easyauth.accounts.urls")),
    path("api/v1/", include("easyauth.api.urls")),
    path("console/", include("easyauth.admin_console.urls")),
    path("integrations/dingtalk/", include("easyauth.integrations.dingtalk.urls")),
    path("oauth/token", TokenView.as_view(), name="oauth-token"),
    path("portal/", include("easyauth.portal.urls")),
    path("errors/forbidden/", error_views.forbidden, name="forbidden"),
    path("health/", health, name="health"),
    path("health/readiness/", readiness, name="readiness"),
]

handler404 = "easyauth.config.error_views.not_found"
handler403 = "easyauth.config.error_views.forbidden"
