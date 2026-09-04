import { useState } from "react";

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
    setExpandedGroupKeys,
    setGrantType,
    setExpiresAt,
    setReason,
  };
}
