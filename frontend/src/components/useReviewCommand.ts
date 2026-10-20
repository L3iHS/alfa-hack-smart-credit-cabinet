import { useState } from "react";
import { api, ApiError, errorMessage } from "../api/client";
import type { CommandResult } from "../api/types";

type Command = { key: string; path: string; body: Record<string, unknown> };
export function readStored<T>(key: string, fallback: T): T {
  try {
    return JSON.parse(sessionStorage.getItem(key) || "null") ?? fallback;
  } catch {
    return fallback;
  }
}
export function writeStored(key: string, value: unknown) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* При отключённом хранилище ввод остаётся в памяти страницы. */
  }
}
export function useReviewCommand(
  owner: string,
  id: string,
  changed: () => Promise<void>,
) {
  const storageKey = `credit-command:v1:${owner}:${id}`;
  const [pending, setPending] = useState<Command | null>(() => {
    const value = readStored<Command | null>(storageKey, null);
    return value &&
      typeof value.key === "string" &&
      typeof value.path === "string" &&
      value.body &&
      Number.isSafeInteger(value.body.expected_version)
      ? value
      : null;
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [conflict, setConflict] = useState(false);
  function remember(value: Command | null) {
    setPending(value);
    writeStored(storageKey, value);
  }
  async function send(path?: string, body?: Record<string, unknown>) {
    if (busy || conflict || (!pending && (!path || !body))) return;
    const command = pending || {
      key: crypto.randomUUID(),
      path: path!,
      body: body!,
    };
    remember(command);
    setBusy(true);
    setError("");
    setFields({});
    try {
      await api<CommandResult>(command.path, {
        method: "POST",
        body: command.body,
        headers: { "Idempotency-Key": command.key },
      });
      remember(null);
      try {
        await changed();
      } catch (value) {
        setError(
          `Действие сохранено. Не удалось обновить карточку: ${errorMessage(value)}`,
        );
      }
    } catch (value) {
      setError(errorMessage(value));
      if (value instanceof ApiError) {
        setFields(value.fields);
        // Смена сессии после POST и отказ авторизации повтора не проясняют прежний исход.
        const uncertainSession =
          value.code === "session_changed" ||
          (!!pending && (value.status === 401 || value.status === 403));
        // Сбой сети, сервера или чтения ответа также не подтверждает отсутствие записи.
        if (
          value.status > 0 &&
          value.status < 500 &&
          value.code !== "invalid_response" &&
          !uncertainSession
        )
          remember(null);
        if (value.status === 409) setConflict(true);
      }
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    if (busy) return;
    setBusy(true);
    try {
      await changed();
      setConflict(false);
      setError("");
      setFields({});
    } catch (value) {
      setError(errorMessage(value));
    } finally {
      setBusy(false);
    }
  }
  return { pending, busy, error, fields, conflict, send, refresh };
}
