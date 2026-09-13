import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { useHandoverTaskDetail } from "./useHandoverTaskDetail";

const VALID_TASK = {
  id: 1,
  kind: "offboard",
  status: "in_progress",
  created_by: "admin",
  created_by_person: null,
  escalation: { deadline: null, days_left: null, level: 0, deferred_at: null, defer_history: [] },
  actions: [],
};

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderDetailHook() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderHook(() => useHandoverTaskDetail("1"), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    ),
  });
}

describe("useHandoverTaskDetail", () => {
  afterEach(() => vi.unstubAllGlobals());

  test("详情缺少 created_by_person 立即失败", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        jsonResponse({
          handover_task: {
            id: 1,
            kind: "offboard",
            status: "in_progress",
            created_by: "admin",
            escalation: { defer_history: [] },
          },
        }),
      ),
    );

    const { result } = renderDetailHook();
    await waitFor(() => expect(result.current.taskQuery.isError).toBe(true));
    expect(result.current.taskQuery.error).toMatchObject({
      message: expect.stringMatching(/created_by_person/),
    });
    expect(result.current.task).toBeUndefined();
  });

  test("认领响应缺少 created_by_person 不写入缓存", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input, init) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.endsWith("/claim") && method === "POST") {
          const { created_by_person: _dropped, ...withoutPerson } = VALID_TASK;
          return jsonResponse({ handover_task: withoutPerson });
        }
        if (url === "/console/api/v1/lifecycle/handover-tasks/1" && method === "GET") {
          return jsonResponse({ handover_task: VALID_TASK });
        }
        throw new Error(`${method} ${url}`);
      }),
    );

    const { result } = renderDetailHook();
    await waitFor(() => expect(result.current.taskQuery.isSuccess).toBe(true));
    expect(result.current.task?.created_by_person).toBeNull();

    act(() => {
      result.current.claimMutation.mutate();
    });
    await waitFor(() => expect(result.current.claimMutation.isError).toBe(true));
    expect(result.current.claimMutation.error).toMatchObject({
      message: expect.stringMatching(/created_by_person/),
    });
    expect(result.current.task?.created_by_person).toBeNull();
  });
});
