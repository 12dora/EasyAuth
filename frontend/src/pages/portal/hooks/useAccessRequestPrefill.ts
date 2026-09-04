import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import type { MessageKey } from "../../../i18n/messages";
import type { PortalGrantRow } from "../portalListPayload";

/** 从授权列表跳转到申请表时携带的预填约定: 目前只支持以某条现有授权为基础发起变更申请。 */
export interface AccessRequestPrefill {
  requestType: "change";
  baseGrantId: string;
}

const PREFILL_STATE_KEY = "accessRequestPrefill";
const PREFILL_FIELDS = ["requestType", "baseGrantId"];

/**
 * 解析 react-router 的 location.state。没有预填时返回 null；
 * 带了预填但形状不符合约定时直接抛错，不做静默忽略。
 */
export function parseAccessRequestPrefill(state: unknown): AccessRequestPrefill | null {
  if (state === null || state === undefined) {
    return null;
  }
  const routerState = requireRecord(state, "申请表路由 state 必须是对象");
  if (!(PREFILL_STATE_KEY in routerState)) {
    return null;
  }
  const prefill = requireRecord(routerState[PREFILL_STATE_KEY], `路由 state.${PREFILL_STATE_KEY} 必须是对象`);
  const unknownFields = Object.keys(prefill).filter((field) => !PREFILL_FIELDS.includes(field));
  if (unknownFields.length > 0) {
    throw new Error(`路由 state.${PREFILL_STATE_KEY} 含未知字段：${unknownFields.join("、")}`);
  }
  if (prefill.requestType !== "change") {
    throw new Error(`路由 state.${PREFILL_STATE_KEY}.requestType 必须是 change`);
  }
  if (typeof prefill.baseGrantId !== "string" || prefill.baseGrantId === "") {
    throw new Error(`路由 state.${PREFILL_STATE_KEY}.baseGrantId 必须是非空字符串`);
  }
  return { requestType: prefill.requestType, baseGrantId: prefill.baseGrantId };
}

function requireRecord(value: unknown, message: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(message);
  }
  return value as Record<string, unknown>;
}

export interface AccessRequestPrefillSource {
  prefill: AccessRequestPrefill | null;
  /** 应用完预填后清空 history state, 避免刷新页面又被预填一次。 */
  clearRouterState: () => void;
}

export function useAccessRequestPrefill(): AccessRequestPrefillSource {
  const location = useLocation();
  const navigate = useNavigate();
  // 预填只在进入页面的那一次有效: 用惰性初值定格, 后面清空 history state 不会把它带走。
  const [prefill] = useState(() => parseAccessRequestPrefill(location.state));
  const clearRouterState = useCallback(() => {
    navigate(location.pathname, { replace: true, state: null });
  }, [location.pathname, navigate]);

  return { prefill, clearRouterState };
}

export interface AccessRequestPrefillApplicationInput {
  prefill: AccessRequestPrefill | null;
  currentGrants: PortalGrantRow[];
  /** 基础授权列表是异步加载的, 只有加载完成才能判断预填的授权是否存在。 */
  currentGrantsAreLoaded: boolean;
  changeBaseGrantId: (grantId: string) => void;
  onApplied?: () => void;
}

/** 基础授权加载完成后应用预填, 只应用一次; 预填的授权不在列表里时返回错误文案 key。 */
export function useAccessRequestPrefillApplication(input: AccessRequestPrefillApplicationInput): MessageKey | "" {
  const { prefill, currentGrants, currentGrantsAreLoaded, changeBaseGrantId, onApplied } = input;
  const appliedRef = useRef(false);
  const [errorMessageKey, setErrorMessageKey] = useState<MessageKey | "">("");

  useEffect(() => {
    if (!prefill || appliedRef.current || !currentGrantsAreLoaded) {
      return;
    }
    appliedRef.current = true;
    const baseGrant = currentGrants.find((grant) => String(grant.grant_id) === prefill.baseGrantId);
    if (!baseGrant) {
      setErrorMessageKey("portal.request.prefillBaseGrantMissing");
    } else {
      changeBaseGrantId(prefill.baseGrantId);
    }
    onApplied?.();
  }, [prefill, currentGrants, currentGrantsAreLoaded, changeBaseGrantId, onApplied]);

  return errorMessageKey;
}
