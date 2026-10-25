import { useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { useSession } from "../auth/session";
import { api, errorMessage } from "../api/client";
import type { Company } from "../api/types";
import { RouteFocus, useResource } from "./shared";
import { ToastProvider } from "./Toast";

export function Brand() {
  return (
    <span className="brand">
      <span className="brand-mark" aria-hidden="true">
        А<span />
      </span>
      <span>
        Альфа-Бизнес<span className="brand-caption">Кредитный кабинет</span>
      </span>
    </span>
  );
}
export default function AppShell() {
  const { user, logout } = useSession();
  const staff = user?.role === "staff";
  const company = useResource(
    () => (staff ? Promise.resolve(null) : api<Company>("/company")),
    user!.id,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  return (
    <ToastProvider>
    <div className="shell">
      <a className="skip-link" href="#content">
        К содержимому
      </a>
      <aside className="sidebar">
        <Link
          to={staff ? "/staff/applications" : "/applications"}
          className="brand-link"
        >
          <Brand />
        </Link>
        <nav aria-label="Основная навигация">
          <NavLink to={staff ? "/staff/applications" : "/applications"}>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M6 3h9l4 4v14H6V3Z M14 3v5h5 M9 12h7 M9 16h5"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
              />
            </svg>
            {staff ? "Заявки" : "Мои заявки"}
          </NavLink>
        {staff && <NavLink to="/staff/analytics"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 20V12h4v8M10 20V8h4v12M16 20V4h4v16" stroke="currentColor" strokeWidth="1.6" /></svg>Аналитика</NavLink>}
        </nav>
        <button className="mobile-account-toggle" aria-expanded={accountOpen} aria-controls="cabinet-account" onClick={() => setAccountOpen(value => !value)}>Аккаунт</button>
          <div id="cabinet-account" className={`account-menu${accountOpen ? " account-open" : ""}`}>
            <div className="company-avatar" aria-hidden="true">
              {staff ? "Б" : "К"}
            </div>
            <div className="company-name">
              <strong>
                {staff
                  ? "Сотрудник банка"
                  : company.data?.name || user?.display_name}
              </strong>
              <span>
                {staff
                  ? user?.display_name
                  : company.data
                    ? `ИНН ${company.data.inn}`
                    : "Кабинет компании"}
              </span>
            </div>
            <button
              className="logout"
              aria-label="Выйти"
              title="Выйти из аккаунта"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  await logout();
                } catch (e) {
                  setError(errorMessage(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M10 5H5v14h5 M10 12h11 M17 8l4 4-4 4"
                  stroke="currentColor"
                  strokeWidth="1.7"
                />
              </svg>
            </button>
          </div>
      </aside>
      <div className="workspace">
        <main id="content" tabIndex={-1}>
          <RouteFocus />
          {error && (
            <div className="notice error" role="alert">
              {error}
            </div>
          )}
          <Outlet />
        </main>
      </div>
    </div>
    </ToastProvider>
  );
}
