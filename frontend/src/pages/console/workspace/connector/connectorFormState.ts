import type { JsonObject } from "../../../../lib/api";
import type {
  ConnectorInstanceItem,
  ConnectorTypeItem,
} from "../../../../lib/domain";
import { stableJson } from "./connectorFormat";

export interface ConnectorFormFlagsInput {
  canManage: boolean;
  instance: ConnectorInstanceItem | null;
  activeType: ConnectorTypeItem | null;
  connectorKey: string;
  selectedTypeKey: string;
  configDraft: JsonObject;
  enabledDraft: boolean;
  draftInstanceId: number | null;
  testedFingerprint: string | null;
  candidateFingerprint: string;
  connectorsLoaded: boolean;
}

export interface ConnectorFormFlags {
  saveBlockedByTest: boolean;
  authoritativeConfigLoaded: boolean;
  candidateLoaded: boolean;
  canOperate: boolean;
  selectionValue: string;
}

/** 保存前置校验口径: 启用态且(新建/原本停用/配置有改动)时必须先测试通过当前指纹。 */
function saveRequiresTest(input: ConnectorFormFlagsInput): boolean {
  const { instance } = input;
  const configChanged = Boolean(
    instance && stableJson(input.configDraft) !== stableJson(instance.config),
  );
  return input.enabledDraft && (!instance || !instance.enabled || configChanged);
}

/** 草稿是否已经装载到当前实例, 未装载时禁止操作以免把空配置写回。 */
function candidateLoaded(
  instance: ConnectorInstanceItem | null,
  draftInstanceId: number | null,
): boolean {
  return !instance || draftInstanceId === instance.id;
}

function selectionValue(
  instance: ConnectorInstanceItem | null,
  selectedTypeKey: string,
): string {
  if (instance) {
    return `instance:${instance.id}`;
  }
  return selectedTypeKey ? `new:${selectedTypeKey}` : "";
}

export function connectorFormFlags(
  input: ConnectorFormFlagsInput,
): ConnectorFormFlags {
  const loaded = candidateLoaded(input.instance, input.draftInstanceId);
  return {
    saveBlockedByTest:
      saveRequiresTest(input) &&
      input.testedFingerprint !== input.candidateFingerprint,
    authoritativeConfigLoaded: input.connectorsLoaded,
    candidateLoaded: loaded,
    canOperate: canOperate(input, loaded),
    selectionValue: selectionValue(input.instance, input.selectedTypeKey),
  };
}

function canOperate(input: ConnectorFormFlagsInput, loaded: boolean): boolean {
  return (
    input.canManage &&
    input.connectorsLoaded &&
    loaded &&
    Boolean(input.connectorKey && input.activeType)
  );
}
