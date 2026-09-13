import type { ComponentProps } from "react";

import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { SecretDialog } from "../../../../components/SecretDialog";
import { StatusBanner } from "../../../../components/StatusBanner";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { AppCapabilityKey, CredentialItem } from "../../../../lib/domain";
import { CreateCredentialForm } from "../credentials/CreateCredentialForm";

export function CreateCredentialDialog({
  open,
  isCreating,
  onClose,
  onCreateCredential,
}: {
  open: boolean;
  isCreating: boolean;
  onClose: () => void;
  onCreateCredential: ComponentProps<typeof CreateCredentialForm>["onCreateCredential"];
}) {
  const { t } = useI18n();
  if (!open) {
    return null;
  }
  return (
    <Dialog title={t("console.credentials.createTitle")} onClose={onClose}>
      <CreateCredentialForm
        isCreating={isCreating}
        onCreateCredential={async (kind, name, capabilities) => {
          await onCreateCredential(kind, name, capabilities);
          onClose();
        }}
      />
    </Dialog>
  );
}

export function CredentialSecretDialog({
  secretEntries,
  onClose,
}: {
  secretEntries: Array<[string, string]>;
  onClose: () => void;
}) {
  const { t } = useI18n();
  if (!secretEntries[0]) {
    return null;
  }
  return (
    <SecretDialog
      title={t("console.credentials.secretTitle")}
      primaryLabel={secretEntries[0][0]}
      primaryValue={secretEntries[0][1]}
      secondaryLabel={secretEntries[1]?.[0]}
      secondaryValue={secretEntries[1]?.[1]}
      onClose={onClose}
    />
  );
}

export function EditCapabilitiesDialog({
  credential,
  capabilities,
  saving,
  onCapabilitiesChange,
  onClose,
  onSave,
}: {
  credential: CredentialItem | null;
  capabilities: AppCapabilityKey[];
  saving: boolean;
  onCapabilitiesChange: (updater: (current: AppCapabilityKey[]) => AppCapabilityKey[]) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const { t } = useI18n();
  if (!credential) {
    return null;
  }
  return (
    <Dialog title={t("console.credentials.editCapabilitiesTitle")} onClose={onClose}>
      <div className="space-y-5">
        <p className="text-body leading-5 text-ink-soft">
          {t("console.credentials.editCapabilitiesDescription", { name: credential.name })}
        </p>
        <div className="grid gap-2 sm:grid-cols-2" role="group" aria-label={t("console.credentials.capabilities")}>
          {(["directory", "notify"] as const).map((capability) => (
            <label key={capability} className="flex items-center gap-2 border border-ink/12 bg-paper-soft px-3 py-2 text-body text-ink">
              <input
                type="checkbox"
                checked={capabilities.includes(capability)}
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  onCapabilitiesChange((current) =>
                    checked ? [...current, capability] : current.filter((item) => item !== capability),
                  );
                }}
              />
              <code>{capability}</code>
            </label>
          ))}
        </div>
        <StatusBanner tone="amber" title={t("console.credentials.capabilityWarningTitle")} message={t("console.credentials.capabilityWarningDescription")} />
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={onClose}>{t("common.cancel")}</Button>
          <Button type="button" variant="primary" loading={saving} onClick={onSave}>
            {t("console.credentials.saveCapabilities")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
