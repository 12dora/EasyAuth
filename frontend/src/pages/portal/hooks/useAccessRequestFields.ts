import { useState } from "react";

import type { AccessGrantType, AccessRequestFields, AccessRequestType } from "./accessRequestTypes";

export function useAccessRequestFields(): AccessRequestFields {
  const [requestType, setRequestType] = useState<AccessRequestType>("grant");
  const [appKey, setAppKey] = useState("");
  const [baseGrantId, setBaseGrantId] = useState("");
  const [baseGrantRevision, setBaseGrantRevision] = useState<number | null>(null);
  const [authorizationGroupKey, setAuthorizationGroupKey] = useState("");
  const [selectedPermissionKeys, setSelectedPermissionKeys] = useState<string[]>([]);
  const [selectedPermissionScopes, setSelectedPermissionScopes] = useState<Record<string, string>>({});
  const [selectedApproverUserIds, setSelectedApproverUserIds] = useState<string[]>([]);
  const [approverSelectionWasEdited, setApproverSelectionWasEdited] = useState(false);
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<string[]>([]);
  const [grantType, setGrantType] = useState<AccessGrantType>("permanent");
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
