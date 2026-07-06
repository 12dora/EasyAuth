from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, override

if TYPE_CHECKING:
    from easyauth.applications.models import PermissionTemplateVersion

type TemplateSource = Literal["upload", "paste", "manual"]
type AuthorizationGroupKind = Literal["role", "bundle"]
type ApprovalRuleTargetType = Literal["authorization_group", "permission"]
type TemplateActionType = str


@dataclass(frozen=True, slots=True)
class AppManifestAppInput:
    app_key: str
    name: str
    description: str = ""
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class AppManifestScopeInput:
    key: str
    name: str
    name_en: str = ""
    description: str = ""
    description_en: str = ""
    is_active: bool = True
    display_order: int = 0


@dataclass(frozen=True, slots=True)
class AppManifestPermissionGroupInput:
    key: str
    name: str
    name_en: str = ""
    description: str = ""
    description_en: str = ""
    parent_key: str = ""
    display_order: int = 0
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class AppManifestPermissionInput:
    key: str
    name: str
    name_en: str = ""
    description: str = ""
    description_en: str = ""
    group_key: str = ""
    supported_scopes: tuple[str, ...] = ()
    risk_level: str = "standard"
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class AppManifestGrantInput:
    permission: str
    scope: str
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class AppManifestAuthorizationGroupInput:
    key: str
    kind: AuthorizationGroupKind
    name: str
    name_en: str = ""
    description: str = ""
    description_en: str = ""
    requestable: bool = True
    is_active: bool = True
    grants: tuple[AppManifestGrantInput, ...] = ()


@dataclass(frozen=True, slots=True)
class AppManifestApprovalRuleInput:
    target_type: ApprovalRuleTargetType
    target_key: str
    approver_userids: tuple[str, ...]
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class AppManifestLifecycleInput:
    # 下游生命周期交接钩子声明(§5.1): URL 可为绝对地址或以 / 开头的站内路径,
    # 相对路径在自动接入时用下游 base_url 补全。
    handover_url: str = ""
    onboard_url: str = ""
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AppManifestInput:
    schema_version: int
    source: TemplateSource
    imported_by: str
    raw_template: str
    app: AppManifestAppInput
    scopes: tuple[AppManifestScopeInput, ...]
    permission_groups: tuple[AppManifestPermissionGroupInput, ...]
    permissions: tuple[AppManifestPermissionInput, ...]
    authorization_groups: tuple[AppManifestAuthorizationGroupInput, ...]
    approval_rules: tuple[AppManifestApprovalRuleInput, ...]
    lifecycle: AppManifestLifecycleInput | None = None


PermissionTemplateInput = AppManifestInput


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
class FlattenedTemplate:
    manifest: AppManifestInput
