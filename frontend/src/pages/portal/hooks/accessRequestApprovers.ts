import { directGrantSelectionPermissionKey, directGrantSelectionScopeKey, uniqueStrings } from "./accessRequestSelection";
import {
  ACCESS_REQUEST_MAX_APPROVERS,
  type AccessRequestPayloadValues,
  type AuthorizationGroupItem,
  type CatalogView,
  type ScopedPermissionItem,
} from "./accessRequestTypes";

export function buildDefaultApproverUserIds(values: AccessRequestPayloadValues, catalogView: CatalogView, currentUserId: string): string[] {
  const app = catalogView.apps.find((item) => item.app_key === values.appKey);
  const authorizationGroup = catalogView.authorizationGroups.find((group) => group.key === values.authorizationGroupKey);
  const directGrantPermissionKeys = Array.from(
    new Set(values.selectedPermissionKeys.map((key) => directGrantSelectionPermissionKey(key))),
  );
  const directGrantApprovers = directGrantPermissionKeys.flatMap(
    (permissionKey) => catalogView.permissionsByKey[permissionKey]?.default_approver_user_ids ?? [],
  );
  const targetApprovers = uniqueStrings([...(authorizationGroup?.default_approver_user_ids ?? []), ...directGrantApprovers]);
  if (targetApprovers.length > 0) {
    // FF-7: 默认审批人同样剔除申请人自己。
    return targetApprovers.filter((userId) => userId !== currentUserId).slice(0, ACCESS_REQUEST_MAX_APPROVERS);
  }
  if (selectedManagedUsersTargetHasMissingDirectManager(values, catalogView)) {
    return [];
  }
  return uniqueStrings(app?.default_approver_user_ids ?? [])
    .filter((userId) => userId !== currentUserId)
    .slice(0, ACCESS_REQUEST_MAX_APPROVERS);
}

export function selectedManagedUsersTargetHasMissingDirectManager(values: AccessRequestPayloadValues, catalogView: CatalogView): boolean {
  return selectedManagedUsersTargets(values, catalogView).some(
    (target) => target.approver_resolution_status === "direct_manager_missing",
  );
}

function selectedManagedUsersTargets(
  values: AccessRequestPayloadValues,
  catalogView: CatalogView,
): Array<AuthorizationGroupItem | ScopedPermissionItem> {
  const targets: Array<AuthorizationGroupItem | ScopedPermissionItem> = [];
  const authorizationGroup = catalogView.authorizationGroups.find((group) => group.key === values.authorizationGroupKey);
  if (authorizationGroup?.grants?.some((grant) => grant.scope_key === "MANAGED_USERS")) {
    targets.push(authorizationGroup);
  }
  const directGrantPermissionKeys = Array.from(new Set(
    values.selectedPermissionKeys
      .filter((key) => directGrantSelectionScopeKey(key) === "MANAGED_USERS")
      .map((key) => directGrantSelectionPermissionKey(key)),
  ));
  for (const permissionKey of directGrantPermissionKeys) {
    const permission = catalogView.permissionsByKey[permissionKey];
    if (permission) {
      targets.push(permission);
    }
  }
  return targets;
}
