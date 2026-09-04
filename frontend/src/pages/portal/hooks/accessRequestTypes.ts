import type { Dispatch, SetStateAction } from "react";

import type { MessageKey } from "../../../i18n/messages";
import type {
  AuthorizationGroupKind,
  PermissionGroupItem,
  PermissionItem,
  PortalCatalogApp,
  PortalRequestCatalog,
} from "../../../lib/domain";
import type { PortalGrantRow } from "../portalListPayload";

export type AccessGrantType = "permanent" | "timed";
export type AccessRequestType = "grant" | "change" | "revoke" | "renew";

export interface AuthorizationGroupGrantRef {
  permission_key: string;
  scope_key: string;
}

export interface AuthorizationGroupItem {
  id: number;
  app_key: string;
  key: string;
  kind: AuthorizationGroupKind;
  name: string;
  name_en?: string;
  description?: string;
  description_en?: string;
  requestable?: boolean;
  requires_approval?: boolean;
  default_approver_user_ids?: string[];
  approver_resolution_status?: string;
  scopes?: ScopeOption[];
  grants?: AuthorizationGroupGrantRef[];
}

export interface ApproverOption {
  user_id: string;
  name?: string;
  label?: string;
  display_name?: string;
  email?: string;
  department?: string;
}

export type PortalCatalogAppView = PortalCatalogApp & { default_approver_user_ids?: string[] };

export interface ScopeOption {
  key: string;
  name: string;
  name_en?: string;
  description?: string;
  description_en?: string;
}

export type ScopedPermissionItem = PermissionItem & {
  scopes?: ScopeOption[];
  default_approver_user_ids?: string[];
  approver_resolution_status?: string;
};
export type ScopedPermissionGroupItem = Omit<PermissionGroupItem, "children" | "permissions"> & {
  children?: Array<ScopedPermissionGroupItem | ScopedPermissionItem>;
  permissions?: ScopedPermissionItem[];
};

export const ACCESS_REQUEST_MAX_APPROVERS = 20;
export const ACCESS_REQUEST_MAX_REASON_LENGTH = 1000;
/** 与后端 AccessRequestSubmitPayload.authorization_group_keys 的 max_length 一致。 */
export const ACCESS_REQUEST_MAX_AUTHORIZATION_GROUPS = 20;

/** 申请类型决定授权期限的初始值: 续期必然是限时授权, 其余从长期开始。 */
export function defaultGrantTypeForRequestType(requestType: AccessRequestType): AccessGrantType {
  return requestType === "renew" ? "timed" : "permanent";
}

export interface PortalRequestCatalogView extends Omit<PortalRequestCatalog, "permission_groups" | "ungrouped_permissions"> {
  apps?: PortalCatalogAppView[];
  approver_options?: ApproverOption[];
  authorization_groups?: AuthorizationGroupItem[];
  permission_groups?: ScopedPermissionGroupItem[];
  ungrouped_permissions?: ScopedPermissionItem[];
}

export interface CatalogView {
  apps: PortalCatalogAppView[];
  approverOptions: ApproverOption[];
  authorizationGroups: AuthorizationGroupItem[];
  permissionGroups: ScopedPermissionGroupItem[];
  ungroupedPermissions: ScopedPermissionItem[];
  visiblePermissionKeys: string[];
  scopesByPermissionKey: Record<string, ScopeOption[]>;
  permissionsByKey: Record<string, ScopedPermissionItem>;
}

export interface AccessRequestPayloadValues {
  requestType: AccessRequestType;
  appKey: string;
  baseGrantId: string;
  baseGrantRevision: number | null;
  authorizationGroupKeys: string[];
  selectedPermissionKeys: string[];
  selectedPermissionScopes: Record<string, string>;
  selectedApproverUserIds: string[];
  grantType: AccessGrantType;
  expiresAt: string;
  reason: string;
}

