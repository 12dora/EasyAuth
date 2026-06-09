import { afterEach, describe, expect, test, vi } from "vitest";

import { apiRequest, readCsrfToken } from "./api";

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
