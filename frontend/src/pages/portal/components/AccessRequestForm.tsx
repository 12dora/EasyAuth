import { Send } from "lucide-react";

import { Button } from "../../../components/Button";
import { StatusBanner } from "../../../components/StatusBanner";
import { PanelSurface } from "../../../components/ui/PanelSurface";
import { useAccessRequestForm } from "../hooks/useAccessRequestForm";
import { AccessRequestFields } from "./AccessRequestFields";
import { RequestTargetPicker } from "./RequestTargetPicker";

export function AccessRequestForm({ currentUserId = "" }: { currentUserId?: string }) {
  const form = useAccessRequestForm(currentUserId);

  return (
    <PanelSurface>
      <div className="flex flex-col gap-5">
        <RequestTargetPicker
          appKey={form.appKey}
          apps={form.apps}
          authorizationGroupKey={form.authorizationGroupKey}
          authorizationGroups={form.authorizationGroups}
          permissionGroups={form.permissionGroups}
          ungroupedPermissions={form.ungroupedPermissions}
          selectedPermissionKeys={form.selectedPermissionKeys}
          expandedGroupKeys={form.expandedGroupKeys}
          catalogIsLoading={form.catalogIsLoading}
          catalogErrorMessage={form.catalogErrorMessage}
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
          onApproverToggle={form.toggleApprover}
          onGrantTypeChange={form.changeGrantType}
          onExpiresAtChange={form.changeExpiresAt}
          onReasonChange={form.changeReason}
        />
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
      {form.toastMessage ? (
        <div className="mt-4" role="status">
          <StatusBanner tone={form.toastMessage === "申请已提交" ? "evergreen" : "amber"} title={form.toastMessage} />
        </div>
      ) : null}
    </PanelSurface>
  );
}
