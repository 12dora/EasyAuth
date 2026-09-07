/**
 * 授权草稿: 管理员直接授权页与组织授权策略编辑共用的表单数据模型。
 *
 * 与门户申请草稿(accessRequestTypes.AccessRequestPayloadValues)刻意分开: 这里没有申请类型、
 * 基础授权与审批人, 提交即生效, 因此校验口径也只保留"目标 + 期限 + 说明"三件事。
 */

import {
  directGrantSelectionKey,
  directGrantSelectionPermissionKey,
  directGrantSelectionScopeKey,
} from "../../pages/portal/hooks/accessRequestSelection";
import type { PortalCatalogAppView, PortalRequestCatalogView } from "../../pages/portal/hooks/accessRequestTypes";

export type GrantTermType = "permanent" | "timed";

export type GrantDraft = {
  appKey: string;
  authorizationGroupKeys: string[];
  /** 门户选择键: JSON.stringify([permissionKey, scopeKey]), 与 PermissionSelector 完全一致。 */
  selectedPermissionKeys: string[];
  grantType: GrantTermType;
  /** datetime-local 控件值; 长期授权时为空串。 */
  expiresAt: string;
  reason: string;
};

export const EMPTY_GRANT_DRAFT: GrantDraft = {
  appKey: "",
  authorizationGroupKeys: [],
  selectedPermissionKeys: [],
  grantType: "permanent",
  expiresAt: "",
  reason: "",
};

export type GrantSubmission = {
  app_key: string;
  authorization_group_keys: string[];
  direct_grants: { permission: string; scope: string }[];
  grant_type: GrantTermType;
  grant_expires_at: string | null;
  reason: string;
};

/** 与后端 direct-grants / department-grant-policies 载荷的 reason max_length 一致。 */
export const GRANT_REASON_MAX_LENGTH = 1000;

/**
 * 提交闸门。
 *
 * 目录是必须的: 应用键要落在目录里, 否则这份草稿必然被后端拒(app_for_key 404)。目录还没加载完
 * 就不放行, 而不是先放行再期待后端兜底。
 */
export function grantDraftIsValid(draft: GrantDraft, catalog: PortalRequestCatalogView | undefined): boolean {
  if (!catalog) {
    return false;
  }
  if (!draft.appKey || !(catalog.apps ?? []).some((app) => app.app_key === draft.appKey)) {
    return false;
  }
  return grantDraftTargetIsPresent(draft) && grantDraftReasonIsValid(draft) && grantDraftTermIsValid(draft);
}

/**
 * 草稿指向的应用条目。
 *
 * 应用不在目录里就直接失败: grantDraftIsValid 已经拦下这种草稿, 走到这里说明接线出了问题,
 * 不能再拼一份必被后端拒(app_for_key 404)的载荷。
 */
export function grantCatalogApp(
  catalog: PortalRequestCatalogView | undefined,
  appKey: string,
): PortalCatalogAppView {
  const app = (catalog?.apps ?? []).find((item) => item.app_key === appKey);
  if (!app) {
    throw new Error(`授权目标的应用不在目录中: ${appKey}`);
  }
  return app;
}

/** 限时授权的到期时间必须晚于当前时刻, 否则授出去就已经过期。 */
export function grantDraftExpiresAtError(draft: GrantDraft): boolean {
  return draft.grantType === "timed" && Boolean(draft.expiresAt) && !grantDraftTermIsValid(draft);
}

export function buildGrantSubmission(draft: GrantDraft): GrantSubmission {
  if (!draft.appKey) {
    throw new Error("授权草稿缺少应用。");
  }
  if (!grantDraftTargetIsPresent(draft)) {
    throw new Error("授权草稿至少要包含一个授权组或一项权限。");
  }
  if (!grantDraftReasonIsValid(draft)) {
    throw new Error(`授权说明不能为空, 且不超过 ${GRANT_REASON_MAX_LENGTH} 个字符。`);
  }
  if (!grantDraftTermIsValid(draft)) {
    throw new Error("限时授权的到期时间必须晚于当前时间。");
  }
  return {
    app_key: draft.appKey,
    authorization_group_keys: [...draft.authorizationGroupKeys],
    direct_grants: draft.selectedPermissionKeys.map((selectionKey) => ({
      permission: directGrantSelectionPermissionKey(selectionKey),
      scope: requireScopeKey(selectionKey),
    })),
    grant_type: draft.grantType,
    grant_expires_at: draft.grantType === "timed" ? new Date(draft.expiresAt).toISOString() : null,
    reason: draft.reason.trim(),
  };
}

export interface GrantPolicySnapshot {
  app_key: string;
  authorization_groups: { key: string }[];
  permissions: { key: string; scope: string }[];
  grant_type: GrantTermType;
  expires_at: string | null;
  reason: string;
}

/** 把后端返回的策略还原成草稿(编辑弹窗用)。到期时间从 ISO 转成 datetime-local(分钟精度)。 */
export function grantDraftFromPolicy(input: GrantPolicySnapshot): GrantDraft {
  if (input.grant_type === "timed" && !input.expires_at) {
    throw new Error("限时授权策略缺少到期时间。");
  }
  if (input.grant_type === "permanent" && input.expires_at) {
    throw new Error("长期授权策略不应带到期时间。");
  }
  return {
    appKey: input.app_key,
    authorizationGroupKeys: input.authorization_groups.map((group) => group.key),
    selectedPermissionKeys: input.permissions.map((permission) =>
      directGrantSelectionKey(permission.key, permission.scope),
    ),
    grantType: input.grant_type,
    expiresAt: input.expires_at ? isoToDatetimeLocal(input.expires_at) : "",
    reason: input.reason,
  };
}

function grantDraftTargetIsPresent(draft: GrantDraft): boolean {
  return draft.authorizationGroupKeys.length > 0 || draft.selectedPermissionKeys.length > 0;
}

function grantDraftReasonIsValid(draft: GrantDraft): boolean {
  return draft.reason.trim().length > 0 && draft.reason.length <= GRANT_REASON_MAX_LENGTH;
}

function grantDraftTermIsValid(draft: GrantDraft): boolean {
  if (draft.grantType === "permanent") {
    return true;
  }
  return Boolean(draft.expiresAt) && new Date(draft.expiresAt) > new Date();
}

function requireScopeKey(selectionKey: string): string {
  const scopeKey = directGrantSelectionScopeKey(selectionKey);
  if (!scopeKey) {
    throw new Error(`直接权限选择缺少权限范围: ${selectionKey}`);
  }
  return scopeKey;
}

/** datetime-local 的 min 与 ISO→控件值转换共用的本地时区格式化(YYYY-MM-DDTHH:mm)。 */
export function toDatetimeLocalValue(date: Date): string {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function isoToDatetimeLocal(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    throw new Error(`到期时间不是合法的时间戳: ${iso}`);
  }
  return toDatetimeLocalValue(date);
}
