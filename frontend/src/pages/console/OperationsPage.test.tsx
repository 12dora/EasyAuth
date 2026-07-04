import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { OperationsPage } from "./OperationsPage";

describe("OperationsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.dataset.currentUserRole = "";
    document.documentElement.dataset.currentUserRole = "";
  });

  test("系统管理员打开运营页时请求运营 API 并渲染数据", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === "/console/api/v1/operations/access-requests") {
        return jsonResponse({
          data: [
            {
              id: 101,
              user_id: "user-a",
              app_key: "crm",
              status: "pending",
              request_type: "grant",
              submitted_at: "2026-07-02T00:00:00Z",
            },
          ],
        });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderOperationsPage();

    await waitFor(() => {
      expect(screen.getByText("user-a")).toBeInTheDocument();
      expect(screen.getByText("crm")).toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-requests",
        expect.objectContaining({ credentials: "include" }),
      );
    });
  });
});

function renderOperationsPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/console/operations/access-requests"]}>
        <Routes>
          <Route path="/console/operations/:section" element={<OperationsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
