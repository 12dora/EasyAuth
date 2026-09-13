import { bindParse } from "../../lib/domain/parse";
import type {
  ApproverOption,
  AuthorizationGroupItem,
  PortalRequestCatalogView,
  ScopedPermissionGroupItem,
  ScopedPermissionItem,
} from "./hooks/accessRequestTypes";

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
  // 别名是可选配置项, 没配时后端下发空字符串; 字段本身必须存在。
  contractString(item.alias, `${path}.alias`);
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
  contractAuthorizationGroupKind(item.kind, `${path}.kind`);
  contractNonEmptyString(item.name, `${path}.name`);
  contractOptionalBoolean(item.requestable, `${path}.requestable`);
  contractOptionalBoolean(item.requires_approval, `${path}.requires_approval`);
  contractOptionalStringArray(item.default_approver_user_ids, `${path}.default_approver_user_ids`);
  contractOptionalString(item.approver_resolution_status, `${path}.approver_resolution_status`);
  // 权限组覆盖范围是必答项: 后端 request_catalog_data 永远下发 grants(没有配置时是空数组),
  // 缺了它前端会把"覆盖范围未知"当成"什么都不覆盖", 直接权限就会重复进载荷。
  contractArray(item.grants, `${path}.grants`).forEach((value, index) => {
    const grant = contractRecord(value, `${path}.grants[${index}]`);
    contractNonEmptyString(grant.permission_key, `${path}.grants[${index}].permission_key`);
    contractNonEmptyString(grant.scope_key, `${path}.grants[${index}].scope_key`);
  });
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

const {
  requireRecord: contractRecord,
  requireArray: contractArray,
  requireNumber,
  requireString: contractString,
  requireNonEmptyString: contractNonEmptyString,
  requireEnum,
  optionalPresentString: contractOptionalString,
  requireBoolean,
} = bindParse({ copula: "为" });

function contractNumber(value: unknown, path: string): void {
  requireNumber(value, path, { expected: "有限数字" });
}

function contractAuthorizationGroupKind(value: unknown, path: string): void {
  requireEnum(value, path, ["role", "bundle"]);
}

function contractOptionalBoolean(value: unknown, path: string): void {
  if (value === undefined) {
    return;
  }
  requireBoolean(value, path);
}

function contractOptionalStringArray(value: unknown, path: string): void {
  if (value === undefined) {
    return;
  }
  contractArray(value, path).forEach((item, index) => contractNonEmptyString(item, `${path}[${index}]`));
}
