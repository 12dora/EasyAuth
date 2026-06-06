from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, override

if TYPE_CHECKING:
    from easyauth.applications.models import PermissionTemplateVersion

type TemplateNodeType = Literal["group", "permission"]
type TemplateSource = Literal["upload", "paste", "manual"]
type TemplateActionType = Literal[
    "create_group",
    "update_group",
    "create_permission",
    "update_permission",
    "move_permission",
    "deprecate_permission",
]


@dataclass(frozen=True, slots=True)
class TemplateNodeInput:
    key: str
    name: str
    node_type: TemplateNodeType
    children: tuple[TemplateNodeInput, ...] = ()


@dataclass(frozen=True, slots=True)
class PermissionTemplateInput:
    version: int
    source: TemplateSource
    imported_by: str
    raw_template: str
    nodes: tuple[TemplateNodeInput, ...]


@dataclass(frozen=True, slots=True)
class TemplateAction:
    action: TemplateActionType
    key: str
    parent_key: str = ""


@dataclass(frozen=True, slots=True)
class PermissionTemplatePreview:
    actions: tuple[TemplateAction, ...]


@dataclass(frozen=True, slots=True)
class PermissionTemplateImportResult:
    template_version: PermissionTemplateVersion
    actions: tuple[TemplateAction, ...]


@dataclass(frozen=True, slots=True)
class PermissionTemplateImportError(Exception):
    code: str
    message: str
    subject: str = ""

    @override
    def __str__(self) -> str:
        if self.subject:
            return f"{self.code}: {self.subject}: {self.message}"
        return f"{self.code}: {self.message}"


@dataclass(frozen=True, slots=True)
class GroupSpec:
    key: str
    name: str
    parent_key: str
    depth: int
    display_order: int


@dataclass(frozen=True, slots=True)
class PermissionSpec:
    key: str
    name: str
    group_key: str


@dataclass(frozen=True, slots=True)
class FlattenedTemplate:
    groups: tuple[GroupSpec, ...]
    permissions: tuple[PermissionSpec, ...]
