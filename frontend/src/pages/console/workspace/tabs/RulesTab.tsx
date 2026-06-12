import { useQuery } from "@tanstack/react-query";

import { Badge } from "../../../../components/Badge";
import { DataTable } from "../../../../components/DataTable";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ApprovalRuleItem } from "../../../../lib/domain";
import { safeJoin } from "../utils";

export function RulesTab({ appKey }: { appKey: string }) {
  const rulesQuery = useQuery({
    queryKey: ["console", "app", appKey, "approval-rules"],
    queryFn: () => apiRequest<{ items?: ApprovalRuleItem[] }>(`/console/api/v1/apps/${appKey}/approval-rules`),
  });
  const rules = itemsFromPayload<ApprovalRuleItem>(rulesQuery.data);

  return (
    <DataTable
      data={rules}
      columns={[
        { header: "对象", cell: ({ row }) => `${row.original.target_type ?? "-"}:${row.original.target_key ?? "-"}` },
        { header: "审批人", cell: ({ row }) => safeJoin(row.original.approver_userids) },
        { header: "状态", cell: ({ row }) => <Badge tone={row.original.is_active ? "success" : "neutral"}>{row.original.is_active ? "启用" : "停用"}</Badge> },
      ]}
      emptyText={rulesQuery.isLoading ? "加载中" : "暂无审批规则"}
    />
  );
}
