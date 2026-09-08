import { Send } from "lucide-react";

import { Button } from "../../../components/Button";
import { StatusBanner } from "../../../components/StatusBanner";
import { PanelSurface } from "../../../components/ui/PanelSurface";
import { useToast } from "../../../components/ui/Toast";
import { useI18n } from "../../../i18n/I18nProvider";
import { useAccessRequestForm } from "../hooks/useAccessRequestForm";
import { useAccessRequestPrefill } from "../hooks/useAccessRequestPrefill";
import { AccessRequestFields } from "./AccessRequestFields";
import { RequestTargetPicker } from "./RequestTargetPicker";

export function AccessRequestForm({ currentUserId = "" }: { currentUserId?: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const { prefill, clearRouterState } = useAccessRequestPrefill();
  // 提交成功是一次性事件: 用 toast 说一次就够, 留在表单里的提示条只承载草稿本身的问题。
  const form = useAccessRequestForm(currentUserId, {
    prefill,
    onPrefillApplied: clearRouterState,
    onSubmitted: () => toast.success(t("portal.request.submitted")),
  });

  const fieldsDisabled = form.isSubmitting;
  // 续期目标必须与基础授权完全一致(后端 _validate_renew_targets), 因此目标选择器整体只读。
  const targetPickerDisabled = fieldsDisabled || form.requestType === "renew";

  return (
    <PanelSurface>
      <div className="flex flex-col gap-5" aria-busy={form.isSubmitting || undefined}>
        {form.prefillErrorMessageKey ? (
          <StatusBanner live="alert" tone="signal" title={t(form.prefillErrorMessageKey)} />
        ) : null}
        <RequestTargetPicker
          appKey={form.appKey}
          apps={form.apps}
          authorizationGroupKeys={form.authorizationGroupKeys}
          authorizationGroups={form.authorizationGroups}
          permissionGroups={form.permissionGroups}
          ungroupedPermissions={form.ungroupedPermissions}
          selectedPermissionKeys={form.selectedPermissionKeys}
          coveredSelectionKeys={form.groupCoveredSelectionKeys}
          revokeBaseGrant={form.revokeBaseGrant}
          expandedGroupKeys={form.expandedGroupKeys}
          catalogIsLoading={form.catalogIsLoading}
          catalogErrorMessage={form.catalogErrorMessage}
          disabled={targetPickerDisabled}
          onAppKeyChange={form.changeAppKey}
          onAuthorizationGroupKeysChange={form.changeAuthorizationGroupKeys}
          onPermissionScopeChange={form.changePermissionScope}
          onPermissionGroupScopeChange={form.changePermissionGroupScope}
          onSelectPermissionKeys={form.selectPermissionKeys}
          onClearPermissionKeys={form.clearPermissionKeys}
          onExpandGroups={form.expandGroups}
          onCollapseGroups={form.collapseGroups}
          onToggleGroup={form.toggleGroup}
        />
        <AccessRequestFields
          requestType={form.requestType}
          appKey={form.appKey}
          baseGrantId={form.baseGrantId}
          baseGrantLockedToApp={form.baseGrantLockedToApp}
          currentGrants={form.currentGrants}
          approverOptions={form.approverOptions}
          selectedApproverUserIds={form.selectedApproverUserIds}
          grantType={form.grantType}
          expiresAt={form.expiresAt}
          expiresAtError={form.expiresAtError}
          reason={form.reason}
          disabled={fieldsDisabled}
          onRequestTypeChange={form.changeRequestType}
          onBaseGrantChange={form.changeBaseGrantId}
          onApproverToggle={form.toggleApprover}
          onGrantTypeChange={form.changeGrantType}
          onExpiresAtChange={form.changeExpiresAt}
          onReasonChange={form.changeReason}
        />
      </div>
      {form.catalogErrorMessage ? <StatusBanner live="alert" tone="signal" title={t("portal.request.catalogLoadFailed")} message={form.catalogErrorMessage} /> : null}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
        <Button
          variant="primary"
          icon={<Send size={16} />}
          loading={form.isSubmitting}
          disabled={!form.canSubmit || form.isSubmitting}
          onClick={form.submit}
        >
          {t("portal.request.submit")}
        </Button>
      </div>
      {form.submitErrorMessage ? <StatusBanner live="alert" tone="signal" title={t("portal.request.submitFailed")} message={form.submitErrorMessage} /> : null}
      {form.noticeMessageKey ? (
        <div className="mt-4">
          <StatusBanner live="status" tone="amber" title={t(form.noticeMessageKey)} />
        </div>
      ) : null}
    </PanelSurface>
  );
}
