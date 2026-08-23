import { apiRequest } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import type { AuthorizationGroupItem } from "../../../../lib/domain";
import { parseAuthorizationGroupsPayload } from "../connectorsContract";

const AUTHORIZATION_GROUP_CONNECTOR_PAGE_SIZE = 100;
const AUTHORIZATION_GROUP_CONNECTOR_MAX_PAGES = 1000;

export async function fetchActiveAuthorizationGroups(appKey: string): Promise<ListPayload<AuthorizationGroupItem>> {
  const data: AuthorizationGroupItem[] = [];
  for (let page = 1; page <= AUTHORIZATION_GROUP_CONNECTOR_MAX_PAGES; page += 1) {
    const payload = parseAuthorizationGroupsPayload(
      await apiRequest<unknown>(
        `/console/api/v1/apps/${appKey}/authorization-groups?status=active&page=${page}&page_size=${AUTHORIZATION_GROUP_CONNECTOR_PAGE_SIZE}`,
      ),
    );
    data.push(...payload.data);
    if (!payload.pagination) {
      throw new Error("AUTHORIZATION_GROUP_PAGINATION_MISSING");
    }
    if (payload.pagination.page >= payload.pagination.total_pages) {
      return { data, pagination: payload.pagination };
    }
  }
  throw new Error("AUTHORIZATION_GROUP_PAGE_LIMIT_EXCEEDED");
}

export function connectorsQueryKey(appKey: string): string[] {
  return ["console", "app", appKey, "connectors"];
}
