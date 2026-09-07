import { describe, expect, test } from "vitest";

import {
  IDENTITY_CHECK_MESSAGE_TYPE,
  IDENTITY_CHECK_VISIBLE_THROTTLE_MS,
  INITIAL_IDENTITY_CHECK_STATE,
  completeIdentityCheck,
  identityCheckAction,
  identityCheckResultFromMessage,
  requestIdentityCheck,
} from "./upstreamIdentityCheck";
import type { IdentityCheckOutcome, IdentityCheckState } from "./upstreamIdentityCheck";

const ORIGIN = "https://iam.jiefakj.com";
const ME = "alice@example.com";

/** 结论里的身份就是本标签页显示的人(最常见的情况)。 */
function result(outcome: IdentityCheckOutcome, userId = outcome === "unchanged" || outcome === "changed" ? ME : "") {
  return { outcome, userId };
}

function runningState(trigger: IdentityCheckState["runningTrigger"], lastCompletedAt: number | null = null): IdentityCheckState {
  return { runningTrigger: trigger, lastCompletedAt };
}

describe("requestIdentityCheck", () => {
  test("首次启动直接发起复核", () => {
    const request = requestIdentityCheck(INITIAL_IDENTITY_CHECK_STATE, "boot", 1_000);

    expect(request.start).toBe(true);
    expect(request.state.runningTrigger).toBe("boot");
  });

  test("已有复核在途时后到的触发被合并掉", () => {
    const state = runningState("boot");

    const request = requestIdentityCheck(state, "interval", 1_000);

    expect(request.start).toBe(false);
    expect(request.state).toBe(state);
  });

  test("401 在途时到达会把在途复核升级成 401 触发, 而不是白跑一趟", () => {
    const request = requestIdentityCheck(runningState("interval"), "session_expired", 1_000);

    expect(request.start).toBe(false);
    expect(request.state.runningTrigger).toBe("session_expired");
  });

  test("回到前台时距上次复核不足 60 秒则跳过", () => {
    const state = runningState(null, 1_000);

    const request = requestIdentityCheck(state, "visible", 1_000 + IDENTITY_CHECK_VISIBLE_THROTTLE_MS - 1);

    expect(request.start).toBe(false);
    expect(request.state).toBe(state);
  });

  test("回到前台时距上次复核满 60 秒则复核", () => {
    const request = requestIdentityCheck(
      runningState(null, 1_000),
      "visible",
      1_000 + IDENTITY_CHECK_VISIBLE_THROTTLE_MS,
    );

    expect(request.start).toBe(true);
  });

  test.each(["boot", "interval", "session_expired"] as const)(
    "%s 不受回到前台的节流窗口约束",
    (trigger) => {
      const request = requestIdentityCheck(runningState(null, 1_000), trigger, 1_500);

      expect(request.start).toBe(true);
    },
  );
});

describe("completeIdentityCheck", () => {
  test("收尾后记下完成时间并按触发源给出动作", () => {
    const completion = completeIdentityCheck(runningState("session_expired"), result("error"), 9_000, ME);

    expect(completion.state).toEqual({ runningTrigger: null, lastCompletedAt: 9_000 });
    expect(completion.action).toBe("session_expired_notice");
  });

  test("超时收尾之后迟到的结论被丢弃, 不再触发任何动作", () => {
    const state = runningState(null, 9_000);

    const completion = completeIdentityCheck(state, result("changed"), 12_000, ME);

    expect(completion.state).toBe(state);
    expect(completion.action).toBe("none");
  });
});

describe("identityCheckAction", () => {
  test.each(["boot", "visible", "interval", "session_expired"] as const)(
    "上游换人时(%s 触发)整页重载",
    (trigger) => {
      expect(identityCheckAction(result("changed"), trigger, ME)).toBe("reload");
    },
  );

  test.each(["boot", "visible", "interval", "session_expired"] as const)(
    "上游已登出时(%s 触发)跳登录页",
    (trigger) => {
      expect(identityCheckAction(result("logged_out"), trigger, ME)).toBe("sign_in");
    },
  );

  test.each(["boot", "visible", "interval"] as const)("身份未变时(%s 触发)不做任何可见动作", (trigger) => {
    expect(identityCheckAction(result("unchanged"), trigger, ME)).toBe("none");
    expect(identityCheckAction(result("error"), trigger, ME)).toBe("none");
  });

  test("401 触发下身份未变说明本地会话已被静默回调重新建立, 重载即可", () => {
    expect(identityCheckAction(result("unchanged"), "session_expired", ME)).toBe("reload");
  });

  test("401 触发下复核自身失败时才回落到登录失效提示", () => {
    expect(identityCheckAction(result("error"), "session_expired", ME)).toBe("session_expired_notice");
  });

  test.each(["boot", "visible", "interval", "session_expired"] as const)(
    "结论说身份没变但绑定的是另一个人时(%s 触发)照样重载: 另一个标签页刚把共享 cookie 换了人",
    (trigger) => {
      expect(identityCheckAction(result("unchanged", "bob@example.com"), trigger, ME)).toBe("reload");
    },
  );
});

describe("identityCheckResultFromMessage", () => {
  test("接受同源的复核结论, 并带出会话现在绑定的上游身份", () => {
    const parsed = identityCheckResultFromMessage(
      { origin: ORIGIN, data: { type: IDENTITY_CHECK_MESSAGE_TYPE, outcome: "changed", user_id: "bob@example.com" } },
      ORIGIN,
    );

    expect(parsed).toEqual({ outcome: "changed", userId: "bob@example.com" });
  });

  test.each(["logged_out", "error"] as const)("%s 的结论不携带身份", (outcome) => {
    expect(
      identityCheckResultFromMessage(
        { origin: ORIGIN, data: { type: IDENTITY_CHECK_MESSAGE_TYPE, outcome, user_id: "" } },
        ORIGIN,
      ),
    ).toEqual({ outcome, userId: "" });
  });

  test.each([
    { label: "缺字段", data: { type: IDENTITY_CHECK_MESSAGE_TYPE, outcome: "unchanged" } },
    { label: "不是字符串", data: { type: IDENTITY_CHECK_MESSAGE_TYPE, outcome: "changed", user_id: 7 } },
  ])("unchanged/changed 的 user_id $label 时按 error 落地, 不当作身份没变", ({ data }) => {
    expect(identityCheckResultFromMessage({ origin: ORIGIN, data }, ORIGIN)).toEqual({
      outcome: "error",
      userId: "",
    });
  });

  test.each([
    {
      label: "跨源消息",
      message: {
        origin: "https://evil.example.test",
        data: { type: IDENTITY_CHECK_MESSAGE_TYPE, outcome: "logged_out", user_id: "" },
      },
    },
    { label: "别的协议", message: { origin: ORIGIN, data: { type: "webpack:hmr" } } },
    { label: "非对象载荷", message: { origin: ORIGIN, data: "easyauth:identity-check" } },
    { label: "数组载荷", message: { origin: ORIGIN, data: [] } },
  ])("忽略与复核无关的消息: $label", ({ message }) => {
    expect(identityCheckResultFromMessage(message, ORIGIN)).toBeNull();
  });

  test("同源且声明本协议但 outcome 未知时当场抛错", () => {
    expect(() =>
      identityCheckResultFromMessage(
        { origin: ORIGIN, data: { type: IDENTITY_CHECK_MESSAGE_TYPE, outcome: "maybe", user_id: "" } },
        ORIGIN,
      ),
    ).toThrow("身份复核回调给出了未知的 outcome: maybe");
  });
});
