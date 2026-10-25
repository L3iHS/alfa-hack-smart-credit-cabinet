import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import type { ApplicationStatus } from "../api/types";
import { ApiError, errorMessage } from "../api/client";

export function Loading() {
  return (
    <div className="state-panel" role="status">
      <span className="spinner" />
      Загружаем данные…
    </div>
  );
}
export function ErrorPanel({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  const { pathname } = useLocation();
  const missing = error instanceof ApiError && error.status === 404;
  return (
    <section className="panel state-panel" role="alert">
      <h2>{missing ? "Заявка не найдена" : "Не удалось загрузить данные"}</h2>
      <p>
        {missing
          ? "Возможно, ссылка изменилась или у вас нет доступа к этой заявке"
          : errorMessage(error)}
      </p>
      {retry && !missing ? (
        <button className="button secondary" onClick={retry}>
          Повторить
        </button>
      ) : (
        <Link className="button secondary" to={pathname.startsWith("/staff/") ? "/staff/applications" : "/applications"}>
          К списку заявок
        </Link>
      )}
    </section>
  );
}
export function useResource<T>(
  load: () => Promise<T>,
  key: string,
  pollMilliseconds?: number,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    let active = true;
    setData(null);
    setError(null);
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function update() {
      try {
        const value = await load();
        if (active) {
          setData(value);
          setError(null);
        }
      } catch (value) {
        if (active) setError(value);
      } finally {
        if (active && pollMilliseconds)
          timer = setTimeout(update, pollMilliseconds);
      }
    }
    void update();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [key, generation, pollMilliseconds]);
  return { data, error, reload: () => setGeneration((value) => value + 1) };
}
export function PageHeading({
  title,
  subtitle,
  metadata,
  children,
}: {
  title: string;
  subtitle?: string;
  metadata?: ReactNode;
  children?: ReactNode;
}) {
  const { pathname } = useLocation();
  const staff = pathname.startsWith("/staff/");
  const listPath = staff ? "/staff/applications" : "/applications";
  const editing = pathname.match(/^\/applications\/([^/]+)\/edit$/);
  const backPath = editing ? `/applications/${editing[1]}` : listPath;
  const backLabel = editing ? "К заявке" : staff ? "Заявки" : "Мои заявки";
  return (
    <div className="page-heading">
      <div>
        <div className="page-title-line">
          {pathname !== listPath && <Link className="back-link" to={backPath} aria-label={backLabel} title={backLabel}><span aria-hidden="true">‹</span></Link>}
          <h1>{title}</h1>
        </div>
        {subtitle && <p>{subtitle}</p>}
        {metadata && <div className="page-metadata">{metadata}</div>}
      </div>
      {children}
    </div>
  );
}
export function ApplicationNumber({ number }: { number: string }) {
  const [feedback, setFeedback] = useState("");
  return <span className="application-number">
    <span>{number || "Номер не указан"}</span>
    <button className="copy-number" type="button" aria-label={`Скопировать номер ${number}`} title="Скопировать номер" disabled={!number} onClick={async () => {
      try {
        await navigator.clipboard.writeText(number);
        setFeedback("Номер скопирован");
      } catch {
        setFeedback("Не удалось скопировать. Выделите номер и скопируйте его вручную");
      }
    }}><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="8" y="8" width="11" height="13" rx="2" stroke="currentColor" strokeWidth="1.6"/><path d="M15 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h3" stroke="currentColor" strokeWidth="1.6"/></svg></button>
    <span className="copy-feedback" role="status">{feedback}</span>
  </span>;
}
export function Status({ status = "draft" }: { status?: ApplicationStatus }) {
  return (
    <span className={`status status-${status}`}>
      <span />
      {statusLabels[status]}
    </span>
  );
}
export function money(value: number | null) {
  if (value === null) return "Не указана";
  const integer = (BigInt(value) / 100n).toLocaleString("ru-RU");
  const fraction = BigInt(value) % 100n;
  return `${integer}${fraction ? `,${String(fraction).padStart(2, "0")}` : ""} ₽`;
}
export function dateTime(value: string) {
  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
export function date(value: string | null) {
  return value
    ? new Date(`${value}T12:00:00`).toLocaleDateString("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      })
    : "Не указан";
}
export function Pagination({
  offset,
  total,
  limit,
  onChange,
}: {
  offset: number;
  total: number;
  limit: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  return (
    <nav className="pagination" aria-label="Страницы">
      <button
        className="button secondary"
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        Назад
      </button>
      <span>
        {offset + 1}–{Math.min(offset + limit, total)} из {total}
      </span>
      <button
        className="button secondary"
        disabled={offset + limit >= total}
        onClick={() => onChange(offset + limit)}
      >
        Далее
      </button>
    </nav>
  );
}
export function RouteFocus() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
    document.getElementById("content")?.focus();
  }, [pathname]);
  return null;
}

export const statusLabels: Record<ApplicationStatus, string> = {
  draft: "Черновик",
  submitted: "Отправлена",
  processing: "Проверяем данные",
  needs_info: "Нужны уточнения",
  manual_review: "На рассмотрении",
  counteroffer: "Другие условия",
  approved: "Одобрена",
  rejected: "Отказ",
};
