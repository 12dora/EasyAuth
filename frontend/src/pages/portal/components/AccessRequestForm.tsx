import { Send } from "lucide-react";

import { Button } from "../../../components/Button";
import { StatusBanner } from "../../../components/StatusBanner";
import { PanelSurface } from "../../../components/ui/PanelSurface";
import { useI18n } from "../../../i18n/I18nProvider";
import { useAccessRequestForm } from "../hooks/useAccessRequestForm";
import { AccessRequestFields } from "./AccessRequestFields";
import { RequestTargetPicker } from "./RequestTargetPicker";

export function AccessRequestForm({ currentUserId = "" }: { currentUserId?: string }) {
  const { t } = useI18n();
  const form = useAccessRequestForm(currentUserId);

  const fieldsDisabled = form.isSubmitting;

  return (
    <PanelSurface>
      <div className="flex flex-col gap-5" aria-busy={form.isSubmitting || undefined}>
        <RequestTargetPicker
          appKey={form.appKey}
          apps={form.apps}
          authorizationGroupKey={form.authorizationGroupKey}
          authorizationGroups={form.authorizationGroups}
          permissionGroups={form.permissionGroups}
          ungroupedPermissions={form.ungroupedPermissions}
          selectedPermissionKeys={form.selectedPermissionKeys}
          coveredSelectionKeys={form.groupCoveredSelectionKeys}
          expandedGroupKeys={form.expandedGroupKeys}
          catalogIsLoading={form.catalogIsLoading}
          catalogErrorMessage={form.catalogErrorMessage}
          disabled={fieldsDisabled}
          onAppKeyChange={form.changeAppKey}
          onAuthorizationGroupKeyChange={form.changeAuthorizationGroupKey}
          onPermissionScopeChange={form.changePermissionScope}
          onPermissionGroupScopeChange={form.changePermissionGroupScope}
          onSelectPermissionKeys={form.selectPermissionKeys}
          onClearPermissionKeys={form.clearPermissionKeys}
          onExpandGroups={form.expandGroups}
          onCollapseGroups={form.collapseGroups}
          onToggleGroup={form.toggleGroup}
        />
        <AccessRequestFields
          appKey={form.appKey}
          approverOptions={form.approverOptions}
          selectedApproverUserIds={form.selectedApproverUserIds}
          grantType={form.grantType}
          expiresAt={form.expiresAt}
          expiresAtError={form.expiresAtError}
          reason={form.reason}
          disabled={fieldsDisabled}
          onApproverToggle={form.toggleApprover}
          onGrantTypeChange={form.changeGrantType}
          onExpiresAtChange={form.changeExpiresAt}
          onReasonChange={form.changeReason}
        />
      </div>
      {form.catalogErrorMessage ? <StatusBanner tone="signal" title={t("portal.request.catalogLoadFailed")} message={form.catalogErrorMessage} /> : null}
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
      {form.submitErrorMessage ? <StatusBanner tone="signal" title={t("portal.request.submitFailed")} message={form.submitErrorMessage} /> : null}
      {form.toastMessageKey ? (
        <div className="mt-4" role="status">
          <StatusBanner
            tone={form.toastMessageKey === "portal.request.submitted" ? "evergreen" : "amber"}
            title={t(form.toastMessageKey)}
          />
        </div>
      ) : null}
    </PanelSurface>
  );
}
