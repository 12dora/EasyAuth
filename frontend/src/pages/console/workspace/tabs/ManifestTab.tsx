/** 编排当前 Manifest、导入流程、差异预览与版本历史。 */

import { useQueryClient } from "@tanstack/react-query";

import { StatusBanner } from "../../../../components/StatusBanner";
import { CurrentManifestPanel } from "../manifest/CurrentManifestPanel";
import { ManifestDiffView } from "../manifest/ManifestDiffView";
import { ManifestHistory, useManifestHistory } from "../manifest/ManifestHistory";
import { ManifestImportPanel } from "../manifest/ManifestImportPanel";
import { manifestVersionsQueryPrefix } from "../manifest/manifestImportModel";
import { useManifestImport } from "../manifest/useManifestImport";

export function ManifestTab({ appKey }: { appKey: string }) {
  const queryClient = useQueryClient();
  const importState = useManifestImport(appKey);
  const historyState = useManifestHistory(appKey);
  const versionsQueryPrefix = manifestVersionsQueryPrefix(appKey);

  return (
    <section className="space-y-6">
      <CurrentManifestPanel
        appKey={appKey}
        onSaved={async () => {
          await queryClient.invalidateQueries({ queryKey: versionsQueryPrefix });
        }}
      />
      <ManifestImportPanel appKey={appKey} state={importState} />
      {historyState.query.error ? <StatusBanner live="alert" tone="signal" title="版本历史加载失败" message={(historyState.query.error as Error).message} /> : null}
      {importState.currentPreview ? <ManifestDiffView preview={importState.currentPreview.payload} /> : null}
      <ManifestHistory state={historyState} />
    </section>
  );
}
