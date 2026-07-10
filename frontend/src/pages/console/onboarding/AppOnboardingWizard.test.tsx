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
        return jsonResponse({ app_key: "billing", status: "ready", data: [] });
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

  test("编辑 manifest 后立即废弃预览和已导入版本", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/billing" && !init?.method) {
        return jsonResponse({ app: { id: 9, app_key: "billing", name: "Billing" } });
      }
      if (url.endsWith("/permission-template-imports/preview") && init?.method === "POST") {
        return jsonResponse({ preview_id: "pv-a", changes: [{ action: "create_permission", key: "permission.a" }] });
      }
      if (url.endsWith("/permission-template-imports/pv-a/confirm") && init?.method === "POST") {
        return jsonResponse({ catalog_version: 3 });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWizard("/console/apps/new?app_key=billing&step=catalog");
    const contentInput = await screen.findByLabelText("Manifest 内容");
    await user.click(contentInput);
    await user.paste("{}");
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    expect(await screen.findByText("create_permission:permission.a")).toBeVisible();

    await user.type(contentInput, " ");
    expect(screen.queryByText("create_permission:permission.a")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认导入" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "预览差异" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "确认导入" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "确认导入" }));
    expect(await screen.findByText("导入成功")).toBeVisible();
    expect(screen.getByRole("button", { name: "下一步" })).toBeEnabled();

    await user.type(contentInput, "\n");
    expect(screen.queryByText("导入成功")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一步" })).toBeDisabled();
  });

  test("manifest 预览在途时编辑不会让旧响应覆盖新文本", async () => {
    const previewResponse = deferred<Response>();
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/billing" && !init?.method) {
        return jsonResponse({ app: { id: 9, app_key: "billing", name: "Billing" } });
      }
      if (url.endsWith("/permission-template-imports/preview") && init?.method === "POST") {
        return previewResponse.promise;
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWizard("/console/apps/new?app_key=billing&step=catalog");
    const contentInput = await screen.findByLabelText("Manifest 内容");
    await user.click(contentInput);
    await user.paste("{\"version\":1}");
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    await user.clear(contentInput);
    await user.paste("{\"version\":2}");
    previewResponse.resolve(jsonResponse({ preview_id: "pv-old", changes: [{ action: "create_permission", key: "old" }] }));

    await waitFor(() => expect(screen.getByRole("button", { name: "预览差异" })).toBeEnabled());
    expect(screen.queryByText("create_permission:old")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认导入" })).toBeDisabled();
  });

  test("畸形 configuration-status 信封进入错误态而不是显示配置就绪", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/billing") {
        return jsonResponse({ app: { id: 9, app_key: "billing", name: "Billing" } });
      }
      if (url.endsWith("/configuration-status")) {
        return jsonResponse({ items: [] });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWizard("/console/apps/new?app_key=billing&step=authz");

    expect(await screen.findByText("配置状态加载失败")).toBeVisible();
    expect(screen.getByText("配置状态响应格式无效。")).toBeVisible();
    expect(screen.queryByText("配置完整性检查通过，可以继续。")).not.toBeInTheDocument();
  });

  test("自动接入输入变化会废弃在途结果并清除 descriptor token", async () => {
    const onboardResponse = deferred<Response>();
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === "/console/api/v1/apps/auto-onboarding" && init?.method === "POST") {
        return onboardResponse.promise;
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWizard("/console/apps/new");
    const baseUrlInput = await screen.findByLabelText("下游地址");
    const tokenInput = screen.getByLabelText("描述符访问 token（可选）");
    await user.type(baseUrlInput, "https://a.example.com");
    await user.type(screen.getByLabelText("下游 app_key"), "billing");
    await user.type(tokenInput, "secret-a");
    await user.click(screen.getByRole("button", { name: "自动接入" }));

    await user.clear(baseUrlInput);
    await user.type(baseUrlInput, "https://b.example.com");
    expect(tokenInput).toHaveValue("");
    onboardResponse.resolve(
      jsonResponse({
        app_key: "billing",
        app_name: "Billing",
        created: true,
        already_up_to_date: false,
        template_version: 4,
        catalog_version: 5,
      }),
    );

    await waitFor(() => expect(screen.getByRole("button", { name: "自动接入" })).toBeEnabled());
    expect(screen.queryByText("自动接入完成")).not.toBeInTheDocument();
  });

  test("创建 OAuth client 后用 client_credentials 换取 access token", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/billing" && !init?.method) {
        return jsonResponse({ app: { id: 9, app_key: "billing", name: "Billing", active_credential_count: 0 } });
      }
      if (url.endsWith("/credentials/oauth-clients") && init?.method === "POST") {
        return jsonResponse({
          credential: { id: 11, kind: "oauth_client", name: "OAuth integration" },
          one_time_secret: { kind: "oauth_client", client_id: "client-1", client_secret: "secret-1" },
        }, 201);
      }
      if (url === "/oauth/token" && init?.method === "POST") {
        return jsonResponse({ access_token: "access-1", token_type: "Bearer", expires_in: 3600 });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWizard("/console/apps/new?app_key=billing&step=credential");
    await user.type(await screen.findByLabelText("凭据名称"), "OAuth integration");
    await user.click(screen.getByRole("button", { name: "创建 OAuth client" }));

    expect(await screen.findByText("access-1")).toBeVisible();
    const tokenCall = fetchMock.mock.calls.find(([input]) => String(input) === "/oauth/token");
    expect(tokenCall?.[1]?.headers).toEqual({ "Content-Type": "application/x-www-form-urlencoded" });
    expect(String(tokenCall?.[1]?.body)).toBe("grant_type=client_credentials&client_id=client-1&client_secret=secret-1");
  });

  test("联调输入变化后旧响应不会覆盖结果或清除新 token", async () => {
    const queryResponse = deferred<Response>();
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/billing" && !init?.method) {
        return jsonResponse({ app: { id: 9, app_key: "billing", name: "Billing" } });
      }
      if (url.startsWith("/console/api/v1/user-options?")) {
        return jsonResponse({ data: [] });
      }
      if (url.endsWith("/permission-query-tests") && init?.method === "POST") {
        return queryResponse.promise;
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWizard("/console/apps/new?app_key=billing&step=verify");
    const userIdInput = await screen.findByLabelText("用户 ID");
    const tokenInput = screen.getByLabelText("Bearer token");
    await user.type(userIdInput, "user-a");
    await user.type(tokenInput, "token-a");
    await user.click(screen.getByRole("button", { name: "执行联调" }));

    await user.type(tokenInput, "-new");
    queryResponse.resolve(jsonResponse({ allowed: true, groups: [], grants: [], snapshot_version: "old" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "执行联调" })).toBeEnabled());
    expect(tokenInput).toHaveValue("token-a-new");
    expect(screen.queryByText("权限查询命中授权")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一步" })).toBeDisabled();
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}
