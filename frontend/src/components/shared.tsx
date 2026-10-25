import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import type { ApplicationStatus } from "../api/types";
import { ApiError, errorMessage } from "../api/client";
import { useToast } from "./Toast";

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
  const showToast = useToast();
  return <span className="application-number">
    <button className="copy-number" type="button" aria-label={`Скопировать номер ${number}`} title="Скопировать номер" disabled={!number} onClick={async () => {
      try {
        await navigator.clipboard.writeText(number);
        showToast("Номер скопирован");
      } catch {
        showToast("Не удалось скопировать. Выделите номер и скопируйте его вручную", true);
      }
    }}><span>{number || "Номер не указан"}</span></button>
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
  withdrawn: "Отозвана",
};

export function StatusFilter({ value, staff = false, onChange }: { value: ApplicationStatus | ''; staff?: boolean; onChange: (status: ApplicationStatus | '') => void }) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const options: { value: ApplicationStatus | ''; label: string }[] = [
    { value: '', label: 'Все статусы' },
    ...Object.entries(statusLabels).filter(([status]) => !staff || status !== 'draft').map(([status, label]) => ({ value: status as ApplicationStatus, label })),
  ];
  const selected = Math.max(0, options.findIndex(option => option.value === value));
  useEffect(() => {
    if (!open) return;
    function outside(event: PointerEvent) { if (!root.current?.contains(event.target as Node)) setOpen(false); }
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open]);
  useEffect(() => {
    const option = list.current?.children[active] as HTMLElement | undefined;
    if (!open || !option || !list.current) return;
    if (option.offsetTop < list.current.scrollTop) list.current.scrollTop = option.offsetTop;
    else if (option.offsetTop + option.offsetHeight > list.current.scrollTop + list.current.clientHeight) list.current.scrollTop = option.offsetTop + option.offsetHeight - list.current.clientHeight;
  }, [active, open]);
  function choose(index: number) { onChange(options[index].value); setOpen(false); }
  function keyboard(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === 'Tab') { setOpen(false); return; }
    if (event.key === 'Escape') { if (open) { event.preventDefault(); event.stopPropagation(); } setOpen(false); return; }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault(); const direction = event.key === 'ArrowDown' ? 1 : -1;
      setActive(((open ? active : selected) + direction + options.length) % options.length); setOpen(true);
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault(); setActive(event.key === 'Home' ? 0 : options.length - 1); setOpen(true);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault(); if (open) choose(active); else { setActive(selected); setOpen(true); }
    }
  }
  return <div className="purpose-picker status-picker" ref={root} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
    <button type="button" className="purpose-trigger" role="combobox" aria-label="Статус" aria-haspopup="listbox" aria-expanded={open} aria-controls={open ? `${id}-options` : undefined} aria-activedescendant={open ? `${id}-option-${active}` : undefined} onClick={() => { setActive(selected); setOpen(current => !current); }} onKeyDown={keyboard}>
      <span>{options[selected].label}</span><span className="purpose-chevron" aria-hidden="true" />
    </button>
    {open && <ul ref={list} id={`${id}-options`} className="purpose-options status-options" role="listbox" aria-label="Статус">
      {options.map((option, index) => <li id={`${id}-option-${index}`} key={option.value} role="option" aria-selected={option.value === value} className={active === index ? 'active' : ''} onMouseDown={event => event.preventDefault()} onMouseEnter={() => setActive(index)} onClick={() => choose(index)}>
        <span className="status-option-check" aria-hidden="true">{option.value === value && <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"><path d="m3 8 3 3 7-7" /></svg>}</span><span>{option.label}</span>
      </li>)}
    </ul>}
  </div>;
}
