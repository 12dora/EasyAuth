import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { I18nProvider } from "../../../i18n/I18nProvider";
import type { HandoverTaskDetail, HandoverTeamItemRow } from "../../../lib/domain";
import { TeamAdjustSection } from "./TeamAdjustSection";

describe("TeamAdjustSection", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("只读接任人展示姓名与部门, 不展示 user_id", () => {
    renderSection(
      [
        pendingItem({
          to_user: { user_id: "u-8", name: "赵六", department: "客服部" },
        }),
      ],
      false,
    );

    expect(screen.getByText("赵六")).toBeVisible();
    expect(screen.getByText("客服部")).toBeVisible();
    expect(screen.queryByText("u-8")).not.toBeInTheDocument();
  });

  test("只读接任人只有 ID 时按 employee 口径解析姓名", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.includes("user_ids=")) {
        return jsonResponse({
          data: [{ user_id: "u-9", name: "王五", department: "捷发-安环部", avatar_url: "" }],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSection(
      [
        pendingItem({
          to_user: { user_id: "u-9", name: "" },
        }),
      ],
      false,
    );

    expect(await screen.findByText("王五")).toBeVisible();
    expect(screen.getByText("捷发-安环部")).toBeVisible();
    expect(screen.queryByText("u-9")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.map(([input]) => String(input)).filter((url) => url.includes("user_ids=")),
      ).toEqual(["/console/api/v1/user-options?user_ids=u-9&purpose=employee"]);
    });
  });

  test("已指定接任人的完成态展示姓名与部门", () => {
    renderSection(
      [
        {
          id: 3,
          team_id: 30,
          team_name: "已交接团队",
          action: "assign_leader",
          status: "done",
          to_user: { user_id: "u-7", name: "周七", department: "销售部" },
        },
      ],
      false,
    );

    expect(screen.getByText("已由 周七 · 销售部 接任负责人")).toBeVisible();
    expect(screen.queryByText("u-7")).not.toBeInTheDocument();
  });
});

function renderSection(teamItems: HandoverTeamItemRow[], canOperate: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderWithProviders(
    <QueryClientProvider client={client}>
      <TeamAdjustSection task={task(teamItems)} taskId="1" onChanged={() => {}} canOperate={canOperate} />
    </QueryClientProvider>,
  );
}

function renderWithProviders(ui: ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

function pendingItem(overrides: Partial<HandoverTeamItemRow>): HandoverTeamItemRow {
  return {
    id: 2,
    team_id: 20,
    team_name: "待调整团队",
    action: "assign_leader",
    status: "pending",
    to_user: null,
    ...overrides,
  };
}

function task(team_items: HandoverTeamItemRow[]): HandoverTaskDetail {
  return {
    id: 1,
    kind: "offboard",
    status: "in_progress",
    generation: 1,
    subject: { user_id: "u-1", name: "张三" },
    assignee: null,
    assignee_state: "manager",
    escalation_level: 0,
    escalation: { deadline: null, days_left: null, level: 0, deferred_at: null, defer_history: [] },
    reason: "",
    created_at: "2026-07-01T09:00:00Z",
    actions: [],
    team_items,
  };
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
