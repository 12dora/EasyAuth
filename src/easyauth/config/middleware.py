from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from easyauth.config.error_views import not_found

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse


class SafeNotFoundMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response: Callable[[HttpRequest], HttpResponse]
        self._get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self._get_response(request)
        if response.status_code != HTTPStatus.NOT_FOUND:
            return response
        if not _is_html_response(response):
            return response
        return not_found(request)


def _is_html_response(response: HttpResponse) -> bool:
    content_type = response.headers.get("Content-Type", "")
    return content_type == "" or content_type.startswith("text/html")
