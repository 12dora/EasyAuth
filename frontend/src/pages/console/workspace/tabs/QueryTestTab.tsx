import { Play } from "lucide-react";

import { Button } from "../../../../components/Button";
import { Field, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import { QueryTestResultView } from "../queryTest/QueryTestResultView";
import { useQueryTest } from "../queryTest/useQueryTest";

export function QueryTestTab({ appKey }: { appKey: string }) {
  const { t } = useI18n();
  const { userId, setUserId, token, setToken, result, testMutation, submit } = useQueryTest(appKey);

  return (
    <section className="space-y-6">
      <PanelSurface padding="lg" className="grid items-end gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <Field label={t("wizard.verify.userId")}>
          <TextInput value={userId} onChange={(event) => setUserId(event.currentTarget.value)} />
        </Field>
        <Field label="Bearer token">
          <TextInput type="password" value={token} onChange={(event) => setToken(event.currentTarget.value)} autoComplete="off" />
        </Field>
        <Button variant="primary" icon={<Play size={16} />} disabled={!userId || !token || testMutation.isPending} onClick={submit}>
          {t("wizard.verify.run")}
        </Button>
      </PanelSurface>
      {testMutation.error ? <StatusBanner live="alert" tone="signal" title={t("wizard.verify.failed")} message={testMutation.error.message} /> : null}
      {result ? <QueryTestResultView result={result} /> : null}
    </section>
  );
}
