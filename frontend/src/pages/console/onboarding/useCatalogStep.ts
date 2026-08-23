import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { apiRequest } from "../../../lib/api";
import type { ManifestImportRequest, ManifestPreviewPayload, ManifestPreviewRequest, ManifestPreviewSnapshot } from "./types";
import { detectTemplateFormat, manifestContentFingerprint, parseManifestImportResult } from "./wizardParsing";

export interface CatalogStepState {
  content: string;
  previewPending: boolean;
  importPending: boolean;
  importedCatalogVersion: string | null;
  currentPreview: ManifestPreviewPayload | null;
  confirmDisabled: boolean;
  previewError: Error | null;
  importError: Error | null;
  updateContent: (nextContent: string) => void;
  selectFile: (file: File) => void;
  previewCurrentContent: () => void;
  importCurrentPreview: () => void;
}

/** 目录导入的本地状态机: 内容指纹 + 请求序号双重把关, 保证过期的预览/导入响应不会落到界面上。 */
export function useCatalogStep(appKey: string, onImportPendingChange: (pending: boolean) => void): CatalogStepState {
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState<ManifestPreviewSnapshot | null>(null);
  const [importedCatalogVersion, setImportedCatalogVersion] = useState<string | null>(null);
  const contentRequestIdRef = useRef(0);
  const fileReadIdRef = useRef(0);
  const previewMutation = useMutation({
    mutationFn: (request: ManifestPreviewRequest) =>
      apiRequest<ManifestPreviewPayload>(`/console/api/v1/apps/${appKey}/permission-template-imports/preview`, {
        method: "POST",
        body: { template_format: detectTemplateFormat(request.content), template: request.content },
      }),
    onSuccess: (payload, request) => {
      if (request.requestId === contentRequestIdRef.current) {
        setPreview({ payload, contentFingerprint: request.contentFingerprint, requestId: request.requestId });
      }
    },
  });
  const importMutation = useMutation({
    mutationFn: async (request: ManifestImportRequest) =>
      parseManifestImportResult(
        await apiRequest<unknown>(
          `/console/api/v1/apps/${appKey}/permission-template-imports/${request.previewId}/confirm`,
          { method: "POST" },
        ),
      ),
    onSuccess: (payload, request) => {
      if (
        request.requestId !== contentRequestIdRef.current ||
        request.contentFingerprint !== manifestContentFingerprint(content)
      ) {
        return;
      }
      setImportedCatalogVersion(String(payload.catalog_version ?? payload.template_version));
      setPreview(null);
    },
  });
  const importPending = importMutation.isPending;

  useEffect(() => {
    onImportPendingChange(importPending);
    if (!importPending) {
      return;
    }
    const preventUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", preventUnload);
    return () => window.removeEventListener("beforeunload", preventUnload);
  }, [importPending, onImportPendingChange]);

  useEffect(
    () => () => {
      onImportPendingChange(false);
    },
    [onImportPendingChange],
  );

  const invalidateCatalogResult = () => {
    contentRequestIdRef.current += 1;
    setPreview(null);
    setImportedCatalogVersion(null);
  };

  const updateContent = (nextContent: string) => {
    fileReadIdRef.current += 1;
    invalidateCatalogResult();
    setContent(nextContent);
  };

  const selectFile = (file: File) => {
    const fileReadId = fileReadIdRef.current + 1;
    fileReadIdRef.current = fileReadId;
    invalidateCatalogResult();
    void file.text().then((fileContent) => {
      if (fileReadId === fileReadIdRef.current) {
        setContent(fileContent);
      }
    });
  };

  const previewCurrentContent = () => {
    const requestId = contentRequestIdRef.current + 1;
    const contentFingerprint = manifestContentFingerprint(content);
    contentRequestIdRef.current = requestId;
    setPreview(null);
    setImportedCatalogVersion(null);
    previewMutation.mutate({ content, contentFingerprint, requestId });
  };

  const importCurrentPreview = () => {
    const previewId = preview?.payload.preview_id;
    const currentFingerprint = manifestContentFingerprint(content);
    if (!previewId || preview.contentFingerprint !== currentFingerprint || preview.requestId !== contentRequestIdRef.current) {
      setPreview(null);
      return;
    }
    onImportPendingChange(true);
    importMutation.mutate({ previewId, contentFingerprint: currentFingerprint, requestId: preview.requestId });
  };

  const previewIsCurrent =
    preview?.contentFingerprint === manifestContentFingerprint(content) && preview.requestId === contentRequestIdRef.current;

  return {
    content,
    previewPending: previewMutation.isPending,
    importPending,
    importedCatalogVersion,
    currentPreview: previewIsCurrent && preview ? preview.payload : null,
    confirmDisabled: !previewIsCurrent || !preview?.payload.preview_id || importPending,
    previewError: previewMutation.variables?.requestId === contentRequestIdRef.current ? previewMutation.error : null,
    importError: importMutation.variables?.requestId === contentRequestIdRef.current ? importMutation.error : null,
    updateContent,
    selectFile,
    previewCurrentContent,
    importCurrentPreview,
  };
}
