import type { MatrixPayload } from "../../../../lib/domain";
import { matrixCellKey } from "./useMatrixDraft";

interface RolePermissionMatrixProps {
  matrix: MatrixPayload | undefined;
  isCellEnabled: (roleId: number, permissionId: number) => boolean;
  onCellChange: (roleId: number, permissionId: number, enabled: boolean) => void;
}

export function RolePermissionMatrix({ matrix, isCellEnabled, onCellChange }: RolePermissionMatrixProps) {
  const roles = matrix?.roles ?? [];
  const permissions = matrix?.permissions ?? [];

  return (
    <div className="matrix-scroll">
      <table className="matrix-table">
        <thead>
          <tr>
            <th>Permission</th>
            {roles.map((role) => (
              <th key={role.id}>{role.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {permissions.map((permission) => (
            <tr key={permission.id}>
              <td>
                <strong>{permission.name}</strong>
                <code>{permission.key}</code>
              </td>
              {roles.map((role) => (
                <td key={matrixCellKey(role.id, permission.id)}>
                  <input
                    type="checkbox"
                    checked={isCellEnabled(role.id, permission.id)}
                    onChange={(event) => onCellChange(role.id, permission.id, event.currentTarget.checked)}
                    aria-label={`${role.key} ${permission.key}`}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
