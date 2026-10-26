import { useRef, useState } from "react";
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
  changed: (version?: number) => Promise<void>,
  refreshAssessment: () => void = () => {},
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
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const active = useRef(false);
  function remember(value: Command | null) {
    setPending(value);
    writeStored(storageKey, value);
  }
  async function send(path?: string, body?: Record<string, unknown>) {
    if (active.current || conflict || needsRefresh || (!pending && (!path || !body))) return;
    active.current = true;
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
      const result = await api<Pick<CommandResult, "version">>(command.path, {
        method: "POST",
        body: command.body,
        headers: { "Idempotency-Key": command.key },
      });
      if (!result || !Number.isSafeInteger(result.version))
        throw new ApiError(200, "invalid_response", "Не удалось прочитать версию заявки в ответе сервера");
      remember(null);
      try {
        await changed(result.version);
      } catch (value) {
        setNeedsRefresh(true);
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
        if (
          value.code === "risk_acknowledgement_required" ||
          value.code === "risk_model_unavailable"
        ) {
          // Эти ответы не сохраняют действие, но сохраняют оценку без смены версии заявки.
          remember(null);
          refreshAssessment();
        } else if (value.status === 409) setConflict(true);
      }
    } finally {
      active.current = false;
      setBusy(false);
    }
  }
  async function refresh() {
    if (active.current) return;
    active.current = true;
    setBusy(true);
    try {
      await changed();
      setConflict(false);
      setNeedsRefresh(false);
      setError("");
      setFields({});
    } catch (value) {
      setError(errorMessage(value));
    } finally {
      active.current = false;
      setBusy(false);
    }
  }
  return { pending, busy, error, fields, conflict, needsRefresh, send, refresh };
}
export type ReviewCommand = ReturnType<typeof useReviewCommand>;
