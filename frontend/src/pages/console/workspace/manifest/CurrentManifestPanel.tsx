/** 获取、展示并保存当前 Manifest 内容。 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { Pencil, RefreshCcw, Save, X } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "../../../../components/Button";
import { CodeBlock } from "../../../../components/CodeBlock";
import { TextArea } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useToast } from "../../../../components/ui/Toast";
import { useI18n } from "../../../../i18n/I18nProvider";
import { apiRequest } from "../../../../lib/api";
import type { JsonObject } from "../../../../lib/api";
import { manifestContentFingerprint, type ManifestImportPayload, type ManifestPreviewPayload } from "./manifestImportModel";

export function CurrentManifestPanel({ appKey, onSaved }: { appKey: string; onSaved: () => Promise<void> }) {
  const { t } = useI18n();
  const state = useCurrentManifest(appKey, onSaved);
  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-ink">{t("manifest.current.title")}</h2>
          <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("manifest.current.description")}</p>
        </div>
        <CurrentManifestActions state={state} />
      </div>
      {state.manifestQuery.error ? (
        <StatusBanner live="alert" tone="signal" title={t("manifest.current.loadFailed")} message={(state.manifestQuery.error as Error).message} />
      ) : null}
      {state.jsonError ? <StatusBanner live="alert" tone="signal" title={state.jsonError} /> : null}
      <CurrentManifestContent state={state} />
    </PanelSurface>
  );
}

function useCurrentManifest(appKey: string, onSaved: () => Promise<void>) {
  const { t } = useI18n();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const draftRef = useRef("");
  const [jsonError, setJsonError] = useState("");
  const manifestQuery = useQuery({
    queryKey: ["console", "app", appKey, "manifest"],
    queryFn: () => apiRequest<JsonObject>(`/console/api/v1/apps/${appKey}/manifest`),
  });
  const manifestText = manifestQuery.data ? JSON.stringify(manifestQuery.data, null, 2) : "";
  const saveMutation = useMutation({
    mutationFn: async ({ draftSnapshot, draftFingerprint }: { draftSnapshot: string; draftFingerprint: string }) => {
      const preview = await apiRequest<ManifestPreviewPayload>(
        `/console/api/v1/apps/${appKey}/permission-template-imports/preview`,
        { method: "POST", body: { template_format: "json", template: draftSnapshot } },
      );
      if (!preview.preview_id) {
        throw new Error(t("manifest.current.saveFailedNoPreview"));
      }
      if (draftFingerprint !== manifestContentFingerprint(draftRef.current)) {
        throw new Error("Manifest 内容已变化，请重新保存。");
      }
      return apiRequest<ManifestImportPayload>(
        `/console/api/v1/apps/${appKey}/permission-template-imports/${preview.preview_id}/confirm`,
        { method: "POST" },
      );
    },
    onSuccess: async (payload) => {
      const version = String(payload.catalog_version ?? payload.template_version ?? "");
      toast.success(t("manifest.current.saveSuccess"), `catalog_version: ${version}`);
      setEditing(false);
      await manifestQuery.refetch();
      await onSaved();
    },
    onError: (error: Error) => {
      toast.error(t("manifest.current.saveFailed"), error.message);
    },
  });
  return createCurrentManifestState({ t, manifestQuery, manifestText, saveMutation, editing, setEditing, draft, setDraft, draftRef, jsonError, setJsonError });
}

function createCurrentManifestState(state: CurrentManifestBaseState) {
  const startEdit = () => {
    if (!state.manifestQuery.data) {
      return;
    }
    const currentVersion = Number(state.manifestQuery.data.schema_version ?? 0);
    // 导入管线要求 schema_version 严格递增, 进入编辑时预先自动 +1。
    const draftManifest = { ...state.manifestQuery.data, schema_version: currentVersion + 1 };
    const nextDraft = JSON.stringify(draftManifest, null, 2);
    state.draftRef.current = nextDraft;
    state.setDraft(nextDraft);
    state.setJsonError("");
    state.setEditing(true);
  };
  const save = () => {
    try {
      JSON.parse(state.draft);
    } catch {
      state.setJsonError(state.t("manifest.current.invalidJson"));
      return;
    }
    state.setJsonError("");
    state.saveMutation.mutate({ draftSnapshot: state.draft, draftFingerprint: manifestContentFingerprint(state.draft) });
  };
  return { ...state, startEdit, save };
}

type CurrentManifestBaseState = {
  t: ReturnType<typeof useI18n>["t"];
  manifestQuery: ReturnType<typeof useQuery<JsonObject>>;
  manifestText: string;
  saveMutation: ReturnType<typeof useMutation<ManifestImportPayload, Error, { draftSnapshot: string; draftFingerprint: string }>>;
  editing: boolean;
  setEditing: (editing: boolean) => void;
  draft: string;
  setDraft: (draft: string) => void;
  draftRef: React.MutableRefObject<string>;
  jsonError: string;
  setJsonError: (error: string) => void;
};

type CurrentManifestState = ReturnType<typeof useCurrentManifest>;

function CurrentManifestActions({ state }: { state: CurrentManifestState }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button icon={<RefreshCcw size={15} />} loading={state.manifestQuery.isFetching} onClick={() => void state.manifestQuery.refetch()}>
        {t("manifest.current.refresh")}
      </Button>
      {state.editing ? (
        <>
          <Button icon={<X size={15} />} disabled={state.saveMutation.isPending} onClick={() => state.setEditing(false)}>
            {t("manifest.current.cancel")}
          </Button>
          <Button variant="primary" icon={<Save size={15} />} loading={state.saveMutation.isPending} disabled={state.saveMutation.isPending} onClick={state.save}>
            {t("manifest.current.save")}
          </Button>
        </>
      ) : (
        <Button icon={<Pencil size={15} />} disabled={!state.manifestQuery.data} onClick={state.startEdit}>
          {t("manifest.current.edit")}
        </Button>
      )}
    </div>
  );
}

function CurrentManifestContent({ state }: { state: CurrentManifestState }) {
  const { t } = useI18n();
  if (state.editing) {
    return (
      <>
        <TextArea
          aria-label={t("manifest.current.title")}
          rows={18}
          className="font-mono text-xs leading-5"
          value={state.draft}
          disabled={state.saveMutation.isPending}
          onChange={(event) => {
            state.draftRef.current = event.currentTarget.value;
            state.setDraft(event.currentTarget.value);
          }}
        />
        <p className="text-body text-ink-soft">{t("manifest.current.saveHint")}</p>
      </>
    );
  }
  return state.manifestQuery.data ? (
    <div className="max-h-96 overflow-y-auto">
      <CodeBlock language="json" code={state.manifestText} />
    </div>
  ) : null;
}
