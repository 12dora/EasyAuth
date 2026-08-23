import { getCoreRowModel, getPaginationRowModel, useReactTable } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";

import { Button } from "../../../../components/Button";
import { Field, SelectInput } from "../../../../components/Field";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { AppScopeItem, PermissionItem } from "../../../../lib/domain";
import { WorkspaceTable } from "../table/WorkspaceTable";
import type { AuthorizationGroupForm } from "./grantFormUpdates";
import { authorizationGroupGrantColumns } from "./matrixColumns";

export function GrantDraftPanel({
  form,
  setForm,
  canManage,
  permissions,
  scopeOptions,
  grantPermission,
  setGrantPermission,
  grantScope,
  setGrantScope,
  addGrant,
}: {
  form: AuthorizationGroupForm;
  setForm: Dispatch<SetStateAction<AuthorizationGroupForm>>;
  canManage: boolean;
  permissions: PermissionItem[];
  scopeOptions: AppScopeItem[];
  grantPermission: string;
  setGrantPermission: (value: string) => void;
  grantScope: string;
  setGrantScope: (value: string) => void;
  addGrant: () => void;
}) {
  const { t } = useI18n();
  const grantTable = useReactTable({
    data: form.grants,
    columns: authorizationGroupGrantColumns({ t, canManage, setForm }),
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <>
      <PanelSurface padding="lg" className="grid items-end gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <Field label={t("console.matrix.field.grantPermission")}>
          <SelectInput value={grantPermission} onChange={(event) => setGrantPermission(event.currentTarget.value)}>
            {permissions.map((permission) => (
              <option key={permission.key} value={permission.key}>{permission.key}</option>
            ))}
          </SelectInput>
        </Field>
        <Field label={t("console.matrix.field.grantScope")}>
          <SelectInput value={grantScope} onChange={(event) => setGrantScope(event.currentTarget.value)}>
            {scopeOptions.map((scope) => (
              <option key={scope.key} value={scope.key}>{scope.key}</option>
            ))}
          </SelectInput>
        </Field>
        <Button type="button" icon={<Plus size={16} />} onClick={addGrant} disabled={!canManage || !grantPermission || !grantScope}>
          {t("console.matrix.addGrant")}
        </Button>
      </PanelSurface>
      <WorkspaceTable table={grantTable} totalItems={form.grants.length} empty={t("console.matrix.grant.empty")} />
      <PanelSurface className="flex flex-wrap items-center justify-between gap-3 bg-paper-deep">
        <span className="min-w-0 text-sm text-ink-soft">{t("console.matrix.grantPreview", { value: form.grants.map((grant) => `${grant.permission} / ${grant.scope}`).join("，") || "-" })}</span>
      </PanelSurface>
    </>
  );
}
