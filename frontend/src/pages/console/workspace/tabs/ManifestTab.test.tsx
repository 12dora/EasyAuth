import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ManifestTab } from "./ManifestTab";

describe("ManifestTab", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("编辑内容后立即废弃已有预览并禁止确认", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.includes("/permission-template-versions?")) {
        return versionsResponse();
      }
      if (url === "/console/api/v1/apps/demo/manifest") {
        return jsonResponse({ schema_version: 1 });
      }
      if (url.endsWith("/permission-template-imports/preview") && init?.method === "POST") {
        return jsonResponse({
          preview_id: "preview-a",
          diff: { added: [{ type: "permission", key: "permission.a" }] },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<ManifestTab appKey="demo" />);

    const input = screen.getByLabelText("Manifest 内容");
    await user.click(input);
    await user.paste('{"permissions":["a"]}');
    await user.click(screen.getByRole("button", { name: "预览差异" }));

    expect(await screen.findByText("permission:permission.a")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认导入" })).toBeEnabled();

    await user.type(input, " ");

    expect(screen.queryByText("permission:permission.a")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认导入" })).toBeDisabled();
  });

  test("预览期间内容变化时丢弃晚到的旧响应", async () => {
    const previewResponse = deferred<Response>();
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.includes("/permission-template-versions?")) {
        return versionsResponse();
      }
      if (url === "/console/api/v1/apps/demo/manifest") {
        return jsonResponse({ schema_version: 1 });
      }
      if (url.endsWith("/permission-template-imports/preview") && init?.method === "POST") {
        return previewResponse.promise;
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<ManifestTab appKey="demo" />);

    const input = screen.getByLabelText("Manifest 内容");
    await user.type(input, "manifest-a");
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    await user.clear(input);
    await user.type(input, "manifest-b");

    await act(async () => {
      previewResponse.resolve(
        jsonResponse({
          preview_id: "preview-a",
          diff: { added: [{ type: "permission", key: "permission.a" }] },
        }),
      );
      await previewResponse.promise;
    });

    await waitFor(() => expect(screen.getByRole("button", { name: "预览差异" })).toBeEnabled());
    expect(screen.queryByText("permission:permission.a")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认导入" })).toBeDisabled();
  });

  test("确认导入只使用当前内容对应的 preview_id", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.includes("/permission-template-versions?")) {
        return versionsResponse();
      }
      if (url === "/console/api/v1/apps/demo/manifest") {
        return jsonResponse({ schema_version: 1 });
      }
      if (url.endsWith("/permission-template-imports/preview") && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as { template: string };
        return jsonResponse({ preview_id: body.template === "manifest-b" ? "preview-b" : "preview-a", diff: {} });
      }
      if (url.endsWith("/permission-template-imports/preview-b/confirm") && init?.method === "POST") {
        return jsonResponse({ catalog_version: "v2" });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<ManifestTab appKey="demo" />);

    const input = screen.getByLabelText("Manifest 内容");
    await user.type(input, "manifest-a");
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "确认导入" })).toBeEnabled());

    await user.clear(input);
    await user.type(input, "manifest-b");
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "确认导入" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "确认导入" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/apps/demo/permission-template-imports/preview-b/confirm",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/preview-a/confirm"))).toBe(false);
  });

  test("后选择的文件不会被先选择文件的晚到读取结果覆盖", async () => {
    const firstRead = deferred<string>();
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.includes("/permission-template-versions?")) {
        return versionsResponse();
      }
      if (url === "/console/api/v1/apps/demo/manifest") {
        return jsonResponse({ schema_version: 1 });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const firstFile = new File(["manifest-a"], "a.json", { type: "application/json" });
    const secondFile = new File(["manifest-b"], "b.json", { type: "application/json" });
    Object.defineProperty(firstFile, "text", { value: () => firstRead.promise });
    Object.defineProperty(secondFile, "text", { value: async () => "manifest-b" });

    renderWithClient(<ManifestTab appKey="demo" />);

    const fileInput = screen.getByLabelText<HTMLInputElement>("上传 Manifest 文件");
    await user.upload(fileInput, firstFile);
    await user.upload(fileInput, secondFile);
    await waitFor(() => expect(screen.getByLabelText("Manifest 内容")).toHaveValue("manifest-b"));

    await act(async () => {
      firstRead.resolve("manifest-a");
      await firstRead.promise;
    });

    expect(screen.getByLabelText("Manifest 内容")).toHaveValue("manifest-b");
  });

  test("当前 Manifest 保存期间锁定输入并使用点击保存时的内容", async () => {
    const previewResponse = deferred<Response>();
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.includes("/permission-template-versions?")) {
        return versionsResponse();
      }
      if (url === "/console/api/v1/apps/demo/manifest") {
        return jsonResponse({ schema_version: 1 });
      }
      if (url.endsWith("/permission-template-imports/preview") && init?.method === "POST") {
        return previewResponse.promise;
      }
      if (url.endsWith("/permission-template-imports/current-preview/confirm") && init?.method === "POST") {
        return jsonResponse({ catalog_version: "v2" });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<ManifestTab appKey="demo" />);

    await user.click(await screen.findByRole("button", { name: "编辑" }));
    const draft = screen.getByLabelText("当前 Manifest");
    await user.clear(draft);
    await user.click(draft);
    await user.paste('{"schema_version":2}');
    await user.click(screen.getByRole("button", { name: "保存为新版本" }));

    expect(draft).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消编辑" })).toBeDisabled();
    const previewCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/permission-template-imports/preview"));
    expect(JSON.parse(String(previewCall?.[1]?.body))).toEqual({
      template_format: "json",
      template: '{"schema_version":2}',
    });

    await act(async () => {
      previewResponse.resolve(jsonResponse({ preview_id: "current-preview", diff: {} }));
      await previewResponse.promise;
    });

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/current-preview/confirm"))).toBe(true);
    });
  });

  test("版本历史使用服务端分页参数和总数", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/permission-template-versions?page=1&page_size=20") {
        return versionsResponse([{ version: "v21" }], 1, 21, 2);
      }
      if (url === "/console/api/v1/apps/demo/permission-template-versions?page=2&page_size=20") {
        return versionsResponse([{ version: "v1" }], 2, 21, 2);
      }
      if (url === "/console/api/v1/apps/demo/manifest") {
        return jsonResponse({ schema_version: 1 });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<ManifestTab appKey="demo" />);

    expect(await screen.findByText("v21")).toBeInTheDocument();
    expect(screen.getByText("第 1-1 条 / 共 21 条")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下一页" }));

    expect(await screen.findByText("v1")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/console/api/v1/apps/demo/permission-template-versions?page=2&page_size=20",
      expect.any(Object),
    );
  });
});

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function versionsResponse(data: unknown[] = [], page = 1, totalItems = 0, totalPages = 1) {
  return jsonResponse({
    data,
    pagination: { page, page_size: 20, total_items: totalItems, total_pages: totalPages },
  });
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}
