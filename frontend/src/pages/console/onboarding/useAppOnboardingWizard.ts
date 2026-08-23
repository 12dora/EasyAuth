import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { apiRequest } from "../../../lib/api";
import type { AppListPayload } from "../../../lib/domain";
import type { CreatedCredentialKind, CredentialProgress, WizardStep } from "./types";
import { buildWizardStepQuery, findStepIndex, resolveActiveStep } from "./wizardSteps";

export interface AppOnboardingWizardState {
  appKey: string;
  activeStep: WizardStep;
  activeStepIndex: number;
  app: AppListPayload["app"];
  catalogImportPending: boolean;
  setCatalogImportPending: (pending: boolean) => void;
  setCredentialProgress: (progress: CredentialProgress | null) => void;
  oauthCompletionBlocked: boolean;
  readyCredentialKind: CreatedCredentialKind | null;
  goToStep: (step: WizardStep, targetAppKey?: string) => void;
}

/** 向导的跨步骤状态机: 步骤来源于 URL, 步骤间只共享目录导入锁与凭据进度两项。 */
export function useAppOnboardingWizard(): AppOnboardingWizardState {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const appKey = searchParams.get("app_key") ?? "";
  const requestedStep = (searchParams.get("step") as WizardStep | null) ?? "basics";
  const activeStep = resolveActiveStep(requestedStep, appKey);
  const [catalogImportPending, setCatalogImportPending] = useState(false);
  const [credentialProgress, setCredentialProgress] = useState<CredentialProgress | null>(null);
  const oauthCompletionBlocked = credentialProgress?.kind === "oauth_client" && !credentialProgress.ready;

  const goToStep = (step: WizardStep, targetAppKey: string = appKey) => {
    if (catalogImportPending || (step === "done" && oauthCompletionBlocked)) {
      return;
    }
    void navigate(`/console/apps/new?${buildWizardStepQuery(step, targetAppKey)}`);
  };

  const appQuery = useQuery({
    queryKey: ["console", "app", appKey],
    queryFn: () => apiRequest<AppListPayload>(`/console/api/v1/apps/${appKey}`),
    enabled: Boolean(appKey),
  });

  return {
    appKey,
    activeStep,
    activeStepIndex: findStepIndex(activeStep),
    app: appQuery.data?.app,
    catalogImportPending,
    setCatalogImportPending,
    setCredentialProgress,
    oauthCompletionBlocked,
    readyCredentialKind: credentialProgress?.ready ? credentialProgress.kind : null,
    goToStep,
  };
}
