import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { TeamPayload } from "../../lib/domain";
import { ConsoleTeamDetail } from "./ConsoleTeamDetail";

const INITIAL_TEAM: TeamPayload = {
  team: {
    id: 7,
    name: "旧团队",
    description: "旧描述",
    is_active: false,
    leaders: [],
    member_count: 0,
    members: [],
    created_at: "2026-07-01T09:00:00Z",
    updated_at: "2026-07-01T09:00:00Z",
  },
};

describe("ConsoleTeamDetail", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("mutation 成功后取消在途详情查询，旧 GET 响应不能覆盖新状态", async () => {
    const staleRequest = deferred<Response>();
    let getRequestCount = 0;
    const staleRequestSignals: AbortSignal[] = [];
    const updatedTeam = teamPayload({ name: "更新后的团队", is_active: true });
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/teams/7" && !init?.method) {
        getRequestCount += 1;
        if (getRequestCount === 1) {
          return Promise.resolve(jsonResponse(INITIAL_TEAM));
        }
        if (init?.signal) {
          staleRequestSignals.push(init.signal);
        }
        return staleRequest.promise;
      }
      if (url === "/console/api/v1/teams/7" && init?.method === "PATCH") {
        return Promise.resolve(jsonResponse(updatedTeam));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const client = renderDetail();

    expect(await screen.findByRole("heading", { name: "旧团队" })).toBeVisible();
    void client.invalidateQueries({ queryKey: ["console", "teams", "7"], exact: true });
    await waitFor(() => expect(getRequestCount).toBe(2));

    await user.click(screen.getByRole("button", { name: "启用" }));

    expect(await screen.findByRole("heading", { name: "更新后的团队" })).toBeVisible();
    expect(staleRequestSignals[0]?.aborted).toBe(true);

    staleRequest.resolve(jsonResponse(INITIAL_TEAM));
    await waitFor(() => expect(screen.getByRole("heading", { name: "更新后的团队" })).toBeVisible());
    expect(screen.queryByRole("heading", { name: "旧团队" })).not.toBeInTheDocument();
  });

  test("同一团队的写请求串行执行，较早响应不能回滚后续修改", async () => {
    const enableRequest = deferred<Response>();
    const saveRequest = deferred<Response>();
    let patchRequestCount = 0;
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/teams/7" && !init?.method) {
        return Promise.resolve(jsonResponse(INITIAL_TEAM));
      }
      if (url === "/console/api/v1/teams/7" && init?.method === "PATCH") {
        patchRequestCount += 1;
        return patchRequestCount === 1 ? enableRequest.promise : saveRequest.promise;
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderDetail();

    expect(await screen.findByRole("heading", { name: "旧团队" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "启用" }));
    await waitFor(() => expect(patchCalls(fetchMock)).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: "编辑" }));
    const dialog = await screen.findByRole("dialog", { name: "编辑团队信息" });
    const nameInput = within(dialog).getByLabelText("名称");
    await user.clear(nameInput);
    await user.type(nameInput, "新团队名");
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    expect(within(dialog).getByRole("button", { name: "保存" })).toBeDisabled();
    expect(patchCalls(fetchMock)).toHaveLength(1);

    enableRequest.resolve(jsonResponse(teamPayload({ is_active: true })));
    await waitFor(() => expect(patchCalls(fetchMock)).toHaveLength(2));
    expect(JSON.parse(String(patchCalls(fetchMock)[1]?.[1]?.body))).toEqual({
      name: "新团队名",
      description: "旧描述",
    });

    saveRequest.resolve(jsonResponse(teamPayload({ name: "新团队名", is_active: true })));
    expect(await screen.findByRole("heading", { name: "新团队名" })).toBeVisible();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "编辑团队信息" })).not.toBeInTheDocument());
  });

  test("保存团队期间不可关闭弹窗", async () => {
    const saveRequest = deferred<Response>();
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/teams/7" && !init?.method) {
        return Promise.resolve(jsonResponse(INITIAL_TEAM));
      }
      if (url === "/console/api/v1/teams/7" && init?.method === "PATCH") {
        return saveRequest.promise;
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderDetail();

    expect(await screen.findByRole("heading", { name: "旧团队" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "编辑" }));
    const dialog = await screen.findByRole("dialog", { name: "编辑团队信息" });
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => expect(patchCalls(fetchMock)).toHaveLength(1));
    expect(within(dialog).getByRole("button", { name: "保存" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "取消" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "关闭弹窗" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog", { name: "编辑团队信息" })).toBeVisible();

    saveRequest.resolve(jsonResponse(teamPayload({ name: "旧团队" })));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "编辑团队信息" })).not.toBeInTheDocument());
  });
});

function renderDetail(): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/console/teams/7"]}>
        <Routes>
          <Route path="/console/teams/:teamId" element={<ConsoleTeamDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

function patchCalls(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>) {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === "PATCH");
}

function teamPayload(overrides: Partial<NonNullable<TeamPayload["team"]>>): TeamPayload {
  return {
    team: {
      ...INITIAL_TEAM.team!,
      ...overrides,
      updated_at: "2026-07-10T09:00:00Z",
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
