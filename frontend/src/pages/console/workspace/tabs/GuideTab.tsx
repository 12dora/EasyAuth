import { useQuery } from "@tanstack/react-query";

import { CodeBlock } from "../../../../components/CodeBlock";
import { StatusBanner } from "../../../../components/StatusBanner";
import { AppTable, type ColumnsType } from "../../../../components/antd/AppTable";
import { textColumn } from "../../../../components/antd/columns";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { apiRequest } from "../../../../lib/api";
import type { IntegrationGuide } from "../../../../lib/domain";

type CredentialModeRow = NonNullable<IntegrationGuide["credential_modes"]>[number];

const CREDENTIAL_MODE_COLUMNS: ColumnsType<CredentialModeRow> = [
  textColumn<CredentialModeRow>({ key: "mode", title: "模式", mono: true, filter: true, sorter: true }),
  {
    key: "active_count",
    dataIndex: "active_count",
    title: "活跃数量",
    width: 140,
    sorter: (a, b) => a.active_count - b.active_count,
  },
];

export function GuideTab({ appKey }: { appKey: string }) {
  const guideQuery = useQuery({
    queryKey: ["console", "app", appKey, "integration-guide"],
    queryFn: () => apiRequest<IntegrationGuide>(`/console/api/v1/apps/${appKey}/integration-guide`),
  });
  const credentialModes = guideQuery.data?.credential_modes ?? [];
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
        <AppTable<CredentialModeRow>
          columns={CREDENTIAL_MODE_COLUMNS}
          dataSource={credentialModes}
          rowKey="mode"
          // 固定列 140(活跃数量) + 唯一的弹性列(模式)240 -> 380; 比卡片窄, 桌面端铺满。
          minWidth={380}
          loading={guideQuery.isLoading}
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
