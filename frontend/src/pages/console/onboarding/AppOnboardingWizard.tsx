import { Button } from "../../../components/Button";
import { ButtonLink } from "../../../components/ButtonLink";
import { PageHeader } from "../../../components/PageHeader";
import { useI18n } from "../../../i18n/I18nProvider";
import { AuthzStep } from "./AuthzStep";
import { BasicsStep } from "./BasicsStep";
import { CatalogStep } from "./CatalogStep";
import { CredentialStep } from "./CredentialStep";
import { DoneStep } from "./DoneStep";
import { useAppOnboardingWizard } from "./useAppOnboardingWizard";
import { VerifyStep } from "./VerifyStep";
import { WizardStepper } from "./WizardStepper";

export function AppOnboardingWizard() {
  const { t } = useI18n();
  const wizard = useAppOnboardingWizard();
  const { app, appKey, activeStep, catalogImportPending, goToStep } = wizard;

  return (
    <>
      <PageHeader
        eyebrow={t("wizard.eyebrow")}
        title={t("wizard.title")}
        description={t("wizard.description")}
        actions={<WizardHeaderActions appKey={appKey} navigationLocked={catalogImportPending} />}
      />
      <WizardStepper
        activeStepIndex={wizard.activeStepIndex}
        appKey={appKey}
        navigationLocked={catalogImportPending}
        doneBlocked={wizard.oauthCompletionBlocked}
        onNavigate={goToStep}
      />
      {activeStep === "basics" ? (
        <BasicsStep
          app={app}
          appKey={appKey}
          onContinue={(key) => goToStep("catalog", key)}
          onAutoOnboarded={(key) => goToStep("authz", key)}
        />
      ) : null}
      {activeStep === "catalog" ? (
        <CatalogStep
          key={appKey}
          appKey={appKey}
          onBack={() => goToStep("basics")}
          onContinue={() => goToStep("authz")}
          onImportPendingChange={wizard.setCatalogImportPending}
        />
      ) : null}
      {activeStep === "authz" ? (
        <AuthzStep key={appKey} appKey={appKey} onBack={() => goToStep("catalog")} onContinue={() => goToStep("credential")} />
      ) : null}
      {activeStep === "credential" ? (
        <CredentialStep
          key={appKey}
          appKey={appKey}
          activeCredentialCount={app?.active_credential_count ?? 0}
          onProgressChange={wizard.setCredentialProgress}
          onBack={() => goToStep("authz")}
          onContinue={() => goToStep("verify")}
        />
      ) : null}
      {activeStep === "verify" ? (
        <VerifyStep key={appKey} appKey={appKey} onBack={() => goToStep("credential")} onContinue={() => goToStep("done")} />
      ) : null}
      {activeStep === "done" ? (
        <DoneStep key={appKey} appKey={appKey} appName={app?.name ?? appKey} credentialKind={wizard.readyCredentialKind} />
      ) : null}
    </>
  );
}

function WizardHeaderActions({ appKey, navigationLocked }: { appKey: string; navigationLocked: boolean }) {
  const { t } = useI18n();

  return (
    <div className="flex flex-col items-stretch gap-2 sm:items-end">
      {navigationLocked ? (
        <Button disabled>{t("wizard.backToList")}</Button>
      ) : (
        <ButtonLink to="/console">{t("wizard.backToList")}</ButtonLink>
      )}
      {appKey ? (
        navigationLocked ? (
          <Button disabled>{t("wizard.openWorkspace")}</Button>
        ) : (
          <ButtonLink to={`/console/apps/${appKey}`}>{t("wizard.openWorkspace")}</ButtonLink>
        )
      ) : null}
    </div>
  );
}
