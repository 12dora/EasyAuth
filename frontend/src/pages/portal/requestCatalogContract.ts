import type {
  ApproverOption,
  AuthorizationGroupItem,
  PortalRequestCatalogView,
  ScopedPermissionGroupItem,
  ScopedPermissionItem,
} from "./hooks/useAccessRequestForm";

export function parsePortalRequestCatalog(value: unknown): PortalRequestCatalogView {
  const catalog = contractRecord(value, "申请目录");
  const apps = contractArray(catalog.apps, "申请目录.apps");
  const approverOptions = contractArray(catalog.approver_options, "申请目录.approver_options");
  const authorizationGroups = contractArray(catalog.authorization_groups, "申请目录.authorization_groups");
  const permissionGroups = contractArray(catalog.permission_groups, "申请目录.permission_groups");
  const ungroupedPermissions = contractArray(catalog.ungrouped_permissions, "申请目录.ungrouped_permissions");

  apps.forEach((item, index) => validateCatalogApp(item, `申请目录.apps[${index}]`));
  approverOptions.forEach((item, index) => validateApproverOption(item, `申请目录.approver_options[${index}]`));
  authorizationGroups.forEach((item, index) => validateAuthorizationGroup(item, `申请目录.authorization_groups[${index}]`));
  permissionGroups.forEach((item, index) => validatePermissionGroup(item, `申请目录.permission_groups[${index}]`));
  ungroupedPermissions.forEach((item, index) => validatePermission(item, `申请目录.ungrouped_permissions[${index}]`));
  return catalog as PortalRequestCatalogView;
}

function validateCatalogApp(value: unknown, path: string): void {
  const item = contractRecord(value, path);
  contractNumber(item.id, `${path}.id`);
  contractNonEmptyString(item.app_key, `${path}.app_key`);
  contractNonEmptyString(item.name, `${path}.name`);
  contractOptionalStringArray(item.default_approver_user_ids, `${path}.default_approver_user_ids`);
  contractOptionalString(item.approver_resolution_status, `${path}.approver_resolution_status`);
}

function validateApproverOption(value: unknown, path: string): asserts value is ApproverOption {
  const item = contractRecord(value, path);
  contractNonEmptyString(item.user_id, `${path}.user_id`);
  for (const field of ["name", "label", "display_name", "email", "department"] as const) {
    contractOptionalString(item[field], `${path}.${field}`);
  }
}

function validateAuthorizationGroup(
  value: unknown,
  path: string,
): asserts value is AuthorizationGroupItem {
  const item = contractRecord(value, path);
  contractNumber(item.id, `${path}.id`);
  contractNonEmptyString(item.app_key, `${path}.app_key`);
  contractNonEmptyString(item.key, `${path}.key`);
  contractNonEmptyString(item.kind, `${path}.kind`);
  contractNonEmptyString(item.name, `${path}.name`);
  contractOptionalBoolean(item.requestable, `${path}.requestable`);
  contractOptionalBoolean(item.requires_approval, `${path}.requires_approval`);
  contractOptionalStringArray(item.default_approver_user_ids, `${path}.default_approver_user_ids`);
  contractOptionalString(item.approver_resolution_status, `${path}.approver_resolution_status`);
  if (item.grants !== undefined) {
    contractArray(item.grants, `${path}.grants`).forEach((value, index) => {
      const grant = contractRecord(value, `${path}.grants[${index}]`);
      contractNonEmptyString(grant.permission_key, `${path}.grants[${index}].permission_key`);
      contractNonEmptyString(grant.scope_key, `${path}.grants[${index}].scope_key`);
    });
  }
}

function validatePermissionGroup(
  value: unknown,
  path: string,
): asserts value is ScopedPermissionGroupItem {
  const item = contractRecord(value, path);
  contractNumber(item.id, `${path}.id`);
  contractNonEmptyString(item.app_key, `${path}.app_key`);
  if (item.type !== "group") {
    throw new Error(`${path}.type 必须为 group`);
  }
  contractNonEmptyString(item.key, `${path}.key`);
  contractNonEmptyString(item.name, `${path}.name`);
  if (item.children !== undefined) {
    contractArray(item.children, `${path}.children`).forEach((child, index) => {
      const childRecord = contractRecord(child, `${path}.children[${index}]`);
      if (childRecord.type === "group") {
        validatePermissionGroup(child, `${path}.children[${index}]`);
      } else {
        validatePermission(child, `${path}.children[${index}]`);
      }
    });
  }
  if (item.permissions !== undefined) {
    contractArray(item.permissions, `${path}.permissions`).forEach((permission, index) =>
      validatePermission(permission, `${path}.permissions[${index}]`),
    );
  }
}

function validatePermission(value: unknown, path: string): asserts value is ScopedPermissionItem {
  const item = contractRecord(value, path);
  contractNumber(item.id, `${path}.id`);
  contractOptionalString(item.app_key, `${path}.app_key`);
  if (item.type !== undefined && item.type !== "permission") {
    throw new Error(`${path}.type 必须为 permission`);
  }
  contractNonEmptyString(item.key, `${path}.key`);
  contractNonEmptyString(item.name, `${path}.name`);
  contractArray(item.scopes, `${path}.scopes`).forEach((scope, index) => {
    const scopeItem = contractRecord(scope, `${path}.scopes[${index}]`);
    contractNonEmptyString(scopeItem.key, `${path}.scopes[${index}].key`);
    contractNonEmptyString(scopeItem.name, `${path}.scopes[${index}].name`);
  });
  contractOptionalStringArray(item.default_approver_user_ids, `${path}.default_approver_user_ids`);
  contractOptionalString(item.approver_resolution_status, `${path}.approver_resolution_status`);
}

function contractRecord(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${path} 必须为对象`);
  }
  return value as Record<string, unknown>;
}

function contractArray(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${path} 必须为数组`);
  }
  return value;
}

function contractNumber(value: unknown, path: string): void {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${path} 必须为有限数字`);
  }
}

function contractNonEmptyString(value: unknown, path: string): void {
  if (typeof value !== "string" || !value) {
    throw new Error(`${path} 必须为非空字符串`);
  }
}

function contractOptionalString(value: unknown, path: string): void {
  if (value !== undefined && typeof value !== "string") {
    throw new Error(`${path} 必须为字符串`);
  }
}

function contractOptionalBoolean(value: unknown, path: string): void {
  if (value !== undefined && typeof value !== "boolean") {
    throw new Error(`${path} 必须为布尔值`);
  }
}

function contractOptionalStringArray(value: unknown, path: string): void {
  if (value === undefined) {
    return;
  }
  contractArray(value, path).forEach((item, index) => contractNonEmptyString(item, `${path}[${index}]`));
}
