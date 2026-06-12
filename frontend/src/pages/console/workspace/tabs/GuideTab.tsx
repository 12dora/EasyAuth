import { useQuery } from "@tanstack/react-query";

import { CodeBlock } from "../../../../components/CodeBlock";
import { DataTable } from "../../../../components/DataTable";
import { apiRequest } from "../../../../lib/api";
import type { IntegrationGuide } from "../../../../lib/domain";

export function GuideTab({ appKey }: { appKey: string }) {
  const guideQuery = useQuery({
    queryKey: ["console", "app", appKey, "integration-guide"],
    queryFn: () => apiRequest<IntegrationGuide>(`/console/api/v1/apps/${appKey}/integration-guide`),
  });
  const endpoint = guideQuery.data?.permission_query_endpoint ?? `/api/v1/apps/${appKey}/users/{user_id}/permissions`;
  const curl = `curl -H "Authorization: Bearer $APP_TOKEN" "${endpoint}"`;
  const ts = `await fetch("${endpoint}", {\n  headers: { Authorization: \`Bearer \${appToken}\` },\n});`;

  return (
    <section className="stack">
      <DataTable
        data={guideQuery.data?.credential_modes ?? []}
        columns={[
          { header: "模式", accessorKey: "mode" },
          { header: "活跃数量", accessorKey: "active_count" },
        ]}
        emptyText={guideQuery.isLoading ? "加载中" : "暂无活跃凭据"}
      />
      <CodeBlock language="curl" code={curl} />
      <CodeBlock language="typescript" code={ts} />
    </section>
  );
}
