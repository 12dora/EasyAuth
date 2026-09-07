import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";

import { Button } from "../../components/Button";
import { Field } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { UserSearchInput } from "../../components/UserSelect";
import { userOptionDisplayName } from "../../components/UserCombobox";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { useToast } from "../../components/ui/Toast";
import {
  EMPTY_GRANT_DRAFT,
  GrantForm,
  buildGrantSubmission,
  grantDraftIsValid,
  useGrantCatalog,
} from "../../features/grantForm";
import type { GrantDraft, GrantSubmission } from "../../features/grantForm";
import { useI18n } from "../../i18n/I18nProvider";
import { ApiError, apiRequest } from "../../lib/api";
import type { JsonValue } from "../../lib/api";
import { formatAppDisplayName } from "../../lib/appDisplayName";

interface DirectGrantRequest {
  payload: GrantSubmission & { user_id: string };
  granteeLabel: string;
  appLabel: string;
}

/** 管理员直接授权: 选被授权人 + 授权目标 + 有效期, 提交后立即生效, 不走审批。 */
export function DirectGrantPage() {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const catalogQuery = useGrantCatalog();
  const [userId, setUserId] = useState("");
  const [granteeLabel, setGranteeLabel] = useState("");
  const [draft, setDraft] = useState<GrantDraft>(EMPTY_GRANT_DRAFT);

  const grantMutation = useMutation<unknown, Error, DirectGrantRequest>({
    mutationFn: (request) =>
      apiRequest<unknown>("/console/api/v1/direct-grants", { method: "POST", body: request.payload }),
    onSuccess: (_data, request) => {
      toast.success(t("directGrant.succeeded", { name: request.granteeLabel, app: request.appLabel }));
      // 被授权人保持选中: 连续给同一个人授权是最常见的操作。
      setDraft(EMPTY_GRANT_DRAFT);
      void queryClient.invalidateQueries({ queryKey: ["console", "operations", "access-grants"] });
    },
  });

  const catalogErrorMessage = catalogQuery.error ? catalogQuery.error.message : "";
  const selectedApp = (catalogQuery.data?.apps ?? []).find((app) => app.app_key === draft.appKey);
  const canSubmit = Boolean(userId) && grantDraftIsValid(draft, catalogQuery.data);
  const submitErrorMessages = detailErrorMessages(grantMutation.error);

  const submit = () => {
    if (!selectedApp) {
      // canSubmit 已保证应用落在目录里, 走到这里说明接线出了问题, 直接失败而不是提交一份必被拒的载荷。
      throw new Error(`授权目标的应用不在目录中: ${draft.appKey}`);
    }
    grantMutation.mutate({
      payload: { user_id: userId, ...buildGrantSubmission(draft) },
      granteeLabel: granteeLabel || userId,
      appLabel: formatAppDisplayName(selectedApp),
    });
  };

  const reset = () => {
    setUserId("");
    setGranteeLabel("");
    setDraft(EMPTY_GRANT_DRAFT);
    grantMutation.reset();
  };

  return (
    <>
      <PageHeader
        eyebrow={t("directGrant.eyebrow")}
        title={t("directGrant.title")}
        description={t("directGrant.description")}
      />
      <PanelSurface>
        <GrantForm
          catalog={catalogQuery.data}
          catalogIsLoading={catalogQuery.isLoading}
          catalogErrorMessage={catalogErrorMessage}
          draft={draft}
          onDraftChange={setDraft}
          disabled={grantMutation.isPending}
          header={
            <Field label={t("directGrant.grantee")} hint={granteeLabel ? undefined : t("directGrant.granteeHint")}>
              <UserSearchInput
                value={userId}
                required
                placeholder={t("directGrant.granteePlaceholder")}
                onChange={(value) => {
                  setUserId(value);
                  // 手输 ID 没有可信姓名, 清掉上一次候选带来的展示名。
                  setGranteeLabel("");
                }}
                onSelectOption={(option) => setGranteeLabel(userOptionDisplayName(option))}
              />
            </Field>
          }
        />
        {granteeLabel ? (
          <p className="mt-2 text-xs leading-5 text-ink-faint">
            {t("directGrant.granteeSelected", { name: granteeLabel })}
          </p>
        ) : null}
        {catalogErrorMessage ? (
          <div className="mt-5">
            <StatusBanner
              live="alert"
              tone="signal"
              title={t("grantForm.catalogLoadFailed")}
              message={catalogErrorMessage}
            />
          </div>
        ) : null}
        <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
          <Button type="button" onClick={reset} disabled={grantMutation.isPending}>
            {t("directGrant.reset")}
          </Button>
          <Button
            type="button"
            variant="primary"
            icon={<ShieldCheck size={16} />}
            loading={grantMutation.isPending}
            disabled={!canSubmit || grantMutation.isPending}
            onClick={submit}
          >
            {t("directGrant.submit")}
          </Button>
        </div>
        {grantMutation.error ? (
          <div className="mt-5">
            <StatusBanner
              live="alert"
              tone="signal"
              title={t("directGrant.failed")}
              message={grantMutation.error.message}
            />
            {submitErrorMessages.length > 0 ? (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-5 text-signal">
                {submitErrorMessages.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </PanelSurface>
    </>
  );
}

/** 后端 422 语义校验把逐条中文原因放在 details.errors 里; 不是这个形状就不猜, 只展示主消息。 */
function detailErrorMessages(error: Error | null): string[] {
  if (!(error instanceof ApiError)) {
    return [];
  }
  const details: JsonValue | undefined = error.details;
  if (typeof details !== "object" || details === null || Array.isArray(details)) {
    return [];
  }
  const errors = details.errors;
  if (!Array.isArray(errors)) {
    return [];
  }
  return errors.filter((item): item is string => typeof item === "string");
}
