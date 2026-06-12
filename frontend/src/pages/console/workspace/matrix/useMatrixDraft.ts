import { useMemo, useState } from "react";

import type { JsonObject } from "../../../../lib/api";
import type { MatrixPayload } from "../../../../lib/domain";

export interface MatrixAssignmentChange extends JsonObject {
  role_id: number;
  permission_id: number;
  enabled: boolean;
}

export interface MatrixSavePayload extends JsonObject {
  base_version: string;
  assignments: MatrixAssignmentChange[];
  add: [];
  remove: [];
}

export function useMatrixDraft(matrix: MatrixPayload | undefined) {
  const [changed, setChanged] = useState<Map<string, boolean>>(new Map());
  const originalCells = useMemo(
    () => new Map((matrix?.cells ?? []).map((cell) => [matrixCellKey(cell.role_id, cell.permission_id), cell.enabled])),
    [matrix?.cells],
  );

  const setCellEnabled = (roleId: number, permissionId: number, enabled: boolean) => {
    const key = matrixCellKey(roleId, permissionId);
    setChanged((current) => {
      const next = new Map(current);
      if (enabled === (originalCells.get(key) ?? false)) {
        next.delete(key);
      } else {
        next.set(key, enabled);
      }
      return next;
    });
  };

  const buildSavePayload = (): MatrixSavePayload => ({
    base_version: matrix?.version ?? "",
    assignments: Array.from(changed.entries()).map(([key, enabled]) => {
      const [roleId, permissionId] = key.split(":").map(Number);
      return { role_id: roleId, permission_id: permissionId, enabled };
    }),
    add: [],
    remove: [],
  });

  return {
    hasChanges: changed.size > 0,
    isCellEnabled: (roleId: number, permissionId: number) =>
      changed.get(matrixCellKey(roleId, permissionId)) ?? originalCells.get(matrixCellKey(roleId, permissionId)) ?? false,
    setCellEnabled,
    buildSavePayload,
    resetDraft: () => setChanged(new Map()),
  };
}

export function matrixCellKey(roleId: number, permissionId: number): string {
  return `${roleId}:${permissionId}`;
}
