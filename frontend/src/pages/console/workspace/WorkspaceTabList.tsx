import { useRef } from "react";

import { useActiveTabIndicator, useRovingTabs } from "../../../components/useRovingTabs";
import { useI18n } from "../../../i18n/I18nProvider";
import { cn } from "../../../lib/cn";
import type { WorkspaceTab, WorkspaceTabDescriptor } from "./workspaceTabs";

export function WorkspaceTabList({
  tabs,
  activeTab,
  onActivate,
}: {
  tabs: WorkspaceTabDescriptor[];
  activeTab: WorkspaceTab;
  onActivate: (key: WorkspaceTab) => void;
}) {
  const { t } = useI18n();
  const tabButtonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const activeTabIndex = tabs.findIndex((item) => item.key === activeTab);
  const onTabListKeyDown = useRovingTabs({
    activeKey: activeTab,
    items: tabs.map((item) => item.key),
    refs: tabButtonRefs,
    onActivate,
  });
  const indicatorStyle = useActiveTabIndicator(tabButtonRefs, activeTabIndex);

  return (
    <div
      className="relative mb-6 flex gap-1 overflow-x-auto border-b border-ink/12"
      role="tablist"
      aria-label={t("workspace.tablist")}
      onKeyDown={onTabListKeyDown}
    >
      <span
        aria-hidden="true"
        className="pointer-events-none absolute bottom-0 h-0.5 bg-accent transition-[left,width] duration-200 ease-out"
        style={{ left: indicatorStyle.left, width: indicatorStyle.width }}
      />
      {tabs.map((item, index) => (
        <button
          key={item.key}
          ref={(node) => {
            tabButtonRefs.current[index] = node;
          }}
          role="tab"
          id={`workspace-tab-${item.key}`}
          aria-selected={item.key === activeTab}
          aria-controls={`workspace-tabpanel-${item.key}`}
          tabIndex={item.key === activeTab ? 0 : -1}
          className={cn(
            "relative z-10 h-10 shrink-0 px-3 text-sm font-semibold transition-colors",
            item.key === activeTab
              ? "text-ink"
              : "text-ink-soft hover:text-ink",
          )}
          onClick={() => onActivate(item.key)}
          type="button"
        >
          {t(item.labelKey)}
        </button>
      ))}
    </div>
  );
}
