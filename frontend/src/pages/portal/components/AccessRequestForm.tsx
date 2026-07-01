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
      <div className="grid gap-5 lg:grid-cols-2">
        <RequestTargetPicker
          appKey={form.appKey}
          authorizationGroupKey={form.authorizationGroupKey}
          apps={form.apps}
          authorizationGroups={form.authorizationGroups}
          permissionGroups={form.permissionGroups}
          ungroupedPermissions={form.ungroupedPermissions}
          selectedPermissionKeys={form.selectedPermissionKeys}
          selectedPermissionScopes={form.selectedPermissionScopes}
          expandedGroupKeys={form.expandedGroupKeys}
          catalogIsLoading={form.catalogIsLoading}
          catalogErrorMessage={form.catalogErrorMessage}
          onAppKeyChange={form.changeAppKey}
          onAuthorizationGroupKeyChange={form.changeAuthorizationGroupKey}
          onTogglePermission={form.togglePermission}
          onPermissionScopeChange={form.changePermissionScope}
          onToggleGroup={form.toggleGroup}
        />
        <AccessRequestFields
          grantType={form.grantType}
          expiresAt={form.expiresAt}
          reason={form.reason}
          onGrantTypeChange={form.changeGrantType}
          onExpiresAtChange={form.changeExpiresAt}
          onReasonChange={form.changeReason}
        />
      </div>
      {form.catalogErrorMessage ? <StatusBanner tone="signal" title="申请目录加载失败" message={form.catalogErrorMessage} /> : null}
      {!form.catalogIsLoading && form.appKey && form.visiblePermissionKeys.length === 0 ? (
        <StatusBanner tone="amber" title="未发现可选直接权限" message="当前应用没有返回权限目录，可仅按权限组发起申请。" />
      ) : null}
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
      {form.toastMessage ? <Toast message={form.toastMessage} /> : null}
    </PanelSurface>
  );
}
