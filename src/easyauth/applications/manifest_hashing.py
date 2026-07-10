from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING, cast

from yaml import safe_load

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue


def canonical_manifest_template(manifest: dict[str, JsonValue]) -> str:
    return json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_manifest_hash(manifest: dict[str, JsonValue]) -> str:
    canonical = canonical_manifest_template(manifest)
    return sha256(canonical.encode("utf-8")).hexdigest()


def canonical_manifest_hash_from_template(raw_template: str) -> str:
    manifest = safe_load(raw_template)
    if not isinstance(manifest, dict):
        msg = "App manifest 顶层必须是对象。"
        raise TypeError(msg)
    return canonical_manifest_hash(cast("dict[str, JsonValue]", manifest))
