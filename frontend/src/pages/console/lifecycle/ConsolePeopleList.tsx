import { RefreshCcw } from "lucide-react";
import { useState } from "react";

import { Button } from "../../../components/Button";
import { PageHeader } from "../../../components/PageHeader";
import { StatusBanner } from "../../../components/StatusBanner";
import { PageState } from "../../../components/ui/PageState";
import { useI18n } from "../../../i18n/I18nProvider";
import { ConsoleHandoverStartDialog } from "./ConsoleHandoverStartDialog";
import { ConsolePeopleFilters } from "./ConsolePeopleFilters";
import { ConsolePeopleTable } from "./ConsolePeopleTable";
import { ConsoleReassignDialog } from "./ConsoleReassignDialog";
import { useConsolePeopleList } from "./useConsolePeopleList";

export function ConsolePeopleList() {
  const { t } = useI18n();
  const page = useConsolePeopleList();
  const { peopleQuery, people, startTarget, createTaskMutation } = page;
  const [reassignOpen, setReassignOpen] = useState(false);

  return (
    <>
      <PageHeader
        eyebrow={t("console.teams.eyebrow")}
        title={t("nav.console.people")}
        description={t("people.description")}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="ghost" onClick={() => setReassignOpen(true)}>
              {t("handover.console.reassign")}
            </Button>
            <Button icon={<RefreshCcw size={16} />} loading={peopleQuery.isFetching} onClick={() => void peopleQuery.refetch()}>
              {t("common.refresh")}
            </Button>
          </div>
        }
      />
      <ConsolePeopleFilters searchInput={page.searchInput} onSearchChange={page.setSearchInput} />
      {peopleQuery.error && people.length > 0 ? (
        <StatusBanner live="alert" tone="signal" title={t("people.loadFailed")} message={(peopleQuery.error as Error).message} />
      ) : null}
      {peopleQuery.error && people.length === 0 ? (
        <PageState
          tone="signal"
          title={t("people.loadFailed")}
          description={(peopleQuery.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={peopleQuery.isFetching} onClick={() => void peopleQuery.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <ConsolePeopleTable
          people={people}
          isLoading={peopleQuery.isLoading || peopleQuery.isPlaceholderData}
          tableProps={page.tableProps}
          actions={{
            onOpenHandover: page.openHandover,
            onStart: (person, kind) => page.startHandover({ person, kind }),
          }}
        />
      )}
      {startTarget ? (
        <ConsoleHandoverStartDialog
          target={startTarget}
          errorMessage={createTaskMutation.error ? (createTaskMutation.error as Error).message : ""}
          isSubmitting={createTaskMutation.isPending}
          onClose={() => page.setStartTarget(null)}
          onSubmit={(reason) => createTaskMutation.mutate({ ...startTarget, reason })}
        />
      ) : null}
      {reassignOpen ? <ConsoleReassignDialog onClose={() => setReassignOpen(false)} /> : null}
    </>
  );
}
