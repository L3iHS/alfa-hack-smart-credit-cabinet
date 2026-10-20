import { useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useSession } from "../auth/session";
import { api, errorMessage } from "../api/client";
import type { Company } from "../api/types";
import { RouteFocus, useResource } from "./shared";

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
  const { pathname } = useLocation();
  const listPath = staff ? "/staff/applications" : "/applications";
  const editMatch = pathname.match(/^\/applications\/([^/]+)\/edit$/);
  const backPath = editMatch ? `/applications/${editMatch[1]}` : listPath;
  const showBack = pathname !== listPath;
  const backLabel = editMatch
    ? "К заявке"
    : staff
      ? "Очередь заявок"
      : "Мои заявки";
  const company = useResource(
    () => (staff ? Promise.resolve(null) : api<Company>("/company")),
    user!.id,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
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
            {staff ? "Заявки на рассмотрение" : "Мои заявки"}
          </NavLink>
        </nav>
        <div className="sidebar-note">
          <span className="demo-dot" />
          Демонстрационный кабинет
          <p>Синтетические данные и условия для хакатона</p>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          {showBack && (
            <Link className="back-link" to={backPath}>
              <span aria-hidden="true">‹&nbsp;</span>
              {backLabel}
            </Link>
          )}
          <div className="account-menu">
            <div className="company-avatar" aria-hidden="true">
              {staff ? "Б" : "К"}
            </div>
            <div className="company-name">
              <strong>
                {staff
                  ? "Рабочее место сотрудника"
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
              Выйти
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M10 5H5v14h5 M10 12h11 M17 8l4 4-4 4"
                  stroke="currentColor"
                  strokeWidth="1.7"
                />
              </svg>
            </button>
          </div>
        </header>
        <main id="content" tabIndex={-1}>
          <RouteFocus />
          {error && (
            <div className="notice error" role="alert">
              {error}
            </div>
          )}
          <Outlet />
        </main>
        <footer className="workspace-footer">
          Прототип для хакатона • Условия не являются предложением банка
        </footer>
      </div>
    </div>
  );
}
