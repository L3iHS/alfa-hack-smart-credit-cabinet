import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { useSession } from "../auth/session";
import { ApiError, errorMessage } from "../api/client";
import { Brand } from "../components/AppShell";
import { ErrorPanel, Loading } from "../components/shared";

export default function LoginPage() {
  const {
    user,
    loading,
    error: sessionError,
    refresh,
    expired,
    login,
    recovery,
  } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  if (loading) return <Loading />;
  if (user)
    return (
      <Navigate
        to={
          recovery.current?.owner === user.id
            ? recovery.current.path
            : user.role === "staff"
              ? "/staff/applications"
              : "/applications"
        }
        replace
      />
    );
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFields({});
    try {
      await login(email.trim(), password);
    } catch (e) {
      setError(errorMessage(e));
      if (e instanceof ApiError) setFields(e.fields);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <header>
        <Brand />
        <span className="demo-label">Демонстрационный прототип</span>
      </header>
      <main className="login-layout">
        <section className="login-intro">
          <span className="intro-rule" />
          <h1>
            Финансирование
            <br />
            для вашего дела
          </h1>
          <p>
            Выберите кредитный продукт и сохраните заявку. Вернитесь к
            заполнению, когда будет удобно.
          </p>
          <div className="login-products">
            <div>
              <span className="product-glyph" aria-hidden="true">
                ↻
              </span>
              <strong>На текущие задачи</strong>
              <span>Оборотный кредит</span>
            </div>
            <div>
              <span className="product-glyph" aria-hidden="true">
                ▧
              </span>
              <strong>На развитие бизнеса</strong>
              <span>Кредит на оборудование</span>
            </div>
          </div>
          <p className="demo-explanation">
            В кабинете используются тестовые компании и демонстрационные условия
            кредитования
          </p>
        </section>
        <section className="panel login-card">
          <h2>Вход в кабинет</h2>
          <p className="muted">Для клиентов и сотрудников банка</p>
          {expired && (
            <div className="notice" role="status">
              Сессия завершилась. Войдите снова
              {recovery.current
                ? " в ту же учётную запись — введённые данные сохранены в этой вкладке"
                : ""}
            </div>
          )}
          {sessionError ? (
            <ErrorPanel error={new Error(sessionError)} retry={refresh} />
          ) : (
            <form onSubmit={submit}>
              <label className="field" htmlFor="email">
                <span>Электронная почта</span>
                <input
                  id="email"
                  type="email"
                  autoComplete="username"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  aria-invalid={!!fields.email}
                  aria-describedby={fields.email ? "email-error" : undefined}
                />
                {fields.email && (
                  <small id="email-error" className="field-error">
                    {fields.email}
                  </small>
                )}
              </label>
              <label className="field" htmlFor="password">
                <span>Пароль</span>
                <input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  aria-invalid={!!fields.password}
                  aria-describedby={
                    fields.password ? "password-error" : undefined
                  }
                />
                {fields.password && (
                  <small id="password-error" className="field-error">
                    {fields.password}
                  </small>
                )}
              </label>
              {error && (
                <div className="notice error" role="alert">
                  {error}
                </div>
              )}
              <button className="button primary login-submit" disabled={busy}>
                {busy ? "Входим…" : "Войти"}
              </button>
            </form>
          )}
          <div className="login-help">
            Используйте демонстрационную учётную запись, которую предоставила
            команда проекта
          </div>
        </section>
      </main>
      <footer>Умный кредитный кабинет • Прототип для хакатона</footer>
    </div>
  );
}
