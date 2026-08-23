import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useOutletContext, useParams } from "react-router-dom";

import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import type { JsonObject } from "../../lib/api";
import type { AppListPayload } from "../../lib/domain";
import { AppBasicInfoDialog } from "./workspace/overview/AppBasicInfoDialog";
import type { AppPatchPayload } from "./workspace/overview/overviewModel";
import { invalidateAppDerivedQueries } from "./workspace/invalidateAppQueries";
import { WorkspaceHeader } from "./workspace/WorkspaceHeader";
import { WorkspaceTabList } from "./workspace/WorkspaceTabList";
import { renderWorkspaceTabPanel } from "./workspace/workspaceTabPanels";
import { useWorkspaceTabs } from "./workspace/useWorkspaceTabs";
import type { AppShellOutletContext } from "../../components/AppShell";

export function ConsoleAppWorkspace() {
  const { t } = useI18n();
  const { appKey = "" } = useParams();
  const queryClient = useQueryClient();
  const outlet = useOutletContext<AppShellOutletContext | null>();
  const isSuperuser = outlet?.isSuperuser === true;
  const { tabs, activeTab, activateTab } = useWorkspaceTabs(isSuperuser);
  const [basicInfoEditing, setBasicInfoEditing] = useState(false);

  const appQuery = useQuery({
    queryKey: ["console", "app", appKey],
    queryFn: () => apiRequest<AppListPayload>(`/console/api/v1/apps/${appKey}`),
    enabled: Boolean(appKey),
  });
  const app = appQuery.data?.app;
  const patchAppMutation = useMutation({
    mutationFn: (payload: AppPatchPayload) =>
      apiRequest(`/console/api/v1/apps/${appKey}`, {
        method: "PATCH",
        body: { ...payload } satisfies JsonObject,
      }),
    onSuccess: () => {
      invalidateAppDerivedQueries(queryClient, appKey);
      setBasicInfoEditing(false);
    },
  });

  useEffect(() => {
    patchAppMutation.reset();
    setBasicInfoEditing(false);
  }, [appKey]);

  return (
    <>
      <WorkspaceHeader
        appKey={appKey}
        app={app}
        onEditBasicInfo={() => {
          patchAppMutation.reset();
          setBasicInfoEditing(true);
        }}
      />
      {appQuery.error ? (
        <StatusBanner live="alert" tone="signal" title={t("workspace.loadFailed")} message={appQuery.error.message} />
      ) : null}
      <WorkspaceTabList tabs={tabs} activeTab={activeTab} onActivate={activateTab} />
      <div key={`${appKey}:${activeTab}`} id={`workspace-tabpanel-${activeTab}`} role="tabpanel" aria-labelledby={`workspace-tab-${activeTab}`}>
      {renderWorkspaceTabPanel(activeTab, { appKey, app, isSuperuser })}
      </div>
      {app?.capabilities?.can_edit_basic_info && basicInfoEditing ? (
        <AppBasicInfoDialog
          app={app}
          errorMessage={patchAppMutation.error ? patchAppMutation.error.message : ""}
          isSubmitting={patchAppMutation.isPending}
          onClose={() => setBasicInfoEditing(false)}
          onSubmit={(payload) => patchAppMutation.mutate(payload)}
        />
      ) : null}
    </>
  );
}
