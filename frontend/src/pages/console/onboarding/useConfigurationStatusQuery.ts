import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../../../lib/api";
import { parseConfigurationStatus } from "./wizardParsing";

/** 配置检查步骤与完成步骤共用同一份配置状态查询, 保持 queryKey 一致以复用缓存。 */
export function useConfigurationStatusQuery(appKey: string) {
  return useQuery({
    queryKey: ["console", "app", appKey, "configuration-status"],
    queryFn: async () =>
      parseConfigurationStatus(await apiRequest<unknown>(`/console/api/v1/apps/${appKey}/configuration-status`), appKey),
    enabled: Boolean(appKey),
  });
}
