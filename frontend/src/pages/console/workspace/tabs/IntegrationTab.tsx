import { ShieldCheck } from "lucide-react";

import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import { CapabilityPanel } from "../integration/CapabilityPanel";
import { NotificationChannelPanel } from "../integration/NotificationChannelPanel";

export function IntegrationTab({ appKey, canManage }: { appKey: string; canManage: boolean }) {
  const { t } = useI18n();

  return (
    <section className="space-y-6">
      <PanelSurface padding="lg" className="overflow-hidden">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.55fr)]">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-ink">
              <ShieldCheck size={18} aria-hidden="true" />
              <h2 className="text-base font-semibold">{t("console.integration.heading")}</h2>
            </div>
            <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("console.integration.description")}</p>
          </div>
          <div className="border-l-2 border-amber/45 bg-amber/8 px-4 py-3">
            <p className="text-label font-semibold uppercase tracking-caps-wide text-amber">
              {t("console.integration.boundaryHeading")}
            </p>
            <p className="mt-1 text-xs leading-5 text-ink-soft">{t("console.integration.boundaryDescription")}</p>
          </div>
        </div>
      </PanelSurface>
      <CapabilityPanel appKey={appKey} />
      <NotificationChannelPanel appKey={appKey} canManage={canManage} />
    </section>
  );
}
