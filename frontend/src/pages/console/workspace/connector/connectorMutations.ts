import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { RefObject } from "react";

import { useToast } from "../../../../components/ui/Toast";
import { useI18n } from "../../../../i18n/I18nProvider";
import { apiRequest } from "../../../../lib/api";
import type { JsonObject } from "../../../../lib/api";
import type {
  ConnectorInstanceItem,
  ConnectorInstancePayload,
  ConnectorsPayload,
  ConnectorTestResult,
} from "../../../../lib/domain";
import { parseConnectorIntervalSeconds } from "../connectorsContract";
import { connectorsQueryKey } from "./connectorApi";
import type { ConnectorDrafts } from "./connectorDrafts";

export interface TestCandidate {
  connectorKey: string;
  instanceId: number | null;
  config: JsonObject;
  fingerprint: string;
}

export interface ConnectorMutationDeps {
  appKey: string;
  drafts: ConnectorDrafts;
  instance: ConnectorInstanceItem | null;
  currentCandidateFingerprint: RefObject<string>;
}

export type ConnectorMutations = ReturnType<typeof useConnectorMutations>;

export function useConnectorMutations(deps: ConnectorMutationDeps) {
  return {
    testMutation: useConnectorTestMutation(deps),
    saveMutation: useConnectorSaveMutation(deps),
    reconcileMutation: useConnectorReconcileMutation(deps),
    deleteMutation: useConnectorDeleteMutation(deps),
  };
}

function useConnectorTestMutation({
  appKey,
  drafts,
  currentCandidateFingerprint,
}: ConnectorMutationDeps) {
  const { t } = useI18n();
  const toast = useToast();
  return useMutation({
    mutationFn: (candidate: TestCandidate) =>
      apiRequest<ConnectorTestResult>(
        `/console/api/v1/apps/${appKey}/connectors/test`,
        {
          method: "POST",
          body: {
            connector_key: candidate.connectorKey,
            config: candidate.config,
          } satisfies JsonObject,
        },
      ),
    onSuccess: (payload, candidate) => {
      if (candidate.fingerprint !== currentCandidateFingerprint.current) {
        return;
      }
      if (payload.ok) {
        drafts.setTestedFingerprint(candidate.fingerprint);
        toast.success(t("console.connector.testPassed"), payload.message);
        return;
      }
      drafts.setTestedFingerprint(null);
      toast.error(t("console.connector.testFailed"), payload.message);
    },
    onError: (error: Error, candidate) => {
      if (candidate.fingerprint !== currentCandidateFingerprint.current) {
        return;
      }
      drafts.setTestedFingerprint(null);
      toast.error(t("console.connector.testFailed"), error.message);
    },
  });
}

function useConnectorSaveMutation({ appKey, drafts, instance }: ConnectorMutationDeps) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => {
      const body = {
        enabled: drafts.enabledDraft,
        reconcile_interval_seconds: parseConnectorIntervalSeconds(drafts.intervalDraft),
        config: drafts.configDraft,
      } satisfies JsonObject;
      if (instance) {
        return apiRequest<ConnectorInstancePayload>(
          `/console/api/v1/apps/${appKey}/connectors/${instance.id}`,
          { method: "PUT", body },
        );
      }
      return apiRequest<ConnectorInstancePayload>(
        `/console/api/v1/apps/${appKey}/connectors`,
        {
          method: "POST",
          body: {
            ...body,
            connector_key: drafts.selectedTypeKey,
          } satisfies JsonObject,
        },
      );
    },
    onSuccess: (payload) => {
      queryClient.setQueryData<ConnectorsPayload>(
        connectorsQueryKey(appKey),
        (current) => {
          if (!current) {
            return current;
          }
          const next = current.data.filter(
            (item) => item.id !== payload.connector.id,
          );
          return { ...current, data: [...next, payload.connector] };
        },
      );
      drafts.setSelectedTypeKey("");
      drafts.setSelectedInstanceId(payload.connector.id);
      drafts.setDraftInstanceId(payload.connector.id);
      drafts.setTestedFingerprint(null);
      void queryClient.invalidateQueries({ queryKey: connectorsQueryKey(appKey) });
      toast.success(t("console.connector.saveSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("console.connector.saveFailed"), error.message);
    },
  });
}

function useConnectorReconcileMutation({ appKey, instance }: ConnectorMutationDeps) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<{ queued: boolean }>(
        `/console/api/v1/apps/${appKey}/connectors/${instance?.id}/reconcile`,
        {
          method: "POST",
          body: {} satisfies JsonObject,
        },
      ),
    onSuccess: (payload) => {
      if (payload.queued) {
        toast.success(t("console.connector.reconcileQueued"));
      } else {
        toast.info(t("console.connector.reconcileCoalesced"));
      }
      void queryClient.invalidateQueries({
        queryKey: ["console", "app", appKey, "connector-sync-runs"],
      });
    },
    onError: (error: Error) => {
      toast.error(t("console.connector.reconcileFailed"), error.message);
    },
  });
}

function useConnectorDeleteMutation({ appKey, drafts, instance }: ConnectorMutationDeps) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest(`/console/api/v1/apps/${appKey}/connectors/${instance?.id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      const deletedInstanceId = instance?.id;
      queryClient.setQueryData<ConnectorsPayload>(
        connectorsQueryKey(appKey),
        (current) =>
          current && deletedInstanceId
            ? {
                ...current,
                data: current.data.filter(
                  (item) => item.id !== deletedInstanceId,
                ),
              }
            : current,
      );
      drafts.setDeleteConfirmOpen(false);
      drafts.setSelectedInstanceId(null);
      drafts.setSelectedTypeKey("");
      drafts.setDraftInstanceId(null);
      drafts.setConfigDraft({});
      drafts.setEnabledDraft(false);
      drafts.setTestedFingerprint(null);
      void queryClient.invalidateQueries({ queryKey: connectorsQueryKey(appKey) });
      toast.success(t("console.connector.deleteSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("console.connector.deleteFailed"), error.message);
    },
  });
}
