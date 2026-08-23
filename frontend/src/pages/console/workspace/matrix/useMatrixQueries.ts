import { useQuery } from "@tanstack/react-query";

import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import type { AppScopeItem, AuthorizationGroupItem, PermissionItem } from "../../../../lib/domain";
import { fetchAllAuthorizationGroups } from "./authorizationGroupsApi";

/** 权限矩阵页签依赖的三条只读查询, 以及它们的列表投影。 */
export function useMatrixQueries(appKey: string) {
  const groupsQueryKey = ["console", "app", appKey, "authorization-groups"];
  const groupsQuery = useQuery({
    queryKey: groupsQueryKey,
    queryFn: () => fetchAllAuthorizationGroups(appKey),
  });
  const permissionsQuery = useQuery({
    queryKey: ["console", "app", appKey, "permissions"],
    queryFn: () => apiRequest<ListPayload<PermissionItem>>(`/console/api/v1/apps/${appKey}/permissions`),
  });
  const scopesQuery = useQuery({
    queryKey: ["console", "app", appKey, "scopes"],
    queryFn: () => apiRequest<ListPayload<AppScopeItem>>(`/console/api/v1/apps/${appKey}/scopes`),
  });
  const scopes = itemsFromPayload<AppScopeItem>(scopesQuery.data);

  return {
    groupsQueryKey,
    groupsQuery,
    permissionsQuery,
    scopesQuery,
    authorizationGroups: itemsFromPayload<AuthorizationGroupItem>(groupsQuery.data),
    permissions: itemsFromPayload<PermissionItem>(permissionsQuery.data),
    activeScopes: scopes.filter((scope) => scope.is_active),
  };
}
