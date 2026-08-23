import { useI18n } from "../../../../i18n/I18nProvider";
import type { EffectiveManagedScopePolicyItem } from "../../../../lib/domain";
import { effectiveManagedScopeLabel, managedScopeHealthLabel, managedScopeSourceLabel } from "./managedScopePolicyPayload";

export function EffectiveManagedScopeCard({ effectivePolicy }: { effectivePolicy: EffectiveManagedScopePolicyItem | null }) {
  const { t } = useI18n();

  return (
    <div className="rounded-[3px] border border-ink/10 bg-paper-soft p-4">
      <p className="text-label font-medium uppercase tracking-caps-wide text-ink-soft">{t("console.managedScope.effectiveTitle")}</p>
      <p className="mt-2 text-sm font-semibold text-ink">{effectiveManagedScopeLabel(t, effectivePolicy)}</p>
      <dl className="mt-3 grid gap-2 text-body text-ink-soft">
        <div className="flex items-center justify-between gap-4">
          <dt>{t("console.managedScope.effective.source")}</dt>
          <dd className="font-mono text-ink">{managedScopeSourceLabel(t, effectivePolicy?.source)}</dd>
        </div>
        <div className="flex items-center justify-between gap-4">
          <dt>{t("console.managedScope.effective.health")}</dt>
          <dd className="font-mono text-ink">{managedScopeHealthLabel(t, effectivePolicy)}</dd>
        </div>
      </dl>
      {effectivePolicy?.health_message ? (
        <p className="mt-3 text-xs leading-5 text-ink-soft">{effectivePolicy.health_message}</p>
      ) : null}
    </div>
  );
}
