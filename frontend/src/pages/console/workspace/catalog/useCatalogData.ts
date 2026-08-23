/** 获取目录查询结果并生成页面直接消费的派生集合。 */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import type { AppScopeItem, PermissionGroupItem, PermissionItem, PermissionTreePayload } from "../../../../lib/domain";
import { flattenGroups } from "../utils";

export function useCatalogData(appKey: string) {
  const treeQuery = useQuery({
    queryKey: ["console", "app", appKey, "permission-tree"],
    queryFn: () => apiRequest<PermissionTreePayload>(`/console/api/v1/apps/${appKey}/permission-tree`),
  });
  const groupsQuery = useQuery({
    queryKey: ["console", "app", appKey, "permission-groups"],
    queryFn: () => apiRequest<ListPayload<PermissionGroupItem>>(`/console/api/v1/apps/${appKey}/permission-groups`),
  });
  const permissionsQuery = useQuery({
    queryKey: ["console", "app", appKey, "permissions"],
    queryFn: () => apiRequest<ListPayload<PermissionItem>>(`/console/api/v1/apps/${appKey}/permissions`),
  });
  const scopesQuery = useQuery({
    queryKey: ["console", "app", appKey, "scopes"],
    queryFn: () => apiRequest<ListPayload<AppScopeItem>>(`/console/api/v1/apps/${appKey}/scopes`),
  });
  const groups = itemsFromPayload<PermissionGroupItem>(groupsQuery.data);
  const treeGroups = useMemo(() => flattenGroups(treeQuery.data?.groups ?? []), [treeQuery.data]);

  return {
    treeQuery,
    groupsQuery,
    permissionsQuery,
    scopesQuery,
    groups,
    groupRows: treeGroups.length > 0 ? treeGroups : groups,
    permissions: itemsFromPayload<PermissionItem>(permissionsQuery.data),
    scopes: itemsFromPayload<AppScopeItem>(scopesQuery.data),
  };
}
