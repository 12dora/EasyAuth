import { useQuery } from "@tanstack/react-query";
import { RefreshCcw } from "lucide-react";

import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { PageHeader } from "../../../components/PageHeader";
import { EmptyState } from "../../../components/ui/EmptyState";
import { PageState } from "../../../components/ui/PageState";
import { MONO_TEXT_CLASS } from "../../../components/ui/tableStyles";
import {
  TableBody,
  TableCell,
  TableEmptyRow,
  TableFrame,
  TableHead,
  TableHeaderCell,
  TableRoot,
  TableRow,
  TableSkeletonRows,
} from "../../../components/ui/TablePrimitives";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest } from "../../../lib/api";
import type { HandoverBlockedAppsPayload } from "../../../lib/domain";
import type { OperationSectionConfig } from "./operationQuery";

type BlockedApp = HandoverBlockedAppsPayload["apps"][number];

/** 未接入应用清单：数据源为 lifecycle/handover-blocked-apps，非 operations 通用列表信封。 */
export function BlockedAppsOperationsSection({ config }: { config: OperationSectionConfig }) {
  const { t } = useI18n();
  const query = useQuery({
    queryKey: ["console", "operations", "blocked-apps"],
    queryFn: () => apiRequest<HandoverBlockedAppsPayload>(config.endpoint),
  });
  const apps = query.data?.apps ?? [];

  return (
    <>
      <PageHeader
        eyebrow={t("nav.console.operations")}
        title={t(config.titleKey)}
        description={t("handover.console.blockedApps.description")}
        actions={
          <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
            {t("common.refresh")}
          </Button>
        }
      />
      {query.error && apps.length === 0 ? (
        <PageState
          tone="signal"
          title={t("console.operations.loadFailed")}
          description={(query.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <BlockedAppsTable apps={apps} isLoading={query.isLoading} />
      )}
    </>
  );
}

function BlockedAppsTable({ apps, isLoading }: { apps: BlockedApp[]; isLoading: boolean }) {
  const { t } = useI18n();

  return (
    <TableFrame>
      <TableRoot>
        <TableHead>
          <TableRow>
            <TableHeaderCell>{t("handover.console.blockedApps.column.app")}</TableHeaderCell>
            <TableHeaderCell>{t("handover.console.blockedApps.column.blockedTasks")}</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {isLoading ? (
            <TableSkeletonRows columns={2} />
          ) : apps.length > 0 ? (
            apps.map((app) => (
              <TableRow key={app.app_key}>
                <TableCell>
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <strong>{app.app_name || app.app_key}</strong>
                    <code className={MONO_TEXT_CLASS}>{app.app_key}</code>
                  </div>
                </TableCell>
                <TableCell>
                  <Badge tone="signal">{app.blocked_task_count}</Badge>
                </TableCell>
              </TableRow>
            ))
          ) : (
            <TableEmptyRow colSpan={2}>
              <EmptyState title={t("handover.console.blockedApps.empty")} />
            </TableEmptyRow>
          )}
        </TableBody>
      </TableRoot>
    </TableFrame>
  );
}
