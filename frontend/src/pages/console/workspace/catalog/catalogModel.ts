/** 目录表单的数据形态、初始值与请求载荷转换。 */

import type { AppScopeItem, PermissionGroupItem, PermissionItem } from "../../../../lib/domain";
import type { JsonObject } from "../../../../lib/api";

export type PermissionGroupForm = {
  key: string;
  name: string;
  description: string;
  parent_key: string;
  display_order: number;
  is_active: boolean;
};

export type ScopeForm = {
  key: string;
  name: string;
  description: string;
  display_order: number;
  is_active: boolean;
};

export type PermissionForm = {
  key: string;
  name: string;
  description: string;
  group_key: string;
  supported_scopes: string;
  risk_level: string;
  is_active: boolean;
};

export type CatalogDialog = "scope" | "group" | "permission" | null;

export const emptyPermissionForm: PermissionForm = {
  key: "",
  name: "",
  description: "",
  group_key: "",
  supported_scopes: "GLOBAL",
  risk_level: "standard",
  is_active: true,
};

export const emptyGroupForm: PermissionGroupForm = {
  key: "",
  name: "",
  description: "",
  parent_key: "",
  display_order: 0,
  is_active: true,
};

export const emptyScopeForm: ScopeForm = {
  key: "",
  name: "",
  description: "",
  display_order: 0,
  is_active: true,
};

export function permissionPayload(form: PermissionForm): JsonObject {
  return {
    key: form.key.trim(),
    name: form.name.trim(),
    description: form.description.trim(),
    group_key: form.group_key || null,
    supported_scopes: form.supported_scopes.split(",").map((scope) => scope.trim()).filter(Boolean),
    risk_level: form.risk_level,
    is_active: form.is_active,
  };
}

export function groupPayload(form: PermissionGroupForm): JsonObject {
  return {
    key: form.key.trim(),
    name: form.name.trim(),
    description: form.description.trim(),
    parent_key: form.parent_key || null,
    display_order: form.display_order,
    is_active: form.is_active,
  };
}

export function scopeFormFromItem(scope: AppScopeItem): ScopeForm {
  return {
    key: scope.key,
    name: scope.name,
    description: scope.description ?? "",
    display_order: scope.display_order,
    is_active: scope.is_active,
  };
}

export function groupFormFromItem(
  group: PermissionGroupItem & { parent_key?: string; display_order?: number; is_active?: boolean },
): PermissionGroupForm {
  return {
    key: group.key,
    name: group.name,
    description: group.description ?? "",
    parent_key: group.parent_key ?? "",
    display_order: group.display_order ?? 0,
    is_active: group.is_active !== false,
  };
}

export function permissionFormFromItem(permission: PermissionItem): PermissionForm {
  return {
    key: permission.key,
    name: permission.name,
    description: permission.description ?? "",
    group_key: permission.group_key ?? "",
    supported_scopes: (permission.supported_scopes ?? []).join(","),
    risk_level: permission.risk_level ?? "standard",
    is_active: permission.is_active !== false,
  };
}
