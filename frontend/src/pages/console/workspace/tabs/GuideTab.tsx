import { useQuery } from "@tanstack/react-query";
import { getCoreRowModel, getPaginationRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { EmptyState } from "../../../../components/ui/EmptyState";

import { CodeBlock } from "../../../../components/CodeBlock";
import { StatusBanner } from "../../../../components/StatusBanner";
import { apiRequest } from "../../../../lib/api";
import type { IntegrationGuide } from "../../../../lib/domain";
import { WorkspaceTable } from "../table/WorkspaceTable";

type CredentialModeRow = NonNullable<IntegrationGuide["credential_modes"]>[number];

const CREDENTIAL_MODE_COLUMNS: ColumnDef<CredentialModeRow>[] = [
  { header: "模式", cell: ({ row }) => row.original.mode },
  { header: "活跃数量", cell: ({ row }) => row.original.active_count },
];

export function GuideTab({ appKey }: { appKey: string }) {
  const guideQuery = useQuery({
    queryKey: ["console", "app", appKey, "integration-guide"],
    queryFn: () => apiRequest<IntegrationGuide>(`/console/api/v1/apps/${appKey}/integration-guide`),
  });
  const credentialModes = guideQuery.data?.credential_modes ?? [];
  const credentialModeTable = useReactTable({
    data: credentialModes,
    columns: CREDENTIAL_MODE_COLUMNS,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });
  const endpoint = guideQuery.data?.permission_query_endpoint ?? `/api/v1/apps/${appKey}/users/{user_id}/permissions`;
  const curl = `curl -H "Authorization: Bearer $APP_TOKEN" "${endpoint}"`;
  const ts = `await fetch("${endpoint}", {\n  headers: { Authorization: \`Bearer \${appToken}\` },\n});`;

  return (
    <section className="space-y-6">
      {guideQuery.error ? (
        <StatusBanner live="alert" tone="signal" title="接入说明加载失败" message={guideQuery.error.message} />
      ) : null}
      <div className="space-y-3">
        <h2 className="text-base font-semibold text-ink">凭据模式</h2>
        <WorkspaceTable
          table={credentialModeTable}
          totalItems={credentialModes.length}
          isLoading={guideQuery.isLoading}
          empty={<EmptyState title="暂无活跃凭据" description="先在「凭据」页签创建凭据，再回到这里查看接入方式。" />}
        />
      </div>
      <div className="space-y-3">
        <h2 className="text-base font-semibold text-ink">权限查询示例</h2>
        <CodeBlock language="curl" code={curl} />
        <CodeBlock language="typescript" code={ts} />
      </div>
    </section>
  );
}
