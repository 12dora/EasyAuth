from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from yaml import YAMLError, safe_load

from easyauth.applications.permission_template_flattening import (
    PERMISSION_TEMPLATE_MAX_RAW_LENGTH,
)
from easyauth.applications.permission_template_types import (
    PermissionTemplateImportError,
    PermissionTemplateInput,
    TemplateNodeInput,
    TemplateNodeType,
)

type TemplateFormat = Literal["json", "yaml"]


class _TemplateNodePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    node_type: TemplateNodeType = Field(default="group", alias="type")
    children: tuple[_TemplateNodePayload, ...] = ()


class _PermissionTemplatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    groups: tuple[_TemplateNodePayload, ...]


def parse_template_format(raw_format: str) -> TemplateFormat:
    match raw_format:
        case "json":
            return "json"
        case "yaml":
            return "yaml"
        case _:
            raise PermissionTemplateImportError(
                code="permission_template_format_invalid",
                message="权限模板格式必须是 JSON 或 YAML。",
                subject=raw_format,
            )


def parse_permission_template(
    *,
    raw_template: str,
    template_format: TemplateFormat,
    imported_by: str,
) -> PermissionTemplateInput:
    try:
        payload = _parse_payload(raw_template=raw_template, template_format=template_format)
    except (ValidationError, ValueError, YAMLError) as exc:
        raise PermissionTemplateImportError(
            code="permission_template_parse_error",
            message="权限模板无法解析。",
            subject=template_format,
        ) from exc
    return PermissionTemplateInput(
        version=payload.version,
        source="paste",
        imported_by=imported_by,
        raw_template=raw_template,
        nodes=_template_nodes(payload.groups),
    )


def _parse_payload(
    *,
    raw_template: str,
    template_format: TemplateFormat,
) -> _PermissionTemplatePayload:
    if len(raw_template) > PERMISSION_TEMPLATE_MAX_RAW_LENGTH:
        raise PermissionTemplateImportError(
            code="permission_template_too_large",
            message="权限模板不符合导入约束。",
            subject=str(len(raw_template)),
        )
    match template_format:
        case "json":
            return _PermissionTemplatePayload.model_validate_json(raw_template)
        case "yaml":
            return _PermissionTemplatePayload.model_validate(safe_load(raw_template))


def _template_nodes(
    payloads: tuple[_TemplateNodePayload, ...],
) -> tuple[TemplateNodeInput, ...]:
    return tuple(_template_node(payload) for payload in payloads)


def _template_node(payload: _TemplateNodePayload) -> TemplateNodeInput:
    return TemplateNodeInput(
        key=payload.key,
        name=payload.name,
        node_type=payload.node_type,
        children=_template_nodes(payload.children),
    )
