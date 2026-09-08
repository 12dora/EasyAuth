import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

import type { ApiError, JsonValue } from "../../lib/api";
import { apiRequest } from "../../lib/api";
import { parseAccessGrantRow } from "../../lib/domain/accessGrantRow";
import type { AccessGrantRow } from "../../lib/domain/accessGrantRow";

/**
 * 某员工在某应用上的当前授权(`GET /console/api/v1/users/<user_id>/apps/<app_key>/current-grant`)。
 *
 * 管理员是在"现状"上做加减, 而不是从空表单重新发明一份授权, 因此选定被授权人与应用后必须先读回它。
 * 返回 null 表示这个人在这个应用上还没有生效授权; 响应形状不符即视为契约违约, 不做兜底。
 */
export function useCurrentGrant(
  userId: string,
  appKey: string,
): UseQueryResult<AccessGrantRow | null, ApiError> {
  return useQuery<AccessGrantRow | null, ApiError>({
    queryKey: ["console", "current-grant", userId, appKey],
    queryFn: async ({ signal }) =>
      parseCurrentGrantPayload(
        await apiRequest<unknown>(
          `/console/api/v1/users/${encodeURIComponent(userId)}/apps/${encodeURIComponent(appKey)}/current-grant`,
          { signal },
        ),
      ),
    enabled: userId !== "" && appKey !== "",
  });
}

export function parseCurrentGrantPayload(payload: unknown): AccessGrantRow | null {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("当前授权响应必须是对象");
  }
  const grant = (payload as Record<string, unknown>).grant;
  if (grant === undefined) {
    throw new Error("当前授权响应缺少 grant 字段");
  }
  if (grant === null) {
    return null;
  }
  return parseAccessGrantRow(grant as JsonValue);
}
