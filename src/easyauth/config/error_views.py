from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.shortcuts import render

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


def not_found(request: HttpRequest, exception: object | None = None) -> HttpResponse:
    _ = exception
    return render(
        request,
        "404.html",
        status=HTTPStatus.NOT_FOUND,
    )


def forbidden(request: HttpRequest, exception: object | None = None) -> HttpResponse:
    _ = exception
    return render(
        request,
        "403.html",
        status=HTTPStatus.FORBIDDEN,
    )
