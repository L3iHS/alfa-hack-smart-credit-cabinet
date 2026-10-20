import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, errorMessage } from "../api/client";
import type {
  Application,
  SubmissionPolicy,
  SubmitBody,
  SubmitResult,
} from "../api/types";

type Command = { key: string; body: SubmitBody };
function readCommand(key: string): Command | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || "null");
    if (
      typeof value?.key === "string" &&
      Number.isSafeInteger(value.body?.expected_version) &&
      typeof value.body?.data_confirmed === "boolean" &&
      typeof value.body?.bki_consent === "boolean" &&
      typeof value.body?.consent_version === "string"
    )
      return value;
  } catch {
    /* Хранилище браузера может быть недоступно; повтор остаётся в памяти страницы. */
  }
  return null;
}
const fields: Record<string, string> = {
  purpose: "Цель финансирования",
  amount_kopecks: "Сумма",
  term_months: "Срок",
  period_start: "Начало периода",
  period_end: "Конец периода",
  revenue_kopecks: "Выручка",
  operating_expenses_kopecks: "Операционные расходы",
  existing_debt_payments_kopecks: "Платежи по кредитам",
  documents: "Документы",
  data_confirmed: "Подтверждение данных",
  bki_consent: "Согласие на проверку БКИ",
  consent_version: "Версия согласий",
};
export default function SubmissionPanel({
  application,
  policy,
  owner,
  staff,
  changed,
  submitted,
  lock,
}: {
  application: Application;
  policy: SubmissionPolicy | null;
  owner: string;
  staff: boolean;
  changed: () => Promise<void>;
  submitted: (result: SubmitResult) => void;
  lock: (value: boolean) => void;
}) {
  const storageKey = `credit-submit:${owner}:${application.id}`;
  const [command, setCommand] = useState<Command | null>(() =>
    readCommand(storageKey),
  );
  const [confirmed, setConfirmed] = useState(false);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [conflict, setConflict] = useState(false);
  function remember(value: Command | null) {
    setCommand(value);
    try {
      if (value) sessionStorage.setItem(storageKey, JSON.stringify(value));
      else sessionStorage.removeItem(storageKey);
    } catch {
      /* Отправка работает и при отключённом хранилище браузера. */
    }
  }
  useEffect(() => {
    lock(!!command || busy);
  }, [command, busy, lock]);

  async function send() {
    if (
      busy ||
      (!command && !policy) ||
      conflict ||
      (!command && !application.available_actions.includes("submit"))
    )
      return;
    const request = command || {
      key: crypto.randomUUID(),
      body: {
        expected_version: application.version,
        data_confirmed: confirmed,
        bki_consent: consent,
        consent_version: policy!.consent_version,
      },
    };
    remember(request);
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      const result = await api<SubmitResult>(
        `/applications/${application.id}/submit`,
        {
          method: "POST",
          body: request.body,
          headers: { "Idempotency-Key": request.key },
        },
      );
      remember(null);
      submitted(result);
    } catch (error) {
      setError(errorMessage(error));
      if (error instanceof ApiError) {
        setFieldErrors(error.fields);
        // При неизвестном исходе повторяем ту же команду: новая версия или ключ создадут конфликт.
        if (
          error.status > 0 &&
          error.status < 500 &&
          error.code !== "invalid_response"
        )
          remember(null);
        if (error.status === 409) setConflict(true);
      }
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    setBusy(true);
    try {
      await changed();
      setConflict(false);
      setError("");
      setFieldErrors({});
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  if (staff || (application.status !== "draft" && !command)) return null;
  return (
    <section className="panel next-step submission-panel">
      <h2>Отправка заявки</h2>
      <p>
        Проверьте сведения и приложите документы. После отправки изменить заявку
        будет нельзя.
      </p>
      {policy && (
        <div className="consent-list">
          <label htmlFor="data-confirmed">
            <input
              id="data-confirmed"
              type="checkbox"
              checked={confirmed}
              disabled={busy || !!command || conflict}
              onChange={(event) => setConfirmed(event.target.checked)}
            />{" "}
            <span>{policy.data_confirmation_text}</span>
          </label>
          <label htmlFor="bki-consent">
            <input
              id="bki-consent"
              type="checkbox"
              checked={consent}
              disabled={busy || !!command || conflict}
              onChange={(event) => setConsent(event.target.checked)}
            />{" "}
            <span>{policy.bki_consent_text}</span>
          </label>
        </div>
      )}
      {error && (
        <div className="notice error submission-errors" role="alert">
          <p>{error}</p>
          {Object.keys(fieldErrors).length > 0 && (
            <ul>
              {Object.entries(fieldErrors).map(([name, message]) => (
                <li key={name}>
                  <strong>{fields[name] || name}:</strong> {message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {command && !busy && (
        <p className="muted">
          Ответ не получен. Повтор безопасен и не создаст вторую заявку.
        </p>
      )}
      {conflict ? (
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => void refresh()}
        >
          Загрузить новую версию заявки
        </button>
      ) : (
        <button
          className="button primary"
          disabled={
            busy ||
            (!command && !policy) ||
            (!command && !application.available_actions.includes("submit"))
          }
          onClick={() => void send()}
        >
          {busy
            ? "Отправляем…"
            : command
              ? "Повторить отправку"
              : "Отправить заявку"}
        </button>
      )}
      {!command && (
        <Link className="text-link" to={`/applications/${application.id}/edit`}>
          Продолжить заполнение
        </Link>
      )}
    </section>
  );
}
