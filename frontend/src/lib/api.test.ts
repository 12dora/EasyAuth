import { afterEach, describe, expect, test, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { apiRequest, readCsrfToken } from "./api";

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
});

describe("readCsrfToken", () => {
  test("从 Django shell 隐藏字段读取 token", () => {
    document.body.innerHTML = '<input name="csrfmiddlewaretoken" value="token-from-shell" />';

    expect(readCsrfToken()).toBe("token-from-shell");
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
