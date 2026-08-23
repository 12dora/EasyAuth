import { useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import type { MessageKey } from "../../../i18n/messages";
import { BASE_TABS, type WorkspaceTab, type WorkspaceTabDescriptor } from "./workspaceTabs";

/** 工作台页签集合与 ?tab= 同步; 非超管深链 handover 时回退 overview。 */
export function useWorkspaceTabs(isSuperuser: boolean) {
  const tabs: WorkspaceTabDescriptor[] = useMemo(
    () =>
      isSuperuser
        ? [...BASE_TABS, { key: "handover" as const, labelKey: "handover.console.capability.tab" as MessageKey }]
        : BASE_TABS,
    [isSuperuser],
  );
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = (searchParams.get("tab") as WorkspaceTab | null) ?? "overview";
  const activeTab = tabs.some((item) => item.key === tab) ? tab : "overview";
  // 无权限时深链 handover 回退 overview
  useEffect(() => {
    if (tab === "handover" && !isSuperuser) {
      setSearchParams({ tab: "overview" }, { replace: true });
    }
  }, [isSuperuser, setSearchParams, tab]);

  return {
    tabs,
    activeTab,
    activateTab: (key: WorkspaceTab) => setSearchParams({ tab: key }),
  };
}
