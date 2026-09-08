import { useState } from "react";

import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { StatusBanner } from "../../components/StatusBanner";
import {
  EMPTY_GRANT_DRAFT,
  GrantForm,
  buildGrantSubmission,
  grantDraftErrors,
  grantDraftFromPolicy,
  grantDraftIsValid,
  useGrantCatalog,
} from "../../features/grantForm";
import type {
  GrantDraft,
  GrantDraftError,
  GrantPolicySnapshot,
  GrantSubmission,
} from "../../features/grantForm";
import { useI18n } from "../../i18n/I18nProvider";
import { departmentDisplayName } from "../../lib/departmentDisplayName";
import type { DepartmentGrantPolicy } from "../../lib/domain/departmentGrants";

interface DepartmentGrantEditorDialogProps {
  /** 当前部门名; 新建时用于提示影响范围。 */
  departmentName: string;
  /** null 表示新建。继承行编辑的是它定义所在部门的策略。 */
  policy: DepartmentGrantPolicy | null;
  /** 定义在当前部门上的既有策略(不含继承); 新建时按应用回填, 避免同一个应用授两条。 */
  ownPolicies: DepartmentGrantPolicy[];
  errorMessage: string;
  errorDetails: string[];
  isSubmitting: boolean;
  /** policyId 为空即新建; 回填了既有策略时带上它的 id, 提交即更新那一条。 */
  onSubmit: (submission: GrantSubmission, policyId: number | null) => void;
  onClose: () => void;
}

/** 部门授权策略的新建/编辑弹窗: 复用 features/grantForm 的授权表单, 只去掉被授权人。 */
export function DepartmentGrantEditorDialog({
  departmentName,
  policy,
  ownPolicies,
  errorMessage,
  errorDetails,
  isSubmitting,
  onSubmit,
  onClose,
}: DepartmentGrantEditorDialogProps) {
  const { t } = useI18n();
  const catalogQuery = useGrantCatalog();
  const [draft, setDraft] = useState<GrantDraft>(() =>
    policy ? grantDraftFromPolicy(policySnapshot(policy)) : EMPTY_GRANT_DRAFT,
  );

  const [draftErrors, setDraftErrors] = useState<GrantDraftError[]>([]);
  // 新建态选中"本部门已经授过"的应用时回填的那条策略; 提交走更新, 不再新增一条同应用的授权。
  const [preloadedPolicy, setPreloadedPolicy] = useState<DepartmentGrantPolicy | null>(null);

  const title = policy
    ? policy.inherited
      ? t("departmentGrants.dialog.editInheritedTitle", { name: departmentDisplayName(policy.defined_on, t) })
      : t("departmentGrants.dialog.editTitle")
    : t("departmentGrants.dialog.createTitle");
  // 编辑继承来的策略时, 影响范围是它定义所在的部门(及其子部门), 不是当前浏览的部门。
  const affectedDepartmentName = policy ? departmentDisplayName(policy.defined_on, t) : departmentName;
  // 提交闸门在点击那一刻重算: 渲染期算出来的结论会过期(限时授权的到期时间会走到过去),
  // 那时按钮还亮着, 载荷却已经不能拼了 —— 拦下来展示在横幅里, 而不是让构造函数抛出去。
  const submit = () => {
    const errors = grantDraftErrors(draft, catalogQuery.data);
    setDraftErrors(errors);
    if (errors.length === 0) {
      // 提交这一刻再认一次目标: 选完应用之后本部门的策略可能才刚取到(或被别人改过),
      // 同一个应用只能有一条部门策略, 认漏了就会建出重复的第二条。
      const target = policy ?? existingPolicyFor(ownPolicies, draft.appKey);
      onSubmit(buildGrantSubmission(draft), target ? target.id : null);
    }
  };
  const canSubmit = grantDraftIsValid(draft, catalogQuery.data) && !isSubmitting;
  const draftErrorMessages = draftErrors.map((error) => t(error.messageKey));
  const bannerTitle = draftErrors.length > 0 ? t("grantForm.invalidDraft") : t("departmentGrants.dialog.saveFailed");
  const bannerMessage = draftErrors.length > 0 ? "" : errorMessage;
  const bannerDetails = draftErrors.length > 0 ? draftErrorMessages : errorDetails;

  return (
    <Dialog
      title={title}
      size="xl"
      onClose={onClose}
      closeDisabled={isSubmitting}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={isSubmitting}>
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            variant="primary"
            loading={isSubmitting}
            disabled={!canSubmit}
            onClick={submit}
          >
            {t("departmentGrants.dialog.submit")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <StatusBanner tone="bond" title={t("departmentGrants.dialog.notice", { dept: affectedDepartmentName })} />
        {preloadedPolicy ? (
          <p className="text-body leading-5 text-ink-soft" role="status">
            {t("departmentGrants.dialog.preloadedExisting")}
          </p>
        ) : null}
        {errorMessage || draftErrors.length > 0 ? (
          <div className="space-y-2">
            <StatusBanner live="alert" tone="signal" title={bannerTitle} message={bannerMessage} />
            {bannerDetails.length > 0 ? (
              <ul className="list-disc space-y-1 pl-5 text-body leading-5 text-signal">
                {bannerDetails.map((detail) => (
                  <li key={detail}>{detail}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
        <GrantForm
          catalog={catalogQuery.data}
          catalogIsLoading={catalogQuery.isLoading}
          catalogErrorMessage={catalogQuery.error ? catalogQuery.error.message : ""}
          draft={draft}
          onDraftChange={(next) => {
            setDraftErrors([]);
            // 新建态选完应用, 先把该应用在本部门已有的授权载进表单: 管理员看到的是现状,
            // 保存即更新那一条, 而不是在同一个应用上再堆一条策略。换成没授过的应用时回填作废。
            const appChanged = !policy && next.appKey !== draft.appKey;
            const existing = appChanged ? existingPolicyFor(ownPolicies, next.appKey) : null;
            if (existing) {
              setPreloadedPolicy(existing);
              setDraft(grantDraftFromPolicy(policySnapshot(existing)));
              return;
            }
            if (appChanged) {
              setPreloadedPolicy(null);
            }
            setDraft(next);
          }}
          disabled={isSubmitting}
          lockedAppKey={policy ? policy.app.app_key : undefined}
        />
      </div>
    </Dialog>
  );
}

function policySnapshot(policy: DepartmentGrantPolicy): GrantPolicySnapshot {
  return {
    app_key: policy.app.app_key,
    authorization_groups: policy.authorization_groups,
    permissions: policy.permissions,
    grant_type: policy.grant_type,
    expires_at: policy.expires_at,
    reason: policy.reason,
  };
}

function existingPolicyFor(ownPolicies: DepartmentGrantPolicy[], appKey: string): DepartmentGrantPolicy | null {
  if (!appKey) {
    return null;
  }
  return ownPolicies.find((item) => item.app.app_key === appKey) ?? null;
}
