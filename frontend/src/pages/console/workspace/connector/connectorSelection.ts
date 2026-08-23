import type { UseQueryResult } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

import type {
  ConnectorInstanceItem,
  ConnectorsPayload,
  ConnectorTypeItem,
} from "../../../../lib/domain";
import type { ConnectorDrafts } from "./connectorDrafts";

export interface ConnectorSelection {
  connectorTypes: ConnectorTypeItem[];
  instances: ConnectorInstanceItem[];
  instance: ConnectorInstanceItem | null;
  availableTypes: ConnectorTypeItem[];
  activeType: ConnectorTypeItem | null;
}

/** 选中实例/待新建类型的派生视图, 并在列表或选择变化时把草稿同步回权威配置。 */
export function useConnectorSelection(
  connectorsQuery: UseQueryResult<ConnectorsPayload, Error>,
  drafts: ConnectorDrafts,
): ConnectorSelection {
  const { selectedInstanceId, selectedTypeKey } = drafts;
  const connectorTypes = connectorsQuery.data?.connector_types ?? [];
  const instances = connectorsQuery.data?.data ?? [];
  const instance =
    instances.find((item) => item.id === selectedInstanceId) ?? null;
  const configuredTypeKeys = useMemo(
    () => new Set(instances.map((item) => item.connector_key)),
    [instances],
  );
  const availableTypes = connectorTypes.filter(
    (item) => !configuredTypeKeys.has(item.key),
  );
  const activeType: ConnectorTypeItem | null = useMemo(() => {
    const key = instance?.connector_key ?? selectedTypeKey;
    return connectorTypes.find((item) => item.key === key) ?? null;
  }, [connectorTypes, instance?.connector_key, selectedTypeKey]);

  useEffect(() => {
    if (!connectorsQuery.data || selectedTypeKey) {
      return;
    }
    if (
      selectedInstanceId !== null &&
      instances.some((item) => item.id === selectedInstanceId)
    ) {
      return;
    }
    drafts.setSelectedInstanceId(instances[0]?.id ?? null);
  }, [connectorsQuery.data, instances, selectedInstanceId, selectedTypeKey]);

  useEffect(() => {
    if (instance) {
      drafts.setConfigDraft(instance.config);
      drafts.setEnabledDraft(instance.enabled);
      drafts.setIntervalDraft(String(instance.reconcile_interval_seconds));
      drafts.setDraftInstanceId(instance.id);
      drafts.setTestedFingerprint(null);
    } else if (selectedTypeKey) {
      drafts.setConfigDraft({});
      drafts.setEnabledDraft(false);
      drafts.setIntervalDraft("300");
      drafts.setDraftInstanceId(null);
      drafts.setTestedFingerprint(null);
    }
  }, [instance, selectedTypeKey]);

  return { connectorTypes, instances, instance, availableTypes, activeType };
}

/** 下拉选择变更: instance:<id> 切换到已有实例, new:<key> 进入新建草稿。 */
export function createSelectionChanger(
  instances: ConnectorInstanceItem[],
  drafts: ConnectorDrafts,
): (selection: string) => void {
  const selectInstance = (nextInstanceId: number) => {
    const nextInstance = instances.find((item) => item.id === nextInstanceId);
    drafts.setSelectedTypeKey("");
    drafts.setSelectedInstanceId(nextInstance?.id ?? null);
    if (nextInstance) {
      drafts.setConfigDraft(nextInstance.config);
      drafts.setEnabledDraft(nextInstance.enabled);
      drafts.setIntervalDraft(String(nextInstance.reconcile_interval_seconds));
      drafts.setDraftInstanceId(nextInstance.id);
    }
  };

  return (selection: string) => {
    const [kind, rawValue] = selection.split(":", 2);
    drafts.setDeleteConfirmOpen(false);
    drafts.setTestedFingerprint(null);
    if (kind === "instance") {
      selectInstance(Number(rawValue));
      return;
    }
    drafts.setSelectedInstanceId(null);
    drafts.setDraftInstanceId(null);
    drafts.setSelectedTypeKey(kind === "new" ? rawValue : "");
  };
}
