/** 管理 Manifest 文件读取、文本变更、预览与确认导入状态。 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { useToast } from "../../../../components/ui/Toast";
import { apiRequest } from "../../../../lib/api";
import {
  manifestContentFingerprint,
  manifestVersionsQueryPrefix,
  type ManifestImportPayload,
  type ManifestPreviewBinding,
  type ManifestPreviewPayload,
} from "./manifestImportModel";

type ImportRefs = {
  contentRef: React.MutableRefObject<string>;
  contentGenerationRef: React.MutableRefObject<number>;
  previewRequestRef: React.MutableRefObject<number>;
};

export function useManifestImport(appKey: string) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const contentRef = useRef("");
  const contentGenerationRef = useRef(0);
  const previewRequestRef = useRef(0);
  const fileReadRef = useRef(0);
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState<ManifestPreviewBinding | null>(null);
  const refs = { contentRef, contentGenerationRef, previewRequestRef };
  const previewMutation = usePreviewMutation(appKey, refs, setPreview);
  const importMutation = useImportMutation(appKey, refs);
  const updateContent = (nextContent: string) => {
    contentRef.current = nextContent;
    contentGenerationRef.current += 1;
    previewRequestRef.current += 1;
    setContent(nextContent);
    setPreview(null);
  };
  const currentPreview =
    preview &&
    preview.generation === contentGenerationRef.current &&
    preview.contentFingerprint === manifestContentFingerprint(content)
      ? preview
      : null;

  return {
    fileInputRef, content, currentPreview, previewMutation, importMutation,
    selectFile: (file: File) => selectFile(file, fileReadRef, refs, setPreview, updateContent),
    changeContent: (nextContent: string) => {
      fileReadRef.current += 1;
      updateContent(nextContent);
    },
    previewContent: () => previewContent(refs, previewMutation.mutate),
    confirmImport: () => confirmImport(currentPreview, importMutation.mutate),
  };
}

function usePreviewMutation(
  appKey: string,
  refs: ImportRefs,
  setPreview: (preview: ManifestPreviewBinding | null) => void,
) {
  const toast = useToast();
  const { contentRef, contentGenerationRef, previewRequestRef } = refs;
  return useMutation({
    mutationFn: ({ contentSnapshot }: { contentSnapshot: string; contentFingerprint: string; generation: number; requestId: number }) =>
      apiRequest<ManifestPreviewPayload>(`/console/api/v1/apps/${appKey}/permission-template-imports/preview`, {
        method: "POST",
        body: { template_format: "json", template: contentSnapshot },
      }),
    onSuccess: (payload, variables) => {
      if (
        variables.requestId !== previewRequestRef.current ||
        variables.generation !== contentGenerationRef.current ||
        variables.contentFingerprint !== manifestContentFingerprint(contentRef.current)
      ) {
        return;
      }
      setPreview({ payload, contentFingerprint: variables.contentFingerprint, generation: variables.generation });
    },
    onError: (error: Error, variables) => {
      if (variables.requestId !== previewRequestRef.current || variables.generation !== contentGenerationRef.current) {
        return;
      }
      toast.error("Manifest 预览失败", error.message);
    },
  });
}

function useImportMutation(appKey: string, refs: ImportRefs) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const versionsQueryPrefix = manifestVersionsQueryPrefix(appKey);
  const { contentRef, contentGenerationRef } = refs;
  return useMutation({
    mutationFn: ({ previewId, contentFingerprint, generation }: { previewId: string; contentFingerprint: string; generation: number }) => {
      if (generation !== contentGenerationRef.current || contentFingerprint !== manifestContentFingerprint(contentRef.current)) {
        throw new Error("Manifest 内容已变化，请重新预览后再导入。");
      }
      return apiRequest<ManifestImportPayload>(`/console/api/v1/apps/${appKey}/permission-template-imports/${previewId}/confirm`, {
        method: "POST",
      });
    },
    onSuccess: async (payload) => {
      const version = String(payload.catalog_version ?? payload.template_version ?? "");
      toast.success("导入成功", `当前目录版本：${version}`);
      await queryClient.invalidateQueries({ queryKey: versionsQueryPrefix });
    },
    onError: (error: Error) => {
      toast.error("Manifest 导入失败", error.message);
    },
  });
}

function selectFile(
  file: File,
  fileReadRef: React.MutableRefObject<number>,
  refs: ImportRefs,
  setPreview: (preview: ManifestPreviewBinding | null) => void,
  updateContent: (content: string) => void,
) {
  const fileReadId = ++fileReadRef.current;
  refs.previewRequestRef.current += 1;
  refs.contentGenerationRef.current += 1;
  setPreview(null);
  void file.text().then((fileContent) => {
    if (fileReadId === fileReadRef.current) {
      updateContent(fileContent);
    }
  });
}

function previewContent(refs: ImportRefs, mutate: ReturnType<typeof usePreviewMutation>["mutate"]) {
  const requestId = ++refs.previewRequestRef.current;
  const contentSnapshot = refs.contentRef.current;
  mutate({
    contentSnapshot,
    contentFingerprint: manifestContentFingerprint(contentSnapshot),
    generation: refs.contentGenerationRef.current,
    requestId,
  });
}

function confirmImport(
  currentPreview: ManifestPreviewBinding | null,
  mutate: ReturnType<typeof useImportMutation>["mutate"],
) {
  const previewId = currentPreview?.payload.preview_id;
  if (!previewId || !currentPreview) {
    return;
  }
  mutate({
    previewId,
    contentFingerprint: currentPreview.contentFingerprint,
    generation: currentPreview.generation,
  });
}
