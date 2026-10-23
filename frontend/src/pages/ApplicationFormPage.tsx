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
  ProductCode,
} from "../api/types";
import { useSession } from "../auth/session";
import { RecommendationPanel } from "../components/RecommendationPanel";
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
    tender_number: application?.tender_number || "",
    beneficiary_name: application?.beneficiary_name || "",
    project_description: application?.project_description || "",
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
    setValues((current) => name === "product_code" ? {
      ...current,
      product_code: value as ProductCode,
      tender_number: value === "tender_guarantee" ? current.tender_number : "",
      beneficiary_name: value === "tender_guarantee" ? current.beneficiary_name : "",
      project_description: value === "investment" ? current.project_description : "",
    } : ({ ...current, [name]: value }));
    setFields((current) => ({ ...current, [name]: "" }));
  }
  function applyRecommendation(code: ProductCode, amount: number, term: number) {
    const target = catalog.items.find((item) => item.code === code);
    if (!target) return;
    if (amount < target.min_amount_kopecks || amount > target.max_amount_kopecks ||
        term < target.min_term_months || term > target.max_term_months) {
      setError("Условия изменились. Повторите подбор");
      return;
    }
    setValues((current) => ({
      ...current,
      product_code: code,
      amount_kopecks: amountInput(amount),
      term_months: String(term),
      tender_number: code === "tender_guarantee" ? current.tender_number : "",
      beneficiary_name: code === "tender_guarantee" ? current.beneficiary_name : "",
      project_description: code === "investment" ? current.project_description : "",
    }));
    setFields((current) => ({
      ...current,
      product_code: "",
      amount_kopecks: "",
      term_months: "",
    }));
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
      tender_number: values.product_code === "tender_guarantee" ? values.tender_number.trim() || null : null,
      beneficiary_name: values.product_code === "tender_guarantee" ? values.beneficiary_name.trim() || null : null,
      project_description: values.product_code === "investment" ? values.project_description.trim() || null : null,
    };
    setBusy(true);
    try {
      const saved = record
        ? await api<Application>(`/applications/${record.id}`, {
            method: "PATCH",
            body: {
              ...body,
              ...(record.status === "needs_info"
                ? { product_code: undefined }
                : {}),
              expected_version: record.version,
            },
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
  if (record && !record.available_actions.includes("edit_draft")) {
    return (
      <section className="panel state-panel">
        <h1>Редактирование недоступно</h1>
        <p>Заявка уже отправлена. Её сохранённые данные доступны в карточке.</p>
        <Link to={`/applications/${record.id}`} className="button secondary">
          Открыть заявку
        </Link>
      </section>
    );
  }
  return (
    <>
      <PageHeading
        title="Заявка на кредитование"
        subtitle={
          record?.status === "needs_info"
            ? "Дополните сведения по запросу. После сохранения отправьте ответ из карточки заявки."
            : "Заполните то, что знаете сейчас. Остальное можно добавить позже."
        }
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
                      disabled={record?.status === "needs_info"}
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
                {field("amount_kopecks", product.payment_kind === "guarantee" ? "Сумма гарантии, ₽" : product.payment_kind === "revolving" ? "Лимит, ₽" : "Сумма кредита, ₽", {
                  hint: `От ${money(product.min_amount_kopecks)} до ${money(product.max_amount_kopecks)}`,
                  maxLength: 24,
                })}
                {field("term_months", product.payment_kind === "annuity" ? "Срок кредита, месяцев" : "Срок, месяцев", {
                  hint: `От ${product.min_term_months} до ${product.max_term_months} месяцев`,
                  maxLength: 3,
                })}
              </div>
              {field("purpose", "Цель финансирования", {
                hint: "Например, закупка сырья или покупка оборудования",
                maxLength: 2000,
              })}
              {values.product_code === "investment" && (
                <label className="field" htmlFor="project_description">
                  <span>Описание проекта</span>
                  <textarea id="project_description" rows={3} maxLength={2000} value={values.project_description} onChange={(event) => change("project_description", event.target.value)} aria-invalid={!!fields.project_description} aria-describedby="project_description-error" />
                  <small id="project_description-error" className="field-error">{fields.project_description}</small>
                </label>
              )}
              {values.product_code === "tender_guarantee" && (
                <div className="field-grid">
                  {field("tender_number", "Номер тендера", { maxLength: 40 })}
                  {field("beneficiary_name", "Заказчик по тендеру", { maxLength: 200 })}
                </div>
              )}
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
                  {product.payment_kind === "guarantee" ? "◇" : product.payment_kind === "revolving" ? "↻" : "▧"}
                </span>
                <span>Условия продукта</span>
              </div>
              <h2>{product.name}</h2>
              <dl className="terms">
                <div>
                  <dt>{product.payment_kind === "guarantee" ? "Сумма гарантии" : product.payment_kind === "revolving" ? "Лимит" : "Сумма кредита"}</dt>
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
                  <dt>{product.payment_kind === "guarantee" ? "Комиссия за год" : "Демонстрационная ставка"}</dt>
                  <dd>
                    {((product.payment_kind === "guarantee" ? product.annual_commission_bps : product.annual_rate_bps || 0) / 100).toLocaleString("ru-RU")}%
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
        {(!record || record.status === "draft") && (
          <RecommendationPanel form={values} onApply={applyRecommendation} />
        )}
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
            <span id="save-hint">Сохранение не отправляет заявку в банк</span>
            <button
              className="button primary"
              disabled={busy || conflict}
              aria-describedby="save-hint"
            >
              {busy
                ? "Сохраняем…"
                : record?.status === "needs_info"
                  ? "Сохранить дополнения"
                  : "Сохранить черновик"}
            </button>
          </div>
        </div>
      </form>
    </>
  );
}
