import { useMutation } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "../../../components/Button";
import { CodeBlock } from "../../../components/CodeBlock";
import { Field, TextInput } from "../../../components/Field";
import { InfoTip } from "../../../components/InfoTip";
import { StatusBanner } from "../../../components/StatusBanner";
import { UserSearchInput } from "../../../components/UserSelect";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest } from "../../../lib/api";
import type { QueryTestResult } from "../../../lib/domain";
import { StepFooter, StepPanel } from "./StepLayout";
import type { QueryTestRequest } from "./types";

export function VerifyStep({ appKey, onBack, onContinue }: { appKey: string; onBack: () => void; onContinue: () => void }) {
  const { t } = useI18n();
  const [userId, setUserId] = useState("");
  const [token, setToken] = useState("");
  const [result, setResult] = useState<QueryTestResult | null>(null);
  const requestIdRef = useRef(0);
  const testMutation = useMutation({
    mutationFn: (request: QueryTestRequest) =>
      apiRequest<QueryTestResult>(`/console/api/v1/apps/${appKey}/permission-query-tests`, {
        method: "POST",
        body: { user_id: request.userId, token: request.token },
      }),
    onSuccess: (payload, request) => {
      if (request.requestId !== requestIdRef.current) {
        return;
      }
      setResult(payload);
      setToken("");
    },
  });

  const invalidateResult = () => {
    requestIdRef.current += 1;
    setResult(null);
  };

  const runVerification = () => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setResult(null);
    testMutation.mutate({ userId, token, requestId });
  };

  const currentRequestError = testMutation.variables?.requestId === requestIdRef.current ? testMutation.error : null;

  return (
    <StepPanel title={t("wizard.verify.title")} description={t("wizard.verify.description")}>
      <div className="grid max-w-3xl items-end gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <Field label={t("wizard.verify.userId")} labelExtra={<InfoTip text={t("wizard.verify.userIdHint")} />}>
          <UserSearchInput
            value={userId}
            onChange={(value) => {
              setUserId(value);
              invalidateResult();
            }}
          />
        </Field>
        <Field label={t("wizard.verify.token")}>
          <TextInput
            type="password"
            value={token}
            onChange={(event) => {
              setToken(event.currentTarget.value);
              invalidateResult();
            }}
            autoComplete="off"
          />
        </Field>
        <Button
          variant="primary"
          icon={<Play size={16} />}
          disabled={!userId || !token || testMutation.isPending}
          loading={testMutation.isPending}
          onClick={runVerification}
        >
          {t("wizard.verify.run")}
        </Button>
      </div>
      {currentRequestError ? (
        <StatusBanner live="alert" tone="signal" title={t("wizard.verify.failed")} message={(currentRequestError as Error).message} />
      ) : null}
      {result ? <QueryTestOutcome result={result} /> : null}
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

function QueryTestOutcome({ result }: { result: QueryTestResult }) {
  const { t } = useI18n();

  return (
    <>
      <StatusBanner
        live="status"
        tone={result.allowed ? "evergreen" : "neutral"}
        title={result.allowed ? t("wizard.verify.hit") : t("wizard.verify.noHit")}
        message={`${t("wizard.verify.groupsCount", { count: result.groups?.length ?? 0 })} · ${t("wizard.verify.grantsCount", {
          count: result.grants?.length ?? 0,
        })} · ${t("wizard.verify.snapshotVersion")}: ${result.snapshot_version ?? "-"}`}
      />
      <CodeBlock language="json" code={JSON.stringify(result, null, 2)} />
    </>
  );
}
