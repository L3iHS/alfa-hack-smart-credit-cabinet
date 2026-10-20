import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, errorMessage } from "../api/client";
import type {
  Application,
  Catalog,
  Company,
  DraftFields,
  FormValues,
  Product,
} from "../api/types";
import { useSession } from "../auth/session";
import {
  ErrorPanel,
  Loading,
  money,
  PageHeading,
  useResource,
} from "../components/shared";

const moneyFields = [
  "amount_kopecks",
  "revenue_kopecks",
  "operating_expenses_kopecks",
  "existing_debt_payments_kopecks",
] as const;
function amountInput(value: number | null) {
  if (value === null) return "";
  const amount = BigInt(value);
  return `${amount / 100n},${String(amount % 100n).padStart(2, "0")}`;
}
function valuesFrom(
  application: Application | null,
  product: Product,
): FormValues {
  return {
    product_code: application?.product_code || product.code,
    purpose: application?.purpose || "",
    description: application?.description || "",
    amount_kopecks: amountInput(application?.amount_kopecks ?? null),
    term_months: application?.term_months?.toString() || "",
    period_start: application?.period_start || "",
    period_end: application?.period_end || "",
    revenue_kopecks: amountInput(application?.revenue_kopecks ?? null),
    operating_expenses_kopecks: amountInput(
      application?.operating_expenses_kopecks ?? null,
    ),
    existing_debt_payments_kopecks: amountInput(
      application?.existing_debt_payments_kopecks ?? null,
    ),
  };
}
function parseMoney(value: string): number | null {
  if (!value.trim()) return null;
  const normalized = value.replace(/[\s\u00a0\u202f]/g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(normalized))
    throw new Error(
      "Укажите сумму в рублях, не более двух знаков после запятой",
    );
  const [whole, fraction = ""] = normalized.split(".");
  const result = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (result > BigInt(Number.MAX_SAFE_INTEGER))
    throw new Error("Сумма не должна превышать 90 071 992 547 409,91 ₽");
  return Number(result);
}
function monthDate(value: string, end: boolean) {
  if (!value) return "";
  const [year, month] = value.split("-").map(Number);
  return end
    ? `${value}-${String(new Date(year, month, 0).getDate()).padStart(2, "0")}`
    : `${value}-01`;
}
export default function ApplicationFormPage() {
  const { id } = useParams();
  const { data, error, reload } = useResource(async () => {
    const [catalog, company, application] = await Promise.all([
      api<Catalog>("/products"),
      api<Company>("/company"),
      id ? api<Application>(`/applications/${id}`) : Promise.resolve(null),
    ]);
    return { catalog, company, application };
  }, id || "new");
  if (error) return <ErrorPanel error={error} retry={reload} />;
  if (!data) return <Loading />;
  if (!data.catalog.items.length)
    return (
      <ErrorPanel
        error={new Error("Сейчас нет доступных кредитных продуктов")}
        retry={reload}
      />
    );
  if (
    data.application &&
    !data.application.available_actions.includes("edit_draft")
  )
    return (
      <section className="panel state-panel">
        <h1>Редактирование недоступно</h1>
        <Link to={`/applications/${id}`} className="button secondary">
          Открыть заявку
        </Link>
      </section>
    );
  return <DraftEditor key={id || "new"} {...data} />;
}
function DraftEditor({
  catalog,
  company,
  application,
}: {
  catalog: Catalog;
  company: Company;
  application: Application | null;
}) {
  const { user, recovery } = useSession();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const restored =
    recovery.current?.owner === user!.id && recovery.current.path === pathname
      ? recovery.current
      : null;
  const [values, setValues] = useState<FormValues>(
    () => restored?.values || valuesFrom(application, catalog.items[0]),
  );
  const [record, setRecord] = useState<Application | null>(
    () => restored?.application || application,
  );
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [reloadError, setReloadError] = useState("");
  const [busy, setBusy] = useState(false);
  const product = catalog.items.find(
    (item) => item.code === values.product_code,
  )!;
  useEffect(() => {
    recovery.current = {
      owner: user!.id,
      path: pathname,
      values,
      application: record,
    };
  }, [values, record, pathname, user, recovery]);
  function change(name: keyof FormValues, value: string) {
    setValues((current) => ({ ...current, [name]: value }));
    setFields((current) => ({ ...current, [name]: "" }));
  }
  function field(
    name: keyof FormValues,
    label: string,
    options: { hint?: string; type?: string; maxLength?: number } = {},
  ) {
    return (
      <label className="field" htmlFor={name}>
        <span>{label}</span>
        <input
          id={name}
          type={options.type || "text"}
          inputMode={
            moneyFields.includes(name as (typeof moneyFields)[number])
              ? "decimal"
              : name === "term_months"
                ? "numeric"
                : undefined
          }
          value={values[name]}
          onChange={(event) => change(name, event.target.value)}
          maxLength={options.maxLength}
          aria-invalid={!!fields[name]}
          aria-describedby={`${name}-hint${fields[name] ? ` ${name}-error` : ""}`}
        />
        <small id={`${name}-hint`}>{options.hint}</small>
        {fields[name] && (
          <small id={`${name}-error`} className="field-error">
            {fields[name]}
          </small>
        )}
      </label>
    );
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    setError("");
    const invalid: Record<string, string> = {};
    const parsed = {} as Record<(typeof moneyFields)[number], number | null>;
    for (const name of moneyFields) {
      try {
        parsed[name] = parseMoney(values[name]);
      } catch (e) {
        invalid[name] = errorMessage(e);
      }
    }
    const term = values.term_months.trim() ? Number(values.term_months) : null;
    if (
      term !== null &&
      (!/^\d+$/.test(values.term_months) ||
        !Number.isSafeInteger(term) ||
        term < product.min_term_months ||
        term > product.max_term_months)
    )
      invalid.term_months = `Укажите целое число от ${product.min_term_months} до ${product.max_term_months}`;
    if (
      parsed.amount_kopecks !== null &&
      parsed.amount_kopecks !== undefined &&
      (parsed.amount_kopecks < product.min_amount_kopecks ||
        parsed.amount_kopecks > product.max_amount_kopecks)
    )
      invalid.amount_kopecks = `От ${money(product.min_amount_kopecks)} до ${money(product.max_amount_kopecks)}`;
    setFields(invalid);
    if (Object.keys(invalid).length) {
      setError("Проверьте выделенные поля");
      document.getElementById(Object.keys(invalid)[0])?.focus();
      return;
    }
    const body: DraftFields = {
      ...parsed,
      product_code: values.product_code,
      purpose: values.purpose.trim() || null,
      description: values.description.trim() || null,
      term_months: term,
      period_start: values.period_start || null,
      period_end: values.period_end || null,
    };
    setBusy(true);
    try {
      const saved = record
        ? await api<Application>(`/applications/${record.id}`, {
            method: "PATCH",
            body: { ...body, expected_version: record.version },
          })
        : await api<Application>("/applications", { method: "POST", body });
      recovery.current = null;
      navigate(`/applications/${saved.id}`, { state: { saved: true } });
    } catch (e) {
      if (e instanceof ApiError) {
        setFields(e.fields);
        setConflict(e.status === 409);
        if (Object.keys(e.fields).length)
          document.getElementById(Object.keys(e.fields)[0])?.focus();
      }
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  async function reloadVersion() {
    if (!record) return;
    setBusy(true);
    setReloadError("");
    try {
      const latest = await api<Application>(`/applications/${record.id}`);
      setRecord(latest);
      setValues(valuesFrom(latest, catalog.items[0]));
      setConflict(false);
      setError("");
      setFields({});
    } catch (e) {
      setReloadError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Link
        className="back-link"
        to={record ? `/applications/${record.id}` : "/applications"}
      >
        ‹ {record ? "К заявке" : "Мои заявки"}
      </Link>
      <PageHeading
        title="Заявка на кредитование"
        subtitle="Заполните то, что знаете сейчас. Остальное можно добавить позже."
      />
      <form onSubmit={save} noValidate>
        <div className="form-layout">
          <div className="form-main">
            <section className="panel form-panel">
              <h2>Выбор продукта</h2>
              <fieldset className="product-options">
                <legend className="sr-only">Кредитный продукт</legend>
                {catalog.items.map((item) => (
                  <label
                    className={`product-option ${values.product_code === item.code ? "selected" : ""}`}
                    key={item.code}
                  >
                    <input
                      type="radio"
                      name="product_code"
                      value={item.code}
                      checked={values.product_code === item.code}
                      onChange={() => change("product_code", item.code)}
                    />
                    <span>{item.name}</span>
                    <span className="choice-mark" aria-hidden="true">
                      {values.product_code === item.code ? "✓" : ""}
                    </span>
                  </label>
                ))}
              </fieldset>
              <p className="product-description">
                {product.purpose_description}
              </p>
              {fields.product_code && (
                <p className="field-error" role="alert">
                  {fields.product_code}
                </p>
              )}
              <div className="field-grid">
                {field("amount_kopecks", "Сумма кредита, ₽", {
                  hint: `От ${money(product.min_amount_kopecks)} до ${money(product.max_amount_kopecks)}`,
                  maxLength: 24,
                })}
                {field("term_months", "Срок кредита, месяцев", {
                  hint: `От ${product.min_term_months} до ${product.max_term_months} месяцев`,
                  maxLength: 3,
                })}
              </div>
              {field("purpose", "Цель финансирования", {
                hint: "Например, закупка сырья или покупка оборудования",
                maxLength: 2000,
              })}
              <label className="field" htmlFor="description">
                <span>Дополнительное описание</span>
                <textarea
                  id="description"
                  rows={3}
                  maxLength={10000}
                  value={values.description}
                  onChange={(e) => change("description", e.target.value)}
                  aria-invalid={!!fields.description}
                  aria-describedby="description-hint description-error"
                />
                <small id="description-hint">Необязательно</small>
                <small id="description-error" className="field-error">
                  {fields.description}
                </small>
              </label>
            </section>
            <section className="panel form-panel">
              <h2>Финансы компании</h2>
              <p className="section-description">
                Укажите суммы за один и тот же период из завершённых календарных
                месяцев
              </p>
              <div className="field-grid">
                {(["period_start", "period_end"] as const).map(
                  (name, index) => (
                    <label className="field" htmlFor={name} key={name}>
                      <span>
                        {index === 0 ? "Начало периода" : "Конец периода"}
                      </span>
                      <input
                        id={name}
                        type="month"
                        value={values[name].slice(0, 7)}
                        onChange={(e) =>
                          change(name, monthDate(e.target.value, index === 1))
                        }
                        aria-invalid={!!fields[name]}
                        aria-describedby={`${name}-hint ${name}-error`}
                      />
                      <small id={`${name}-hint`}>
                        {index === 0
                          ? "С первого числа месяца"
                          : "По последний день месяца включительно"}
                      </small>
                      <small id={`${name}-error`} className="field-error">
                        {fields[name]}
                      </small>
                    </label>
                  ),
                )}
              </div>
              {field("revenue_kopecks", "Выручка за период, ₽", {
                maxLength: 24,
              })}
              {field(
                "operating_expenses_kopecks",
                "Операционные расходы за период, ₽",
                { maxLength: 24 },
              )}
              {field(
                "existing_debt_payments_kopecks",
                "Платежи по кредитам за период, ₽",
                {
                  hint: "Если кредитов нет, укажите 0. Пустое поле означает, что данные пока не заполнены.",
                  maxLength: 24,
                },
              )}
            </section>
          </div>
          <aside className="form-aside">
            <section className="panel terms-panel">
              <div className="terms-heading">
                <span className="product-glyph small" aria-hidden="true">
                  {product.code === "working_capital" ? "↻" : "▧"}
                </span>
                <span>Условия продукта</span>
              </div>
              <h2>{product.name}</h2>
              <dl className="terms">
                <div>
                  <dt>Сумма кредита</dt>
                  <dd>
                    {money(product.min_amount_kopecks)} —<br />
                    {money(product.max_amount_kopecks)}
                  </dd>
                </div>
                <div>
                  <dt>Срок</dt>
                  <dd>
                    {product.min_term_months}–{product.max_term_months} месяцев
                  </dd>
                </div>
                <div>
                  <dt>Демонстрационная ставка</dt>
                  <dd>
                    {(product.annual_rate_bps / 100).toLocaleString("ru-RU")}%
                    годовых
                  </dd>
                </div>
              </dl>
              <div className="terms-note">
                Условия прототипа. Не являются действующим предложением
                Альфа-Банка.
              </div>
            </section>
            <section className="company-summary">
              <h3>{company.name}</h3>
              <p>ИНН {company.inn}</p>
              <p>{company.industry}</p>
              <span>Компания определена по вашей учётной записи</span>
            </section>
          </aside>
        </div>
        <div className="save-area">
          {conflict ? (
            <div className="notice conflict" role="alert">
              <strong>Заявка изменилась в другой вкладке</strong>
              <p>
                Ваш ввод сохранён здесь. Загрузка новой версии заменит поля
                данными с сервера; при необходимости сначала скопируйте свои
                изменения.
              </p>
              {reloadError && <p className="field-error">{reloadError}</p>}
              <button
                className="button secondary"
                type="button"
                disabled={busy}
                onClick={reloadVersion}
              >
                Загрузить новую версию
              </button>
            </div>
          ) : (
            error && (
              <div className="notice error" role="alert">
                {error}
              </div>
            )
          )}
          <div className="save-actions">
            <button className="button primary" disabled={busy || conflict}>
              {busy ? "Сохраняем…" : "Сохранить черновик"}
            </button>
            <span>Сохранение не отправляет заявку в банк</span>
          </div>
        </div>
      </form>
    </>
  );
}
