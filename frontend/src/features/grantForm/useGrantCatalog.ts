import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

import type { ApiError } from "../../lib/api";
import { apiRequest } from "../../lib/api";
import type { PortalRequestCatalogView } from "../../pages/portal/hooks/accessRequestTypes";
import { parsePortalRequestCatalog } from "../../pages/portal/requestCatalogContract";

/**
 * 控制台授权目录。
 *
 * 后端 /console/api/v1/grant-catalog 与门户申请目录是同一份序列化结构(approver_options 恒为空数组),
 * 因此直接复用门户的契约解析: 形状不符时抛错, 不做任何字段兜底。
 */
export function useGrantCatalog(): UseQueryResult<PortalRequestCatalogView, ApiError> {
  return useQuery<PortalRequestCatalogView, ApiError>({
    queryKey: ["console", "grant-catalog"],
    queryFn: async ({ signal }) =>
      parsePortalRequestCatalog(await apiRequest<unknown>("/console/api/v1/grant-catalog", { signal })),
  });
}
