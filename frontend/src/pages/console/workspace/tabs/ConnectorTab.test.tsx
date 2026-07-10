import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ToastProvider } from "../../../../components/ui/Toast";
import { ConnectorTab } from "./ConnectorTab";

const connectorTypes = [
  {
    key: "fake",
    display_name: "Fake A",
    config_schema: {
      type: "object",
      properties: { endpoint: { type: "string", title: "Endpoint A" } },
      required: ["endpoint"],
    },
  },
  {
    key: "other",
    display_name: "Fake B",
    config_schema: {
      type: "object",
      properties: { endpoint: { type: "string", title: "Endpoint B" } },
      required: ["endpoint"],
    },
  },
];

const instances = [
  connectorInstance(11, "fake", "Fake A", "https://a.example.com"),
  connectorInstance(22, "other", "Fake B", "https://b.example.com"),
];

describe("ConnectorTab", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("连接器多实例都可选择和维护", async () => {
    const fetchMock = installConnectorFetch();
    const user = userEvent.setup();
    renderWithClient(<ConnectorTab appKey="demo" />);

    const selector = await screen.findByLabelText("连接器类型");
    await waitFor(() => expect(selector).toHaveValue("instance:11"));
    await waitFor(() =>
      expect(screen.getByLabelText("Endpoint A *")).toHaveValue(
        "https://a.example.com",
      ),
    );

    await user.selectOptions(selector, "instance:22");

    expect(await screen.findByLabelText("Endpoint B *")).toHaveValue(
      "https://b.example.com",
    );
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/apps/demo/connectors/22/mappings",
        expect.any(Object),
      );
    });
  });

  test("启用或修改启用态配置必须通过当前候选连接测试", async () => {
    const fetchMock = installConnectorFetch({ instances: [instances[0]] });
    const user = userEvent.setup();
    renderWithClient(<ConnectorTab appKey="demo" />);

    const endpoint = await screen.findByLabelText("Endpoint A *");
    const formPanel = screen
      .getByRole("heading", { name: "出站供给连接器" })
      .closest("section");
    expect(formPanel).not.toBeNull();
    const save = within(formPanel as HTMLElement).getByRole("button", {
      name: "保存",
    });
    const enabled = within(formPanel as HTMLElement).getByRole("checkbox", {
      name: "启用连接器",
    });

    await user.click(enabled);
    expect(save).toBeDisabled();
    await user.click(
      within(formPanel as HTMLElement).getByRole("button", {
        name: "测试连接",
      }),
    );
    await waitFor(() => expect(save).toBeEnabled());

    await user.clear(endpoint);
    await user.type(endpoint, "https://changed.example.com");
    expect(save).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledWith(
      "/console/api/v1/apps/demo/connectors/test",
      expect.objectContaining({ method: "POST" }),
    );
  });

  test("mapping 权威读取失败时禁止整表保存并可重试", async () => {
    installConnectorFetch({ instances: [instances[0]], mappingsFail: true });
    const user = userEvent.setup();
    renderWithClient(<ConnectorTab appKey="demo" />);

    const heading = await screen.findByRole("heading", { name: "授权组映射" });
    const panel = heading.closest("section");
    expect(panel).not.toBeNull();
    expect(
      within(panel as HTMLElement).getByRole("button", { name: "保存" }),
    ).toBeDisabled();
    expect(
      await within(panel as HTMLElement).findByText("连接器配置加载失败"),
    ).toBeInTheDocument();
    expect(
      within(panel as HTMLElement).getByRole("button", { name: "重新加载" }),
    ).toBeEnabled();

    await user.click(
      within(panel as HTMLElement).getByRole("button", { name: "重新加载" }),
    );
  });

  test("运行历史使用服务端总数并可访问第二页", async () => {
    const fetchMock = installConnectorFetch({ instances: [instances[0]] });
    const user = userEvent.setup();
    renderWithClient(<ConnectorTab appKey="demo" />);

    expect(
      await screen.findByText("第 1-10 条 / 共 12 条"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下一页" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/apps/demo/connectors/11/sync-runs?page=2&page_size=10",
        expect.any(Object),
      );
    });
    expect(
      await screen.findByText("第 11-12 条 / 共 12 条"),
    ).toBeInTheDocument();
  });
});

function installConnectorFetch({
  instances: configuredInstances = instances,
  mappingsFail = false,
}: {
  instances?: typeof instances;
  mappingsFail?: boolean;
} = {}) {
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (url === "/console/api/v1/apps/demo/connectors") {
      return jsonResponse({
        connector_types: connectorTypes,
        data: configuredInstances,
      });
    }
    if (
      url === "/console/api/v1/apps/demo/connectors/test" &&
      init?.method === "POST"
    ) {
      return jsonResponse({ ok: true, message: "ok" });
    }
    if (url === "/console/api/v1/apps/demo/authorization-groups") {
      return jsonResponse({
        data: [{ key: "vpn", name: "VPN", is_active: true }],
      });
    }
    if (url.endsWith("/external-groups")) {
      return jsonResponse({ data: [] });
    }
    if (url.endsWith("/mappings")) {
      return mappingsFail
        ? jsonResponse(
            { code: "internal_error", message: "mapping read failed" },
            500,
          )
        : jsonResponse({ data: [], revision: "a".repeat(64) });
    }
    if (url.includes("/sync-runs?")) {
      const page =
        new URL(url, "https://example.test").searchParams.get("page") === "2"
          ? 2
          : 1;
      const count = page === 2 ? 2 : 10;
      return jsonResponse({
        data: Array.from({ length: count }, (_, index) =>
          syncRun((page - 1) * 10 + index + 1),
        ),
        pagination: { page, page_size: 10, total_items: 12, total_pages: 2 },
      });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function connectorInstance(
  id: number,
  connectorKey: string,
  displayName: string,
  endpoint: string,
) {
  return {
    id,
    connector_key: connectorKey,
    display_name: displayName,
    enabled: false,
    config: { endpoint },
    configured_secrets: [],
    reconcile_interval_seconds: 300,
    last_reconcile_at: null,
    last_status: "",
    last_error: "",
    consecutive_failures: 0,
    updated_by: "admin",
    updated_at: "2026-07-10T00:00:00Z",
  };
}

function syncRun(id: number) {
  return {
    id,
    trigger: "manual",
    status: "success",
    started_at: `2026-07-10T00:${String(id).padStart(2, "0")}:00Z`,
    finished_at: `2026-07-10T00:${String(id).padStart(2, "0")}:01Z`,
    stats: {},
    error: "",
  };
}

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
