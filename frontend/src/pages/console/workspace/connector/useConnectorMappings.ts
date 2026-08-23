import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useToast } from "../../../../components/ui/Toast";
import { useI18n } from "../../../../i18n/I18nProvider";
import { apiRequest } from "../../../../lib/api";
import type { JsonObject, ListPayload } from "../../../../lib/api";
import type { ConnectorExternalGroupItem } from "../../../../lib/domain";
import {
  parseConnectorMappingsPayload,
  type ConnectorMappingsPayload,
} from "../connectorsContract";
import { fetchActiveAuthorizationGroups } from "./connectorApi";

export interface MappingDraft {
  external_ref: string;
  auto_create: boolean;
}

export type ConnectorMappingsController = ReturnType<typeof useConnectorMappings>;

export function useConnectorMappings(appKey: string, instanceId: number) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const mappingsQueryKey = [
    "console",
    "app",
    appKey,
    "connector-mappings",
    instanceId,
  ];
  const [drafts, setDrafts] = useState<Record<string, MappingDraft>>({});

  const groupsQuery = useQuery({
    queryKey: ["console", "app", appKey, "authorization-groups"],
    queryFn: () => fetchActiveAuthorizationGroups(appKey),
    enabled: Boolean(appKey),
  });
  const mappingsQuery = useQuery({
    queryKey: mappingsQueryKey,
    queryFn: async () =>
      parseConnectorMappingsPayload(
        await apiRequest<unknown>(
          `/console/api/v1/apps/${appKey}/connectors/${instanceId}/mappings`,
        ),
      ),
  });
  const externalGroupsQuery = useQuery({
    queryKey: [
      "console",
      "app",
      appKey,
      "connector-external-groups",
      instanceId,
    ],
    queryFn: () =>
      apiRequest<ListPayload<ConnectorExternalGroupItem>>(
        `/console/api/v1/apps/${appKey}/connectors/${instanceId}/external-groups`,
      ),
    retry: false,
  });

  const groups = (groupsQuery.data?.data ?? []).filter(
    (group) => group.is_active,
  );
  const externalGroups = externalGroupsQuery.data?.data ?? [];
  const datalistId = `connector-external-groups-${instanceId}`;
  const authoritativeMappingsLoaded =
    mappingsQuery.isSuccess &&
    !mappingsQuery.error &&
    groupsQuery.isSuccess &&
    !groupsQuery.error;

  useEffect(() => {
    if (!mappingsQuery.data) {
      return;
    }
    const mappings = mappingsQuery.data.data;
    setDrafts(
      Object.fromEntries(
        mappings.map((mapping) => [
          mapping.authorization_group_key,
          {
            external_ref: mapping.external_ref,
            auto_create: mapping.auto_create,
          },
        ]),
      ),
    );
  }, [mappingsQuery.data]);

  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<ConnectorMappingsPayload>(
        `/console/api/v1/apps/${appKey}/connectors/${instanceId}/mappings`,
        {
          method: "PUT",
          body: {
            revision: mappingsQuery.data?.revision ?? "",
            mappings: Object.entries(drafts)
              .filter(([, draft]) => draft.external_ref.trim() !== "")
              .map(([groupKey, draft]) => ({
                authorization_group_key: groupKey,
                external_ref: draft.external_ref.trim(),
                auto_create: draft.auto_create,
              })),
          } satisfies JsonObject,
        },
      ),
    onSuccess: (payload) => {
      queryClient.setQueryData(mappingsQueryKey, payload);
      toast.success(t("console.connector.mappingsSaveSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("console.connector.mappingsSaveFailed"), error.message);
    },
  });

  const setDraft = (groupKey: string, patch: Partial<MappingDraft>) => {
    setDrafts((current) => {
      const base = current[groupKey] ?? {
        external_ref: "",
        auto_create: false,
      };
      return { ...current, [groupKey]: { ...base, ...patch } };
    });
  };

  return {
    groupsQuery,
    mappingsQuery,
    externalGroupsQuery,
    groups,
    externalGroups,
    datalistId,
    authoritativeMappingsLoaded,
    drafts,
    setDraft,
    saveMutation,
  };
}
