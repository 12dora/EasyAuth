import { afterEach, describe, expect, test, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { API_SESSION_EXPIRED_EVENT, apiRequest, itemsFromPayload, readCsrfToken } from "./api";

const domainSource = readFileSync(resolve(process.cwd(), "src/lib/domain.ts"), "utf8");

function interfaceBody(interfaceName: string): string {
  const match = domainSource.match(
    new RegExp(`export interface ${interfaceName}(?:\\s+extends\\s+[^\\{]+)? \\{([\\s\\S]*?)\\n\\}`),
  );
  return match?.[1] ?? "";
}

function inheritedInterfaceBody(interfaceName: string): string {
  const declaration = domainSource.match(
    new RegExp(`export interface ${interfaceName}(?:\\s+extends\\s+([^\\{]+))? \\{([\\s\\S]*?)\\n\\}`),
  );
  if (!declaration) {
    return "";
  }
  const inherited = declaration[1]
    ?.split(",")
    .map((parent) => interfaceBody(parent.trim()))
    .join("\n");
  return `${inherited ?? ""}\n${declaration[2]}`;
}

function expectInterfaceFields(interfaceName: string, fields: string[]): void {
  const body = inheritedInterfaceBody(interfaceName);
  expect(body, `${interfaceName} 应存在`).not.toBe("");
  for (const field of fields) {
    expect(body, `${interfaceName} 应包含字段 ${field}`).toMatch(new RegExp(`\\b${field}\\??:`));
  }
}

describe("apiRequest", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  test("带上同源 session 和 CSRF token", async () => {
    document.body.innerHTML = '<input name="csrfmiddlewaretoken" value="csrf-123" />';
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        headers: { "Content-Type": "application/json" },
      }),
    );

    await apiRequest("/console/api/v1/apps", {
      method: "POST",
      body: { name: "CRM" },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/console/api/v1/apps",
      expect.objectContaining({
        credentials: "include",
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-CSRFToken": "csrf-123",
        }),
        body: JSON.stringify({ name: "CRM" }),
      }),
    );
  });

  test("非 JSON 错误响应体不回显, 按状态码降级为确定性文案", async () => {
    const htmlBody = "<html><body>Traceback: secret internal detail at line 42</body></html>";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(htmlBody, {
        status: 500,
        headers: { "Content-Type": "text/html" },
      }),
    );

    const rejection = await apiRequest("/console/api/v1/apps").catch((error: unknown) => error);
    expect(rejection).toMatchObject({ status: 500 });
    const message = (rejection as Error).message;
    expect(message).not.toContain("Traceback");
    expect(message).not.toContain("secret internal detail");
    expect(message).toContain("500");
  });

  test("非 JSON 成功响应作为协议错误失败", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<html>login page</html>", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      }),
    );

    await expect(apiRequest("/console/api/v1/settings/integrations")).rejects.toMatchObject({
      status: 200,
      code: "UNEXPECTED_RESPONSE_TYPE",
    });
  });

  test("损坏 JSON 成功响应作为协议错误失败", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{bad-json", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(apiRequest("/console/api/v1/settings/integrations")).rejects.toMatchObject({
      status: 200,
      code: "INVALID_JSON_RESPONSE",
    });
  });

  test("网络失败归一化为稳定错误码", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(apiRequest("/console/api/v1/apps")).rejects.toMatchObject({
      status: 0,
      code: "NETWORK_ERROR",
      message: "网络连接失败，请检查网络后重试。",
    });
  });

  test("解析统一错误结构", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "VALIDATION_ERROR",
            message: "请求参数无效。",
            details: { field: "app_key" },
          },
        }),
        {
          status: 422,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    await expect(apiRequest("/console/api/v1/apps")).rejects.toMatchObject({
      status: 422,
      code: "VALIDATION_ERROR",
      message: "请求参数无效。",
      details: { field: "app_key" },
    });
  });

  test("401 响应发布单一会话失效事件", async () => {
    const listener = vi.fn();
    window.addEventListener(API_SESSION_EXPIRED_EVENT, listener);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "AUTHENTICATION_FAILED",
            message: "控制台登录已失效。",
          },
        }),
        {
          status: 401,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    await apiRequest("/console/api/v1/apps").catch(() => undefined);

    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener.mock.calls[0]?.[0]).toMatchObject({
      detail: { code: "AUTHENTICATION_FAILED", message: "控制台登录已失效。" },
    });
    window.removeEventListener(API_SESSION_EXPIRED_EVENT, listener);
  });
});

describe("readCsrfToken", () => {
  test("从 Django shell 隐藏字段读取 token", () => {
    document.body.innerHTML = '<input name="csrfmiddlewaretoken" value="token-from-shell" />';

    expect(readCsrfToken()).toBe("token-from-shell");
  });
});

describe("itemsFromPayload", () => {
  test("未加载数据时返回稳定空数组引用", () => {
    expect(itemsFromPayload(undefined)).toEqual([]);
    expect(itemsFromPayload(null)).toEqual([]);
  });

  test("成功信封缺少列表数据时快速失败", () => {
    expect(() => itemsFromPayload({})).toThrow("列表响应契约异常");
  });

  test("保留 payload 中已有列表引用", () => {
    const items = [{ id: 1 }];

    expect(itemsFromPayload<{ id: number }>({ data: items })).toBe(items);
  });

  test("payload.data 非数组时快速失败", () => {
    expect(() => itemsFromPayload({ data: "oops" })).toThrow("列表响应契约异常");
  });
});

describe("前端领域契约", () => {
  test("声明应用写入 payload 和授权目录核心类型", () => {
    expectInterfaceFields("AppCreatePayload", ["app_key", "name", "description", "is_active"]);
    expectInterfaceFields("AppUpdatePayload", ["name", "description", "is_active"]);
    expectInterfaceFields("AppMembershipItem", ["id", "user_id", "role", "is_active"]);
    expectInterfaceFields("AppScopeItem", ["key", "name", "description", "is_active", "display_order"]);
    expectInterfaceFields("AuthorizationGroupGrantItem", ["permission", "scope", "is_active"]);
    expectInterfaceFields("AuthorizationGroupItem", [
      "key",
      "kind",
      "name",
      "description",
      "requestable",
      "is_active",
      "grants",
    ]);
  });

  test("扩展权限、查询结果和门户 catalog 契约", () => {
    expectInterfaceFields("PermissionItem", ["supported_scopes", "risk_level", "deprecated_at"]);
    expectInterfaceFields("ExpandedGrantItem", ["permission", "scope", "source_type", "source_key"]);
    expectInterfaceFields("QueryTestResult", [
      "groups",
      "grants",
      "grant_version",
      "catalog_version",
      "snapshot_version",
      "expires_at",
    ]);
    expectInterfaceFields("PortalRequestCatalog", [
      "authorization_groups",
      "direct_grant_scope_options",
      "catalog_version",
      "snapshot_version",
    ]);
    expect(interfaceBody("PortalRequestCatalog")).not.toMatch(/\broles\??:/);
  });
});
