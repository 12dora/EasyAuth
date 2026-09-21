import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { UsageConfig, UsageSettingsPayload } from "../usageTypes";
import { UsageSettingsDialog } from "./UsageSettingsDialog";

const SETTINGS_URL = "/console/api/v1/operations/system-health/usage/settings";

// F2 的 useUsageData 只提供概览数字, 这里用固定快照替代, 避免依赖对方实现。
const mocks = vi.hoisted(() => ({
  summary: {
    metrics: [
      { metric: "api", today: { used: 412 }, month: { used: 9120 } },
      { metric: "webhook", today: { used: 3 }, month: { used: 40 } },
      { metric: "stream", today: { used: 7 }, month: { used: 90 } },
    ],
    alerts: { sent_today: 1, suppressed_today: 0, daily_cap: 30, sender_ready: true, sender_problem: null, recipient_count: 3 },
    stream: { paused: false, paused_at: null, can_resume: false },
  },
}));

// 只替换两个概览 hook, 其余导出(接口地址、查询前缀)保持真实值, 否则设置请求会打到 undefined。
vi.mock("../useUsageData", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../useUsageData")>()),
  useUsageSummary: () => ({ data: mocks.summary, isLoading: false, error: null }),
  useUsageAlerts: () => ({ data: { data: [] }, isLoading: false, error: null }),
}));

const ANOMALY = { enabled: true, hourly_absolute: null, baseline_multiplier: 5, baseline_min_calls: 200 };

const DOCUMENT: UsageConfig = {
  api: {
    monthly_quota: 500000,
    daily_cap: 5000,
    alert_thresholds_percent: [50, 80, 100],
    over_limit_policy: "degrade",
    degrade_escalation_percent: 120,
    throttle_per_hour: { p1: 200, p2: 20 },
    anomaly: ANOMALY,
  },
  webhook: {
    monthly_quota: 50000,
    daily_cap: null,
    alert_thresholds_percent: [50, 80, 100],
    over_limit_policy: "alert_only",
    anomaly: ANOMALY,
  },
  stream: {
    monthly_quota: null,
    daily_cap: null,
    alert_thresholds_percent: [50, 80, 100],
    over_limit_policy: "alert_only",
    anomaly: ANOMALY,
  },
  alerts: { enabled: true, cooldown_minutes: 60, daily_cap: 30, sender_app_key: "host-ops" },
};

const PAYLOAD: UsageSettingsPayload = {
  config: DOCUMENT,
  version: 3,
  updated_at: "2026-09-20T02:00:00Z",
  updated_by: "admin",
};

