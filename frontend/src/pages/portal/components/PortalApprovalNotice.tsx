import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";

import { noticeLive, noticeTone } from "./portalApprovalFacts";
import type { ApprovalNoticeKey } from "./portalApprovalTypes";

/** 决定结果提示条: 空 key 表示当前无提示。 */
export function PortalApprovalNotice({ noticeKey }: { noticeKey: ApprovalNoticeKey }) {
  const { t } = useI18n();
  if (!noticeKey) {
    return null;
  }

  return (
    <div className="mb-4">
      <StatusBanner
        live={noticeLive(noticeKey)}
        tone={noticeTone(noticeKey)}
        title={t(noticeKey)}
        message={
          noticeKey === "approvals.grantFailedCommitted"
            ? t("approvals.grantFailedCommittedDescription")
            : undefined
        }
      />
    </div>
  );
}
