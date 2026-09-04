import { useEffect } from "react";

import type { PortalListPayload } from "./portalListPayload";

/** 门户列表默认页大小; 三张表口径一致。 */
export const PORTAL_DEFAULT_PAGE_SIZE = 20;

/** 服务端总页数收缩时把当前页钳制回最后一页, 否则会停在不存在的空页。 */
export function useClampPage<T>(
  payload: PortalListPayload<T> | undefined,
  page: number,
  setPage: (page: number) => void,
) {
  const totalPages = payload?.pagination.total_pages;
  useEffect(() => {
    if (totalPages === undefined) {
      return;
    }
    const lastPage = Math.max(1, totalPages);
    if (page > lastPage) {
      setPage(lastPage);
    }
  }, [page, setPage, totalPages]);
}
