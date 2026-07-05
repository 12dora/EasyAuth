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
  data?: T[];
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

const EMPTY_ITEMS: never[] = [];

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

  const response = await fetch(url, { ...init, headers });
  const payload = await parseResponse(response);
  if (!response.ok) {
    throw buildApiError(response, payload);
  }
  return payload as T;
}

export function itemsFromPayload<T>(payload: unknown): T[] {
  if (isRecord(payload)) {
    const items = payload.data;
    if (Array.isArray(items)) {
      return items as T[];
    }
    // 契约漂移(payload 是对象但 data 不是数组)不得静默吞掉; 开发环境显式告警。
    if (items !== undefined && isDevEnvironment()) {
      console.warn("itemsFromPayload: 期望 payload.data 为数组, 但收到", items);
    }
  }
  return EMPTY_ITEMS;
}

function isDevEnvironment(): boolean {
  const meta = import.meta as unknown as { env?: { DEV?: boolean } };
  return Boolean(meta.env?.DEV);
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
    return response.json();
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
    return new ApiError(
      typeof error.message === "string" ? error.message : statusMessage(response.status),
      response.status,
      typeof error.code === "string" ? error.code : undefined,
      error.details,
    );
  }
  // 非结构化(含非 JSON 哨兵/字符串)响应统一降级为按状态码生成的确定性文案, 不回显原始 body。
  return new ApiError(statusMessage(response.status), response.status);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
