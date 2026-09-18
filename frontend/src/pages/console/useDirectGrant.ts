import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { userOptionDisplayName } from "../../components/UserCombobox";
import type {
  DirectoryOnlyUserOption,
  DirectoryUserRef,
  UserOption,
  UserSearchOption,
} from "../../components/UserCombobox";
import { useToast } from "../../components/ui/Toast";
import {
  EMPTY_GRANT_DRAFT,
  buildGrantSubmission,
  departmentSourcedGroupKeys,
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
import { apiRequest } from "../../lib/api";
import type { JsonValue } from "../../lib/api";
import { parseAccessGrantRow } from "../../lib/domain/accessGrantRow";
import type { AccessGrantRow } from "../../lib/domain/accessGrantRow";
import { formatAppDisplayName } from "../../lib/appDisplayName";
import { buildCatalogView } from "../portal/hooks/accessRequestCatalog";
import { detailErrorMessages } from "./DirectGrantErrors";

/**
 * 被授权人: 已有账号的人按用户 ID(也可能是手输的 ID), 尚无账号的通讯录人员按钉钉三元组。
 *
 * 通讯录人员还没有账号, 自然也没有现有授权: 不读现状, 从空草稿开始; 提交时后端先为他开通账号。
 */
export type GranteeSelection =
  | { kind: "user"; userId: string }
  | { kind: "directory"; directoryUser: DirectoryUserRef };

const NO_GRANTEE: GranteeSelection = { kind: "user", userId: "" };

type DirectGrantPayload = GrantSubmission & ({ user_id: string } | { directory_user: DirectoryUserRef });

interface DirectGrantRequest {
  payload: DirectGrantPayload;
  selection: GranteeSelection;
  granteeOption: UserSearchOption | null;
  granteeLabel: string;
  appLabel: string;
}

export function useDirectGrant() {
  const { t } = useI18n();
  const catalogQuery = useGrantCatalog();
  const [selection, setSelection] = useState<GranteeSelection>(NO_GRANTEE);
  const [grantee, setGrantee] = useState<UserSearchOption | null>(null);
  const [draft, setDraft] = useState<GrantDraft>(EMPTY_GRANT_DRAFT);
  const [draftErrorKeys, setDraftErrorKeys] = useState<MessageKey[]>([]);
  const userId = selection.kind === "user" ? selection.userId : "";
  const hasGrantee = selection.kind === "directory" || userId !== "";
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

  useDirectGrantPrefill({
    catalogQuery,
    currentGrantQuery,
    grantPairKey,
    lastPairRef,
    settledPairRef,
    setDraft,
  });

  useCurrentGrantErrorToast(grantPairKey, currentGrantQuery.error, reportedErrorPairRef);

  const grantMutation = useDirectGrantMutation(() => {
    setDraftErrorKeys([]);
    setDraft(EMPTY_GRANT_DRAFT);
    // 现状已经被这次授权改写: 允许重新回填, 否则再选回同一个应用会回填过期的现状。
    settledPairRef.current = "";
    lastPairRef.current = "";
  }, (row, request) => {
    // 被授权人保持选中: 连续给同一个人授权是最常见的操作。通讯录人员此时已经有了账号,
    // 切换成按用户 ID 选中, 之后选应用就像普通员工一样读回现状。期间管理员换了人就不动他的新选择。
    setSelection((current) =>
      sameSelection(current, request.selection) ? { kind: "user", userId: row.user_id } : current,
    );
    setGrantee((current) =>
      current === request.granteeOption ? granteeAfterGrant(row, request.granteeOption) : current,
    );
  });

  const selectGrantee = (nextSelection: GranteeSelection, nextOption: UserSearchOption | null) => {
    setSelection(nextSelection);
    setGrantee(nextOption);
    // 目标与期限描述的是上一个人的现状, 换人后一条都不成立。
    setDraft(grantDraftWithoutGrantee(draft));
    setDraftErrorKeys([]);
  };

  return {
    t,
    catalogQuery,
    selection,
    userId,
    grantee,
    draft,
    draftErrorKeys,
    currentGrantQuery,
    currentGrant,
    lockedAuthorizationGroupKeys,
    lockedPermissionKeys,
    grantMutation,
    catalogErrorMessage: catalogQuery.error ? catalogQuery.error.message : "",
    canSubmit: hasGrantee && grantDraftIsValid(draft, catalogQuery.data),
    submitErrorMessages: detailErrorMessages(grantMutation.error),
    submit: () => {
      // 渲染时算出来的闸门会过期: 用户填完未来的到期时间后可以一直等到它走进过去, 那时按钮还亮着。
      // 这里重算一次, 拦下来就把原因显示出来, 而不是让 buildGrantSubmission 同步抛错却什么都不显示。
      const errors = grantDraftErrors(draft, catalogQuery.data);
      if (errors.length > 0) {
        setDraftErrorKeys(errors.map((error) => error.messageKey));
        return;
      }
      setDraftErrorKeys([]);
      const submission = buildGrantSubmission(draft);
      grantMutation.mutate({
        payload:
          selection.kind === "user"
            ? { user_id: selection.userId, ...submission }
            : { directory_user: selection.directoryUser, ...submission },
        selection,
        granteeOption: grantee,
        granteeLabel: grantee ? userOptionDisplayName(grantee) : userId,
        appLabel: formatAppDisplayName(grantCatalogApp(catalogQuery.data, draft.appKey)),
      });
    },
    changeGrantee: (nextUserId: string, nextOption: UserOption | null) =>
      selectGrantee({ kind: "user", userId: nextUserId }, nextOption),
    selectDirectoryGrantee: (option: DirectoryOnlyUserOption) =>
      selectGrantee({ kind: "directory", directoryUser: option.directory_user }, option),
    setGrantee,
    setDraft,
    setDraftErrorKeys,
    settledPairRef,
    grantPairKey,
    reset: () => {
      setSelection(NO_GRANTEE);
      setGrantee(null);
      setDraft(EMPTY_GRANT_DRAFT);
      setDraftErrorKeys([]);
      settledPairRef.current = "";
      lastPairRef.current = "";
      reportedErrorPairRef.current = "";
      grantMutation.reset();
    },
  };
}

function useCurrentGrantErrorToast(
  grantPairKey: string,
  error: Error | null,
  reportedErrorPairRef: { current: string },
) {
  const { t } = useI18n();
  const toast = useToast();
  useEffect(() => {
    // 读不到现状就把失败说出来, 让表单停在空白态: 静默留白会让管理员以为这个人还没有权限。
    if (grantPairKey === "" || !error || reportedErrorPairRef.current === grantPairKey) {
      return;
    }
    reportedErrorPairRef.current = grantPairKey;
    toast.error(t("directGrant.currentGrantFailed"), error.message);
  }, [grantPairKey, error, reportedErrorPairRef, toast, t]);
}

function useDirectGrantMutation(
  resetDraft: () => void,
  switchGrantee: (row: AccessGrantRow, request: DirectGrantRequest) => void,
) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  return useMutation<AccessGrantRow, Error, DirectGrantRequest>({
    mutationFn: async (request) =>
      parseDirectGrantResponse(
        await apiRequest<unknown>("/console/api/v1/direct-grants", { method: "POST", body: request.payload }),
      ),
    onSuccess: (row, request) => {
      toast.success(t("directGrant.succeeded", { name: request.granteeLabel, app: request.appLabel }));
      resetDraft();
      switchGrantee(row, request);
      // 现状已经被这次授权改写: 连缓存一起丢掉。
      queryClient.removeQueries({ queryKey: ["console", "current-grant"] });
      void queryClient.invalidateQueries({ queryKey: ["console", "operations", "access-grants"] });
    },
  });
}

