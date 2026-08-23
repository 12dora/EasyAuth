import { StatusBanner } from "../../../../components/StatusBanner";
import type { AppSummary } from "../../../../lib/domain";
import { useI18n } from "../../../../i18n/I18nProvider";
import { readinessLabel, readinessTone } from "../../../../lib/status";
import { AppBasicInfoPanel } from "../overview/AppBasicInfoPanel";
import { ConfigurationIssuesPanel } from "../overview/ConfigurationIssuesPanel";
import { MembershipCreateDialog } from "../overview/MembershipCreateDialog";
import { MembershipsPanel } from "../overview/MembershipsPanel";
import { OverviewMetrics } from "../overview/OverviewMetrics";
import { deriveOverviewSummary, normalizeStatusBannerTone } from "../overview/overviewModel";
import { useOverviewData } from "../overview/useOverviewData";

export function OverviewTab({ appKey, app }: { appKey: string; app?: AppSummary }) {
  const { t } = useI18n();
  const {
    statusQuery,
    membershipsQuery,
    memberships,
    createMembershipMutation,
    disableMembershipMutation,
    membershipDialogOpen,
    setMembershipDialogOpen,
  } = useOverviewData(appKey);
  const { issues, status, issueCount } = deriveOverviewSummary(app, statusQuery.data);

  return (
    <section className="space-y-6">
      {status && status !== "ready" ? (
        <StatusBanner
          live="status"
          tone={normalizeStatusBannerTone(readinessTone(status))}
          title={t("console.overview.configBanner", { status: readinessLabel(t, status) })}
        />
      ) : null}
      {statusQuery.error ? (
        <StatusBanner live="alert" tone="signal" title={t("console.overview.configStatusLoadFailed")} message={statusQuery.error.message} />
      ) : null}
      <OverviewMetrics app={app} issueCount={issueCount} />
      <AppBasicInfoPanel app={app} status={status} />
      <MembershipsPanel
        canWrite={app?.capabilities?.can_manage_memberships === true}
        memberships={memberships}
        isLoading={membershipsQuery.isLoading}
        loadError={membershipsQuery.error}
        operationError={disableMembershipMutation.error}
        onCreate={() => setMembershipDialogOpen(true)}
        onDisable={(membershipId) => disableMembershipMutation.mutate(membershipId)}
      />
      {membershipDialogOpen ? (
        <MembershipCreateDialog
          errorMessage={createMembershipMutation.error ? createMembershipMutation.error.message : ""}
          isSubmitting={createMembershipMutation.isPending}
          onClose={() => setMembershipDialogOpen(false)}
          onSubmit={(payload) => createMembershipMutation.mutate(payload)}
        />
      ) : null}
      <ConfigurationIssuesPanel issues={issues} isLoading={statusQuery.isLoading} />
    </section>
  );
}
