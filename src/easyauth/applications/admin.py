from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from django.contrib import admin

from easyauth.applications.catalog_version import bump_catalog_version
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
    from collections.abc import Iterable

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


def _admin_actor_id(request: HttpRequest) -> str:
    user = getattr(request, "user", None)
    username = str(getattr(user, "username", "") or "")
    return username or "django-admin"


def _bump_catalog_for_admin_change(
    request: HttpRequest,
    app: App,
    *,
    action: str,
    target: object,
) -> None:
    # /admin/ 直改目录必须与控制台同口径 bump catalog_version 并留审计,
    # 否则下游持有的 snapshot_version 永远认不到这次变更。
    _ = bump_catalog_version(
        app,
        actor_id=_admin_actor_id(request),
        reason=f"django_admin_{action}",
        metadata={
            "model": type(target).__name__,
            "object": str(target),
        },
    )


class CatalogVersionAdminMixin:
    # 目录相关模型的 admin 变更统一 bump catalog_version。

    def catalog_app(self, obj: object) -> App:
        app = getattr(obj, "app", None)
        if not isinstance(app, App):
            message = f"无法从 {type(obj).__name__} 解析所属 App。"
            raise TypeError(message)
        return app

    def save_model(
        self,
        request: HttpRequest,
        obj: object,
        form: object,
        change: bool,  # noqa: FBT001 - Django admin API 固定签名。
    ) -> None:
        super().save_model(request, obj, form, change)  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType]
        _bump_catalog_for_admin_change(
            request,
            self.catalog_app(obj),
            action="updated" if change else "created",
            target=obj,
        )

    def delete_model(self, request: HttpRequest, obj: object) -> None:
        app = self.catalog_app(obj)
        super().delete_model(request, obj)  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType]
        _bump_catalog_for_admin_change(request, app, action="deleted", target=obj)

    def delete_queryset(self, request: HttpRequest, queryset: Iterable[object]) -> None:
        objects = list(queryset)
        apps_by_id = {self.catalog_app(obj).id: self.catalog_app(obj) for obj in objects}
        super().delete_queryset(request, queryset)  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType]
        for app in apps_by_id.values():
            _bump_catalog_for_admin_change(request, app, action="bulk_deleted", target=app)


@admin.register(App)
@final
class AppAdmin(CatalogVersionAdminMixin, AppAdminBase):
    list_display = ("app_key", "name", "is_active", "created_at", "updated_at")
    search_fields = ("app_key", "name")
    list_filter = ("is_active",)
    readonly_fields = ("created_at", "updated_at")

    @override
    def catalog_app(self, obj: object) -> App:
        if not isinstance(obj, App):
            message = f"无法从 {type(obj).__name__} 解析所属 App。"
            raise TypeError(message)
        return obj


@admin.register(Role)
@final
class RoleAdmin(CatalogVersionAdminMixin, RoleAdminBase):
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
class AppScopeAdmin(CatalogVersionAdminMixin, AppScopeAdminBase):
    list_display = (
        "app",
        "key",
        "name",
        "name_en",
        "is_active",
        "display_order",
        "created_at",
        "updated_at",
    )
    search_fields = ("app__app_key", "key", "name", "name_en")
    list_filter = ("app", "is_active")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Permission)
@final
class PermissionAdmin(CatalogVersionAdminMixin, PermissionAdminBase):
    list_display = (
        "app",
        "key",
        "name",
        "name_en",
        "risk_level",
        "is_active",
        "created_at",
        "updated_at",
    )
    search_fields = ("app__app_key", "key", "name", "name_en")
    list_filter = ("app", "risk_level", "is_active")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AuthorizationGroup)
@final
class AuthorizationGroupAdmin(CatalogVersionAdminMixin, AuthorizationGroupAdminBase):
    list_display = (
        "app",
        "key",
        "kind",
        "name",
        "name_en",
        "requestable",
        "is_active",
        "created_at",
        "updated_at",
    )
    search_fields = ("app__app_key", "key", "name", "name_en")
    list_filter = ("app", "kind", "requestable", "is_active")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AuthorizationGroupGrant)
@final
class AuthorizationGroupGrantAdmin(CatalogVersionAdminMixin, AuthorizationGroupGrantAdminBase):
    list_display = ("authorization_group", "permission", "scope_key", "is_active", "created_at")
    search_fields = (
        "authorization_group__app__app_key",
        "authorization_group__key",
        "permission__key",
        "scope_key",
    )
    list_filter = ("authorization_group__app", "scope_key", "is_active")
    readonly_fields = ("created_at", "updated_at")

    @override
    def catalog_app(self, obj: object) -> App:
        if not isinstance(obj, AuthorizationGroupGrant):
            message = f"无法从 {type(obj).__name__} 解析所属 App。"
            raise TypeError(message)
        return obj.authorization_group.app


@admin.register(RolePermission)
@final
class RolePermissionAdmin(CatalogVersionAdminMixin, RolePermissionAdminBase):
    list_display = ("role", "permission", "created_at")
    search_fields = ("role__app__app_key", "role__key", "permission__key")
    list_filter = ("role__app",)
    readonly_fields = ("created_at",)

    @override
    def catalog_app(self, obj: object) -> App:
        if not isinstance(obj, RolePermission):
            message = f"无法从 {type(obj).__name__} 解析所属 App。"
            raise TypeError(message)
        return obj.role.app


@admin.register(ApprovalRule)
@final
class ApprovalRuleAdmin(CatalogVersionAdminMixin, ApprovalRuleAdminBase):
    list_display = ("app", "role", "permission", "is_active", "created_at", "updated_at")
    search_fields = ("app__app_key", "role__key", "permission__key")
    list_filter = ("app", "is_active")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AppCredential)
@final
class AppCredentialAdmin(AppCredentialAdminBase):
    exclude = ("token_hash", "token_lookup")
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
