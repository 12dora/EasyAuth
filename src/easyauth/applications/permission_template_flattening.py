from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from easyauth.applications.ops_models import (
    PERMISSION_GROUP_MAX_DEPTH,
    TEMPLATE_SOURCE_MANUAL,
    TEMPLATE_SOURCE_PASTE,
    TEMPLATE_SOURCE_UPLOAD,
)
from easyauth.applications.permission_template_types import (
    FlattenedTemplate,
    GroupSpec,
    PermissionSpec,
    PermissionTemplateImportError,
    PermissionTemplateInput,
    TemplateNodeInput,
)

PERMISSION_TEMPLATE_MAX_RAW_LENGTH: Final = 65536


@dataclass(slots=True)
class _FlattenState:
    groups: list[GroupSpec]
    permissions: list[PermissionSpec]
    seen_group_keys: set[str]
    seen_permission_keys: set[str]


@dataclass(frozen=True, slots=True)
class _NodePosition:
    parent_key: str
    depth: int
    display_order: int
    ancestors: tuple[str, ...]


def flatten_template(template: PermissionTemplateInput) -> FlattenedTemplate:
    _validate_template_boundary(template)
    state = _FlattenState(
        groups=[],
        permissions=[],
        seen_group_keys=set(),
        seen_permission_keys=set(),
    )
    for display_order, node in enumerate(template.nodes):
        _flatten_node(
            node=node,
            position=_NodePosition(
                parent_key="",
                depth=1,
                display_order=display_order,
                ancestors=(),
            ),
            state=state,
        )
    return FlattenedTemplate(groups=tuple(state.groups), permissions=tuple(state.permissions))


def _flatten_node(
    *,
    node: TemplateNodeInput,
    position: _NodePosition,
    state: _FlattenState,
) -> None:
    match node.node_type:
        case "group":
            _append_group_node(node=node, position=position, state=state)
        case "permission":
            if node.key in state.seen_permission_keys:
                _raise_template_error("permission_template_duplicate_key", node.key)
            state.seen_permission_keys.add(node.key)
            state.permissions.append(
                PermissionSpec(key=node.key, name=node.name, group_key=position.parent_key),
            )


def _append_group_node(
    *,
    node: TemplateNodeInput,
    position: _NodePosition,
    state: _FlattenState,
) -> None:
    if node.key in position.ancestors:
        _raise_template_error("permission_template_cycle", node.key)
    if node.key in state.seen_group_keys:
        _raise_template_error("permission_template_duplicate_key", node.key)
    if position.depth > PERMISSION_GROUP_MAX_DEPTH:
        _raise_template_error("permission_template_depth_exceeded", node.key)
    state.seen_group_keys.add(node.key)
    state.groups.append(
        GroupSpec(
            key=node.key,
            name=node.name,
            parent_key=position.parent_key,
            depth=position.depth,
            display_order=position.display_order,
        ),
    )
    for child_order, child in enumerate(node.children):
        _flatten_node(
            node=child,
            position=_NodePosition(
                parent_key=node.key,
                depth=position.depth + 1,
                display_order=child_order,
                ancestors=(*position.ancestors, node.key),
            ),
            state=state,
        )


def _validate_template_boundary(template: PermissionTemplateInput) -> None:
    if template.version < 1:
        _raise_template_error("permission_template_version_invalid", str(template.version))
    supported_sources = {TEMPLATE_SOURCE_UPLOAD, TEMPLATE_SOURCE_PASTE, TEMPLATE_SOURCE_MANUAL}
    if template.source not in supported_sources:
        _raise_template_error("permission_template_source_invalid", template.source)
    if len(template.raw_template) > PERMISSION_TEMPLATE_MAX_RAW_LENGTH:
        _raise_template_error("permission_template_too_large", str(len(template.raw_template)))


def _raise_template_error(code: str, subject: str) -> None:
    message = "权限模板不符合导入约束。"
    raise PermissionTemplateImportError(code=code, message=message, subject=subject)
