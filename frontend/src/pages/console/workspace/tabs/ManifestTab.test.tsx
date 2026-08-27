import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ManifestTab } from "./ManifestTab";
import {
  ANTD_TEST_TIMEOUT_MS,
  columnSortOrder,
  renderWithAntd,
  sortByColumn,
} from "../../../../components/antd/testing";

// antd Table 在 jsdom 里每次筛选/排序/翻页都要重建整棵表格, 比自研原语慢得多,
// 整套用例并行跑时默认 5s 不够; 这里只放宽本文件的用例超时。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

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

  test("版本列表头排序是服务端排序: 带 ordering 请求、回到第 1 页, 指示器跟着走", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/manifest") {
        return jsonResponse({ schema_version: 1 });
      }
      if (!url.startsWith("/console/api/v1/apps/demo/permission-template-versions?")) {
        throw new Error(`Unexpected fetch: ${url}`);
      }
      const page = new URLSearchParams(url.split("?")[1]).get("page") ?? "1";
      return versionsResponse([{ version: `v${page}` }], Number(page), 21, 2);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<ManifestTab appKey="demo" />);

    // 表格不设默认排序: 首屏不带 ordering, 表头也没有指示器。
    expect(await screen.findByText("v1")).toBeInTheDocument();
    expect(columnSortOrder("版本")).toBeNull();

    const history = screen.getByRole("heading", { name: "版本历史" }).parentElement as HTMLElement;
    await user.click(within(history).getByTitle("下一页"));
    await screen.findByText("v2");

    // 排序变了旧页码可能越界, 因此排序同时回到第 1 页。
    await sortByColumn(user, "版本");
    await waitFor(() =>
      expect(lastVersionsUrl(fetchMock)).toBe(
        "/console/api/v1/apps/demo/permission-template-versions?page=1&page_size=20&ordering=version",
      ),
    );
    expect(columnSortOrder("版本")).toBe("ascend");

    await sortByColumn(user, "版本");
    await waitFor(() =>
      expect(lastVersionsUrl(fetchMock)).toBe(
        "/console/api/v1/apps/demo/permission-template-versions?page=1&page_size=20&ordering=-version",
      ),
    );
    expect(columnSortOrder("版本")).toBe("descend");

    // antd 的三态循环第三档是「取消排序」: 不带 ordering, 后端回落到自己的默认序。
    await sortByColumn(user, "版本");
    await waitFor(() =>
      expect(lastVersionsUrl(fetchMock)).toBe(
        "/console/api/v1/apps/demo/permission-template-versions?page=1&page_size=20",
      ),
    );
    expect(columnSortOrder("版本")).toBeNull();
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
    const history = screen.getByRole("heading", { name: "版本历史" }).parentElement as HTMLElement;
    // antd 的区间文案按 page/page_size 推算, 不按当前页实际行数收窄。
    expect(within(history).getByText("第 1-20 条 / 共 21 条")).toBeInTheDocument();
    await user.click(within(history).getByTitle("下一页"));

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
  renderWithAntd(
    <QueryClientProvider client={client}>
      {ui}
    </QueryClientProvider>,
  );
}

function lastVersionsUrl(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>) {
  return fetchMock.mock.calls
    .map(([input]) => String(input))
    .filter((url) => url.startsWith("/console/api/v1/apps/demo/permission-template-versions?"))
    .at(-1);
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
