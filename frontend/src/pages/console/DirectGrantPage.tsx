import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "../../components/Button";
import { Field } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { UserSearchInput } from "../../components/UserSelect";
import { userOptionName } from "../../components/UserCombobox";
import type { UserOption } from "../../components/UserCombobox";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { useToast } from "../../components/ui/Toast";
import {
  EMPTY_GRANT_DRAFT,
  GrantForm,
  buildGrantSubmission,
  grantCatalogApp,
  grantDraftErrors,
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
import type { AccessGrantRow } from "../../lib/domain/accessGrantRow";

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
  // 现有权限每个"被授权人 + 应用"只回填一次: 迟到的响应不能盖掉管理员回填之后的编辑。
  const prefilledPairRef = useRef("");
  const reportedErrorPairRef = useRef("");
  const grantPairKey = userId !== "" && draft.appKey !== "" ? `${userId}\u0000${draft.appKey}` : "";
  const currentGrant = currentGrantQuery.data ?? null;

  useEffect(() => {
    if (grantPairKey === "" || prefilledPairRef.current === grantPairKey || !currentGrantQuery.isSuccess) {
      return;
    }
    prefilledPairRef.current = grantPairKey;
    const grant = currentGrantQuery.data;
    if (grant) {
      setDraft((current) => grantDraftFromCurrentGrant(grant, current));
    }
  }, [grantPairKey, currentGrantQuery.isSuccess, currentGrantQuery.data]);

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
            // 管理员在回填到达之前就动了目标: 这一对"人 + 应用"不再回填, 免得响应回来把编辑抹掉。
            if (next.appKey === draft.appKey && targetWasEdited(draft, next)) {
              prefilledPairRef.current = grantPairKey;
            }
            setDraft(next);
            setDraftErrorKeys([]);
          }}
          disabled={grantMutation.isPending}
          header={
            <>
              <Field label={t("directGrant.grantee")} hint={grantee ? undefined : t("directGrant.granteeHint")}>
                <UserSearchInput
                  value={userId}
                  required
                  placeholder={t("directGrant.granteePlaceholder")}
                  selectedOption={grantee}
                  // 手输 ID 没有可信姓名, 清掉上一次候选带来的展示名。
                  onChange={(value) => changeGrantee(value, null)}
                  onSelectOption={(option) => changeGrantee(option.user_id, option)}
                />
              </Field>
              {currentGrantQuery.isFetching ? (
                <p className="text-xs leading-5 text-ink-faint">{t("directGrant.currentGrantLoading")}</p>
              ) : null}
              <DepartmentSourcedGrants grant={currentGrant} />
            </>
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

/**
 * 组织授权下发的成员关系, 只读展示。
 *
 * 这部分由部门策略维护, 在这一页改不了: 直接授权提交时只替换本人来源的成员关系。
 * 不展示的话管理员会以为这个人没有这些权限, 于是重复授一遍。
 */
function DepartmentSourcedGrants({ grant }: { grant: AccessGrantRow | null }) {
  const { t } = useI18n();
  const groups = (grant?.authorization_groups ?? []).filter((group) => group.source === "department");
  const permissions = (grant?.direct_grants ?? []).filter((permission) => permission.source === "department");
  if (groups.length === 0 && permissions.length === 0) {
    return null;
  }
  return (
    <section className="rounded-[3px] border border-ink/12 bg-paper-soft px-3 py-2.5">
      <h3 className="text-xs font-semibold text-ink">{t("directGrant.departmentSourced")}</h3>
      <p className="mt-1 text-xs leading-5 text-ink-faint">{t("directGrant.departmentSourcedHint")}</p>
      <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs leading-5 text-ink-soft">
        {groups.map((group) => (
          <li key={`group:${group.key}`}>{group.name}</li>
        ))}
        {permissions.map((permission) => (
          <li key={`permission:${permission.permission}:${permission.scope}`}>
            {`${permission.permission_name} · ${permission.scope_name}`}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** 管理员是否动过授权目标(授权组或直接权限)。 */
function targetWasEdited(draft: GrantDraft, next: GrantDraft): boolean {
  return (
    next.authorizationGroupKeys.join("\u0000") !== draft.authorizationGroupKeys.join("\u0000")
    || next.selectedPermissionKeys.join("\u0000") !== draft.selectedPermissionKeys.join("\u0000")
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
