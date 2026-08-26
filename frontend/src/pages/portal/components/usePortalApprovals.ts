import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import {
  ORDERING_PARAM,
  orderingSerializer,
  serverTableQuery,
  useServerTable,
  type ServerSortValue,
  type UseServerTableResult,
} from "../../../components/antd/AppTable";
import { useI18n } from "../../../i18n/I18nProvider";
import { ApiError, apiRequest } from "../../../lib/api";

import {
  applicationConflictRequiresResubmit,
  committedGrantStatus,
  parseApprovalDetailPayload,
  parseApprovalListPayload,
} from "./portalApprovalPayload";
import {
  DEFAULT_PAGE_SIZE,
  type ApprovalDetailState,
  type ApprovalListPayload,
  type ApprovalNoticeKey,
  type ApprovalTab,
  type PendingDecision,
  type PortalApprovalRow,
} from "./portalApprovalTypes";

/**
 * 列 key -> 后端 `ordering` 字段。
 * 提交时间列的 key 是 payload 的 submitted_at, 后端公开的排序字段名叫 created_at;
 * 申请人列的 key 就是 applicant。内容 / 期限 / 我的意见三列后端排不了。
 */
const APPROVAL_ORDERING_FIELDS = {
  submitted_at: "created_at",
  decided_at: "decided_at",
  app: "app_key",
  applicant: "applicant",
} as const;

/**
 * 两个页签的后端默认序不同: 待办按提交时间正序(最早的先处理), 已处理按决定时间倒序。
 * `defaultSort` 只在建 hook 时生效, 所以切页签时要显式把排序改到对应的默认值,
 * 否则已处理页会沿用待办的 created_at 序, 与后端默认行为不一致。
 */
const APPROVAL_DEFAULT_SORT: Record<ApprovalTab, ServerSortValue> = {
  pending: { field: "submitted_at", order: "ascend" },
  processed: { field: "decided_at", order: "descend" },
};

export interface PortalApprovalsController {
  tab: ApprovalTab;
  switchTab: (nextTab: ApprovalTab) => void;
  /** 分页与排序状态、antd onChange 的唯一容器; 两者都映射成后端查询参数。 */
  serverTable: UseServerTableResult<PortalApprovalRow>;
  query: UseQueryResult<ApprovalListPayload, Error>;
  approvals: PortalApprovalRow[];
  detail: ApprovalDetailState;
  noticeKey: ApprovalNoticeKey;
  pendingDecision: PendingDecision | null;
  openDecision: (mode: ApprovalDecisionMode, approval: PortalApprovalRow) => void;
  closeDecision: () => void;
  submitDecision: (decision: PendingDecision & { comment: string }) => void;
  isSubmitting: boolean;
  dialogErrorMessage: string;
}

