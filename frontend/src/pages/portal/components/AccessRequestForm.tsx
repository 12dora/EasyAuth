import { Send } from "lucide-react";

import { Button } from "../../../components/Button";
import { StatusBanner } from "../../../components/StatusBanner";
import { Toast } from "../../../components/Toast";
import { PanelSurface } from "../../../components/ui/PanelSurface";
import { useAccessRequestForm } from "../hooks/useAccessRequestForm";
import { AccessRequestFields } from "./AccessRequestFields";
import { RequestTargetPicker } from "./RequestTargetPicker";

export function AccessRequestForm() {
  const form = useAccessRequestForm();

  return (
    <PanelSurface>
      <div className="grid items-start gap-5 lg:grid-cols-2">
        <div className="self-start">
          <RequestTargetPicker
            appKey={form.appKey}
            apps={form.apps}
            permissionGroups={form.permissionGroups}
            ungroupedPermissions={form.ungroupedPermissions}
            selectedPermissionKeys={form.selectedPermissionKeys}
            selectedPermissionScopes={form.selectedPermissionScopes}
            expandedGroupKeys={form.expandedGroupKeys}
            catalogIsLoading={form.catalogIsLoading}
            catalogErrorMessage={form.catalogErrorMessage}
            onAppKeyChange={form.changeAppKey}
            onTogglePermission={form.togglePermission}
            onTogglePermissionGroup={form.togglePermissionGroup}
            onPermissionScopeChange={form.changePermissionScope}
            onPermissionGroupScopeChange={form.changePermissionGroupScope}
            onToggleGroup={form.toggleGroup}
          />
        </div>
        <div className="self-start">
          <AccessRequestFields
            appKey={form.appKey}
            authorizationGroupKey={form.authorizationGroupKey}
            authorizationGroups={form.authorizationGroups}
            approverOptions={form.approverOptions}
            selectedApproverUserIds={form.selectedApproverUserIds}
            grantType={form.grantType}
            expiresAt={form.expiresAt}
            reason={form.reason}
            onAuthorizationGroupKeyChange={form.changeAuthorizationGroupKey}
            onApproverToggle={form.toggleApprover}
            onGrantTypeChange={form.changeGrantType}
            onExpiresAtChange={form.changeExpiresAt}
            onReasonChange={form.changeReason}
          />
        </div>
      </div>
      {form.catalogErrorMessage ? <StatusBanner tone="signal" title="申请目录加载失败" message={form.catalogErrorMessage} /> : null}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
        <Button
          variant="primary"
          icon={<Send size={16} />}
          loading={form.isSubmitting}
          disabled={!form.canSubmit}
          onClick={form.submit}
        >
          提交申请
        </Button>
      </div>
      {form.submitErrorMessage ? <StatusBanner tone="signal" title="提交失败" message={form.submitErrorMessage} /> : null}
      {form.toastMessage ? <Toast tone={form.toastMessage === "申请已提交" ? "evergreen" : "amber"} message={form.toastMessage} /> : null}
    </PanelSurface>
  );
}
