import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ApprovalTemplatesPage } from "./ApprovalTemplatesPage";

const TEMPLATES = [
  {
    id: 1,
    app_key: "",
    key: "leave",
    name: "请假审批",
    dingtalk_process_code: "PROC-LEAVE",
    form_schema: { reason: { type: "string", required: true } },
    form_mapping: { reason: "TextField-1" },
    is_active: true,
    created_at: "2026-07-01T09:00:00Z",
    updated_at: "2026-07-01T09:00:00Z",
  },
  {
    id: 2,
    app_key: "crm",
    key: "purchase",
    name: "采购审批",
    dingtalk_process_code: "PROC-PURCHASE",
    form_schema: {},
    form_mapping: {},
    is_active: false,
    created_at: "2026-06-01T09:00:00Z",
    updated_at: "2026-06-02T09:00:00Z",
  },
];

describe("ApprovalTemplatesPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("模板列表展示 key、名称、所属应用(空为平台共用)、启用状态", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => jsonResponse({ data: TEMPLATES })),
    );

    renderPage();

    expect(await screen.findByText("leave")).toBeVisible();
    expect(screen.getByText("请假审批")).toBeVisible();
    expect(screen.getByText("平台共用")).toBeVisible();
    expect(screen.getByText("purchase")).toBeVisible();
    expect(screen.getByText("crm")).toBeVisible();
    expect(screen.getByText("启用")).toBeVisible();
    expect(screen.getByText("停用")).toBeVisible();
    expect(screen.getByRole("button", { name: "新建模板" })).toBeVisible();
    expect(screen.getAllByRole("button", { name: "发起测试审批" })).toHaveLength(2);
  });

  test("新建模板严格校验 form_schema 和 form_mapping 契约", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/approval-templates" && !init?.method) {
        return jsonResponse({ data: [] });
      }
      if (url === "/console/api/v1/approval-templates" && init?.method === "POST") {
        return jsonResponse({ approval_template: { ...TEMPLATES[0], id: 9 } }, 201);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderPage();

    await user.click(await screen.findByRole("button", { name: "新建模板" }));
    const dialog = await screen.findByRole("dialog", { name: "新建审批模板" });
    await user.type(within(dialog).getByLabelText("模板 Key"), "leave");
    await user.type(within(dialog).getByLabelText("名称"), "请假审批");
    await user.type(within(dialog).getByLabelText("钉钉流程码（process_code）"), "PROC-LEAVE");
    const schemaInput = within(dialog).getByLabelText("表单结构（form_schema，JSON）");
    const mappingInput = within(dialog).getByLabelText("表单映射（form_mapping，JSON）");
    for (const invalidSchema of [
      "not-json",
      '{"reason": "string"}',
      '{"reason": {}}',
      '{"reason": {"type": "text"}}',
      '{"reason": {"type": "string", "required": "yes"}}',
      '{"reason": {"type": "string", "label": "原因"}}',
      '{" ": {"type": "string"}}',
    ]) {
      await user.clear(schemaInput);
      await user.click(schemaInput);
      await user.paste(invalidSchema);
      await user.click(within(dialog).getByRole("button", { name: "保存" }));

      expect(await within(dialog).findByText("form_schema 不符合字段契约，请检查字段名、type 和 required。")).toBeVisible();
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    }

    const validSchema = {
      reason: { type: "string", required: true },
      days: { type: "integer" },
      amount: { type: "number" },
      urgent: { type: "boolean" },
    };
    await user.clear(schemaInput);
    await user.click(schemaInput);
    await user.paste(JSON.stringify(validSchema));
    for (const invalidMapping of [
      "not-json",
      '{"reason": 1}',
      '{"reason": null}',
      '{"reason": {"field": "TextField-1"}}',
      '{"reason": ["TextField-1"]}',
      '{"reason": " "}',
      '{"undeclared": "TextField-2"}',
    ]) {
      await user.clear(mappingInput);
      await user.click(mappingInput);
      await user.paste(invalidMapping);
      await user.click(within(dialog).getByRole("button", { name: "保存" }));

      expect(
        await within(dialog).findByText("form_mapping 必须只引用 form_schema 字段，且控件名必须为非空字符串。"),
      ).toBeVisible();
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    }

    await user.clear(mappingInput);
    await user.click(mappingInput);
    await user.paste('{"reason": "TextField-1"}');
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/console/api/v1/approval-templates" && init?.method === "POST",
      );
      expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
        app_key: "",
        key: "leave",
        name: "请假审批",
        dingtalk_process_code: "PROC-LEAVE",
        form_schema: validSchema,
        form_mapping: { reason: "TextField-1" },
        is_active: true,
      });
    });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "新建审批模板" })).not.toBeInTheDocument());
  });

  test("编辑模板时展示并 PATCH 提交 form_schema", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/approval-templates" && !init?.method) {
        return jsonResponse({ data: [TEMPLATES[0]] });
      }
      if (url === "/console/api/v1/approval-templates/1" && init?.method === "PATCH") {
        return jsonResponse({ approval_template: TEMPLATES[0] });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderPage();

    await user.click(await screen.findByRole("button", { name: "编辑" }));
    const dialog = await screen.findByRole("dialog", { name: "编辑审批模板" });
    const schemaInput = within(dialog).getByLabelText("表单结构（form_schema，JSON）");
    expect(schemaInput).toHaveValue(JSON.stringify(TEMPLATES[0].form_schema, null, 2));

    await user.clear(schemaInput);
    await user.click(schemaInput);
    await user.paste('{"reason":{"type":"string","required":true},"days":{"type":"integer"}}');
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/console/api/v1/approval-templates/1" && init?.method === "PATCH",
      );
      expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({
        name: "请假审批",
        dingtalk_process_code: "PROC-LEAVE",
        form_schema: {
          reason: { type: "string", required: true },
          days: { type: "integer" },
        },
        form_mapping: { reason: "TextField-1" },
        is_active: true,
      });
    });
  });

  test("平台共用模板发起测试审批需填 app_key, 成功后展示钉钉实例号", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/approval-templates" && !init?.method) {
        return jsonResponse({ data: [TEMPLATES[0]] });
      }
      if (url.startsWith("/console/api/v1/user-options")) {
        return jsonResponse({ data: [] });
      }
      if (url === "/console/api/v1/approval-templates/1/test" && init?.method === "POST") {
        return jsonResponse({
          instance_id: "ai-100",
          status: "submitted",
          dingtalk_process_instance_id: "PROC-INST-100",
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderPage();

    await user.click(await screen.findByRole("button", { name: "发起测试审批" }));
    const dialog = await screen.findByRole("dialog", { name: "发起测试审批" });

    await user.type(within(dialog).getByRole("combobox"), "emp-1");
    await user.click(within(dialog).getByRole("button", { name: "发起测试" }));
    expect(await within(dialog).findByText("平台共用模板需填写发起应用 app_key")).toBeVisible();
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/test"))).toBe(false);

    await user.type(within(dialog).getByLabelText("发起应用 app_key"), "crm");
    await user.click(within(dialog).getByRole("button", { name: "发起测试" }));

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/console/api/v1/approval-templates/1/test" && init?.method === "POST",
      );
      expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
        originator_user_id: "emp-1",
        app_key: "crm",
      });
    });
    expect(await within(dialog).findByText("测试审批已发起")).toBeVisible();
    expect(within(dialog).getByText("PROC-INST-100")).toBeVisible();
  });

  test("同 key 模板发起测试时请求所选模板的精确 ID", async () => {
    const sameKeyTemplates = [
      TEMPLATES[0],
      { ...TEMPLATES[1], key: TEMPLATES[0].key },
    ];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/approval-templates" && !init?.method) {
        return jsonResponse({ data: sameKeyTemplates });
      }
      if (url.startsWith("/console/api/v1/user-options")) {
        return jsonResponse({ data: [] });
      }
      if (url === "/console/api/v1/approval-templates/2/test" && init?.method === "POST") {
        return jsonResponse({
          instance_id: "ai-200",
          status: "submitted",
          dingtalk_process_instance_id: "PROC-INST-200",
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderPage();

    const targetRow = (await screen.findByText("采购审批")).closest("tr");
    expect(targetRow).not.toBeNull();
    await user.click(within(targetRow!).getByRole("button", { name: "发起测试审批" }));
    const dialog = await screen.findByRole("dialog", { name: "发起测试审批" });
    await user.type(within(dialog).getByRole("combobox"), "emp-2");
    await user.click(within(dialog).getByRole("button", { name: "发起测试" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/approval-templates/2/test",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(fetchMock.mock.calls.some(([input]) => String(input) === "/console/api/v1/approval-templates/1/test")).toBe(false);
  });
});

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/console/approval-templates"]}>
        <ApprovalTemplatesPage />
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
