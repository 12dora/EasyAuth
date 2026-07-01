export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface Pagination {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
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
    const items = payload.items ?? payload.data;
    if (Array.isArray(items)) {
      return items as T[];
    }
  }
  return EMPTY_ITEMS;
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

async function parseResponse(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return null;
  }
  const contentType = response.headers.get("Content-Type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function buildApiError(response: Response, payload: unknown): ApiError {
  if (isRecord(payload) && isRecord(payload.error)) {
    const error = payload.error as ApiErrorShape;
    return new ApiError(
      typeof error.message === "string" ? error.message : `请求失败 (${response.status})`,
      response.status,
      typeof error.code === "string" ? error.code : undefined,
      error.details,
    );
  }
  const message = typeof payload === "string" && payload ? payload : `请求失败 (${response.status})`;
  return new ApiError(message, response.status);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
