import { SelectInput } from "../../../components/Field";
import { useI18n } from "../../../i18n/I18nProvider";
import { ASSIGNEE_STATES, TASK_KINDS, TASK_STATUSES, type HandoverTaskFilterValues } from "./handoverTaskListModel";
import { handoverAssigneeStateLabel, handoverKindLabel, handoverTaskStatusLabel } from "./lifecycleLabels";

export function HandoverTaskFilters({
  filters,
  onChange,
}: {
  filters: HandoverTaskFilterValues;
  onChange: (patch: Partial<HandoverTaskFilterValues>) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <SelectInput
        aria-label={t("handover.list.filter.status")}
        className="w-44"
        value={filters.status}
        onChange={(event) => onChange({ status: event.currentTarget.value })}
      >
        <option value="">{t("handover.list.filter.allStatuses")}</option>
        {TASK_STATUSES.map((status) => (
          <option key={status} value={status}>
            {handoverTaskStatusLabel(t, status)}
          </option>
        ))}
      </SelectInput>
      <SelectInput
        aria-label={t("handover.list.filter.kind")}
        className="w-44"
        value={filters.kind}
        onChange={(event) => onChange({ kind: event.currentTarget.value })}
      >
        <option value="">{t("handover.list.filter.allKinds")}</option>
        {TASK_KINDS.map((kind) => (
          <option key={kind} value={kind}>
            {handoverKindLabel(t, kind)}
          </option>
        ))}
      </SelectInput>
      <SelectInput
        aria-label={t("handover.console.filter.assigneeState")}
        className="w-44"
        value={filters.assigneeState}
        onChange={(event) => onChange({ assigneeState: event.currentTarget.value })}
      >
        <option value="">{t("handover.console.filter.allAssigneeStates")}</option>
        {ASSIGNEE_STATES.map((state) => (
          <option key={state} value={state}>
            {handoverAssigneeStateLabel(t, state)}
          </option>
        ))}
      </SelectInput>
      <SelectInput
        aria-label={t("handover.console.filter.blockedAll")}
        className="w-44"
        value={filters.blocked}
        onChange={(event) => onChange({ blocked: event.currentTarget.value })}
      >
        <option value="">{t("handover.console.filter.blockedAll")}</option>
        <option value="true">{t("handover.console.filter.blockedYes")}</option>
        <option value="false">{t("handover.console.filter.blockedNo")}</option>
      </SelectInput>
    </div>
  );
}
