import { useState } from "react";

import type { MessageKey } from "../../../i18n/messages";
import {
  defaultGrantTypeForRequestType,
  type AccessGrantType,
  type AccessRequestFields,
  type AccessRequestType,
} from "./accessRequestTypes";

export function useAccessRequestFields(initialRequestType: AccessRequestType = "grant"): AccessRequestFields {
  const [requestType, setRequestType] = useState<AccessRequestType>(initialRequestType);
  const [appKey, setAppKey] = useState("");
  const [baseGrantId, setBaseGrantId] = useState("");
  const [baseGrantRevision, setBaseGrantRevision] = useState<number | null>(null);
  const [authorizationGroupKey, setAuthorizationGroupKey] = useState("");
  const [selectedPermissionKeys, setSelectedPermissionKeys] = useState<string[]>([]);
  const [selectedPermissionScopes, setSelectedPermissionScopes] = useState<Record<string, string>>({});
  const [selectedApproverUserIds, setSelectedApproverUserIds] = useState<string[]>([]);
  const [approverSelectionWasEdited, setApproverSelectionWasEdited] = useState(false);
  const [groupMaterializationNoticeKey, setGroupMaterializationNoticeKey] = useState<MessageKey | "">("");
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<string[]>([]);
  const [grantType, setGrantType] = useState<AccessGrantType>(defaultGrantTypeForRequestType(initialRequestType));
  const [expiresAt, setExpiresAt] = useState("");
  const [reason, setReason] = useState("");

  return {
    appKey,
    requestType,
    baseGrantId,
    baseGrantRevision,
    authorizationGroupKey,
    selectedPermissionKeys,
    selectedPermissionScopes,
    selectedApproverUserIds,
    expandedGroupKeys,
    approverSelectionWasEdited,
    groupMaterializationNoticeKey,
    grantType,
    expiresAt,
    reason,
    setRequestType,
    setAppKey,
    setBaseGrantId,
    setBaseGrantRevision,
    setAuthorizationGroupKey,
    setSelectedPermissionKeys,
    setSelectedPermissionScopes,
    setSelectedApproverUserIds,
    setApproverSelectionWasEdited,
    setGroupMaterializationNoticeKey,
    setExpandedGroupKeys,
    setGrantType,
    setExpiresAt,
    setReason,
  };
}