describe("UsageSettingsDialog", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("按文档回填表单, 保存时提交完整文档与版本号", async () => {
    const fetchMock = settingsFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    renderDialog();

    const monthlyQuota = await screen.findByLabelText("月配额");
    await waitFor(() => expect(monthlyQuota).toHaveValue(500000));
    // 预览条按「当前用量 / 正在输入的上限」实时计算。
    expect(screen.getByText(/已用 412 \/ 5,?000（8\.2%）/)).toBeVisible();

    fireEvent.change(monthlyQuota, { target: { value: "600000" } });
    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() => expect(requestBody(fetchMock)).not.toBeNull());
    expect(requestBody(fetchMock)).toEqual({
      config: { ...DOCUMENT, api: { ...DOCUMENT.api, monthly_quota: 600000 } },
      version: 3,
    });
    expect(await screen.findByText("已保存")).toBeVisible();
  });

  test("限流策略才显示每小时上限字段", async () => {
    vi.stubGlobal("fetch", settingsFetchMock());
    renderDialog();

    await screen.findByLabelText("月配额");
    expect(screen.getByLabelText("P1 升级阈值（月用量 %）")).toBeVisible();
    expect(screen.queryByLabelText("P1 每小时上限")).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: /限流/ }));

    expect(await screen.findByLabelText("P1 每小时上限")).toHaveValue(200);
    expect(screen.getByLabelText("P2 每小时上限")).toHaveValue(20);
    expect(screen.queryByLabelText("P1 升级阈值（月用量 %）")).toBeNull();
  });

  test("选择「全部禁止」必须二次确认, 取消则策略不变", async () => {
    vi.stubGlobal("fetch", settingsFetchMock());
    renderDialog();

    await screen.findByLabelText("月配额");
    fireEvent.click(screen.getByRole("radio", { name: /全部禁止/ }));

    const confirmDialog = await screen.findByRole("dialog", { name: "确认启用「全部禁止」？" });
    await userEvent.click(within(confirmDialog).getByRole("button", { name: "取消" }));
    expect(screen.getByRole("radio", { name: /降级/ })).toBeChecked();

    fireEvent.click(screen.getByRole("radio", { name: /全部禁止/ }));
    await userEvent.click(await screen.findByRole("button", { name: "我已理解，启用" }));

    await waitFor(() => expect(screen.getByRole("radio", { name: /全部禁止/ })).toBeChecked());
    expect(screen.getByText("同样拒绝：员工与管理员都无法通过钉钉登录")).toBeVisible();
  });

  test("客户端校验不通过时不发请求, 并把错误标在字段上", async () => {
    const fetchMock = settingsFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    renderDialog();

    const monthlyQuota = await screen.findByLabelText("月配额");
    fireEvent.change(monthlyQuota, { target: { value: "0" } });
    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));

    expect(await screen.findByText("请输入 1 到 1000000000 之间的整数")).toBeVisible();
    expect(screen.getByText("有 1 项需要修正")).toBeVisible();
    expect(requestBody(fetchMock)).toBeNull();
  });

  test("409 版本冲突提示重新加载, 重新加载后取回最新文档", async () => {
    const fetchMock = settingsFetchMock({ putStatus: 409 });
    vi.stubGlobal("fetch", fetchMock);
    renderDialog();

    const dailyCap = await screen.findByLabelText("日上限");
    fireEvent.change(dailyCap, { target: { value: "4000" } });
    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));

    expect(await screen.findByText("设置已被其他管理员更新")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "重新加载最新设置" }));

    await waitFor(() => expect(screen.getByLabelText("日上限")).toHaveValue(5000));
  });

  test("422 字段错误落到对应输入框", async () => {
    const fetchMock = settingsFetchMock({ putStatus: 422, putFields: ["config.api.daily_cap"] });
    vi.stubGlobal("fetch", fetchMock);
    renderDialog();

    const dailyCap = await screen.findByLabelText("日上限");
    fireEvent.change(dailyCap, { target: { value: "4000" } });
    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));

    expect(await screen.findByText("该字段未通过服务端校验")).toBeVisible();
    expect(screen.getByText("设置保存失败")).toBeVisible();
  });

  test("有未保存修改时关闭要先确认", async () => {
    const onClose = vi.fn();
    vi.stubGlobal("fetch", settingsFetchMock());
    renderDialog(onClose);

    const monthlyQuota = await screen.findByLabelText("月配额");
    fireEvent.change(monthlyQuota, { target: { value: "600000" } });
    await userEvent.click(screen.getByRole("button", { name: "取消" }));

    expect(await screen.findByText("放弃未保存的修改？")).toBeVisible();
    expect(onClose).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test("告警分区展示发送方状态与接收人规模", async () => {
    vi.stubGlobal("fetch", settingsFetchMock());
    renderDialog();

    await screen.findByLabelText("月配额");
    await userEvent.click(screen.getByRole("tab", { name: "告警" }));

    expect(await screen.findByLabelText("发送方 app_key")).toHaveValue("host-ops");
    expect(screen.getByText("发送方就绪")).toBeVisible();
    expect(screen.getByText("接收人 3 人")).toBeVisible();
  });
});

function renderDialog(onClose: () => void = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <UsageSettingsDialog onClose={onClose} />
    </QueryClientProvider>,
  );
}

/** 有状态的假服务端: PUT 成功后版本自增并成为后续 GET 的返回值, 与真实接口一致。 */
function settingsFetchMock(options: { putStatus?: number; putFields?: string[] } = {}) {
  let current: UsageSettingsPayload = PAYLOAD;
  return vi.fn<typeof fetch>(async (input, init) => {
    if (String(input) !== SETTINGS_URL) {
      throw new Error(`Unexpected fetch: ${String(input)}`);
    }
    if ((init?.method ?? "GET") === "GET") {
      return jsonResponse(current);
    }
    const status = options.putStatus ?? 200;
    if (status === 200) {
      const body = typeof init?.body === "string" ? (JSON.parse(init.body) as { config: UsageConfig }) : null;
      current = { ...current, config: body?.config ?? current.config, version: current.version + 1 };
      return jsonResponse(current);
    }
    return jsonResponse(
      {
        error: {
          code: status === 409 ? "CONFLICT" : "VALIDATION_ERROR",
          message: "rejected",
          details: options.putFields ? { fields: options.putFields } : undefined,
        },
      },
      status,
    );
  });
}

function requestBody(fetchMock: ReturnType<typeof settingsFetchMock>): unknown {
  const call = fetchMock.mock.calls.find(([, init]) => (init?.method ?? "GET") !== "GET");
  const body = call?.[1]?.body;
  return typeof body === "string" ? (JSON.parse(body) as unknown) : null;
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
