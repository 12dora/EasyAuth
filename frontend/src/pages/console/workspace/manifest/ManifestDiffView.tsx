/** 将 Manifest 预览差异按新增、变更和移除分区展示。 */

import { getCoreRowModel, getPaginationRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";

import { Badge } from "../../../../components/Badge";
import { CodeBlock } from "../../../../components/CodeBlock";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { TableView } from "../../../../components/ui/TableView";
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

function ManifestDiffTable({ items }: { items: ManifestDiffItem[] }) {
  const columns: ColumnDef<ManifestDiffItem>[] = [
    { header: "对象", cell: ({ row }) => `${row.original.type ?? "-"}:${row.original.key ?? "-"}` },
    { header: "名称", cell: ({ row }) => row.original.name ?? "-" },
    { header: "详情", cell: ({ row }) => <CodeBlock language="json" code={JSON.stringify({ before: row.original.before, after: row.original.after }, null, 2)} /> },
  ];
  const table = useReactTable({
    data: items,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <TableView table={table} totalItems={items.length} empty="无差异" />
  );
}
