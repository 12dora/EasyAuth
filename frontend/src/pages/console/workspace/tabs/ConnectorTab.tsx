import { ConnectorDeleteDialog } from "../connector/ConnectorDeleteDialog";
import { ConnectorInstancePanel } from "../connector/ConnectorInstancePanel";
import { MappingsPanel } from "../connector/MappingsPanel";
import { SyncRunsPanel } from "../connector/SyncRunsPanel";
import { useConnectorInstanceForm } from "../connector/useConnectorInstanceForm";

export function ConnectorTab({ appKey, canManage }: { appKey: string; canManage: boolean }) {
  const controller = useConnectorInstanceForm(appKey, canManage);
  const { instance } = controller.selection;

  return (
    <section className="space-y-6">
      <ConnectorInstancePanel controller={controller} />
      {instance ? (
        <MappingsPanel
          key={`mappings:${instance.id}`}
          appKey={appKey}
          instance={instance}
          canManage={canManage}
        />
      ) : null}
      {instance ? (
        <SyncRunsPanel
          key={`runs:${instance.id}`}
          appKey={appKey}
          instance={instance}
        />
      ) : null}
      {controller.drafts.deleteConfirmOpen && instance ? (
        <ConnectorDeleteDialog controller={controller} />
      ) : null}
    </section>
  );
}
