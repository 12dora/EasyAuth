from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from json import loads
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, TypeGuard, cast

from django.shortcuts import render

from easyauth.accounts.auth import AUTHENTIK_GROUPS_SESSION_KEY, AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.config.settings.base import BASE_DIR

if TYPE_CHECKING:

    from django.http import HttpRequest, HttpResponse

    from easyauth.api.errors import JsonValue

type ShellName = Literal["console", "portal"]

REACT_SHELL_TEMPLATE: Final = "easyauth/react_shell.html"
VITE_ENTRY: Final = "src/main.tsx"
VITE_MANIFEST_PATH: Final = Path("src/easyauth/static/easyauth/frontend/.vite/manifest.json")
VITE_STATIC_PREFIX: Final = "easyauth/frontend/"


@dataclass(frozen=True, slots=True)
class ViteAsset:
    path: str


@dataclass(frozen=True, slots=True)
class ViteEntryAssets:
    scripts: tuple[ViteAsset, ...] = ()
    stylesheets: tuple[ViteAsset, ...] = ()


@dataclass(frozen=True, slots=True)
class ShellUser:
    user_id: str
    display_name: str
    role: str
    avatar_url: str = ""


def render_react_shell(
    request: HttpRequest,
    *,
    surface: ShellName,
    title: str,
    initial_app_key: str = "",
    current_user: ShellUser | None = None,
) -> HttpResponse:
    shell_user = current_user or shell_user_from_session(request)
    return _render_react_shell_response(
        request,
        surface=surface,
        title=title,
        initial_app_key=initial_app_key,
        shell_user=shell_user,
    )


def render_public_react_shell(
    request: HttpRequest,
    *,
    surface: ShellName,
    title: str,
    initial_app_key: str = "",
) -> HttpResponse:
    return _render_react_shell_response(
        request,
        surface=surface,
        title=title,
        initial_app_key=initial_app_key,
        shell_user=None,
    )


def _render_react_shell_response(
    request: HttpRequest,
    *,
    surface: ShellName,
    title: str,
    initial_app_key: str,
    shell_user: ShellUser | None,
) -> HttpResponse:
    response = render(
        request,
        REACT_SHELL_TEMPLATE,
        {
            "initial_app_key": initial_app_key,
            "current_user": shell_user,
            "logout_url": "/auth/logout/",
            "shell": surface,
            "title": title,
            "vite_assets": vite_entry_assets(),
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def shell_user_from_session(request: HttpRequest) -> ShellUser | None:
    user_id = _session_string(request, AUTHENTIK_SESSION_KEY)
    if user_id == "":
        return None

    user = UserMirror.objects.filter(
        authentik_user_id=user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if user is None:
        return None
    return shell_user_from_user(request, user)


def shell_user_from_user(request: HttpRequest, user: UserMirror) -> ShellUser:
    return ShellUser(
        user_id=user.authentik_user_id,
        display_name=_display_name(user),
        role=_role_label(request),
        avatar_url=user.avatar_url,
    )


def vite_entry_assets() -> ViteEntryAssets:
    manifest = _manifest_payload()
    entry = manifest.get(VITE_ENTRY)
    if not isinstance(entry, dict):
        return ViteEntryAssets()

    scripts = _entry_scripts(entry)
    stylesheets = _entry_stylesheets(entry)
    return ViteEntryAssets(scripts=scripts, stylesheets=stylesheets)


def _manifest_payload() -> dict[str, JsonValue]:
    manifest_path = BASE_DIR / VITE_MANIFEST_PATH
    if not manifest_path.exists():
        return {}
    payload = cast("object", loads(manifest_path.read_text(encoding="utf-8")))
    if not _is_json_object(payload):
        return {}
    return payload


def _entry_scripts(entry: dict[str, JsonValue]) -> tuple[ViteAsset, ...]:
    file_path = entry.get("file")
    if not isinstance(file_path, str) or file_path == "":
        return ()
    return (ViteAsset(path=f"{VITE_STATIC_PREFIX}{file_path}"),)


def _entry_stylesheets(entry: dict[str, JsonValue]) -> tuple[ViteAsset, ...]:
    css_paths = entry.get("css")
    if not isinstance(css_paths, list):
        return ()
    return tuple(
        ViteAsset(path=f"{VITE_STATIC_PREFIX}{css_path}")
        for css_path in css_paths
        if isinstance(css_path, str) and css_path != ""
    )


def _is_json_object(value: object) -> TypeGuard[dict[str, JsonValue]]:
    if not isinstance(value, dict):
        return False
    items = cast("dict[object, object]", value).items()
    return all(isinstance(key, str) and _is_json_value(item) for key, item in items)


def _is_json_value(value: object) -> TypeGuard[JsonValue]:
    if value is None or isinstance(value, str | int | float | bool):
        return True
    if isinstance(value, list):
        items = cast("list[object]", value)
        return all(_is_json_value(item) for item in items)
    return _is_json_object(value)


def _display_name(user: UserMirror) -> str:
    for value in (user.name, user.email):
        normalized_value = value.strip()
        if normalized_value:
            return normalized_value
    return "当前用户"


def _role_label(request: HttpRequest) -> str:
    groups = _session_string_list(request, AUTHENTIK_GROUPS_SESSION_KEY)
    if groups:
        return "、".join(groups[:2])
    return "未分组"


def _session_string(request: HttpRequest, key: str) -> str:
    match request.session.get(key):
        case str() as value:
            return value
        case _:
            return ""


def _session_string_list(request: HttpRequest, key: str) -> tuple[str, ...]:
    value = request.session.get(key)
    if isinstance(value, str):
        return tuple(part for part in value.split() if part)
    if isinstance(value, Sequence):
        return tuple(item for item in value if isinstance(item, str) and item)
    return ()
