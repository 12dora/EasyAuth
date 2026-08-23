import { Link } from "react-router-dom";

import { Button } from "../../../../components/Button";
import { Field, SelectInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import { EffectiveManagedScopeCard } from "./EffectiveManagedScopeCard";
import { MANAGED_SCOPE_OPTIONS, type ManagedScopeSelection } from "./managedScopePolicyPayload";
import { useManagedScopePolicy } from "./useManagedScopePolicy";

export function ManagedScopeTab({ appKey }: { appKey: string }) {
  const { t } = useI18n();
  const {
    selection,
    setSelection,
    policyQuery,
    policyQueryError,
    saveMutation,
    loadState,
    effectivePolicy,
    hasAuthoritativeSnapshot,
    teamBasedSelection,
  } = useManagedScopePolicy(appKey);

  return (
    <section className="space-y-6">
      <PanelSurface padding="lg" className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <h2 className="text-base font-semibold text-ink">{t("console.managedScope.heading")}</h2>
            <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("console.managedScope.description")}</p>
          </div>
          <Button
            type="button"
            variant="primary"
            loading={saveMutation.isPending}
            disabled={saveMutation.isPending || !hasAuthoritativeSnapshot}
            onClick={() => saveMutation.mutate()}
          >
            {t("console.managedScope.save")}
          </Button>
        </div>
        {loadState === "error" ? (
          <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-0 flex-1">
              <StatusBanner live="alert" tone="signal" title={t("console.managedScope.loadFailed")} message={policyQueryError?.message ?? ""} />
            </div>
            <Button type="button" loading={policyQuery.isFetching} onClick={() => void policyQuery.refetch()}>
              {t("common.retry")}
            </Button>
          </div>
        ) : null}
        {saveMutation.error ? (
          <StatusBanner live="alert" tone="signal" title={t("console.managedScope.saveFailed")} message={saveMutation.error.message} />
        ) : null}
        {hasAuthoritativeSnapshot ? <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
          <ManagedScopeSelector
            selection={selection}
            onSelect={setSelection}
            disabled={policyQuery.isLoading || saveMutation.isPending}
            teamBasedSelection={teamBasedSelection}
          />
          <EffectiveManagedScopeCard effectivePolicy={effectivePolicy} />
        </div> : null}
      </PanelSurface>
    </section>
  );
}

function ManagedScopeSelector({
  selection,
  onSelect,
  disabled,
  teamBasedSelection,
}: {
  selection: ManagedScopeSelection;
  onSelect: (selection: ManagedScopeSelection) => void;
  disabled: boolean;
  teamBasedSelection: boolean;
}) {
  const { t } = useI18n();

  return (
    <div className="space-y-2">
      <Field label={t("console.managedScope.policyLabel")} hint={t("console.managedScope.policyHint")}>
        <SelectInput
          value={selection}
          onChange={(event) => onSelect(event.currentTarget.value as ManagedScopeSelection)}
          disabled={disabled}
        >
          {MANAGED_SCOPE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {t(option.labelKey)}
            </option>
          ))}
        </SelectInput>
      </Field>
      {teamBasedSelection ? (
        <p className="text-xs leading-5 text-ink-soft">
          {t("console.managedScope.teamHint")}{" "}
          <Link className="font-medium text-accent hover:underline" to="/console/teams">
            {t("console.managedScope.teamHintLink")}
          </Link>
        </p>
      ) : null}
    </div>
  );
}
