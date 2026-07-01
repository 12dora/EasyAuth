import { useQuery } from "@tanstack/react-query";

import { DataTable } from "../../../../components/DataTable";
import { StatusBanner } from "../../../../components/StatusBanner";
import { apiRequest } from "../../../../lib/api";
import type { AppSummary, ConfigurationStatus } from "../../../../lib/domain";
import { readinessLabel, readinessTone } from "../../../../lib/status";

export function OverviewTab({ appKey, app }: { appKey: string; app?: AppSummary }) {
  const statusQuery = useQuery({
    queryKey: ["console", "app", appKey, "configuration-status"],
    queryFn: () => apiRequest<ConfigurationStatus>(`/console/api/v1/apps/${appKey}/configuration-status`),
    enabled: Boolean(appKey),
  });
  const issues = statusQuery.data?.issues ?? statusQuery.data?.items ?? [];
  const status = statusQuery.data?.status ?? app?.configuration_status;

  return (
    <section className="workspace-grid">
      <div className="metric-grid">
        <Metric label="角色" value={app?.role_count ?? 0} />
        <Metric label="权限" value={app?.permission_count ?? 0} />
        <Metric label="活跃凭据" value={app?.active_credential_count ?? 0} />
        <Metric label="配置问题" value={app?.configuration_summary?.issue_count ?? issues.length} />
      </div>
      <StatusBanner tone={readinessTone(status)} title={`配置${readinessLabel(status)}`} />
      <DataTable
        data={issues}
        columns={[
          { header: "级别", cell: ({ row }) => row.original.severity ?? row.original.level ?? "-" },
          { header: "对象", cell: ({ row }) => row.original.subject ?? row.original.target_id ?? "-" },
          { header: "说明", cell: ({ row }) => row.original.message ?? "-" },
          { header: "代码", cell: ({ row }) => <code>{row.original.code ?? "-"}</code> },
        ]}
        emptyText={statusQuery.isLoading ? "加载中" : "暂无配置问题"}
      />
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
