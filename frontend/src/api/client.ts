import type { CsrfBinding, User } from "./types";

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
let binding: CsrfBinding | null = null;
let csrfRequest: Promise<CsrfBinding> | null = null;
let identity: string | null = null;
let generation = 0;
function invalidateCsrf() {
  generation++;
  binding = null;
  csrfRequest = null;
}
export function setIdentity(user: User | null) {
  const next = user?.id ?? null;
  if (next !== identity) {
    identity = next;
    invalidateCsrf();
  }
}
export function setCsrf(token: string | null, userId: string | null = null) {
  invalidateCsrf();
  binding = token ? { csrf_token: token, user_id: userId } : null;
}
function expire() {
  identity = null;
  invalidateCsrf();
  window.dispatchEvent(new Event("session-expired"));
}
function sessionChanged() {
  return new ApiError(
    401,
    "session_changed",
    "Сессия изменилась. Войдите снова перед сохранением",
  );
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
async function csrf(): Promise<CsrfBinding> {
  if (binding) return binding;
  if (!csrfRequest) {
    const started = generation;
    const request = raw("/auth/csrf")
      .then(async (response) => {
        const body = await decode(response);
        if (!response.ok)
          throw new ApiError(response.status, body.code, body.message);
        if (
          !body ||
          typeof body.csrf_token !== "string" ||
          !body.csrf_token ||
          (body.user_id !== null && typeof body.user_id !== "string")
        )
          throw sessionChanged();
        // Ответ старой сессии не должен заменить токен после нового входа.
        if (generation !== started) throw sessionChanged();
        binding = { csrf_token: body.csrf_token, user_id: body.user_id };
        return binding;
      })
      .finally(() => {
        if (csrfRequest === request) csrfRequest = null;
      });
    csrfRequest = request;
  }
  return csrfRequest;
}
export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    rawBody?: Blob;
    headers?: Record<string, string>;
    responseType?: "json" | "blob";
  } = {},
): Promise<T> {
  const method = options.method || "GET";
  const login = path === "/auth/login" && method === "POST";
  const expectedIdentity = identity;
  const started = generation;
  const unchanged = () =>
    identity === expectedIdentity && generation === started;
  const headers = new Headers(options.headers);
  // Произвольные заголовки не могут подменить токен текущего владельца формы.
  headers.delete("X-CSRF-Token");
  if (method !== "GET") {
    if (!login && expectedIdentity === null) {
      expire();
      throw sessionChanged();
    }
    let current: CsrfBinding;
    try {
      current = await csrf();
    } catch (error) {
      if (!login && unchanged()) expire();
      throw error;
    }
    if (!unchanged()) throw sessionChanged();
    if (!login && current.user_id !== expectedIdentity) {
      expire();
      throw sessionChanged();
    }
    headers.set("X-CSRF-Token", current.csrf_token);
  }
  if (options.rawBody !== undefined) {
    headers.set(
      "Content-Type",
      options.rawBody.type || "application/octet-stream",
    );
  } else if (options.body !== undefined)
    headers.set("Content-Type", "application/json");
  const response = await raw(path, {
    method,
    headers,
    body:
      options.rawBody ??
      (options.body === undefined ? undefined : JSON.stringify(options.body)),
  });
  if (!unchanged()) throw sessionChanged();
  if (response.ok && options.responseType === "blob") {
    try {
      return (await response.blob()) as T;
    } catch {
      throw new ApiError(
        0,
        "network_error",
        "Не удалось скачать файл. Проверьте подключение и повторите попытку",
      );
    }
  }
  const body = await decode(response);
  if (!response.ok) {
    if (
      response.status === 401 &&
      !login &&
      expectedIdentity !== null &&
      unchanged()
    )
      expire();
    if (response.status === 403 && body.code === "csrf_failed" && unchanged()) {
      invalidateCsrf();
      if (!login) {
        const checking = generation;
        try {
          const current = await csrf();
          if (
            generation === checking &&
            identity === expectedIdentity &&
            current.user_id !== expectedIdentity
          )
            expire();
        } catch {
          // Неподтверждённый владелец токена запрещает следующий повтор изменения.
          if (generation === checking && identity === expectedIdentity)
            expire();
        }
      }
      // Изменение автоматически не повторяется даже при подтверждённой сессии.
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
