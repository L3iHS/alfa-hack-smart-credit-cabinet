import type { User } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields: Record<string, string> = {},
  ) {
    super(message);
  }
}
let csrfToken: string | null = null;
let csrfRequest: Promise<string> | null = null;
let identity: string | null = null;
export function setIdentity(user: User | null) {
  identity = user?.id ?? null;
}
export function setCsrf(token: string | null) {
  csrfToken = token;
}
function expire() {
  csrfToken = null;
  window.dispatchEvent(new Event("session-expired"));
}
async function decode(response: Response) {
  if (response.status === 204) return undefined;
  try {
    return JSON.parse(await response.text(), (_key, value: unknown) => {
      if (
        typeof value === "number" &&
        Number.isInteger(value) &&
        !Number.isSafeInteger(value)
      )
        throw new Error("unsafe_integer");
      return value;
    });
  } catch {
    throw new ApiError(
      response.status,
      "invalid_response",
      "Не удалось прочитать ответ сервера. Обновите страницу или попробуйте позже",
    );
  }
}
async function raw(path: string, init?: RequestInit) {
  try {
    return await fetch(`/api/v1${path}`, {
      credentials: "same-origin",
      ...init,
    });
  } catch {
    throw new ApiError(
      0,
      "network_error",
      "Нет связи с сервером. Проверьте подключение и повторите попытку",
    );
  }
}
async function csrf() {
  if (csrfToken) return csrfToken;
  if (!csrfRequest)
    csrfRequest = raw("/auth/csrf")
      .then(async (response) => {
        const body = await decode(response);
        if (!response.ok)
          throw new ApiError(response.status, body.code, body.message);
        csrfToken = body.csrf_token;
        return body.csrf_token as string;
      })
      .finally(() => {
        csrfRequest = null;
      });
  return csrfRequest;
}
export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const method = options.method || "GET";
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["X-CSRF-Token"] = await csrf();
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await raw(path, {
    method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const body = await decode(response);
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login" && identity !== null)
      expire();
    if (response.status === 403 && body.code === "csrf_failed") {
      csrfToken = null;
      const current = await raw("/me");
      if (
        current.status === 401 ||
        (current.ok && (await decode(current)).id !== identity)
      )
        expire();
      else await csrf();
      // Повтор изменения выполняет пользователь: автоматическая отправка может потерять данные.
    }
    throw new ApiError(
      response.status,
      body.code || "request_failed",
      body.message || "Не удалось выполнить запрос",
      body.field_errors || {},
    );
  }
  return body as T;
}
export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Не удалось выполнить запрос";
}