/** `POST /console/api/v1/direct-grants` 的 201 响应: `{data: {grant: <授权行>}}`; 形状不符即契约违约。 */
export function parseDirectGrantResponse(payload: unknown): AccessGrantRow {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("direct grant response contract violated: payload");
  }
  const data = (payload as Record<string, unknown>).data;
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("direct grant response contract violated: data");
  }
  const grant = (data as Record<string, unknown>).grant;
  if (grant === undefined || grant === null) {
    throw new Error("direct grant response contract violated: data.grant");
  }
  return parseAccessGrantRow(grant as JsonValue);
}

function sameSelection(left: GranteeSelection, right: GranteeSelection): boolean {
  if (left.kind === "user") {
    return right.kind === "user" && right.userId === left.userId;
  }
  if (right.kind === "user") {
    return false;
  }
  const a = left.directoryUser;
  const b = right.directoryUser;
  return a.source_slug === b.source_slug && a.corp_id === b.corp_id && a.user_id === b.user_id;
}

/**
 * 授权成功后的被授权人候选项。已有账号的人原样保留; 通讯录人员换成授权行里的真实账号,
 * 部门路径授权行没带时沿用搜索候选里的那一份(同一个人, 同一套部门口径)。
 */
function granteeAfterGrant(row: AccessGrantRow, option: UserSearchOption | null): UserSearchOption | null {
  if (option === null || option.user_id !== null) {
    return option;
  }
  return {
    user_id: row.user_id,
    name: row.user_name,
    department: row.user_department || option.department,
    account_kind: row.user_account_kind,
    directory_user: option.directory_user,
  };
}

function useDirectGrantPrefill({
  catalogQuery,
  currentGrantQuery,
  grantPairKey,
  lastPairRef,
  settledPairRef,
  setDraft,
}: {
  catalogQuery: ReturnType<typeof useGrantCatalog>;
  currentGrantQuery: ReturnType<typeof useCurrentGrant>;
  grantPairKey: string;
  lastPairRef: { current: string };
  settledPairRef: { current: string };
  setDraft: (updater: (current: GrantDraft) => GrantDraft) => void;
}) {
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
  }, [grantPairKey, currentGrantQuery.isSuccess, currentGrantQuery.data, catalogQuery.data, lastPairRef, settledPairRef, setDraft]);
}
