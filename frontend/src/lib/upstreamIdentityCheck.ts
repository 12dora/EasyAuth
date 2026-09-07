/**
 * 上游(Authentik)身份静默复核的纯状态机。
 *
 * 背景: Authentik 会话可能在应用毫不知情的情况下结束, 或者换成另一个人登录,
 * 而 EasyAuth 自己的 Django 会话还活着, 页面就会拿着一个过期或错人的身份继续用。
 * 复核动作本身是往隐藏 iframe 里打 `/auth/login/?silent=1`(后端带 prompt=none 走一趟 Authentik),
 * 回调页用 postMessage 回吐结论。这里只放「什么时候该发起」「结论该落成什么动作」的判定,
 * 与 DOM 无关, 便于单测穷举节流、合并与四种结论。
 */

export const IDENTITY_CHECK_URL = "/auth/login/?silent=1";
export const IDENTITY_CHECK_MESSAGE_TYPE = "easyauth:identity-check";
/** 单次复核的上限; 超时按 error 处理, 也就是回到既有的登录失效提示。 */
export const IDENTITY_CHECK_TIMEOUT_MS = 15_000;
/** 页面可见时的轮询间隔。 */
export const IDENTITY_CHECK_INTERVAL_MS = 300_000;
/** 标签页回到前台时的节流窗口: 窗口内刚复核过就不再复核。 */
export const IDENTITY_CHECK_VISIBLE_THROTTLE_MS = 60_000;

const IDENTITY_CHECK_OUTCOMES = ["unchanged", "changed", "logged_out", "error"] as const;

/** 回调页给出的四种结论, 取值由后端契约固定。 */
export type IdentityCheckOutcome = (typeof IDENTITY_CHECK_OUTCOMES)[number];

/**
 * 回调页给出的完整结论。
 *
 * `userId` 是复核走完之后会话真正绑定的上游(Authentik)用户 id, logged_out/error 下为空串。
 * 结论必须带上它: 后端比的是「新的上游身份」与「会话 cookie 当前绑定的身份」,
 * 而 cookie 是同一浏览器所有标签页共享的。两个标签页都显示 A 时, 其中一个把 cookie 换成了 B,
 * 另一个标签页再复核只会拿到 unchanged(B == B), 但它渲染的还是 A。
 * 所以本标签页必须再拿 `userId` 和自己显示的人对一遍, 对不上就重载。
 */
export interface IdentityCheckResult {
  outcome: IdentityCheckOutcome;
  userId: string;
}

/** 复核自身失败(含超时)时的结论; 失败下没有身份可言。 */
export const IDENTITY_CHECK_ERROR_RESULT: IdentityCheckResult = { outcome: "error", userId: "" };

/** 复核的触发源; 只有 session_expired(API 返回 401) 需要把结论落到用户可见的提示上。 */
export type IdentityCheckTrigger = "boot" | "visible" | "interval" | "session_expired";

/**
 * 结论要执行的动作。
 * - reload: 上游换人后本地会话已切到新身份, 整页重载让所有数据按新身份重取。
 * - sign_in: 上游已登出, 跳到登录页并带上当前地址作为 next。
 * - session_expired_notice: 复核本身失败, 回落到既有的「登录状态已失效」提示。
 * - none: 无需可见变化。
 */
export type IdentityCheckAction = "none" | "reload" | "sign_in" | "session_expired_notice";

export interface IdentityCheckState {
  /** 在途复核的触发源; 没有复核在跑时为 null。 */
  runningTrigger: IdentityCheckTrigger | null;
  /** 上一次复核收尾的时间戳(ms); 供回到前台时节流。 */
  lastCompletedAt: number | null;
}

export const INITIAL_IDENTITY_CHECK_STATE: IdentityCheckState = {
  runningTrigger: null,
  lastCompletedAt: null,
};

export interface IdentityCheckRequest {
  state: IdentityCheckState;
  /** true 表示调用方现在要真的挂起 iframe 发起一次复核。 */
  start: boolean;
}

/**
 * 收到一个触发源时决定是否真的发起复核。
 *
 * 同一时刻只允许一次复核在途: 后到的触发直接丢弃, 不排队(排队只会在网络抖动时堆出一串重复请求)。
 * 唯一的例外是 401: 它必须影响用户可见结果, 所以把在途复核的触发源升级成 session_expired,
 * 让那次复核的结论按 401 的口径落地, 而不是白跑一趟后什么都不做。
 */
