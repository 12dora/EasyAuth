import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest } from "../../../lib/api";
import type { HandoverBlockedAppsPayload } from "../../../lib/domain";

/** 超管专用未接入告警条：非超管不请求、不渲染。 */
export function BlockedAppsBanner({ enabled }: { enabled: boolean }) {
  const { t } = useI18n();
  const query = useQuery({
    queryKey: ["console", "handover-blocked-apps"],
    queryFn: () => apiRequest<HandoverBlockedAppsPayload>("/console/api/v1/lifecycle/handover-blocked-apps"),
    enabled,
    staleTime: 30_000,
  });

  if (!enabled) {
    return null;
  }
  const data = query.data;
  if (!data || data.app_count <= 0) {
    return null;
  }

  return (
    <div className="mb-4" data-testid="blocked-apps-banner">
      <StatusBanner
        live="status"
        tone="amber"
        title={t("handover.console.blockedBanner", {
          appCount: data.app_count,
          taskCount: data.task_count,
        })}
        message={t("handover.console.blockedBannerView")}
      />
      <div className="mt-2">
        <Link className="text-body font-semibold text-accent underline" to="/console/operations/blocked-apps">
          {t("handover.console.blockedBannerView")}
        </Link>
      </div>
    </div>
  );
}
