import { SelectInput, TextInput } from "../../../components/Field";
import { useI18n } from "../../../i18n/I18nProvider";
import { PERSON_STATUSES } from "./consolePeopleModel";
import { personStatusLabel } from "./lifecycleLabels";

export function ConsolePeopleFilters({
  statusFilter,
  onStatusChange,
  searchInput,
  onSearchChange,
}: {
  statusFilter: string;
  onStatusChange: (next: string) => void;
  searchInput: string;
  onSearchChange: (next: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <SelectInput
        aria-label={t("people.filter.status")}
        className="w-44"
        value={statusFilter}
        onChange={(event) => onStatusChange(event.currentTarget.value)}
      >
        <option value="">{t("people.filter.all")}</option>
        {PERSON_STATUSES.map((status) => (
          <option key={status} value={status}>
            {personStatusLabel(t, status)}
          </option>
        ))}
      </SelectInput>
      <TextInput
        aria-label={t("people.searchPlaceholder")}
        className="w-64"
        placeholder={t("people.searchPlaceholder")}
        autoComplete="off"
        value={searchInput}
        onChange={(event) => onSearchChange(event.currentTarget.value)}
      />
    </div>
  );
}
