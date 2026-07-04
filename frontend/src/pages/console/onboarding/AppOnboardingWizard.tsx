import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Compass, Eye, FileUp, KeyRound, Play, Plus, RefreshCcw, UploadCloud } from "lucide-react";
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { AppKeyInput } from "../../../components/AppKeyInput";
import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { ButtonLink } from "../../../components/ButtonLink";
import { CodeBlock } from "../../../components/CodeBlock";
import { Field, TextArea, TextInput } from "../../../components/Field";
import { InfoTip } from "../../../components/InfoTip";
import { PageHeader } from "../../../components/PageHeader";
import { StatusBanner } from "../../../components/StatusBanner";
import { UserMultiSelect, UserSearchInput } from "../../../components/UserSelect";
import { PanelSurface } from "../../../components/ui/PanelSurface";
import { useI18n } from "../../../i18n/I18nProvider";
import type { MessageKey } from "../../../i18n/messages";
import { apiRequest } from "../../../lib/api";
import type { JsonObject } from "../../../lib/api";
import { generateAppKey } from "../../../lib/appKey";
import { cn } from "../../../lib/cn";
import type { AppListPayload, ConfigurationStatus, QueryTestResult, SecretPayload } from "../../../lib/domain";

type WizardStep = "basics" | "catalog" | "authz" | "credential" | "verify" | "done";

const WIZARD_STEPS: Array<{ key: WizardStep; labelKey: MessageKey }> = [
  { key: "basics", labelKey: "wizard.step.basics" },
  { key: "catalog", labelKey: "wizard.step.catalog" },
  { key: "authz", labelKey: "wizard.step.authz" },
  { key: "credential", labelKey: "wizard.step.credential" },
  { key: "verify", labelKey: "wizard.step.verify" },
  { key: "done", labelKey: "wizard.step.done" },
];

export function AppOnboardingWizard() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const appKey = searchParams.get("app_key") ?? "";
  const requestedStep = (searchParams.get("step") as WizardStep | null) ?? "basics";
  const stepIsKnown = WIZARD_STEPS.some((step) => step.key === requestedStep);
  const activeStep: WizardStep = !stepIsKnown || (!appKey && requestedStep !== "basics") ? "basics" : requestedStep;
  const activeStepIndex = WIZARD_STEPS.findIndex((step) => step.key === activeStep);

  const goToStep = (step: WizardStep, targetAppKey: string = appKey) => {
    const params = new URLSearchParams();
    if (targetAppKey) {
      params.set("app_key", targetAppKey);
    }
    params.set("step", step);
    void navigate(`/console/apps/new?${params.toString()}`);
  };

  const appQuery = useQuery({
    queryKey: ["console", "app", appKey],
    queryFn: () => apiRequest<AppListPayload>(`/console/api/v1/apps/${appKey}`),
    enabled: Boolean(appKey),
  });
  const app = appQuery.data?.app;

  return (
    <>
      <PageHeader
        eyebrow={t("wizard.eyebrow")}
        title={t("wizard.title")}
        description={t("wizard.description")}
        actions={
          <div className="flex flex-col items-stretch gap-2 sm:items-end">
            <ButtonLink to="/console">{t("wizard.backToList")}</ButtonLink>
            {appKey ? <ButtonLink to={`/console/apps/${appKey}`}>{t("wizard.openWorkspace")}</ButtonLink> : null}
          </div>
        }
      />
      <WizardStepper activeStepIndex={activeStepIndex} appKey={appKey} onNavigate={goToStep} />
      {activeStep === "basics" ? (
        <BasicsStep
          app={app}
          appKey={appKey}
          onContinue={(key) => goToStep("catalog", key)}
          onAutoOnboarded={(key) => goToStep("authz", key)}
        />
      ) : null}
      {activeStep === "catalog" ? (
        <CatalogStep appKey={appKey} onBack={() => goToStep("basics")} onContinue={() => goToStep("authz")} />
      ) : null}
      {activeStep === "authz" ? (
        <AuthzStep appKey={appKey} onBack={() => goToStep("catalog")} onContinue={() => goToStep("credential")} />
      ) : null}
      {activeStep === "credential" ? (
        <CredentialStep
          appKey={appKey}
          activeCredentialCount={app?.active_credential_count ?? 0}
          onBack={() => goToStep("authz")}
          onContinue={() => goToStep("verify")}
        />
      ) : null}
      {activeStep === "verify" ? (
        <VerifyStep appKey={appKey} onBack={() => goToStep("credential")} onContinue={() => goToStep("done")} />
      ) : null}
      {activeStep === "done" ? <DoneStep appKey={appKey} appName={app?.name ?? appKey} /> : null}
    </>
  );
}

