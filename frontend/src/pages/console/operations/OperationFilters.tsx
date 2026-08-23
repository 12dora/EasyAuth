import { SelectInput, TextInput } from "../../../components/Field";
import { useI18n } from "../../../i18n/I18nProvider";
import { accessRequestStatusLabel, grantStatusLabel } from "../../../lib/status";
import { ACCESS_GRANT_STATUSES, ACCESS_REQUEST_STATUSES } from "./operationQuery";

export function OperationFilters({
  section,
  searchParams,
  onChange,
}: {
  section: string;
  searchParams: URLSearchParams;
  onChange: (key: string, value: string) => void;
}) {
  const { t } = useI18n();
  const userFilterKey = section === "audit" ? "actor_id" : "user_id";
  const statuses = section === "access-requests" ? ACCESS_REQUEST_STATUSES : section === "access-grants" ? ACCESS_GRANT_STATUSES : [];

  return (
    <div className="mb-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
      <TextInput
        aria-label="app_key"
        placeholder="app_key"
        autoComplete="off"
        value={searchParams.get("app_key") ?? ""}
        onChange={(event) => onChange("app_key", event.currentTarget.value)}
      />
      <TextInput
        aria-label={userFilterKey}
        placeholder={userFilterKey}
        autoComplete="off"
        value={searchParams.get(userFilterKey) ?? ""}
        onChange={(event) => onChange(userFilterKey, event.currentTarget.value)}
      />
      {statuses.length > 0 ? (
        <SelectInput
          aria-label="status"
          value={searchParams.get("status") ?? ""}
          onChange={(event) => onChange("status", event.currentTarget.value)}
        >
          <option value="">{t("approvalInstances.filter.allStatuses")}</option>
          {statuses.map((status) => (
            <option key={status} value={status}>
              {section === "access-requests" ? accessRequestStatusLabel(t, status) : grantStatusLabel(t, status)}
            </option>
          ))}
        </SelectInput>
      ) : null}
      <TextInput
        type="datetime-local"
        aria-label="created_from"
        value={searchParams.get("created_from") ?? ""}
        onChange={(event) => onChange("created_from", event.currentTarget.value)}
      />
      <TextInput
        type="datetime-local"
        aria-label="created_to"
        value={searchParams.get("created_to") ?? ""}
        onChange={(event) => onChange("created_to", event.currentTarget.value)}
      />
      {section === "access-grants" ? <AccessGrantFilters searchParams={searchParams} onChange={onChange} /> : null}
    </div>
  );
}

function AccessGrantFilters({
  searchParams,
  onChange,
}: {
  searchParams: URLSearchParams;
  onChange: (key: string, value: string) => void;
}) {
  const { t } = useI18n();

  return (
    <>
      <TextInput
        type="number"
        min={1}
        aria-label="version"
        placeholder="version"
        value={searchParams.get("version") ?? ""}
        onChange={(event) => onChange("version", event.currentTarget.value)}
      />
      <SelectInput
        aria-label="current"
        value={searchParams.get("current") ?? ""}
        onChange={(event) => onChange("current", event.currentTarget.value)}
      >
        <option value="">{t("console.operations.filter.allCurrentStates")}</option>
        <option value="true">{t("console.operations.filter.currentOnly")}</option>
        <option value="false">{t("console.operations.filter.historyOnly")}</option>
      </SelectInput>
    </>
  );
}