/** 门户审批区的数据与决定流程: 列表分页、详情复核、同意/驳回提交与提示语状态。 */
export function usePortalApprovals(): PortalApprovalsController {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<ApprovalTab>("pending");
  const serverTable = useServerTable<PortalApprovalRow>({
    defaultPageSize: DEFAULT_PAGE_SIZE,
    sortParam: ORDERING_PARAM,
    defaultSort: APPROVAL_DEFAULT_SORT.pending,
    serializeSort: orderingSerializer(APPROVAL_ORDERING_FIELDS),
  });
  // status 由页签给出, 不走表头筛选; ordering 必须一起进查询串和查询键,
  // 否则点了表头也不会重新请求。
  const approvalsSearch = serverTableQuery({ status: tab, ...serverTable.params });
  const [pendingDecision, setPendingDecision] = useState<PendingDecision | null>(null);
  const [noticeKey, setNoticeKey] = useState<ApprovalNoticeKey>("");
  const [detailRequestVersion, setDetailRequestVersion] = useState(0);
  const decisionSubmittingRef = useRef(false);
  const pendingApprovalId = pendingDecision?.approval.id;

  const query = useQuery({
    queryKey: ["portal", "approvals", approvalsSearch],
    queryFn: async () =>
      parseApprovalListPayload(
        await apiRequest<unknown>(`/portal/api/v1/me/approvals?${approvalsSearch}`),
        t("portal.approvals.invalidPayload"),
      ),
  });
  const detailQuery = useQuery({
    queryKey: ["portal", "approvals", "detail", pendingApprovalId, detailRequestVersion],
    queryFn: async () =>
      parseApprovalDetailPayload(
        await apiRequest<unknown>(`/portal/api/v1/me/approvals/${pendingApprovalId ?? 0}`),
        t("portal.approvals.invalidPayload"),
        pendingApprovalId ?? 0,
      ),
    enabled: pendingApprovalId !== undefined,
  });
  const decisionMutation = useMutation({
    mutationFn: ({ mode, approval, comment }: PendingDecision & { comment: string }) =>
      apiRequest(`/portal/api/v1/me/approvals/${approval.id}/${mode}`, {
        method: "POST",
        body: mode === "reject" || comment ? { comment } : {},
      }),
    onSuccess: (_, variables) => {
      setPendingDecision(null);
      setNoticeKey(variables.mode === "approve" ? "approvals.approved" : "approvals.rejected");
      void queryClient.invalidateQueries({ queryKey: ["portal", "approvals"] });
    },
    onError: (error, variables) => {
      const settledNoticeKey = failedDecisionNoticeKey(error, variables.approval.id);
      if (settledNoticeKey) {
        setPendingDecision(null);
        setNoticeKey(settledNoticeKey);
        void queryClient.invalidateQueries({ queryKey: ["portal", "approvals"] });
      }
    },
    onSettled: () => {
      decisionSubmittingRef.current = false;
    },
  });

  const openDecision = (mode: ApprovalDecisionMode, approval: PortalApprovalRow) => {
    decisionSubmittingRef.current = false;
    decisionMutation.reset();
    setNoticeKey("");
    setDetailRequestVersion((current) => current + 1);
    setPendingDecision({ mode, approval });
  };
  const closeDecision = () => {
    if (decisionSubmittingRef.current || decisionMutation.isPending) {
      return;
    }
    setPendingDecision(null);
  };
  const submitDecision = (decision: PendingDecision & { comment: string }) => {
    decisionSubmittingRef.current = true;
    decisionMutation.mutate(decision);
  };
  const switchTab = (nextTab: ApprovalTab) => {
    setTab(nextTab);
    // setSort 自带「回到第 1 页」, 因此不必再 setPage(1)。
    serverTable.setSort(APPROVAL_DEFAULT_SORT[nextTab]);
  };

  // 服务端总页数收缩时(别的审批人先处理掉了)当前页可能已越界, 钳回最后一页。
  const totalPages = query.data?.pagination.total_pages;
  const currentPage = serverTable.query.page;
  const setPage = serverTable.setPage;
  useEffect(() => {
    if (totalPages === undefined) {
      return;
    }
    const lastPage = Math.max(1, totalPages);
    if (currentPage > lastPage) {
      setPage(lastPage);
    }
  }, [currentPage, setPage, totalPages]);

  const dialogErrorMessage =
    decisionMutation.error && !(decisionMutation.error instanceof ApiError && decisionMutation.error.status === 409)
      ? (decisionMutation.error as Error).message
      : "";

  // 总条数拿到响应后回填进 serverTable.tableProps, 页面不再手工拼 pagination。
  serverTable.setTotal(query.data?.pagination.total_items);

  return {
    tab,
    switchTab,
    serverTable,
    query,
    approvals: query.data?.data ?? [],
    detail: {
      approval: detailQuery.data?.approval,
      isLoading: detailQuery.isLoading,
      isFetching: detailQuery.isFetching,
      error: detailQuery.error,
    },
    noticeKey,
    pendingDecision,
    openDecision,
    closeDecision,
    submitDecision,
    isSubmitting: decisionMutation.isPending,
    dialogErrorMessage,
  };
}

/**
 * 决定提交失败但仍需清空待办的两类结果:
 * 决定已提交但授权未落地是复合结果, 不得保留旧待办或允许重复提交;
 * 409 冲突则按是否需要重新提交给出不同提示。
 */
function failedDecisionNoticeKey(error: Error, approvalId: number): ApprovalNoticeKey | null {
  const committedStatus = committedGrantStatus(error, approvalId);
  if (committedStatus) {
    return committedStatus === "grant_failed" ? "approvals.grantFailedCommitted" : "status.request.grantExpired";
  }
  if (error instanceof ApiError && error.status === 409) {
    return applicationConflictRequiresResubmit(error) ? "approvals.resubmitRequired" : "approvals.conflict";
  }
  return null;
}
