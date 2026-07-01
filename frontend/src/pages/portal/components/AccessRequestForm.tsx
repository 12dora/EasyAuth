import { Send } from "lucide-react";

import { Button } from "../../../components/Button";
import { StatusBanner } from "../../../components/StatusBanner";
import { Toast } from "../../../components/Toast";
import { useAccessRequestForm } from "../hooks/useAccessRequestForm";
import { AccessRequestFields } from "./AccessRequestFields";
import { RequestTargetPicker } from "./RequestTargetPicker";

export function AccessRequestForm() {
  const form = useAccessRequestForm();

  return (
    <section className="form-surface">
      <div className="form-grid">
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
      {form.catalogErrorMessage ? <StatusBanner tone="danger" title="申请目录加载失败" message={form.catalogErrorMessage} /> : null}
      {!form.catalogIsLoading && form.appKey && form.visiblePermissionKeys.length === 0 ? (
        <StatusBanner tone="warning" title="未发现可选直接权限" message="当前应用没有返回权限目录，可仅按权限组发起申请。" />
      ) : null}
      <div className="panel-toolbar">
        <Button variant="primary" icon={<Send size={16} />} disabled={!form.canSubmit} onClick={form.submit}>
          提交申请
        </Button>
      </div>
      {form.submitErrorMessage ? <StatusBanner tone="danger" title="提交失败" message={form.submitErrorMessage} /> : null}
      {form.toastMessage ? <Toast message={form.toastMessage} /> : null}
    </section>
  );
}
