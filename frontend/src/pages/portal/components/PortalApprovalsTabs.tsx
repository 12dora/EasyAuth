import { useRef } from "react";

import { useRovingTabs } from "../../../components/useRovingTabs";
import { useI18n } from "../../../i18n/I18nProvider";
import { cn } from "../../../lib/cn";

import { APPROVAL_TAB_KEYS, type ApprovalTab } from "./portalApprovalTypes";

export function PortalApprovalsTabs({
  tab,
  onSwitchTab,
}: {
  tab: ApprovalTab;
  onSwitchTab: (nextTab: ApprovalTab) => void;
}) {
  const { t } = useI18n();
  const tabButtonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const onTabListKeyDown = useRovingTabs({
    activeKey: tab,
    items: APPROVAL_TAB_KEYS,
    refs: tabButtonRefs,
    onActivate: onSwitchTab,
  });

  return (
    <div
      className="mb-4 flex gap-1 border-b border-ink/12"
      role="tablist"
      aria-label={t("portal.approvals.tablist")}
      onKeyDown={onTabListKeyDown}
    >
      {APPROVAL_TAB_KEYS.map((item, index) => (
        <button
          key={item}
          ref={(node) => {
            tabButtonRefs.current[index] = node;
          }}
          type="button"
          role="tab"
          id={`portal-approvals-tab-${item}`}
          aria-selected={item === tab}
          aria-controls={`portal-approvals-tabpanel-${item}`}
          tabIndex={item === tab ? 0 : -1}
          className={cn(
            "relative -mb-px h-10 shrink-0 border-b-2 px-3 text-sm font-semibold transition-colors",
            item === tab ? "border-accent text-ink" : "border-transparent text-ink-soft hover:text-ink",
          )}
          onClick={() => onSwitchTab(item)}
        >
          {item === "pending" ? t("portal.approvals.tab.pending") : t("portal.approvals.tab.processed")}
        </button>
      ))}
    </div>
  );
}
