import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import type { AuthorizationGroupItem } from "../../../../lib/domain";

const AUTHORIZATION_GROUP_MATRIX_PAGE_SIZE = 100;
const AUTHORIZATION_GROUP_MATRIX_MAX_PAGES = 1000;

/** 逐页拉全量授权组(含停用), 缺分页元信息或超过页数上限直接抛错, 不做静默截断。 */
export async function fetchAllAuthorizationGroups(appKey: string): Promise<ListPayload<AuthorizationGroupItem>> {
  const data: AuthorizationGroupItem[] = [];
  for (let page = 1; page <= AUTHORIZATION_GROUP_MATRIX_MAX_PAGES; page += 1) {
    const payload = await apiRequest<ListPayload<AuthorizationGroupItem>>(
      `/console/api/v1/apps/${appKey}/authorization-groups?include_inactive=true&page=${page}&page_size=${AUTHORIZATION_GROUP_MATRIX_PAGE_SIZE}`,
    );
    data.push(...itemsFromPayload<AuthorizationGroupItem>(payload));
    if (!payload.pagination) {
      throw new Error("AUTHORIZATION_GROUP_PAGINATION_MISSING");
    }
    if (payload.pagination.page >= payload.pagination.total_pages) {
      return { data, pagination: payload.pagination };
    }
  }
  throw new Error("AUTHORIZATION_GROUP_PAGE_LIMIT_EXCEEDED");
}