export function requestIdentityCheck(
  state: IdentityCheckState,
  trigger: IdentityCheckTrigger,
  now: number,
): IdentityCheckRequest {
  if (state.runningTrigger !== null) {
    if (trigger === "session_expired") {
      return { state: { ...state, runningTrigger: "session_expired" }, start: false };
    }
    return { state, start: false };
  }
  if (trigger === "visible" && isWithinVisibleThrottle(state.lastCompletedAt, now)) {
    return { state, start: false };
  }
  return { state: { ...state, runningTrigger: trigger }, start: true };
}

export interface IdentityCheckCompletion {
  state: IdentityCheckState;
  action: IdentityCheckAction;
}

/**
 * 结论(或超时)到手时收尾。
 *
 * 没有在途复核时说明这是超时收尾之后迟到的那条消息, 只能丢弃:
 * 那次复核已经按 error 落过地了, 再按迟到结论跳转会把用户从当前操作上踢走。
 */
export function completeIdentityCheck(
  state: IdentityCheckState,
  result: IdentityCheckResult,
  now: number,
  currentUserId: string,
): IdentityCheckCompletion {
  const trigger = state.runningTrigger;
  if (trigger === null) {
    return { state, action: "none" };
  }
  return {
    state: { runningTrigger: null, lastCompletedAt: now },
    action: identityCheckAction(result, trigger, currentUserId),
  };
}

/**
 * 结论到动作的映射。
 *
 * unchanged/changed 都先拿结论里的上游身份和本标签页正在显示的人对一遍, 对不上就重载:
 * 后端的「变没变」是相对共享的会话 cookie 说的, 不是相对本标签页渲染的那个人说的(见 IdentityCheckResult)。
 *
 * unchanged 在 401 触发下同样要重载: 静默复核走的是真实 OIDC 回调,
 * 上游身份没变意味着本地会话已经被这次回调重新建立好, 重载即可让刚才 401 的请求成功;
 * 重载会重新经过后端的登录门控, 所以即使会话没恢复也只会被服务端引导到登录页, 不会在前端空转。
 */
export function identityCheckAction(
  result: IdentityCheckResult,
  trigger: IdentityCheckTrigger,
  currentUserId: string,
): IdentityCheckAction {
  switch (result.outcome) {
    case "changed":
      return "reload";
    case "logged_out":
      return "sign_in";
    case "unchanged":
      if (result.userId !== currentUserId) {
        return "reload";
      }
      return trigger === "session_expired" ? "reload" : "none";
    case "error":
      return trigger === "session_expired" ? "session_expired_notice" : "none";
  }
}

export interface IdentityCheckMessage {
  origin: string;
  data: unknown;
}

/**
 * 从 message 事件里取结论。
 *
 * 非同源、非本协议的消息一律返回 null(页面上还有别的 postMessage 来源, 这是正常流量, 不是故障)。
 * 但同源且声明了本协议却给出未知 outcome, 说明前后端契约漂移, 必须当场抛错而不是静默忽略。
 *
 * unchanged/changed 必须带上 `user_id`(会话复核后绑定的上游身份); 缺了就无从判断这条结论说的是不是
 * 本标签页显示的那个人, 按 error 落地(什么都不做 / 401 下回落到提示), 绝不假装身份没变。
 * logged_out/error 用不上身份, 后端给的是空串。
 */
export function identityCheckResultFromMessage(
  message: IdentityCheckMessage,
  expectedOrigin: string,
): IdentityCheckResult | null {
  if (message.origin !== expectedOrigin || !isRecord(message.data)) {
    return null;
  }
  if (message.data.type !== IDENTITY_CHECK_MESSAGE_TYPE) {
    return null;
  }
  const outcome = message.data.outcome;
  if (!isIdentityCheckOutcome(outcome)) {
    throw new Error(`身份复核回调给出了未知的 outcome: ${String(outcome)}`);
  }
  const userId = message.data.user_id;
  if (typeof userId === "string") {
    return { outcome, userId };
  }
  if (outcome === "unchanged" || outcome === "changed") {
    return IDENTITY_CHECK_ERROR_RESULT;
  }
  return { outcome, userId: "" };
}

function isWithinVisibleThrottle(lastCompletedAt: number | null, now: number): boolean {
  return lastCompletedAt !== null && now - lastCompletedAt < IDENTITY_CHECK_VISIBLE_THROTTLE_MS;
}

function isIdentityCheckOutcome(value: unknown): value is IdentityCheckOutcome {
  return (
    typeof value === "string" && (IDENTITY_CHECK_OUTCOMES as readonly string[]).includes(value)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
