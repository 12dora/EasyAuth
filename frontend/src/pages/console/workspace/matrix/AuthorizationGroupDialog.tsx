import { Check } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";

import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { AppScopeItem, PermissionItem } from "../../../../lib/domain";
import { AuthorizationGroupFields } from "./AuthorizationGroupFields";
import { GrantDraftPanel } from "./GrantDraftPanel";
import type { AuthorizationGroupForm } from "./grantFormUpdates";

export function AuthorizationGroupDialog({
  isEditing,
  canManage,
  form,
  setForm,
  permissions,
  scopeOptions,
  grantPermission,
  setGrantPermission,
  grantScope,
  setGrantScope,
  addGrant,
  isSaving,
  onSave,
  onClose,
}: {
  isEditing: boolean;
  canManage: boolean;
  form: AuthorizationGroupForm;
  setForm: Dispatch<SetStateAction<AuthorizationGroupForm>>;
  permissions: PermissionItem[];
  scopeOptions: AppScopeItem[];
  grantPermission: string;
  setGrantPermission: (value: string) => void;
  grantScope: string;
  setGrantScope: (value: string) => void;
  addGrant: () => void;
  isSaving: boolean;
  onSave: () => void;
  onClose: () => void;
}) {
  const { t } = useI18n();

  return (
    <Dialog title={isEditing ? t("console.matrix.editTitle") : t("console.matrix.createTitle")} size="xl" onClose={onClose} footer={
      <>
        <Button type="button" onClick={onClose}>{t("common.cancel")}</Button>
        <Button
          form="authorization-group-form"
          type="submit"
          variant="primary"
          icon={<Check size={16} />}
          disabled={!canManage || !form.key || !form.name || isSaving}
          loading={isSaving}
        >
          {t("common.save")}
        </Button>
      </>
    }>
    <form id="authorization-group-form" className="space-y-4" onSubmit={(event) => {
      event.preventDefault();
      onSave();
    }}>
      <AuthorizationGroupFields form={form} setForm={setForm} canManage={canManage} />
      <GrantDraftPanel
        form={form}
        setForm={setForm}
        canManage={canManage}
        permissions={permissions}
        scopeOptions={scopeOptions}
        grantPermission={grantPermission}
        setGrantPermission={setGrantPermission}
        grantScope={grantScope}
        setGrantScope={setGrantScope}
        addGrant={addGrant}
      />
    </form>
    </Dialog>
  );
}
