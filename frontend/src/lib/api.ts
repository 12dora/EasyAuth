export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface Pagination {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
}

/**
 * 后端统一列表信封: `{ data, pagination? }`(见 api_payloads.list_payload / paginated_list_payload)。
 * 作为前端唯一的列表载荷类型来源, 避免各处零散声明 `{ items?: T[] }` 与后端契约漂移。
 */
export interface ListPayload<T> {
  data: T[];
  pagination?: Pagination;
}

export interface ApiErrorShape {
  code?: string;
  message?: string;
  details?: JsonValue;
}

export class ApiError extends Error {
  status: number;
  code?: string;
  details?: JsonValue;

  constructor(message: string, status: number, code?: string, details?: JsonValue) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export interface ApiRequestOptions extends Omit<RequestInit, "body"> {
  body?: BodyInit | JsonValue;
}

export const API_SESSION_EXPIRED_EVENT = "easyauth:api-session-expired";

export function readCsrfToken(): string {
  const input = document.querySelector<HTMLInputElement>('input[name="csrfmiddlewaretoken"]');
  if (input?.value) {
    return input.value;
  }
  const meta = document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]');
  if (meta?.content) {
    return meta.content;
  }
  const cookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("csrftoken="));
  return cookie ? decodeURIComponent(cookie.slice("csrftoken=".length)) : "";
}

export async function apiRequest<T = unknown>(
  url: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const headers = headerRecord(options.headers);
  const init: RequestInit = {
    credentials: "include",
    method: options.method,
    mode: options.mode,
    cache: options.cache,
    redirect: options.redirect,
    referrer: options.referrer,
    referrerPolicy: options.referrerPolicy,
    integrity: options.integrity,
    keepalive: options.keepalive,
    signal: options.signal,
  };

  if (options.body !== undefined) {
    if (isBodyInit(options.body)) {
      init.body = options.body;
    } else {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
  }

  if (shouldAttachCsrf(init.method ?? "GET")) {
    const token = readCsrfToken();
    if (token) {
      headers["X-CSRFToken"] = token;
    }
  }

  let response: Response;
  try {
    response = await fetch(url, { ...init, headers });
  } catch {
    throw new ApiError("网络连接失败，请检查网络后重试。", 0, "NETWORK_ERROR", undefined);
  }
  const payload = await parseResponse(response);
  if (!response.ok) {
    throw buildApiError(response, payload);
  }
  if (payload === NON_JSON_BODY) {
    throw new ApiError("服务响应格式异常，请刷新后重试。", response.status, "UNEXPECTED_RESPONSE_TYPE");
  }
  return payload as T;
}

export function itemsFromPayload<T>(payload: unknown): T[] {
  if (payload === undefined || payload === null) {
    return [];
  }
  if (isRecord(payload)) {
    const items = payload.data;
    if (Array.isArray(items)) {
      return items as T[];
    }
  }
  throw new ApiError("列表响应契约异常，请刷新后重试。", 200, "LIST_PAYLOAD_CONTRACT_ERROR", {
    expected: "data[]",
  });
}

function shouldAttachCsrf(method: string): boolean {
  return !["GET", "HEAD", "OPTIONS", "TRACE"].includes(method.toUpperCase());
}

function headerRecord(headers: HeadersInit | undefined): Record<string, string> {
  if (!headers) {
    return {};
  }
  if (headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }
  return { ...headers };
}

function isBodyInit(body: ApiRequestOptions["body"]): body is BodyInit {
  return (
    typeof body === "string" ||
    body instanceof Blob ||
    body instanceof FormData ||
    body instanceof URLSearchParams ||
    body instanceof ArrayBuffer
  );
}

/** 非 JSON 响应体的哨兵: 绝不把网关 HTML / DEBUG traceback 原文当作用户可见文案。 */
const NON_JSON_BODY = Symbol("easyauth.nonJsonBody");

async function parseResponse(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return null;
  }
  const contentType = response.headers.get("Content-Type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      return await response.json();
    } catch {
      if (response.ok) {
        throw new ApiError("服务响应格式异常，请刷新后重试。", response.status, "INVALID_JSON_RESPONSE");
      }
      throw new ApiError(statusMessage(response.status), response.status, "INVALID_JSON_RESPONSE");
    }
  }
  // 非 JSON 响应体不回传, 避免被 buildApiError 或调用方原样回显给用户。
  return NON_JSON_BODY;
}

const STATUS_MESSAGES: Record<number, string> = {
  400: "请求参数有误",
  401: "登录状态已失效, 请重新登录",
  403: "没有访问权限",
  404: "请求的资源不存在",
  409: "操作与当前状态冲突, 请刷新后重试",
  422: "请求参数校验未通过",
  429: "操作过于频繁, 请稍后再试",
  500: "服务器内部错误",
  502: "网关错误",
  503: "服务暂不可用",
};

function statusMessage(status: number): string {
  const base = STATUS_MESSAGES[status];
  return base ? `${base} (${status})` : `请求失败 (${status})`;
}

function buildApiError(response: Response, payload: unknown): ApiError {
  if (isRecord(payload) && isRecord(payload.error)) {
    const error = payload.error as ApiErrorShape;
    const apiError = new ApiError(
      typeof error.message === "string" ? error.message : statusMessage(response.status),
      response.status,
      typeof error.code === "string" ? error.code : undefined,
      error.details,
    );
    emitSessionExpired(apiError);
    return apiError;
  }
  // 非结构化(含非 JSON 哨兵/字符串)响应统一降级为按状态码生成的确定性文案, 不回显原始 body。
  const apiError = new ApiError(statusMessage(response.status), response.status);
  emitSessionExpired(apiError);
  return apiError;
}

function emitSessionExpired(error: ApiError): void {
  if (error.status !== 401) {
    return;
  }
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(
    new CustomEvent(API_SESSION_EXPIRED_EVENT, {
      detail: {
        code: error.code ?? "AUTHENTICATION_FAILED",
        message: error.message,
      },
    }),
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
