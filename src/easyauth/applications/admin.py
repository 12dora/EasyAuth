from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from django.contrib import admin

from easyauth.applications.models import (
    App,
    AppCredential,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
    Role,
    RolePermission,
)

if TYPE_CHECKING:
    from django.http import HttpRequest

    class AppAdminBase(admin.ModelAdmin[App]):
        pass

    class RoleAdminBase(admin.ModelAdmin[Role]):
        pass

    class AppScopeAdminBase(admin.ModelAdmin[AppScope]):
        pass

    class AuthorizationGroupAdminBase(admin.ModelAdmin[AuthorizationGroup]):
        pass

    class AuthorizationGroupGrantAdminBase(admin.ModelAdmin[AuthorizationGroupGrant]):
        pass

    class PermissionAdminBase(admin.ModelAdmin[Permission]):
        pass

    class RolePermissionAdminBase(admin.ModelAdmin[RolePermission]):
        pass

    class ApprovalRuleAdminBase(admin.ModelAdmin[ApprovalRule]):
        pass

    class AppCredentialAdminBase(admin.ModelAdmin[AppCredential]):
        pass

else:

    class AppAdminBase(admin.ModelAdmin):
        pass

    class RoleAdminBase(admin.ModelAdmin):
        pass

    class AppScopeAdminBase(admin.ModelAdmin):
        pass

    class AuthorizationGroupAdminBase(admin.ModelAdmin):
        pass

    class AuthorizationGroupGrantAdminBase(admin.ModelAdmin):
        pass

    class PermissionAdminBase(admin.ModelAdmin):
        pass

    class RolePermissionAdminBase(admin.ModelAdmin):
        pass

    class ApprovalRuleAdminBase(admin.ModelAdmin):
        pass

    class AppCredentialAdminBase(admin.ModelAdmin):
        pass


@admin.register(App)
@final
class AppAdmin(AppAdminBase):
    list_display = ("app_key", "name", "is_active", "created_at", "updated_at")
    search_fields = ("app_key", "name")
    list_filter = ("is_active",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Role)
@final
class RoleAdmin(RoleAdminBase):
    list_display = (
        "app",
        "key",
        "name",
        "is_active",
        "requestable",
        "approval_rule_status",
    )
    search_fields = ("app__app_key", "key", "name")
    list_filter = ("app", "is_active", "requestable")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="审批规则状态")
    def approval_rule_status(self, obj: Role) -> str:
        if not obj.requestable:
            return "不可申请"
        authorization_group = AuthorizationGroup.objects.filter(
            app=obj.app,
            key=obj.key,
            kind="role",
            is_active=True,
        ).first()
        if (
            authorization_group is not None
            and ApprovalRule.objects.filter(
                authorization_group=authorization_group,
                is_active=True,
            ).exists()
        ):
            return "有效"
        return "缺少有效审批规则"


@admin.register(AppScope)
@final
class AppScopeAdmin(AppScopeAdminBase):
    list_display = ("app", "key", "name", "is_active", "display_order", "created_at", "updated_at")
    search_fields = ("app__app_key", "key", "name")
    list_filter = ("app", "is_active")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Permission)
@final
class PermissionAdmin(PermissionAdminBase):
    list_display = (
        "app",
        "key",
        "name",
        "risk_level",
        "is_active",
        "created_at",
        "updated_at",
    )
    search_fields = ("app__app_key", "key", "name")
    list_filter = ("app", "risk_level", "is_active")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AuthorizationGroup)
@final
class AuthorizationGroupAdmin(AuthorizationGroupAdminBase):
    list_display = (
        "app",
        "key",
        "kind",
        "name",
        "requestable",
        "is_active",
        "created_at",
        "updated_at",
    )
    search_fields = ("app__app_key", "key", "name")
    list_filter = ("app", "kind", "requestable", "is_active")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AuthorizationGroupGrant)
@final
class AuthorizationGroupGrantAdmin(AuthorizationGroupGrantAdminBase):
    list_display = ("authorization_group", "permission", "scope_key", "is_active", "created_at")
    search_fields = (
        "authorization_group__app__app_key",
        "authorization_group__key",
        "permission__key",
        "scope_key",
    )
    list_filter = ("authorization_group__app", "scope_key", "is_active")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RolePermission)
@final
class RolePermissionAdmin(RolePermissionAdminBase):
    list_display = ("role", "permission", "created_at")
    search_fields = ("role__app__app_key", "role__key", "permission__key")
    list_filter = ("role__app",)
    readonly_fields = ("created_at",)


@admin.register(ApprovalRule)
@final
class ApprovalRuleAdmin(ApprovalRuleAdminBase):
    list_display = ("app", "role", "permission", "is_active", "created_at", "updated_at")
    search_fields = ("app__app_key", "role__key", "permission__key")
    list_filter = ("app", "is_active")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AppCredential)
@final
class AppCredentialAdmin(AppCredentialAdminBase):
    exclude = ("token_hash",)
    fields = (
        "app",
        "credential_type",
        "name",
        "is_active",
        "disabled_at",
        "created_at",
        "updated_at",
    )
    list_display = (
        "app",
        "credential_type",
        "name",
        "is_active",
        "disabled_at",
        "created_at",
        "updated_at",
    )
    search_fields = ("app__app_key", "credential_type", "name")
    list_filter = ("app", "credential_type", "is_active")
    readonly_fields = fields

    @override
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @override
    def has_change_permission(
        self,
        request: HttpRequest,
        obj: AppCredential | None = None,
    ) -> bool:
        if obj is not None:
            return False
        return super().has_change_permission(request, obj)

    @override
    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: AppCredential | None = None,
    ) -> bool:
        return False
