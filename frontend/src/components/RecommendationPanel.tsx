import { useState } from "react";
import { api, errorMessage } from "../api/client";
import type {
  ProductCode,
  RecommendationCollateral,
  RecommendationItem,
  RecommendationOptions,
  RecommendationPurpose,
  RecommendationRequest,
  RecommendationResponse,
} from "../api/types";
import { money, useResource } from "./shared";

export interface RecommendationFormSnapshot {
  amount_kopecks: string;
  term_months: string;
  period_start: string;
  period_end: string;
  revenue_kopecks: string;
  operating_expenses_kopecks: string;
  existing_debt_payments_kopecks: string;
}

function parseMoney(value: string): number | null {
  if (!value.trim()) return null;
  const normalized = value.replace(/[\s\u00a0\u202f]/g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) return null;
  const [whole, fraction = ""] = normalized.split(".");
  const result = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  return result > BigInt(Number.MAX_SAFE_INTEGER) ? null : Number(result);
}

function percentage(value: number | null) {
  return value === null ? "—" : `${value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })}%`;
}

function Item({
  item,
  onApply,
}: {
  item: RecommendationItem;
  onApply?: (code: ProductCode, amount: number, term: number) => void;
}) {
  return (
    <article className="recommendation-card">
      <div className="recommendation-card-head">
        <div>
          <h3>{item.product_name}</h3>
          {item.purpose_match ? (
            <span className="recommendation-tag">Подходит под цель</span>
          ) : (
            <span className="recommendation-tag neutral">Смежная цель</span>
          )}
        </div>
        <span className="recommendation-score">{item.score}/100</span>
      </div>
      <dl className="recommendation-terms">
        <div>
          <dt>Сумма</dt>
          <dd>{money(item.approved_amount_kopecks)}</dd>
        </div>
        <div>
          <dt>Срок</dt>
          <dd>{item.term_months} мес.</dd>
        </div>
        <div>
          <dt>Ставка / стоимость</dt>
          <dd>
            {item.commission_year_pct !== null
              ? `комиссия ${percentage(item.commission_year_pct)} в год`
              : percentage(item.base_rate_pct)}
          </dd>
        </div>
        <div>
          <dt>Платёж</dt>
          <dd>{money(item.monthly_payment_kopecks)}</dd>
        </div>
        <div>
          <dt>Одобрение</dt>
          <dd>{item.approval_likelihood}%</dd>
        </div>
        <div>
          <dt>Решение</dt>
          <dd>{item.approval_time_hours === 0 ? "сразу" : `${item.approval_time_hours} ч`}</dd>
        </div>
      </dl>
      {item.client_reasons.length > 0 && (
        <ul className="recommendation-reasons">
          {item.client_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {item.missing_data.length > 0 && (
        <p className="recommendation-missing">
          Не хватает: {item.missing_data.join(", ")}.
        </p>
      )}
      {item.next_action && <p className="recommendation-hint">{item.next_action}</p>}
      {item.is_available_in_cabinet && item.cabinet_product_code && onApply && (
        <button
          type="button"
          className="button secondary recommendation-apply"
          onClick={() =>
            onApply(item.cabinet_product_code!, item.approved_amount_kopecks, item.term_months)
          }
        >
          Подставить в заявку
        </button>
      )}
    </article>
  );
}

export function RecommendationPanel({
  form,
  onApply,
}: {
  form: RecommendationFormSnapshot;
  onApply?: (code: ProductCode, amount: number, term: number) => void;
}) {
  const options = useResource(
    () => api<RecommendationOptions>("/product-recommendations/options"),
    "recommendation-options",
  );
  const [purpose, setPurpose] = useState<RecommendationPurpose>("working_capital");
  const [urgency, setUrgency] = useState<"high" | "normal">("normal");
  const [hasCollateral, setHasCollateral] = useState(false);
  const [collateralType, setCollateralType] =
    useState<RecommendationCollateral>("equipment");
  const [invoice, setInvoice] = useState(false);
  const [businessPlan, setBusinessPlan] = useState(false);
  const [downPayment, setDownPayment] = useState("");
  const [tenderNumber, setTenderNumber] = useState("");
  const [result, setResult] = useState<RecommendationResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setError("");
    setResult(null);
    const amount = parseMoney(form.amount_kopecks);
    const term = Number(form.term_months);
    if (amount === null || !Number.isSafeInteger(term) || term < 1) {
      setError("Сначала укажите сумму и срок кредита.");
      return;
    }
    const body: RecommendationRequest = {
      purpose,
      amount_kopecks: amount,
      term_months: term,
      urgency,
      has_collateral: hasCollateral,
      collateral_type: hasCollateral ? collateralType : "none",
      supplier_invoice_attached: invoice,
      down_payment_pct: downPayment.trim() ? Number(downPayment) : null,
      business_plan_attached: businessPlan,
      tender_number: tenderNumber.trim() || null,
      revenue_total_kopecks: parseMoney(form.revenue_kopecks),
      expenses_total_kopecks: parseMoney(form.operating_expenses_kopecks),
      existing_debt_payments_kopecks: parseMoney(form.existing_debt_payments_kopecks),
      period_start: form.period_start || null,
      period_end: form.period_end || null,
    };
    if ((body.period_start && !body.period_end) || (!body.period_start && body.period_end)) {
      setError("Для расчёта нужны обе даты финансового периода.");
      return;
    }
    setBusy(true);
    try {
      setResult(await api<RecommendationResponse>("/product-recommendations", {
        method: "POST",
        body,
      }));
    } catch (value) {
      setError(errorMessage(value));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel recommendation-panel" aria-labelledby="recommendation-title">
      <div className="recommendation-heading">
        <div>
          <h2 id="recommendation-title">Подбор кредитного продукта</h2>
          <p>
            Укажите цель и параметры — банк покажет подходящие продукты, сумму и срок.
            Итоговые условия и вероятность одобрения уточняются после рассмотрения заявки.
          </p>
        </div>
      </div>
      <div className="recommendation-controls">
        <label className="field">
          <span>Цель финансирования</span>
          <select value={purpose} onChange={(event) => setPurpose(event.target.value as RecommendationPurpose)}>
            {(options.data?.purposes || []).map((item) => (
              <option key={item.code} value={item.code}>{item.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Срочность</span>
          <select value={urgency} onChange={(event) => setUrgency(event.target.value as "high" | "normal")}>
            {(options.data?.urgency_levels || []).map((item) => (
              <option key={item.code} value={item.code}>{item.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Первоначальный взнос, %</span>
          <input
            inputMode="numeric"
            value={downPayment}
            maxLength={3}
            onChange={(event) => setDownPayment(event.target.value)}
          />
        </label>
        <label className="field">
          <span>Номер тендера</span>
          <input
            value={tenderNumber}
            maxLength={40}
            onChange={(event) => setTenderNumber(event.target.value)}
          />
        </label>
      </div>
      <div className="recommendation-checks">
        <label>
          <input
            type="checkbox"
            checked={hasCollateral}
            onChange={(event) => setHasCollateral(event.target.checked)}
          />
          <span>Есть залог</span>
        </label>
        {hasCollateral && (
          <label className="field inline-field">
            <span>Тип залога</span>
            <select
              value={collateralType}
              onChange={(event) => setCollateralType(event.target.value as RecommendationCollateral)}
            >
              {(options.data?.collateral_types || []).map((item) => (
                <option key={item.code} value={item.code}>{item.label}</option>
              ))}
            </select>
          </label>
        )}
        <label>
          <input type="checkbox" checked={invoice} onChange={(event) => setInvoice(event.target.checked)} />
          <span>Есть счёт поставщика</span>
        </label>
        <label>
          <input
            type="checkbox"
            checked={businessPlan}
            onChange={(event) => setBusinessPlan(event.target.checked)}
          />
          <span>Есть бизнес-план</span>
        </label>
      </div>
      {options.error ? (
        <div className="notice error" role="alert">
          Не удалось загрузить варианты подбора. {errorMessage(options.error)}
          <button type="button" className="text-link" onClick={options.reload}>Повторить</button>
        </div>
      ) : (
        <div className="recommendation-actions">
          <button type="button" className="button primary" disabled={busy || !options.data} onClick={submit}>
            {busy ? "Подбираем..." : "Подобрать продукт"}
          </button>
          {options.data && <span className="muted">Правила {options.data.config_version}</span>}
        </div>
      )}
      {error && <div className="notice error" role="alert">{error}</div>}
      {result && (
        <div className="recommendation-results" aria-live="polite">
          <div className={`notice ${result.status === "no_match" ? "error" : result.status === "request_data" ? "" : "success"}`}>
            {result.message}
          </div>
          {result.items.length > 0 && (
            <div className="recommendation-list">
              {result.items.map((item) => (
                <Item key={item.offer_id} item={item} onApply={onApply} />
              ))}
            </div>
          )}
          {result.items.length === 0 && result.actions.length > 0 && (
            <p className="recommendation-hint">
              Что можно сделать: {result.actions.map((action) => action.label).join("; ")}.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
