import { SelectInput, TextInput } from "../../components/Field";
import { useI18n } from "../../i18n/I18nProvider";
import { APPROVAL_STATUS_LABEL_KEYS } from "../../lib/status";

const APPROVAL_STATUSES = ["created", "submitted", "approved", "rejected", "canceled", "failed"] as const;

export function ApprovalInstancesFilters({
  statusFilter,
  onStatusChange,
  appKeyInput,
  onAppKeyChange,
}: {
  statusFilter: string;
  onStatusChange: (next: string) => void;
  appKeyInput: string;
  onAppKeyChange: (next: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <SelectInput
        aria-label={t("approvalInstances.filter.status")}
        className="w-44"
        value={statusFilter}
        onChange={(event) => onStatusChange(event.currentTarget.value)}
      >
        <option value="">{t("approvalInstances.filter.allStatuses")}</option>
        {APPROVAL_STATUSES.map((status) => (
          <option key={status} value={status}>
            {t(APPROVAL_STATUS_LABEL_KEYS[status])}
          </option>
        ))}
      </SelectInput>
      <TextInput
        aria-label={t("approvalInstances.filter.appKey")}
        className="w-64"
        placeholder={t("approvalInstances.filter.appKey")}
        autoComplete="off"
        value={appKeyInput}
        onChange={(event) => onAppKeyChange(event.currentTarget.value)}
      />
    </div>
  );
}