function WizardStepper({
  activeStepIndex,
  appKey,
  onNavigate,
}: {
  activeStepIndex: number;
  appKey: string;
  onNavigate: (step: WizardStep) => void;
}) {
  const { t } = useI18n();

  return (
    <ol className="mb-6 flex flex-wrap gap-x-1 gap-y-2 border-b border-ink/12 pb-4" aria-label={t("wizard.stepsAria")}>
      {WIZARD_STEPS.map((step, index) => {
        const isActive = index === activeStepIndex;
        const isDone = index < activeStepIndex;
        const isReachable = index === 0 || Boolean(appKey);
        const stateLabel = isActive
          ? t("wizard.stepState.current")
          : isDone
            ? t("wizard.stepState.done")
            : t("wizard.stepState.pending");

        return (
          <li key={step.key} className="flex items-center gap-1">
            {index > 0 ? <span aria-hidden="true" className="mx-1 hidden h-px w-6 bg-ink/15 sm:block" /> : null}
            <button
              type="button"
              disabled={!isReachable}
              aria-current={isActive ? "step" : undefined}
              aria-label={`${t(step.labelKey)} - ${stateLabel}`}
              className={cn(
                "flex items-center gap-2 rounded-[3px] px-2 py-1 text-sm font-semibold transition-colors",
                isActive ? "text-ink" : "text-ink-soft",
                isReachable ? "hover:text-ink" : "cursor-not-allowed opacity-50",
              )}
              onClick={() => onNavigate(step.key)}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "flex size-6 items-center justify-center rounded-full border text-xs",
                  isActive && "border-accent bg-accent text-paper",
                  isDone && "border-evergreen bg-evergreen/10 text-evergreen",
                  !isActive && !isDone && "border-ink/20 text-ink-soft",
                )}
              >
                {isDone ? <Check size={13} /> : index + 1}
              </span>
              {t(step.labelKey)}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function StepPanel({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <PanelSurface padding="lg" className="space-y-5">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        <p className="max-w-3xl text-body leading-5 text-ink-soft">{description}</p>
      </div>
      {children}
    </PanelSurface>
  );
}

function StepFooter({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center justify-end gap-2 border-t border-ink/10 pt-4">{children}</div>;
}

interface AppSummaryLike {
  app_key: string;
  name: string;
  description?: string;
  owners?: string[];
}

function BasicsStep({
  app,
  appKey,
  onContinue,
  onAutoOnboarded,
}: {
  app?: AppSummaryLike;
  appKey: string;
  onContinue: (appKey: string) => void;
  onAutoOnboarded: (appKey: string) => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [appKeyInput, setAppKeyInput] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [ownerUserIds, setOwnerUserIds] = useState<string[]>([]);
  const [developerUserIds, setDeveloperUserIds] = useState<string[]>([]);
  const createMutation = useMutation({
    mutationFn: (payload: JsonObject) =>
      apiRequest<AppListPayload>("/console/api/v1/apps", { method: "POST", body: payload }),
    onSuccess: (payload) => {
      void queryClient.invalidateQueries({ queryKey: ["console", "apps"] });
      const createdKey = payload.app?.app_key;
      if (createdKey) {
        onContinue(createdKey);
      }
    },
  });

  if (appKey) {
    return (
      <StepPanel title={t("wizard.basics.title")} description={t("wizard.basics.description")}>
        <StatusBanner tone="evergreen" title={t("wizard.basics.existing.title")} message={t("wizard.basics.existing.description")} />
        <dl className="grid gap-x-8 gap-y-3 text-body sm:grid-cols-2">
          <SummaryItem label="app_key" value={<code>{app?.app_key ?? appKey}</code>} />
          <SummaryItem label={t("common.name")} value={app?.name ?? "-"} />
          <SummaryItem label={t("common.description")} value={app?.description || "-"} />
          <SummaryItem label={t("appList.column.owners")} value={(app?.owners ?? []).join(", ") || "-"} />
        </dl>
        <StepFooter>
          <Button variant="primary" onClick={() => onContinue(appKey)}>
            {t("common.next")}
          </Button>
        </StepFooter>
      </StepPanel>
    );
  }

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    createMutation.mutate({
      app_key: appKeyInput.trim(),
      name: name.trim(),
      description: description.trim(),
      is_active: true,
      owner_user_ids: ownerUserIds,
      developer_user_ids: developerUserIds,
    });
  };

  return (
    <StepPanel title={t("wizard.basics.title")} description={t("wizard.basics.description")}>
      <AutoOnboardPanel onAutoOnboarded={onAutoOnboarded} />
      <div className="space-y-1 border-t border-ink/10 pt-4">
        <h3 className="text-sm font-semibold text-ink">{t("wizard.auto.manualTitle")}</h3>
      </div>
      <form className="grid max-w-2xl gap-4" onSubmit={submit}>
        <Field label="app_key" hint={t("wizard.basics.appKeyHint")}>
          <AppKeyInput value={appKeyInput} onChange={setAppKeyInput} onGenerate={() => setAppKeyInput(generateAppKey(name))} required />
        </Field>
        <Field label={t("appList.createDialog.name")}>
          <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} required />
        </Field>
        <Field label={t("appList.createDialog.description")}>
          <TextArea rows={3} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        <Field label={t("appList.createDialog.ownerIds")} hint={t("appList.createDialog.userIdsHint")}>
          <UserMultiSelect value={ownerUserIds} onChange={setOwnerUserIds} />
        </Field>
        <Field label={t("appList.createDialog.developerIds")} hint={t("appList.createDialog.userIdsHint")}>
          <UserMultiSelect value={developerUserIds} onChange={setDeveloperUserIds} />
        </Field>
        {createMutation.error ? (
          <StatusBanner tone="signal" title={t("wizard.basics.createFailed")} message={(createMutation.error as Error).message} />
        ) : null}
        <StepFooter>
          <Button type="submit" variant="primary" icon={<Plus size={16} />} loading={createMutation.isPending} disabled={createMutation.isPending}>
            {t("wizard.basics.createAndContinue")}
          </Button>
        </StepFooter>
      </form>
    </StepPanel>
  );
}

interface AutoOnboardingResult {
  app_key: string;
  app_name: string;
  created: boolean;
  already_up_to_date: boolean;
  template_version: number;
  catalog_version: number | string;
}

function AutoOnboardPanel({ onAutoOnboarded }: { onAutoOnboarded: (appKey: string) => void }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [baseUrl, setBaseUrl] = useState("");
  const [appKey, setAppKey] = useState("");
  const [descriptorToken, setDescriptorToken] = useState("");
  const [result, setResult] = useState<AutoOnboardingResult | null>(null);
  const onboardMutation = useMutation({
    mutationFn: () =>
      apiRequest<AutoOnboardingResult>("/console/api/v1/apps/auto-onboarding", {
        method: "POST",
        body: {
          base_url: baseUrl.trim(),
          app_key: appKey.trim(),
          ...(descriptorToken.trim() ? { descriptor_token: descriptorToken.trim() } : {}),
        },
      }),
    onSuccess: (payload) => {
      setResult(payload);
      void queryClient.invalidateQueries({ queryKey: ["console", "apps"] });
      void queryClient.invalidateQueries({ queryKey: ["console", "app", payload.app_key] });
    },
  });

  return (
    <section className="space-y-4 rounded-[3px] border border-accent/25 bg-accent/4 p-4">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-ink">{t("wizard.auto.title")}</h3>
        <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("wizard.auto.description")}</p>
      </div>
      <div className="grid max-w-3xl items-end gap-4 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
        <Field label={t("wizard.auto.baseUrl")}>
          <TextInput
            value={baseUrl}
            placeholder="https://downstream.example.com"
            onChange={(event) => setBaseUrl(event.currentTarget.value)}
          />
        </Field>
        <Field label={t("wizard.auto.appKey")}>
          <TextInput value={appKey} onChange={(event) => setAppKey(event.currentTarget.value)} />
        </Field>
        <Field label={t("wizard.auto.token")}>
          <TextInput
            type="password"
            autoComplete="off"
            value={descriptorToken}
            onChange={(event) => setDescriptorToken(event.currentTarget.value)}
          />
        </Field>
        <Button
          variant="primary"
          icon={<Compass size={16} />}
          disabled={!baseUrl.trim() || !appKey.trim() || onboardMutation.isPending}
          loading={onboardMutation.isPending}
          onClick={() => onboardMutation.mutate()}
        >
          {t("wizard.auto.run")}
        </Button>
      </div>
      {onboardMutation.error ? (
        <StatusBanner tone="signal" title={t("wizard.auto.failed")} message={(onboardMutation.error as Error).message} />
      ) : null}
      {result ? (
        <div className="space-y-3">
          <StatusBanner
            tone="evergreen"
            title={t("wizard.auto.success")}
            message={
              result.already_up_to_date
                ? t("wizard.auto.upToDate", { appKey: result.app_key, version: result.template_version })
                : t("wizard.auto.successDetail", {
                    appKey: result.app_key,
                    version: result.template_version,
                    catalogVersion: String(result.catalog_version),
                  })
            }
          />
          <Button variant="primary" onClick={() => onAutoOnboarded(result.app_key)}>
            {t("wizard.auto.continue")}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

type ManifestPreviewPayload = {
  diff?: {
    added?: ManifestDiffItem[];
    changed?: ManifestDiffItem[];
    removed?: ManifestDiffItem[];
  };
  changes?: Array<{ action?: string; key?: string; parent_key?: string }>;
  preview_id?: string;
};

type ManifestDiffItem = {
  type?: string;
  key?: string;
  name?: string;
  before?: unknown;
  after?: unknown;
};

function CatalogStep({ appKey, onBack, onContinue }: { appKey: string; onBack: () => void; onContinue: () => void }) {
  const { t } = useI18n();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState<ManifestPreviewPayload | null>(null);
  const [importedCatalogVersion, setImportedCatalogVersion] = useState<string | null>(null);
  const previewMutation = useMutation({
    mutationFn: () =>
      apiRequest<ManifestPreviewPayload>(`/console/api/v1/apps/${appKey}/permission-template-imports/preview`, {
        method: "POST",
        body: { template_format: detectTemplateFormat(content), template: content },
      }),
    onSuccess: (payload) => setPreview(payload),
  });
  const importMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ catalog_version?: string | number; template_version?: string | number }>(
        `/console/api/v1/apps/${appKey}/permission-template-imports/${preview?.preview_id ?? ""}/confirm`,
        { method: "POST" },
      ),
    onSuccess: (payload) => {
      setImportedCatalogVersion(String(payload.catalog_version ?? payload.template_version ?? ""));
      setPreview(null);
    },
  });

  return (
    <StepPanel title={t("wizard.catalog.title")} description={t("wizard.catalog.description")}>
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={fileInputRef}
          type="file"
          accept=".json,.yaml,.yml,application/json,text/yaml,text/plain"
          className="sr-only"
          aria-label={t("wizard.catalog.uploadAria")}
          onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            if (!file) {
              return;
            }
            void file.text().then(setContent);
          }}
        />
        <Button icon={<FileUp size={16} />} onClick={() => fileInputRef.current?.click()}>
          {t("wizard.catalog.uploadFile")}
        </Button>
      </div>
      <Field label={t("wizard.catalog.content")} hint={t("wizard.catalog.contentHint")}>
        <TextArea
          aria-label={t("wizard.catalog.content")}
          rows={10}
          value={content}
          onChange={(event) => setContent(event.currentTarget.value)}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          icon={<Eye size={16} />}
          disabled={!content || previewMutation.isPending}
          loading={previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
        >
          {t("wizard.catalog.preview")}
        </Button>
        <Button
          variant="primary"
          icon={<UploadCloud size={16} />}
          disabled={!preview?.preview_id || importMutation.isPending}
          loading={importMutation.isPending}
          onClick={() => importMutation.mutate()}
        >
          {t("wizard.catalog.confirm")}
        </Button>
      </div>
      {previewMutation.error ? (
        <StatusBanner tone="signal" title={t("wizard.catalog.previewFailed")} message={(previewMutation.error as Error).message} />
      ) : null}
      {importMutation.error ? (
        <StatusBanner tone="signal" title={t("wizard.catalog.importFailed")} message={(importMutation.error as Error).message} />
      ) : null}
      {importedCatalogVersion ? (
        <StatusBanner
          tone="evergreen"
          title={t("wizard.catalog.importSuccess")}
          message={t("wizard.catalog.currentCatalogVersion", { version: importedCatalogVersion })}
        />
      ) : null}
      {preview ? <ManifestDiffSummary preview={preview} /> : null}
      <p className="text-body text-ink-soft">{t("wizard.catalog.skipHint")}</p>
      <StepFooter>
        <Button onClick={onBack}>{t("common.back")}</Button>
        <Button onClick={onContinue}>{t("common.skip")}</Button>
        <Button variant="primary" disabled={!importedCatalogVersion} onClick={onContinue}>
          {t("common.next")}
        </Button>
      </StepFooter>
    </StepPanel>
  );
}

function ManifestDiffSummary({ preview }: { preview: ManifestPreviewPayload }) {
  const { t } = useI18n();
  const diff = preview.diff ?? diffFromChanges(preview.changes ?? []);
  const sections = [
    { titleKey: "wizard.catalog.diff.added" as MessageKey, tone: "evergreen" as const, items: diff.added ?? [] },
    { titleKey: "wizard.catalog.diff.changed" as MessageKey, tone: "amber" as const, items: diff.changed ?? [] },
    { titleKey: "wizard.catalog.diff.removed" as MessageKey, tone: "signal" as const, items: diff.removed ?? [] },
  ];

  return (
    <div className="space-y-3">
      {sections.map((section) => (
        <div key={section.titleKey} className="rounded-[3px] border border-ink/10 bg-paper-soft p-3">
          <div className="mb-2 flex items-center gap-2">
            <Badge tone={section.tone}>{t(section.titleKey)}</Badge>
            <span className="text-body text-ink-soft">{section.items.length}</span>
          </div>
          {section.items.length > 0 ? (
            <ul className="grid gap-1 text-body text-ink-soft sm:grid-cols-2">
              {section.items.map((item, index) => (
                <li key={`${item.type ?? "item"}:${item.key ?? index}`}>
                  <code className="text-xs">{`${item.type ?? "-"}:${item.key ?? "-"}`}</code>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-body text-ink-soft">{t("wizard.catalog.diff.empty")}</p>
          )}
        </div>
      ))}
    </div>
  );
}

function AuthzStep({ appKey, onBack, onContinue }: { appKey: string; onBack: () => void; onContinue: () => void }) {
  const { t } = useI18n();
  const statusQuery = useQuery({
    queryKey: ["console", "app", appKey, "configuration-status"],
    queryFn: () => apiRequest<ConfigurationStatus>(`/console/api/v1/apps/${appKey}/configuration-status`),
    enabled: Boolean(appKey),
  });
  const issues = statusQuery.data?.items ?? [];
  const blockingCount = issues.filter((issue) => (issue.severity ?? issue.level) === "blocking").length;

  return (
    <StepPanel title={t("wizard.authz.title")} description={t("wizard.authz.description")}>
      {statusQuery.error ? (
        <StatusBanner tone="signal" title={t("wizard.authz.statusLoadFailed")} message={(statusQuery.error as Error).message} />
      ) : null}
      {statusQuery.data ? (
        issues.length === 0 ? (
          <StatusBanner tone="evergreen" title={t("wizard.authz.ready")} />
        ) : (
          <StatusBanner
            tone={blockingCount > 0 ? "signal" : "amber"}
            title={t("wizard.authz.issuesFound", { count: issues.length })}
          />
        )
      ) : null}
      {issues.length > 0 ? (
        <div className="overflow-x-auto rounded-[3px] border border-ink/10">
          <table className="w-full text-body">
            <thead className="bg-paper-soft text-left text-label uppercase tracking-caps-wide text-ink-soft">
              <tr>
                <th className="px-3 py-2">{t("wizard.authz.issue.column.severity")}</th>
                <th className="px-3 py-2">{t("wizard.authz.issue.column.message")}</th>
                <th className="px-3 py-2">{t("wizard.authz.issue.column.subject")}</th>
              </tr>
            </thead>
            <tbody>
              {issues.map((issue, index) => (
                <tr key={`${issue.code ?? "issue"}:${issue.subject ?? index}`} className="border-t border-ink/8">
                  <td className="px-3 py-2">
                    <Badge tone={(issue.severity ?? issue.level) === "blocking" ? "signal" : "amber"}>
                      {(issue.severity ?? issue.level) === "blocking" ? t("wizard.authz.severity.blocking") : t("wizard.authz.severity.warning")}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-ink">{issue.message ?? issue.code ?? "-"}</td>
                  <td className="px-3 py-2">
                    <code className="text-xs">{issue.subject || "-"}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <ButtonLink to={`/console/apps/${appKey}?tab=matrix`}>{t("wizard.authz.goMatrix")}</ButtonLink>
        <ButtonLink to={`/console/apps/${appKey}?tab=rules`}>{t("wizard.authz.goRules")}</ButtonLink>
        <ButtonLink to={`/console/apps/${appKey}?tab=catalog`}>{t("wizard.authz.goCatalog")}</ButtonLink>
        <Button icon={<RefreshCcw size={16} />} loading={statusQuery.isFetching} onClick={() => void statusQuery.refetch()}>
          {t("wizard.authz.recheck")}
        </Button>
      </div>
      <StepFooter>
        <Button onClick={onBack}>{t("common.back")}</Button>
        <Button variant="primary" onClick={onContinue}>
          {t("common.next")}
        </Button>
      </StepFooter>
    </StepPanel>
  );
}

function CredentialStep({
  appKey,
  activeCredentialCount,
  onBack,
  onContinue,
}: {
  appKey: string;
  activeCredentialCount: number;
  onBack: () => void;
  onContinue: () => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<SecretPayload | null>(null);
  const createMutation = useMutation({
    mutationFn: (kind: "static-tokens" | "oauth-clients") =>
      apiRequest<SecretPayload>(`/console/api/v1/apps/${appKey}/credentials/${kind}`, {
        method: "POST",
        body: { name },
      }),
    onSuccess: (payload) => {
      setSecret(payload);
      setName("");
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey] });
    },
  });
  const secretEntries = Object.entries(secret?.one_time_secret ?? {}).filter(([key]) => key !== "kind");

  return (
    <StepPanel title={t("wizard.credential.title")} description={t("wizard.credential.description")}>
      {activeCredentialCount > 0 ? (
        <StatusBanner tone="neutral" title={t("wizard.credential.existingCount", { count: activeCredentialCount })} />
      ) : null}
      <div className="grid max-w-3xl items-end gap-4 md:grid-cols-[minmax(0,1fr)_auto_auto]">
        <Field label={t("wizard.credential.name")}>
          <TextInput
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            placeholder={t("wizard.credential.namePlaceholder")}
          />
        </Field>
        <Button
          variant="primary"
          icon={<Plus size={16} />}
          disabled={!name || createMutation.isPending}
          onClick={() => createMutation.mutate("static-tokens")}
        >
          {t("wizard.credential.createStaticToken")}
        </Button>
        <Button icon={<KeyRound size={16} />} disabled={!name || createMutation.isPending} onClick={() => createMutation.mutate("oauth-clients")}>
          {t("wizard.credential.createOauthClient")}
        </Button>
      </div>
      {createMutation.error ? (
        <StatusBanner tone="signal" title={t("wizard.credential.createFailed")} message={(createMutation.error as Error).message} />
      ) : null}
      {secretEntries.length > 0 ? (
        <div className="space-y-3 rounded-[3px] border border-amber/30 bg-amber/8 p-4">
          <p className="text-sm font-semibold text-ink">{t("wizard.credential.secretTitle")}</p>
          <p className="text-body text-ink-soft">{t("wizard.credential.secretWarning")}</p>
          {secretEntries.map(([key, value]) => (
            <CodeBlock key={key} language={key} code={value} />
          ))}
        </div>
      ) : null}
      <p className="text-body text-ink-soft">{t("wizard.credential.skipHint")}</p>
      <StepFooter>
        <Button onClick={onBack}>{t("common.back")}</Button>
        <Button onClick={onContinue}>{t("common.skip")}</Button>
        <Button variant="primary" disabled={secretEntries.length === 0 && activeCredentialCount === 0} onClick={onContinue}>
          {t("common.next")}
        </Button>
      </StepFooter>
    </StepPanel>
  );
}

function VerifyStep({ appKey, onBack, onContinue }: { appKey: string; onBack: () => void; onContinue: () => void }) {
  const { t } = useI18n();
  const [userId, setUserId] = useState("");
  const [token, setToken] = useState("");
  const [result, setResult] = useState<QueryTestResult | null>(null);
  const testMutation = useMutation({
    mutationFn: () =>
      apiRequest<QueryTestResult>(`/console/api/v1/apps/${appKey}/permission-query-tests`, {
        method: "POST",
        body: { user_id: userId, token },
      }),
    onSuccess: (payload) => {
      setResult(payload);
      setToken("");
    },
  });

  return (
    <StepPanel title={t("wizard.verify.title")} description={t("wizard.verify.description")}>
      <div className="grid max-w-3xl items-end gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <Field label={t("wizard.verify.userId")} labelExtra={<InfoTip text={t("wizard.verify.userIdHint")} />}>
          <UserSearchInput value={userId} onChange={setUserId} />
        </Field>
        <Field label={t("wizard.verify.token")}>
          <TextInput type="password" value={token} onChange={(event) => setToken(event.currentTarget.value)} autoComplete="off" />
        </Field>
        <Button
          variant="primary"
          icon={<Play size={16} />}
          disabled={!userId || !token || testMutation.isPending}
          loading={testMutation.isPending}
          onClick={() => testMutation.mutate()}
        >
          {t("wizard.verify.run")}
        </Button>
      </div>
      {testMutation.error ? (
        <StatusBanner tone="signal" title={t("wizard.verify.failed")} message={(testMutation.error as Error).message} />
      ) : null}
      {result ? (
        <>
          <StatusBanner
            tone={result.allowed ? "evergreen" : "neutral"}
            title={result.allowed ? t("wizard.verify.hit") : t("wizard.verify.noHit")}
            message={`${t("wizard.verify.groupsCount", { count: result.groups?.length ?? 0 })} · ${t("wizard.verify.grantsCount", {
              count: result.grants?.length ?? 0,
            })} · ${t("wizard.verify.snapshotVersion")}: ${result.snapshot_version ?? "-"}`}
          />
          <CodeBlock language="json" code={JSON.stringify(result, null, 2)} />
        </>
      ) : null}
      <p className="text-body text-ink-soft">{t("wizard.verify.skipHint")}</p>
      <StepFooter>
        <Button onClick={onBack}>{t("common.back")}</Button>
        <Button onClick={onContinue}>{t("common.skip")}</Button>
        <Button variant="primary" disabled={!result} onClick={onContinue}>
          {t("common.next")}
        </Button>
      </StepFooter>
    </StepPanel>
  );
}

function DoneStep({ appKey, appName }: { appKey: string; appName: string }) {
  const { t } = useI18n();
  const statusQuery = useQuery({
    queryKey: ["console", "app", appKey, "configuration-status"],
    queryFn: () => apiRequest<ConfigurationStatus>(`/console/api/v1/apps/${appKey}/configuration-status`),
    enabled: Boolean(appKey),
  });
  const issues = statusQuery.data?.items ?? [];
  const origin = window.location.origin;
  const endpoint = `${origin}/api/v1/apps/${appKey}/users/{user_id}/permissions`;
  const integrationSnippet = [
    `# ${appName}`,
    `EASYAUTH_BASE_URL=${origin}`,
    `EASYAUTH_APP_KEY=${appKey}`,
    "",
    `GET ${endpoint}`,
    "Authorization: Bearer <app_token>",
  ].join("\n");
  const curlSnippet = `curl -H "Authorization: Bearer $APP_TOKEN" "${endpoint}"`;

  if (!appKey) {
    return (
      <StepPanel title={t("wizard.done.title")} description={t("wizard.error.appMissing")}>
        <StepFooter>
          <ButtonLink variant="primary" to="/console/apps/new">
            {t("wizard.error.restart")}
          </ButtonLink>
        </StepFooter>
      </StepPanel>
    );
  }

  return (
    <StepPanel title={t("wizard.done.title")} description={t("wizard.done.description")}>
      {statusQuery.data ? (
        issues.length === 0 ? (
          <StatusBanner tone="evergreen" title={t("wizard.done.configReady")} />
        ) : (
          <StatusBanner tone="amber" title={t("wizard.done.configIssues", { count: issues.length })} />
        )
      ) : null}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-ink">{t("wizard.done.integrationTitle")}</h3>
        <CodeBlock language="env" code={integrationSnippet} />
        <CodeBlock language="curl" code={curlSnippet} />
        <p className="text-body text-ink-soft">{t("wizard.done.integrationHint")}</p>
      </div>
      <StepFooter>
        <ButtonLink to={`/console/apps/${appKey}?tab=guide`}>{t("wizard.done.guideLink")}</ButtonLink>
        <ButtonLink variant="primary" icon={<Compass size={16} />} to={`/console/apps/${appKey}`}>
          {t("wizard.openWorkspace")}
        </ButtonLink>
      </StepFooter>
    </StepPanel>
  );
}

function SummaryItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="space-y-1">
      <dt className="text-label font-medium uppercase tracking-caps-wide text-ink-soft">{label}</dt>
      <dd className="text-sm text-ink">{value}</dd>
    </div>
  );
}

function detectTemplateFormat(content: string): "json" | "yaml" {
  return content.trimStart().startsWith("{") ? "json" : "yaml";
}

function diffFromChanges(changes: Array<{ action?: string; key?: string; parent_key?: string }>): NonNullable<ManifestPreviewPayload["diff"]> {
  return {
    added: changes.filter((change) => change.action?.startsWith("create")).map(changeItem),
    changed: changes.filter((change) => change.action?.startsWith("update")).map(changeItem),
    removed: changes.filter((change) => change.action?.startsWith("deactivate")).map(changeItem),
  };
}

function changeItem(change: { action?: string; key?: string; parent_key?: string }): ManifestDiffItem {
  return {
    type: change.action,
    key: change.key,
    name: change.parent_key,
  };
}

