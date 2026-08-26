/** 将 Manifest 预览差异按新增、变更和移除分区展示。 */

import { useMemo } from "react";

import { Badge } from "../../../../components/Badge";
import { CodeBlock } from "../../../../components/CodeBlock";
import { AppTable, type ColumnsType } from "../../../../components/antd/AppTable";
import { textColumn } from "../../../../components/antd/columns";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { diffFromChanges, type ManifestDiffItem, type ManifestPreviewPayload } from "./manifestImportModel";

export function ManifestDiffView({ preview }: { preview: ManifestPreviewPayload }) {
  const diff = preview.diff ?? diffFromChanges(preview.changes ?? []);
  const sections = [
    { title: "新增", tone: "evergreen" as const, items: diff.added ?? [] },
    { title: "变更", tone: "amber" as const, items: diff.changed ?? [] },
    { title: "移除", tone: "signal" as const, items: diff.removed ?? [] },
  ];

  return (
    <div className="space-y-4">
      {sections.map((section) => (
        <PanelSurface className="space-y-3" key={section.title}>
          <div className="flex items-center justify-between gap-3">
            <Badge tone={section.tone}>{section.title}</Badge>
          </div>
          <ManifestDiffTable items={section.items} />
        </PanelSurface>
      ))}
    </div>
  );
}

/** 差异条目全在客户端(预览响应一次给全), 分页/筛选/排序都由 antd 本地完成。 */
function ManifestDiffTable({ items }: { items: ManifestDiffItem[] }) {
  const columns = useMemo<ColumnsType<ManifestDiffItem>>(
    () => [
      textColumn<ManifestDiffItem>({
        key: "object",
        title: "对象",
        getValue: (item) => `${item.type ?? "-"}:${item.key ?? "-"}`,
        filter: true,
        sorter: true,
        mono: true,
        width: 280,
      }),
      textColumn<ManifestDiffItem>({ key: "name", title: "名称", filter: true, sorter: true, width: 200 }),
      {
        key: "detail",
        title: "详情",
        render: (_value: unknown, item: ManifestDiffItem) => (
          <CodeBlock language="json" code={JSON.stringify({ before: item.before, after: item.after }, null, 2)} />
        ),
      },
    ],
    [],
  );

  return (
    <AppTable<ManifestDiffItem>
      columns={columns}
      dataSource={items}
      emptyTitle="无差异"
      rowKey={(item) => `${item.type ?? ""}:${item.key ?? ""}`}
    />
  );
}
