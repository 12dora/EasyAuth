/** 渲染 Manifest 文件选择、文本输入和导入操作。 */

import { Download, Eye, FileUp, UploadCloud } from "lucide-react";

import { Button } from "../../../../components/Button";
import { Field, TextArea } from "../../../../components/Field";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import type { useManifestImport } from "./useManifestImport";

type ManifestImportState = ReturnType<typeof useManifestImport>;

export function ManifestImportPanel({ appKey, state }: { appKey: string; state: ManifestImportState }) {
  return (
    <>
      <PanelSurface className="flex flex-wrap items-center gap-2">
        <input
          ref={state.fileInputRef}
          type="file"
          accept=".json,.yaml,.yml,application/json,text/yaml,text/plain"
          className="sr-only"
          aria-label="上传 Manifest 文件"
          disabled={state.importMutation.isPending}
          onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            if (!file) {
              return;
            }
            state.selectFile(file);
          }}
        />
        <Button icon={<FileUp size={16} />} disabled={state.importMutation.isPending} onClick={() => state.fileInputRef.current?.click()}>
          上传文件
        </Button>
        <Button
          icon={<Download size={16} />}
          onClick={() => {
            window.location.assign(`/console/api/v1/apps/${appKey}/manifest`);
          }}
        >
          导出清单
        </Button>
      </PanelSurface>
      <Field label="Manifest 内容" hint="支持粘贴 JSON 或 YAML；上传文件后会填充到这里。">
        <TextArea
          aria-label="Manifest 内容"
          rows={10}
          value={state.content}
          disabled={state.importMutation.isPending}
          onChange={(event) => state.changeContent(event.currentTarget.value)}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          icon={<Eye size={16} />}
          disabled={!state.content || state.previewMutation.isPending}
          onClick={state.previewContent}
        >
          预览差异
        </Button>
        <Button
          variant="primary"
          icon={<UploadCloud size={16} />}
          disabled={!state.currentPreview?.payload.preview_id || state.importMutation.isPending}
          onClick={state.confirmImport}
        >
          确认导入
        </Button>
      </div>
    </>
  );
}
