import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { JsonObject } from "../../../../lib/api";

/** 连接器编辑态: 选中项、表单草稿与测试指纹, 由 useConnectorSelection 与各 mutation 共同维护。 */
export interface ConnectorDrafts {
  selectedInstanceId: number | null;
  setSelectedInstanceId: Dispatch<SetStateAction<number | null>>;
  selectedTypeKey: string;
  setSelectedTypeKey: Dispatch<SetStateAction<string>>;
  draftInstanceId: number | null;
  setDraftInstanceId: Dispatch<SetStateAction<number | null>>;
  configDraft: JsonObject;
  setConfigDraft: Dispatch<SetStateAction<JsonObject>>;
  enabledDraft: boolean;
  setEnabledDraft: Dispatch<SetStateAction<boolean>>;
  intervalDraft: string;
  setIntervalDraft: Dispatch<SetStateAction<string>>;
  testedFingerprint: string | null;
  setTestedFingerprint: Dispatch<SetStateAction<string | null>>;
  deleteConfirmOpen: boolean;
  setDeleteConfirmOpen: Dispatch<SetStateAction<boolean>>;
}

export function useConnectorDrafts(): ConnectorDrafts {
  const [selectedInstanceId, setSelectedInstanceId] = useState<number | null>(
    null,
  );
  const [selectedTypeKey, setSelectedTypeKey] = useState("");
  const [draftInstanceId, setDraftInstanceId] = useState<number | null>(null);
  const [configDraft, setConfigDraft] = useState<JsonObject>({});
  const [enabledDraft, setEnabledDraft] = useState(false);
  const [intervalDraft, setIntervalDraft] = useState("300");
  const [testedFingerprint, setTestedFingerprint] = useState<string | null>(
    null,
  );
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  return {
    selectedInstanceId,
    setSelectedInstanceId,
    selectedTypeKey,
    setSelectedTypeKey,
    draftInstanceId,
    setDraftInstanceId,
    configDraft,
    setConfigDraft,
    enabledDraft,
    setEnabledDraft,
    intervalDraft,
    setIntervalDraft,
    testedFingerprint,
    setTestedFingerprint,
    deleteConfirmOpen,
    setDeleteConfirmOpen,
  };
}
