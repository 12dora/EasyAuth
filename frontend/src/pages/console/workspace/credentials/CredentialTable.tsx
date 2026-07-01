import { RotateCw, ShieldOff } from "lucide-react";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { DataTable } from "../../../../components/DataTable";
import type { CredentialItem } from "../../../../lib/domain";
import { credentialKindLabel } from "../utils";

interface CredentialTableProps {
  credentials: CredentialItem[];
  isLoading: boolean;
  onRotateStaticToken: (credentialId: number) => void;
  onDisableCredential: (credential: CredentialItem) => void;
}

export function CredentialTable({
  credentials,
  isLoading,
  onRotateStaticToken,
  onDisableCredential,
}: CredentialTableProps) {
  return (
    <DataTable
      data={credentials}
      columns={[
        { header: "名称", accessorKey: "name" },
        { header: "类型", cell: ({ row }) => credentialKindLabel(row.original.kind) },
        { header: "client_id", cell: ({ row }) => (row.original.client_id ? <code>{row.original.client_id}</code> : "-") },
        {
          header: "状态",
          cell: ({ row }) => (
            <Badge tone={row.original.is_active ? "success" : "neutral"}>{row.original.is_active ? "启用" : "停用"}</Badge>
          ),
        },
        {
          header: "操作",
          cell: ({ row }) => (
            <div className="row-actions">
              {row.original.kind === "static_token" ? (
                <Button variant="ghost" icon={<RotateCw size={14} />} onClick={() => onRotateStaticToken(row.original.id)} aria-label="轮换" />
              ) : null}
              <Button variant="ghost" icon={<ShieldOff size={14} />} onClick={() => onDisableCredential(row.original)} aria-label="禁用" />
            </div>
          ),
        },
      ]}
      emptyText={isLoading ? "加载中" : "暂无凭据"}
    />
  );
}
