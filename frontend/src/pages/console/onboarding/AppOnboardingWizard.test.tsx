import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { AppOnboardingWizard } from "./AppOnboardingWizard";

describe("AppOnboardingWizard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("无 app_key 时展示基本信息表单, 创建成功后进入权限目录步骤", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps" && init?.method === "POST") {
        return jsonResponse({ app: { id: 9, app_key: "billing", name: "Billing" } }, 201);
      }
      if (url === "/console/api/v1/apps/billing" && !init?.method) {
        return jsonResponse({ app: { id: 9, app_key: "billing", name: "Billing", owners: ["owner-a"] } });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWizard("/console/apps/new");

    expect(await screen.findByRole("heading", { name: "注册应用基本信息" })).toBeVisible();
    await user.type(screen.getByLabelText("app_key"), "billing");
    await user.type(screen.getByLabelText("名称"), "Billing");
    await user.type(screen.getByLabelText("Owner 用户 ID"), "owner-a");
    await user.click(screen.getByRole("button", { name: "创建并继续" }));

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(([input, init]) => String(input) === "/console/api/v1/apps" && init?.method === "POST");
      expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
        app_key: "billing",
        name: "Billing",
        description: "",
        is_active: true,
        owner_user_ids: ["owner-a"],
        developer_user_ids: [],
      });
    });
    expect(await screen.findByRole("heading", { name: "导入权限目录 Manifest" })).toBeVisible();
  });

  test("自动接入成功后可直接进入配置检查步骤", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/auto-onboarding" && init?.method === "POST") {
        return jsonResponse({
          app_key: "billing",
          app_name: "Billing",
          created: true,
          already_up_to_date: false,
          template_version: 4,
          catalog_version: 5,
        });
      }
      if (url === "/console/api/v1/apps/billing" && !init?.method) {
        return jsonResponse({ app: { id: 9, app_key: "billing", name: "Billing" } });
      }
      if (url.startsWith("/console/api/v1/apps/billing/configuration-status")) {
        return jsonResponse({ issues: [] });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWizard("/console/apps/new");

    expect(await screen.findByRole("heading", { name: "注册应用基本信息" })).toBeVisible();
    await user.type(screen.getByLabelText("下游地址"), "http://localhost:8000");
    await user.type(screen.getByLabelText("下游 app_key"), "billing");
    await user.click(screen.getByRole("button", { name: "自动接入" }));

    expect(await screen.findByText("自动接入完成")).toBeVisible();
    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/console/api/v1/apps/auto-onboarding" && init?.method === "POST",
      );
      expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
        base_url: "http://localhost:8000",
        app_key: "billing",
      });
    });
    await user.click(screen.getByRole("button", { name: "继续配置检查" }));
    expect(await screen.findByRole("heading", { name: "确认授权组与审批规则" })).toBeVisible();
  });

  test("manifest 预览并确认导入后允许进入下一步", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/billing" && !init?.method) {
        return jsonResponse({ app: { id: 9, app_key: "billing", name: "Billing" } });
      }
      if (url === "/console/api/v1/apps/billing/permission-template-imports/preview" && init?.method === "POST") {
        return jsonResponse({
          preview_id: "pv-1",
          changes: [{ action: "create_permission", key: "customer.profile.view" }],
        });
      }
      if (url === "/console/api/v1/apps/billing/permission-template-imports/pv-1/confirm" && init?.method === "POST") {
        return jsonResponse({ catalog_version: 3 });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWizard("/console/apps/new?app_key=billing&step=catalog");

    expect(await screen.findByRole("heading", { name: "导入权限目录 Manifest" })).toBeVisible();
    const nextButton = screen.getByRole("button", { name: "下一步" });
    expect(nextButton).toBeDisabled();

    await user.click(screen.getByLabelText("Manifest 内容"));
    await user.paste("{}");
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    expect(await screen.findByText("create_permission:customer.profile.view")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "确认导入" }));
    expect(await screen.findByText("导入成功")).toBeVisible();
    expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled();
  });

  test("直接访问后续步骤但缺少 app_key 时回落到第一步", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse({})));

    renderWizard("/console/apps/new?step=credential");

    expect(await screen.findByRole("heading", { name: "注册应用基本信息" })).toBeVisible();
  });
});

function renderWizard(initialEntry: string) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/console/apps/new" element={<AppOnboardingWizard />} />
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
