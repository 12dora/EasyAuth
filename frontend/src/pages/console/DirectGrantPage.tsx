import { ShieldCheck } from "lucide-react";

import { Button } from "../../components/Button";
import { Field } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { UserSearchInput, userSearchFieldHint } from "../../components/UserSelect";
import { PanelSurface } from "../../components/ui/PanelSurface";
import {
  DepartmentSourcedGrants,
  GrantForm,
  departmentSourcedNoticeStatus,
} from "../../features/grantForm";
import { useDirectGrant } from "./useDirectGrant";
import { ErrorList } from "./DirectGrantErrors";

/** 管理员直接授权: 选被授权人 + 授权目标 + 有效期, 提交后立即生效, 不走审批。 */
export function DirectGrantPage() {
  const page = useDirectGrant();
  const { t, catalogQuery, draft, grantMutation } = page;

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
          catalogErrorMessage={page.catalogErrorMessage}
          draft={draft}
          onDraftChange={(next) => {
            // 应用没变 => 这一次是管理员自己的编辑(目标、期限或说明): 这一对"人 + 应用"就此结清,
            // 免得还在路上的现状响应回来把编辑抹掉。换应用会带出新的一对, 那一对照常回填。
            if (next.appKey === draft.appKey) {
              page.settledPairRef.current = page.grantPairKey;
            }
            page.setDraft(next);
            page.setDraftErrorKeys([]);
          }}
          disabled={grantMutation.isPending}
          lockedAuthorizationGroupKeys={page.lockedAuthorizationGroupKeys}
          lockedPermissionKeys={page.lockedPermissionKeys}
          lockedHint={t("selector.scope.lockedByOrganizationAdmin")}
          header={<DirectGrantHeader page={page} />}
        />
        {page.catalogErrorMessage ? (
          <div className="mt-5">
            <StatusBanner
              live="alert"
              tone="signal"
              title={t("grantForm.catalogLoadFailed")}
              message={page.catalogErrorMessage}
            />
          </div>
        ) : null}
        <DirectGrantActions page={page} />
        {page.draftErrorKeys.length > 0 ? (
          <div className="mt-5">
            <StatusBanner live="alert" tone="signal" title={t("grantForm.invalidDraft")} />
            <ErrorList messages={page.draftErrorKeys.map((key) => t(key))} />
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
            <ErrorList messages={page.submitErrorMessages} />
          </div>
        ) : null}
      </PanelSurface>
    </>
  );
}

function DirectGrantHeader({ page }: { page: ReturnType<typeof useDirectGrant> }) {
  const { t, userId, grantee, currentGrant, currentGrantQuery, draft } = page;
  return (
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
          onChange={(value) => page.changeGrantee(value, null)}
          onSelectOption={(option) => page.changeGrantee(option.user_id, option)}
          onResolvedOptionChange={(option) => {
            if (option) {
              page.setGrantee(option);
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
  );
}

function DirectGrantActions({ page }: { page: ReturnType<typeof useDirectGrant> }) {
  const { t, grantMutation, canSubmit, reset, submit } = page;
  return (
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
  );
}
