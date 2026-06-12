import { useMutation, useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";

import { Button } from "../../../../components/Button";
import { StatusBanner } from "../../../../components/StatusBanner";
import { apiRequest } from "../../../../lib/api";
import type { MatrixPayload } from "../../../../lib/domain";
import { queryClient } from "../../../../lib/query";
import { RolePermissionMatrix } from "../matrix/RolePermissionMatrix";
import { useMatrixDraft } from "../matrix/useMatrixDraft";

export function MatrixTab({ appKey }: { appKey: string }) {
  const matrixQuery = useQuery({
    queryKey: ["console", "app", appKey, "matrix"],
    queryFn: () => apiRequest<MatrixPayload>(`/console/api/v1/apps/${appKey}/role-permission-matrix`),
  });
  const matrix = matrixQuery.data;
  const { hasChanges, isCellEnabled, setCellEnabled, buildSavePayload, resetDraft } = useMatrixDraft(matrix);
  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<MatrixPayload>(`/console/api/v1/apps/${appKey}/role-permission-matrix`, {
        method: "PATCH",
        body: buildSavePayload(),
      }),
    onSuccess: () => {
      resetDraft();
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "matrix"] });
    },
  });

  return (
    <section className="matrix-panel">
      <div className="panel-toolbar">
        <span>目录版本 <code>{matrix?.version?.slice(0, 12) ?? "-"}</code></span>
        <Button
          variant="primary"
          icon={<Check size={16} />}
          disabled={!hasChanges || saveMutation.isPending || !matrix?.version}
          onClick={() => saveMutation.mutate()}
        >
          保存变更
        </Button>
      </div>
      {saveMutation.error ? <StatusBanner tone="danger" title="保存失败" message={(saveMutation.error as Error).message} /> : null}
      <RolePermissionMatrix matrix={matrix} isCellEnabled={isCellEnabled} onCellChange={setCellEnabled} />
    </section>
  );
}
