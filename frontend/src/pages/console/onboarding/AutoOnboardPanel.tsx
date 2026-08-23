import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Compass } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "../../../components/Button";
import { Field, TextInput } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest } from "../../../lib/api";
import type { AutoOnboardingRequest, AutoOnboardingResult } from "./types";

export function AutoOnboardPanel({ onAutoOnboarded }: { onAutoOnboarded: (appKey: string) => void }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [baseUrl, setBaseUrl] = useState("");
  const [appKey, setAppKey] = useState("");
  const [descriptorToken, setDescriptorToken] = useState("");
  const [result, setResult] = useState<AutoOnboardingResult | null>(null);
  const requestIdRef = useRef(0);
  const onboardMutation = useMutation({
    mutationFn: (request: AutoOnboardingRequest) =>
      apiRequest<AutoOnboardingResult>("/console/api/v1/apps/auto-onboarding", {
        method: "POST",
        body: {
          base_url: request.baseUrl,
          app_key: request.appKey,
          ...(request.descriptorToken ? { descriptor_token: request.descriptorToken } : {}),
        },
      }),
    onSuccess: (payload, request) => {
      if (request.requestId !== requestIdRef.current) {
        return;
      }
      setResult(payload);
      setDescriptorToken("");
      void queryClient.invalidateQueries({ queryKey: ["console", "apps"] });
      void queryClient.invalidateQueries({ queryKey: ["console", "app", payload.app_key] });
    },
  });

  const invalidateResult = () => {
    requestIdRef.current += 1;
    setResult(null);
  };

  const runAutoOnboarding = () => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setResult(null);
    onboardMutation.mutate({
      baseUrl: baseUrl.trim(),
      appKey: appKey.trim(),
      descriptorToken: descriptorToken.trim(),
      requestId,
    });
  };

  const currentRequestError = onboardMutation.variables?.requestId === requestIdRef.current ? onboardMutation.error : null;

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
            onChange={(event) => {
              setBaseUrl(event.currentTarget.value);
              setDescriptorToken("");
              invalidateResult();
            }}
          />
        </Field>
        <Field label={t("wizard.auto.appKey")}>
          <TextInput
            value={appKey}
            onChange={(event) => {
              setAppKey(event.currentTarget.value);
              invalidateResult();
            }}
          />
        </Field>
        <Field label={t("wizard.auto.token")}>
          <TextInput
            type="password"
            autoComplete="off"
            value={descriptorToken}
            onChange={(event) => {
              setDescriptorToken(event.currentTarget.value);
              invalidateResult();
            }}
          />
        </Field>
        <Button
          variant="primary"
          icon={<Compass size={16} />}
          disabled={!baseUrl.trim() || !appKey.trim() || onboardMutation.isPending}
          loading={onboardMutation.isPending}
          onClick={runAutoOnboarding}
        >
          {t("wizard.auto.run")}
        </Button>
      </div>
      {currentRequestError ? (
        <StatusBanner live="alert" tone="signal" title={t("wizard.auto.failed")} message={(currentRequestError as Error).message} />
      ) : null}
      {result ? (
        <div className="space-y-3">
          <StatusBanner
            live="status"
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
