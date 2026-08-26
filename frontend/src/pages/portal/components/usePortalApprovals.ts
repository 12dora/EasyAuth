import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import { useServerTable, type UseServerTableResult } from "../../../components/antd/AppTable";
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

export interface PortalApprovalsController {
  tab: ApprovalTab;
  switchTab: (nextTab: ApprovalTab) => void;
  /** 分页状态与 antd onChange 的唯一容器; 排序/筛选在这张表上都是客户端行为。 */
  serverTable: UseServerTableResult<PortalApprovalRow>;
  totalItems: number;
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
  // 后端只认 status(由页签给出)+page+page_size: serializeSort 置空,
  // 表头排序退化为 antd 对当前页的客户端排序。
  const serverTable = useServerTable<PortalApprovalRow>({
    defaultPageSize: DEFAULT_PAGE_SIZE,
    serializeSort: () => ({}),
  });
  const { page, page_size: pageSize } = serverTable.params;
  const [pendingDecision, setPendingDecision] = useState<PendingDecision | null>(null);
  const [noticeKey, setNoticeKey] = useState<ApprovalNoticeKey>("");
  const [detailRequestVersion, setDetailRequestVersion] = useState(0);
  const decisionSubmittingRef = useRef(false);
  const pendingApprovalId = pendingDecision?.approval.id;

  const query = useQuery({
    queryKey: ["portal", "approvals", tab, page, pageSize],
    queryFn: async () =>
      parseApprovalListPayload(
        await apiRequest<unknown>(
          `/portal/api/v1/me/approvals?status=${tab}&page=${page}&page_size=${pageSize}`,
        ),
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
    serverTable.setPage(1);
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

  return {
    tab,
    switchTab,
    serverTable,
    totalItems: query.data?.pagination.total_items ?? 0,
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
