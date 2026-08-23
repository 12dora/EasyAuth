import { useQuery } from "@tanstack/react-query";
import { useRef, type FormEvent } from "react";

import { apiRequest } from "../../../../lib/api";
import type { ConnectorsPayload } from "../../../../lib/domain";
import { connectorCandidateFingerprint } from "./connectorFormat";
import { useConnectorDrafts } from "./connectorDrafts";
import { connectorFormFlags } from "./connectorFormState";
import { useConnectorMutations } from "./connectorMutations";
import { createSelectionChanger, useConnectorSelection } from "./connectorSelection";

export type ConnectorInstanceFormController = ReturnType<typeof useConnectorInstanceForm>;

export function useConnectorInstanceForm(appKey: string, canManage: boolean) {
  const connectorsQuery = useQuery({
    queryKey: ["console", "app", appKey, "connectors"],
    queryFn: () =>
      apiRequest<ConnectorsPayload>(
        `/console/api/v1/apps/${appKey}/connectors`,
      ),
    enabled: Boolean(appKey),
  });
  const drafts = useConnectorDrafts();
  const selection = useConnectorSelection(connectorsQuery, drafts);
  const { instance } = selection;

  const connectorKey = instance?.connector_key ?? drafts.selectedTypeKey;
  const candidateFingerprint = connectorCandidateFingerprint(
    connectorKey,
    instance?.id ?? null,
    drafts.configDraft,
  );
  const currentCandidateFingerprint = useRef(candidateFingerprint);
  currentCandidateFingerprint.current = candidateFingerprint;

  const mutations = useConnectorMutations({
    appKey,
    drafts,
    instance,
    currentCandidateFingerprint,
  });
  const flags = connectorFormFlags({
    canManage,
    instance,
    activeType: selection.activeType,
    connectorKey,
    selectedTypeKey: drafts.selectedTypeKey,
    configDraft: drafts.configDraft,
    enabledDraft: drafts.enabledDraft,
    draftInstanceId: drafts.draftInstanceId,
    testedFingerprint: drafts.testedFingerprint,
    candidateFingerprint,
    connectorsLoaded: connectorsQuery.isSuccess && !connectorsQuery.error,
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    mutations.saveMutation.mutate();
  };
  const runTest = () => {
    mutations.testMutation.mutate({
      connectorKey,
      instanceId: instance?.id ?? null,
      config: drafts.configDraft,
      fingerprint: candidateFingerprint,
    });
  };

  return {
    canManage,
    connectorsQuery,
    drafts,
    selection,
    mutations,
    flags,
    changeSelection: createSelectionChanger(selection.instances, drafts),
    submit,
    runTest,
  };
}
