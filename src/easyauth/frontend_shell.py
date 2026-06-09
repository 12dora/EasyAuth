from __future__ import annotations

from dataclasses import dataclass
from json import loads
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, TypeGuard, cast

from django.shortcuts import render

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


def render_react_shell(
    request: HttpRequest,
    *,
    surface: ShellName,
    title: str,
    initial_app_key: str = "",
    current_user_id: str = "",
) -> HttpResponse:
    return render(
        request,
        REACT_SHELL_TEMPLATE,
        {
            "initial_app_key": initial_app_key,
            "current_user_id": current_user_id,
            "shell": surface,
            "title": title,
            "vite_assets": vite_entry_assets(),
        },
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