export interface AccessRequestFields extends AccessRequestPayloadValues {
  expandedGroupKeys: string[];
  approverSelectionWasEdited: boolean;
  /**
   * 权限组落地成直接权限后的提示文案 key。
   *
   * 只对上一次选择操作负责: 再选一次权限、换权限组、换目标或提交都会清空它。
   */
  groupMaterializationNoticeKey: MessageKey | "";
  setRequestType: Dispatch<SetStateAction<AccessRequestType>>;
  setAppKey: Dispatch<SetStateAction<string>>;
  setBaseGrantId: Dispatch<SetStateAction<string>>;
  setBaseGrantRevision: Dispatch<SetStateAction<number | null>>;
  setAuthorizationGroupKeys: Dispatch<SetStateAction<string[]>>;
  setSelectedPermissionKeys: Dispatch<SetStateAction<string[]>>;
  setSelectedPermissionScopes: Dispatch<SetStateAction<Record<string, string>>>;
  setSelectedApproverUserIds: Dispatch<SetStateAction<string[]>>;
  setApproverSelectionWasEdited: Dispatch<SetStateAction<boolean>>;
  setGroupMaterializationNoticeKey: Dispatch<SetStateAction<MessageKey | "">>;
  setExpandedGroupKeys: Dispatch<SetStateAction<string[]>>;
  setGrantType: Dispatch<SetStateAction<AccessGrantType>>;
  setExpiresAt: Dispatch<SetStateAction<string>>;
  setReason: Dispatch<SetStateAction<string>>;
}

export interface AccessRequestActions {
  changeRequestType: (requestType: AccessRequestType) => void;
  changeBaseGrantId: (grantId: string) => void;
  changeAppKey: (nextAppKey: string) => void;
  changeAuthorizationGroupKeys: (groupKeys: string[]) => void;
  selectPermissionKeys: (keys: string[]) => void;
  clearPermissionKeys: (keys: string[]) => void;
  expandGroups: (keys: string[]) => void;
  collapseGroups: (keys: string[]) => void;
  toggleApprover: (userId: string) => void;
  changePermissionScope: (permission: ScopedPermissionItem, scopeKey: string) => void;
  changePermissionGroupScope: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => void;
  toggleGroup: (key: string) => void;
  submit: () => void;
}

export interface AccessRequestFormResult {
  requestType: AccessRequestType;
  appKey: string;
  baseGrantId: string;
  authorizationGroupKeys: string[];
  selectedPermissionKeys: string[];
  selectedPermissionScopes: Record<string, string>;
  selectedApproverUserIds: string[];
  expandedGroupKeys: string[];
  grantType: AccessGrantType;
  expiresAt: string;
  reason: string;
  apps: PortalCatalogAppView[];
  currentGrants: PortalGrantRow[];
  approverOptions: ApproverOption[];
  authorizationGroups: AuthorizationGroupItem[];
  permissionGroups: ScopedPermissionGroupItem[];
  ungroupedPermissions: ScopedPermissionItem[];
  visiblePermissionKeys: string[];
  /** 所选权限组(可多个)覆盖的权限范围并集(展示态联动勾选用, 不计入直接权限提交)。 */
  groupCoveredSelectionKeys: string[];
  catalogIsLoading: boolean;
  catalogErrorMessage: string;
  submitErrorMessage: string;
  /** 提示条文案的 i18n key: 由组件用 t() 渲染, hook 不生产用户可见文案。 */
  toastMessageKey: MessageKey | "";
  /** 路由预填失效(基础授权已不在当前授权里)时的错误文案 key。 */
  prefillErrorMessageKey: MessageKey | "";
  canSubmit: boolean;
  expiresAtError: boolean;
  isSubmitting: boolean;
  changeAppKey: (nextAppKey: string) => void;
  changeRequestType: (requestType: AccessRequestType) => void;
  changeBaseGrantId: (grantId: string) => void;
  changeAuthorizationGroupKeys: (groupKeys: string[]) => void;
  changeGrantType: Dispatch<SetStateAction<AccessGrantType>>;
  changeExpiresAt: Dispatch<SetStateAction<string>>;
  changeReason: Dispatch<SetStateAction<string>>;
  selectPermissionKeys: (keys: string[]) => void;
  clearPermissionKeys: (keys: string[]) => void;
  expandGroups: (keys: string[]) => void;
  collapseGroups: (keys: string[]) => void;
  toggleApprover: (userId: string) => void;
  changePermissionScope: (permission: ScopedPermissionItem, scopeKey: string) => void;
  changePermissionGroupScope: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => void;
  toggleGroup: (key: string) => void;
  submit: () => void;
}
