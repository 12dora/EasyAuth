import type { PermissionGroupItem, PermissionItem } from "../../../lib/domain";

export function flattenGroups(groups: PermissionGroupItem[]): PermissionGroupItem[] {
  return groups.flatMap((group) => [
    group,
    ...flattenGroups((group.children ?? []).filter(isPermissionGroup)),
  ]);
}

export function isPermissionGroup(item: PermissionGroupItem | PermissionItem): item is PermissionGroupItem {
  return "type" in item && item.type === "group";
}

export function safeJoin(values: string[] | undefined): string {
  return values && values.length > 0 ? values.join("、") : "-";
}

export function credentialKindLabel(kind: string): string {
  switch (kind) {
    case "static_token":
      return "静态 token";
    case "oauth_client":
      return "OAuth client";
    default:
      return kind;
  }
}
