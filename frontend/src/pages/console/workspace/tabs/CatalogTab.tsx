import { useQuery } from "@tanstack/react-query";

import { Badge } from "../../../../components/Badge";
import { DataTable } from "../../../../components/DataTable";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { PermissionItem, PermissionTreePayload, RoleItem } from "../../../../lib/domain";
import { flattenGroups } from "../utils";

export function CatalogTab({ appKey }: { appKey: string }) {
  const treeQuery = useQuery({
    queryKey: ["console", "app", appKey, "permission-tree"],
    queryFn: () => apiRequest<PermissionTreePayload>(`/console/api/v1/apps/${appKey}/permission-tree`),
  });
  const rolesQuery = useQuery({
    queryKey: ["console", "app", appKey, "roles"],
    queryFn: () => apiRequest<{ items?: RoleItem[] }>(`/console/api/v1/apps/${appKey}/roles`),
  });
  const permissionsQuery = useQuery({
    queryKey: ["console", "app", appKey, "permissions"],
    queryFn: () => apiRequest<{ items?: PermissionItem[] }>(`/console/api/v1/apps/${appKey}/permissions`),
  });
  const groups = flattenGroups(treeQuery.data?.groups ?? []);
  const roles = itemsFromPayload<RoleItem>(rolesQuery.data);
  const permissions = itemsFromPayload<PermissionItem>(permissionsQuery.data);

  return (
    <div className="two-column">
      <DataTable
        data={groups}
        columns={[
          { header: "模块", cell: ({ row }) => <code>{row.original.key}</code> },
          { header: "名称", accessorKey: "name" },
          { header: "权限数", cell: ({ row }) => row.original.permissions?.length ?? 0 },
        ]}
        emptyText={treeQuery.isLoading ? "加载中" : "暂无权限分组"}
      />
      <div className="stack">
        <DataTable
          data={roles}
          columns={[
            { header: "Role", cell: ({ row }) => <code>{row.original.key}</code> },
            { header: "名称", accessorKey: "name" },
            { header: "可申请", cell: ({ row }) => <Badge tone={row.original.requestable ? "success" : "neutral"}>{row.original.requestable ? "是" : "否"}</Badge> },
          ]}
          emptyText="暂无角色"
        />
        <DataTable
          data={permissions}
          columns={[
            { header: "Permission", cell: ({ row }) => <code>{row.original.key}</code> },
            { header: "名称", accessorKey: "name" },
            { header: "分组", cell: ({ row }) => row.original.group_key || "-" },
          ]}
          emptyText="暂无权限"
        />
      </div>
    </div>
  );
}
