import { expect, test, type Page } from "@playwright/test";

interface ConnectorInstanceState {
  id: number;
  connector_key: string;
  display_name: string;
  enabled: boolean;
  config: Record<string, unknown>;
  configured_secrets: string[];
  reconcile_interval_seconds: number;
  last_reconcile_at: string | null;
  last_status: string;
  last_error: string;
  consecutive_failures: number;
  updated_by: string;
  updated_at: string;
}

interface MappingState {
  authorization_group_key: string;
  authorization_group_name: string;
  external_ref: string;
  auto_create: boolean;
}

const NETBIRD_TYPE = {
  key: "netbird",
  display_name: "NetBird VPN",
  config_schema: {
    type: "object",
    properties: {
      api_url: { type: "string", title: "管理 API 地址", description: "NetBird 管理服务地址" },
      api_token: { type: "string", title: "服务用户 API Token", "x-secret": true },
      precreate_users: { type: "boolean", title: "预创建用户", default: true },
      block_users_without_grant: { type: "boolean", title: "封禁无授权用户", default: true },
    },
    required: ["api_url", "api_token"],
  },
};

test("连接器动线: 选择类型 → 测试连接 → 保存启用 → 配置映射", async ({ page }) => {
  const state: { instances: ConnectorInstanceState[]; mappings: MappingState[] } = {
    instances: [],
    mappings: [],
  };
  await setConsoleAdmin(page);
  await mockConsoleApp(page);
  await mockConnectorApis(page, state);

  await page.goto("/console/apps/demo?tab=connector");
  await expect(page.getByRole("heading", { name: "出站供给连接器" })).toBeVisible();

  // 1. 选择连接器类型, schema 驱动的表单出现。
  await page.getByLabel("连接器类型").selectOption("netbird");
  await expect(page.getByLabel(/管理 API 地址/)).toBeVisible();

  // 2. 填配置并勾选启用: 首次启用前保存按钮被测试门槛拦住。
  await page.getByLabel(/管理 API 地址/).fill("https://netbird.example.com");
  await page.getByLabel(/服务用户 API Token/).fill("nbp_test_token");
  await page.getByRole("checkbox", { name: "启用连接器" }).check();
  await expect(page.getByRole("button", { name: "保存" })).toBeDisabled();

  // 3. 测试连接成功后放行保存。
  await page.getByRole("button", { name: "测试连接" }).click();
  await expect(page.getByText("连接测试通过").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "保存" })).toBeEnabled();
  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.getByText("连接器配置已保存").first()).toBeVisible();

  // 4. 实例状态卡与映射/运行历史面板出现。
  await expect(page.getByText("最近对账")).toBeVisible();
  await expect(page.getByRole("heading", { name: "授权组映射" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "运行历史" })).toBeVisible();

  // 5. 填写映射(外部组来自 datalist, 也可手输)并整表保存。
  await page.getByLabel("外部组").fill("vpn-users");
  await page.getByRole("checkbox", { name: "不存在则创建" }).check();
  await page.getByRole("button", { name: "保存" }).last().click();
  await expect(page.getByText("映射已保存").first()).toBeVisible();
});

async function setConsoleAdmin(page: Page) {
  // 对齐 smoke.spec 的做法: 向文档注入控制台管理员身份, 避免 console shell 重定向。
  await page.route("**/*", async (route) => {
    const request = route.request();
    if (request.resourceType() !== "document") {
      await route.fallback();
      return;
    }
    const response = await route.fetch();
    const html = await response.text();
    await route.fulfill({
      response,
      body: html
        .replace("<body", '<body data-current-user-role="EasyAuth Admins" data-current-user-id="admin-001"')
        .replace(
          '<div id="root"',
          '<div id="root" data-current-user-role="EasyAuth Admins" data-current-user-id="admin-001"',
        )
        .replace(
          '<div id="easyauth-root"',
          '<div id="easyauth-root" data-current-user-role="EasyAuth Admins" data-current-user-id="admin-001"',
        ),
      headers: { ...response.headers(), "content-type": "text/html" },
    });
  });
}

async function mockConsoleApp(page: Page) {
  await page.route("**/console/api/v1/apps/demo", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        app: {
          id: 1,
          app_key: "demo",
          name: "Demo App",
          description: "Demo console app",
          can_manage: true,
        },
      },
    });
  });
}

async function mockConnectorApis(
  page: Page,
  state: { instances: ConnectorInstanceState[]; mappings: MappingState[] },
) {
  await page.route("**/console/api/v1/apps/demo/connectors", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as {
        connector_key: string;
        enabled: boolean;
        reconcile_interval_seconds: number;
        config: Record<string, unknown>;
      };
      state.instances = [
        {
          id: 1,
          connector_key: body.connector_key,
          display_name: "NetBird VPN",
          enabled: body.enabled,
          config: { ...body.config, api_token: "" },
          configured_secrets: ["api_token"],
          reconcile_interval_seconds: body.reconcile_interval_seconds,
          last_reconcile_at: null,
          last_status: "",
          last_error: "",
          consecutive_failures: 0,
          updated_by: "admin-001",
          updated_at: "2026-07-07T10:00:00+08:00",
        },
      ];
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        json: { connector: state.instances[0] },
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      json: { connector_types: [NETBIRD_TYPE], data: state.instances },
    });
  });
  await page.route("**/console/api/v1/apps/demo/connectors/test", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: { ok: true, message: "连接成功, NetBird 现有 2 个组。" },
    });
  });
  await page.route("**/console/api/v1/apps/demo/authorization-groups", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        data: [
          {
            key: "vpn-users",
            kind: "bundle",
            name: "VPN 基础准入",
            requestable: true,
            is_active: true,
            grants: [],
          },
        ],
      },
    });
  });
  await page.route("**/console/api/v1/apps/demo/connectors/1/mappings", async (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as {
        mappings: Array<{ authorization_group_key: string; external_ref: string; auto_create: boolean }>;
      };
      state.mappings = body.mappings.map((entry) => ({
        authorization_group_key: entry.authorization_group_key,
        authorization_group_name: "VPN 基础准入",
        external_ref: entry.external_ref,
        auto_create: entry.auto_create,
      }));
    }
    await route.fulfill({ contentType: "application/json", json: { data: state.mappings } });
  });
  await page.route("**/console/api/v1/apps/demo/connectors/1/external-groups", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: { data: [{ ref: "vpn-users", name: "vpn-users" }] },
    });
  });
  await page.route("**/console/api/v1/apps/demo/connectors/1/sync-runs*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: { data: [], pagination: { page: 1, page_size: 10, total_items: 0, total_pages: 0 } },
    });
  });
}
