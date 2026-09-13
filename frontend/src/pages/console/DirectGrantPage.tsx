import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "../../components/Button";
import { Field } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { UserSearchInput, userSearchFieldHint } from "../../components/UserSelect";
import { userOptionName } from "../../components/UserCombobox";
import type { UserOption } from "../../components/UserCombobox";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { useToast } from "../../components/ui/Toast";
import {
  DepartmentSourcedGrants,
  EMPTY_GRANT_DRAFT,
  GrantForm,
  buildGrantSubmission,
  departmentSourcedGroupKeys,
  departmentSourcedNoticeStatus,
  departmentSourcedPermissionKeys,
  grantCatalogApp,
  grantDraftErrors,
  grantDraftExcludingLockedKeys,
  grantDraftFromCurrentGrant,
  grantDraftIsValid,
  grantDraftWithoutGrantee,
  useCurrentGrant,
  useGrantCatalog,
} from "../../features/grantForm";
import type { GrantDraft, GrantSubmission } from "../../features/grantForm";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/messages";
import { ApiError, apiRequest } from "../../lib/api";
import type { JsonValue } from "../../lib/api";
import { formatAppDisplayName } from "../../lib/appDisplayName";
import { buildCatalogView } from "../portal/hooks/accessRequestCatalog";

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
  const [grantee, setGrantee] = useState<UserOption | null>(null);
  const [draft, setDraft] = useState<GrantDraft>(EMPTY_GRANT_DRAFT);
  const [draftErrorKeys, setDraftErrorKeys] = useState<MessageKey[]>([]);
  const currentGrantQuery = useCurrentGrant(userId, draft.appKey);
  /**
   * 已经结清回填的那一对"被授权人 + 应用"。
   *
   * 回填对每一对只做一次: 管理员在响应到达之前就动了表单, 这一对立即结清, 迟到的响应不能盖掉编辑。
   * 换人、换应用或清空之后这一对重新开张(见下面的效果), 否则再选回同一对时表单会一直空着。
   */
  const settledPairRef = useRef("");
  const lastPairRef = useRef("");
  const reportedErrorPairRef = useRef("");
  const grantPairKey = userId !== "" && draft.appKey !== "" ? `${userId}\u0000${draft.appKey}` : "";
  const currentGrant = currentGrantQuery.isSuccess ? (currentGrantQuery.data ?? null) : null;
  const lockedAuthorizationGroupKeys = currentGrant ? departmentSourcedGroupKeys(currentGrant) : [];
  const lockedPermissionKeys = currentGrant ? departmentSourcedPermissionKeys(currentGrant) : [];

  useEffect(() => {
    if (lastPairRef.current !== grantPairKey) {
      // 换了人、换了应用或清空重来: 上一对的结论作废, 这一对重新等待回填。
      lastPairRef.current = grantPairKey;
      settledPairRef.current = "";
    }
    if (grantPairKey === "" || settledPairRef.current === grantPairKey || !currentGrantQuery.isSuccess) {
      return;
    }
    settledPairRef.current = grantPairKey;
    const grant = currentGrantQuery.data;
    if (grant) {
      setDraft((current) => {
        const next = grantDraftFromCurrentGrant(grant, current);
        // 锁定组覆盖的直接权限也要从草稿里摘掉, 否则提交会把组织授权再抄一份。
        return grantDraftExcludingLockedKeys(
          next,
          departmentSourcedGroupKeys(grant),
          departmentSourcedPermissionKeys(grant),
          buildCatalogView(catalogQuery.data, next.appKey, ""),
        );
      });
    }
  }, [grantPairKey, currentGrantQuery.isSuccess, currentGrantQuery.data, catalogQuery.data]);

  useEffect(() => {
    // 读不到现状就把失败说出来, 让表单停在空白态: 静默留白会让管理员以为这个人还没有权限。
    if (grantPairKey === "" || !currentGrantQuery.error || reportedErrorPairRef.current === grantPairKey) {
      return;
    }
    reportedErrorPairRef.current = grantPairKey;
    toast.error(t("directGrant.currentGrantFailed"), currentGrantQuery.error.message);
  }, [grantPairKey, currentGrantQuery.error, toast, t]);

  const grantMutation = useMutation<unknown, Error, DirectGrantRequest>({
    mutationFn: (request) =>
      apiRequest<unknown>("/console/api/v1/direct-grants", { method: "POST", body: request.payload }),
    onSuccess: (_data, request) => {
      toast.success(t("directGrant.succeeded", { name: request.granteeLabel, app: request.appLabel }));
      setDraftErrorKeys([]);
      // 被授权人保持选中: 连续给同一个人授权是最常见的操作。
      setDraft(EMPTY_GRANT_DRAFT);
      // 现状已经被这次授权改写: 连缓存一起丢掉并允许重新回填, 否则再选回同一个应用会回填过期的现状。
      settledPairRef.current = "";
      lastPairRef.current = "";
      queryClient.removeQueries({ queryKey: ["console", "current-grant"] });
      void queryClient.invalidateQueries({ queryKey: ["console", "operations", "access-grants"] });
    },
  });

  const catalogErrorMessage = catalogQuery.error ? catalogQuery.error.message : "";
  const canSubmit = Boolean(userId) && grantDraftIsValid(draft, catalogQuery.data);
  const submitErrorMessages = detailErrorMessages(grantMutation.error);

  const submit = () => {
    // 渲染时算出来的闸门会过期: 用户填完未来的到期时间后可以一直等到它走进过去, 那时按钮还亮着。
    // 这里重算一次, 拦下来就把原因显示出来, 而不是让 buildGrantSubmission 同步抛错却什么都不显示。
    const errors = grantDraftErrors(draft, catalogQuery.data);
    if (errors.length > 0) {
      setDraftErrorKeys(errors.map((error) => error.messageKey));
      return;
    }
    setDraftErrorKeys([]);
    grantMutation.mutate({
      payload: { user_id: userId, ...buildGrantSubmission(draft) },
      granteeLabel: userOptionName(grantee ?? undefined, userId),
      appLabel: formatAppDisplayName(grantCatalogApp(catalogQuery.data, draft.appKey)),
    });
  };

  const changeGrantee = (nextUserId: string, nextOption: UserOption | null) => {
    setUserId(nextUserId);
    setGrantee(nextOption);
    // 目标与期限描述的是上一个人的现状, 换人后一条都不成立。
    setDraft(grantDraftWithoutGrantee(draft));
    setDraftErrorKeys([]);
  };

  const reset = () => {
    setUserId("");
    setGrantee(null);
    setDraft(EMPTY_GRANT_DRAFT);
    setDraftErrorKeys([]);
    settledPairRef.current = "";
    lastPairRef.current = "";
    reportedErrorPairRef.current = "";
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
          onDraftChange={(next) => {
            // 应用没变 => 这一次是管理员自己的编辑(目标、期限或说明): 这一对"人 + 应用"就此结清,
            // 免得还在路上的现状响应回来把编辑抹掉。换应用会带出新的一对, 那一对照常回填。
            if (next.appKey === draft.appKey) {
              settledPairRef.current = grantPairKey;
            }
            setDraft(next);
            setDraftErrorKeys([]);
          }}
          disabled={grantMutation.isPending}
          lockedAuthorizationGroupKeys={lockedAuthorizationGroupKeys}
          lockedPermissionKeys={lockedPermissionKeys}
          lockedHint={t("selector.scope.lockedByOrganizationAdmin")}
          header={
            <div>
              <Field
                label={t("directGrant.grantee")}
                hint={userSearchFieldHint(grantee, t, t("userSelect.searchHint"))}
              >
                <UserSearchInput
                  value={userId}
                  required
                  placeholder={t("directGrant.granteePlaceholder")}
                  selectedOption={grantee}
                  // 手输 ID 没有可信姓名, 清掉上一次候选带来的展示名。
                  onChange={(value) => changeGrantee(value, null)}
                  onSelectOption={(option) => changeGrantee(option.user_id, option)}
                  onResolvedOptionChange={(option) => {
                    if (option) {
                      setGrantee(option);
                    }
                  }}
                />
              </Field>
              <DepartmentSourcedGrants
                identityKey={userId}
                grant={currentGrant}
                status={departmentSourcedNoticeStatus(Boolean(userId && draft.appKey), currentGrantQuery)}
                isFetching={currentGrantQuery.isFetching}
                title={t("directGrant.departmentSourced")}
                hint={t("directGrant.departmentSourcedHint")}
                loadingLabel={t("directGrant.currentGrantLoading")}
              />
            </div>
          }
        />
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
        {draftErrorKeys.length > 0 ? (
          <div className="mt-5">
            <StatusBanner live="alert" tone="signal" title={t("grantForm.invalidDraft")} />
            <ErrorList messages={draftErrorKeys.map((key) => t(key))} />
          </div>
        ) : null}
        {grantMutation.error ? (
          <div className="mt-5">
            <StatusBanner
              live="alert"
              tone="signal"
              title={t("directGrant.failed")}
              message={grantMutation.error.message}
            />
            <ErrorList messages={submitErrorMessages} />
          </div>
        ) : null}
      </PanelSurface>
    </>
  );
}

function ErrorList({ messages }: { messages: string[] }) {
  if (messages.length === 0) {
    return null;
  }
  return (
    <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-5 text-signal">
      {messages.map((message) => (
        <li key={message}>{message}</li>
      ))}
    </ul>
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
