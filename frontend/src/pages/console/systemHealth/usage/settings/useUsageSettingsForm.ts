import { useEffect, useState } from "react";

import type { UsageMetricKey, UsageOverLimitPolicy, UsageSettingsPayload } from "../usageTypes";
import type { ApiOverLimitPolicy, UsageSettingsSection } from "./usageSettingsDocument";
import {
  documentToForm,
  firstErrorSection,
  formToDocument,
  formsEqual,
  validateForm,
  type UsageAlertsFormState,
  type UsageFieldErrors,
  type UsageMetricFormState,
  type UsageSettingsFormState,
} from "./usageSettingsForm";
import { isVersionConflict, serverFieldErrors, useSaveUsageSettings, useUsageSettingsQuery } from "./useUsageSettings";

interface EditorState {
  version: number;
  /** 载入时的表单快照, 用来判断脏状态; 保存成功后整体替换。 */
  baseline: UsageSettingsFormState;
  draft: UsageSettingsFormState;
}

export interface UsageSettingsController {
  query: ReturnType<typeof useUsageSettingsQuery>;
  saveMutation: ReturnType<typeof useSaveUsageSettings>;
  payload: UsageSettingsPayload | undefined;
  form: UsageSettingsFormState | null;
  section: UsageSettingsSection;
  errors: UsageFieldErrors;
  dirty: boolean;
  conflict: boolean;
  /** 服务端版本比本地载入的新: 有人在别处改过。 */
  staleRemote: boolean;
  pendingPolicy: ApiOverLimitPolicy | null;
  pendingClose: boolean;
  setSection: (section: UsageSettingsSection) => void;
  updateMetric: (metric: UsageMetricKey, updater: (current: UsageMetricFormState) => UsageMetricFormState) => void;
  updateAlerts: (updater: (current: UsageAlertsFormState) => UsageAlertsFormState) => void;
  selectPolicy: (metric: UsageMetricKey, policy: UsageOverLimitPolicy) => void;
  confirmPolicy: () => void;
  cancelPolicy: () => void;
  requestClose: () => void;
  confirmClose: () => void;
  cancelClose: () => void;
  reload: () => void;
  submit: () => void;
}

export function useUsageSettingsForm(onClose: () => void): UsageSettingsController {
  const query = useUsageSettingsQuery();
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [section, setSection] = useState<UsageSettingsSection>("api");
  const [clientErrors, setClientErrors] = useState<UsageFieldErrors>({});
  const [pendingClose, setPendingClose] = useState(false);
  const [pendingPolicy, setPendingPolicy] = useState<ApiOverLimitPolicy | null>(null);
  const saveMutation = useSaveUsageSettings((saved) => {
    setEditor(editorFromPayload(saved));
    setClientErrors({});
  });
  const payload = query.data;

  useEffect(() => {
    if (payload === undefined || editor !== null) {
      return;
    }
    setEditor(editorFromPayload(payload));
  }, [editor, payload]);

  const dirty = editor !== null && !formsEqual(editor.baseline, editor.draft);
  const updateDraft = (updater: (current: UsageSettingsFormState) => UsageSettingsFormState) => {
    setEditor((current) => (current === null ? current : { ...current, draft: updater(current.draft) }));
  };
  const applyPolicy = (metric: UsageMetricKey, policy: UsageOverLimitPolicy) => {
    updateDraft((form) => withMetric(form, metric, { ...form[metric], policy }));
  };

  const submit = () => {
    if (editor === null) {
      return;
    }
    const errors = validateForm(editor.draft);
    setClientErrors(errors);
    const target = firstErrorSection(errors);
    if (target !== null) {
      setSection(target);
      return;
    }
    saveMutation.reset();
    saveMutation.mutate({ config: formToDocument(editor.draft), version: editor.version });
  };

  return {
    query,
    saveMutation,
    payload,
    form: editor?.draft ?? null,
    section,
    errors: { ...serverFieldErrors(saveMutation.error), ...clientErrors },
    dirty,
    conflict: isVersionConflict(saveMutation.error),
    staleRemote: payload !== undefined && editor !== null && payload.version !== editor.version,
    pendingPolicy,
    pendingClose,
    setSection,
    updateMetric: (metric, updater) => updateDraft((form) => withMetric(form, metric, updater(form[metric]))),
    updateAlerts: (updater) => updateDraft((form) => ({ ...form, alerts: updater(form.alerts) })),
    selectPolicy: (metric, policy) => {
      // 「全部禁止」会连登录一起拦掉, 必须先显式确认再落到表单上。
      if (metric === "api" && policy === "block_all") {
        setPendingPolicy("block_all");
        return;
      }
      applyPolicy(metric, policy);
    },
    confirmPolicy: () => {
      if (pendingPolicy !== null) {
        applyPolicy("api", pendingPolicy);
      }
      setPendingPolicy(null);
    },
    cancelPolicy: () => setPendingPolicy(null),
    requestClose: () => {
      if (dirty) {
        setPendingClose(true);
        return;
      }
      onClose();
    },
    confirmClose: () => {
      setPendingClose(false);
      onClose();
    },
    cancelClose: () => setPendingClose(false),
    reload: () => {
      saveMutation.reset();
      setClientErrors({});
      void query.refetch().then((result) => {
        if (result.data !== undefined) {
          setEditor(editorFromPayload(result.data));
        }
      });
    },
    submit,
  };
}

function editorFromPayload(payload: UsageSettingsPayload): EditorState {
  const form = documentToForm(payload.config);
  return { version: payload.version, baseline: form, draft: documentToForm(payload.config) };
}

function withMetric(
  form: UsageSettingsFormState,
  metric: UsageMetricKey,
  next: UsageMetricFormState,
): UsageSettingsFormState {
  if (metric === "api") {
    return { ...form, api: next };
  }
  return metric === "webhook" ? { ...form, webhook: next } : { ...form, stream: next };
}
