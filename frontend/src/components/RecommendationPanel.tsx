import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api, errorMessage } from "../api/client";
import type { ProductCode, RecommendationItem, RecommendationOptions, RecommendationPurpose, RecommendationRequest, RecommendationResponse } from "../api/types";
import PaymentTermsView from "./PaymentTermsView";
import { documentLabels } from "./ApplicationDocuments";
import { useResource } from "./shared";

export interface RecommendationFormSnapshot {
  amount_kopecks: string;
  term_months: string;
  period_start: string;
  period_end: string;
  revenue_kopecks: string;
  operating_expenses_kopecks: string;
  existing_debt_payments_kopecks: string;
}
const missingLabels: Record<string, string> = {
  revenue_total_kopecks: "выручку", expenses_total_kopecks: "операционные расходы",
  existing_debt_payments_kopecks: "платежи по кредитам (укажите 0, если их нет)",
  period_months: "финансовый период", amount_kopecks: "сумму",
};
const targetFields: Record<string, string> = {
  revenue_total_kopecks: "revenue_kopecks", expenses_total_kopecks: "operating_expenses_kopecks",
  existing_debt_payments_kopecks: "existing_debt_payments_kopecks", period_months: "period_start", amount_kopecks: "amount_kopecks",
};
function parseMoney(value: string): number | null {
  if (!value.trim()) return null;
  const normalized = value.replace(/[\s\u00a0\u202f]/g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) return null;
  const [whole, fraction = ""] = normalized.split(".");
  const result = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  return result > BigInt(Number.MAX_SAFE_INTEGER) ? null : Number(result);
}
function PurposePicker({
  options,
  value,
  onChange,
}: {
  options: RecommendationOptions["purposes"];
  value: RecommendationPurpose;
  onChange: (value: RecommendationPurpose) => void;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const selected = options.findIndex((option) => option.code === value);
  const label = options[selected]?.label || "Выберите цель";
  useEffect(() => {
    if (!open) return;
    function closeOutside(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);
  useEffect(() => {
    if (!open || !list.current) return;
    const option = list.current.children[active] as HTMLElement | undefined;
    if (!option) return;
    if (option.offsetTop < list.current.scrollTop) list.current.scrollTop = option.offsetTop;
    else if (option.offsetTop + option.offsetHeight > list.current.scrollTop + list.current.clientHeight) {
      list.current.scrollTop = option.offsetTop + option.offsetHeight - list.current.clientHeight;
    }
  }, [active, open]);
  function choose(index: number) {
    if (!options[index]) return;
    onChange(options[index].code);
    setOpen(false);
  }
  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Tab") {
      setOpen(false);
      return;
    }
    if (event.key === "Escape") {
      if (open) event.preventDefault();
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      const start = open ? active : selected >= 0 ? selected : direction === 1 ? -1 : 0;
      setActive((start + direction + options.length) % options.length);
      setOpen(true);
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      setActive(event.key === "Home" ? 0 : options.length - 1);
      setOpen(true);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (open) choose(active);
      else {
        setActive(Math.max(0, selected));
        setOpen(true);
      }
    }
  }
  return <div className="purpose-picker field" ref={root} onBlur={(event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }}>
    <span id="recommendation-purpose-label">Что планируете финансировать</span>
    <button
      type="button"
      className="purpose-trigger"
      role="combobox"
      aria-labelledby="recommendation-purpose-label"
      aria-haspopup="listbox"
      aria-expanded={open}
      aria-controls={open ? "recommendation-purpose-options" : undefined}
      aria-activedescendant={open ? `recommendation-purpose-option-${active}` : undefined}
      disabled={!options.length}
      onClick={() => {
        setActive(Math.max(0, selected));
        setOpen((current) => !current);
      }}
      onKeyDown={handleKeyDown}
    >
      <span>{label}</span><span className="purpose-chevron" aria-hidden="true" />
    </button>
    {open && <ul id="recommendation-purpose-options" ref={list} role="listbox" aria-labelledby="recommendation-purpose-label" className="purpose-options">
      {options.map((option, index) => <li
        id={`recommendation-purpose-option-${index}`}
        key={option.code}
        role="option"
        aria-selected={option.code === value}
        className={active === index ? "active" : ""}
        onMouseDown={(event) => event.preventDefault()}
        onMouseEnter={() => setActive(index)}
        onClick={() => choose(index)}
      >{option.label}</li>)}
    </ul>}
  </div>;
}
function Item({ item, apply }: { item: RecommendationItem; apply: () => void }) {
  const fieldLabels = { tender_number: "номер тендера", beneficiary_name: "название заказчика", project_description: "описание проекта" };
  return <article className="recommendation-card">
    <div className="recommendation-card-head"><h3>{item.product_name}</h3><span className="recommendation-tag">{item.purpose_match ? "Подходит под цель" : "Возможная альтернатива"}</span></div>
    <PaymentTermsView terms={item.payment_terms} collapseAssumptions />
    {item.client_reasons.length > 0 && <ul className="recommendation-reasons">{item.client_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
    {item.required_application_fields.length > 0 && <p className="recommendation-hint">Для заявки понадобятся: {item.required_application_fields.map((field) => fieldLabels[field]).join(", ")}.</p>}
    {item.required_document_types.length > 0 && <p className="recommendation-hint">Документы для отправки: {item.required_document_types.map((type) => documentLabels[type]).join(", ")}.</p>}
    <button type="button" className="button secondary recommendation-apply" aria-label={`Подставить ${item.product_name} в заявку`} onClick={apply}>Подставить в заявку</button>
  </article>;
}
export function RecommendationPanel({ form, onApply }: { form: RecommendationFormSnapshot; onApply?: (code: ProductCode, amount: number, term: number) => void }) {
  const options = useResource(() => api<RecommendationOptions>("/product-recommendations/options"), "recommendation-options");
  const [purpose, setPurpose] = useState<RecommendationPurpose>("working_capital");
  const [result, setResult] = useState<{ value: RecommendationResponse; key: string; generation: number } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const wasApplied = useRef(false);
  const key = JSON.stringify({ form, purpose });
  const latestKey = useRef(key);
  const effectKey = useRef(key);
  if (latestKey.current !== key) {
    latestKey.current = key;
    generation.current++;
    controller.current?.abort();
  }
  useEffect(() => {
    if (effectKey.current === key) return;
    effectKey.current = key;
    setResult(null);
    setBusy(false);
    setNotice(wasApplied.current ? "Условия подставлены. Проверьте данные и сохраните черновик" : "Данные изменились. Подберите продукт заново");
    wasApplied.current = false;
  }, [key]);
  useEffect(() => () => { generation.current++; controller.current?.abort(); }, []);
  async function submit() {
    const requestGeneration = ++generation.current;
    controller.current?.abort();
    const currentController = new AbortController();
    controller.current = currentController;
    setResult(null); setError(""); setNotice("");
    const amount = parseMoney(form.amount_kopecks);
    const term = Number(form.term_months);
    if (amount === null || amount <= 0 || !/^\d+$/.test(form.term_months) || !Number.isSafeInteger(term) || term < 1 || term > 120) {
      setError("Сначала укажите сумму и срок финансирования."); return;
    }
    const body: RecommendationRequest = {
      purpose, amount_kopecks: amount, term_months: term,
      revenue_total_kopecks: parseMoney(form.revenue_kopecks), expenses_total_kopecks: parseMoney(form.operating_expenses_kopecks),
      existing_debt_payments_kopecks: parseMoney(form.existing_debt_payments_kopecks),
      period_start: form.period_start || null, period_end: form.period_end || null,
    };
    if (Boolean(body.period_start) !== Boolean(body.period_end)) { setError("Для расчёта нужны обе даты финансового периода."); return; }
    setBusy(true);
    try {
      const value = await api<RecommendationResponse>("/product-recommendations", { method: "POST", body, signal: currentController.signal });
      if (requestGeneration === generation.current && key === latestKey.current) setResult({ value, key, generation: requestGeneration });
    } catch (value) {
      if (requestGeneration === generation.current && key === latestKey.current) setError(errorMessage(value));
    } finally { if (requestGeneration === generation.current) setBusy(false); }
  }
  function apply(item: RecommendationItem, resultGeneration: number) {
    if (!result || result.generation !== resultGeneration || resultGeneration !== generation.current || result.key !== latestKey.current) {
      setError("Условия изменились. Повторите подбор"); return;
    }
    onApply?.(item.product_code, item.recommended_amount_kopecks, item.term_months);
    wasApplied.current = true;
    setNotice("Условия подставлены. Проверьте данные и сохраните черновик");
  }
  const visible = result?.key === key && result.generation === generation.current ? result : null;
  return <section className="panel recommendation-panel" aria-labelledby="recommendation-title">
    <div className="recommendation-heading"><div><h2 id="recommendation-title">Подбор кредитного продукта</h2><p>Укажите цель и параметры. Подбор использует финансовые данные этой формы и не является кредитным решением.</p></div></div>
    <div className="recommendation-input-row">
      <PurposePicker options={options.data?.purposes || []} value={purpose} onChange={setPurpose} />
      {!options.error && <div className="recommendation-actions"><button type="button" className="button primary" disabled={busy || !options.data} onClick={submit}>{busy ? "Подбираем…" : "Подобрать продукт"}</button></div>}
    </div>
    {options.error ? <div className="notice error" role="alert">Не удалось загрузить варианты подбора. {errorMessage(options.error)} <button type="button" className="text-link" onClick={options.reload}>Повторить</button></div> : null}
    {error && <div className="notice error" role="alert">{error}</div>}
    <div aria-live="polite">{notice && <p className="recommendation-hint">{notice}</p>}{visible && <div className="recommendation-results"><div className={`notice ${visible.value.status === "no_match" ? "error" : visible.value.status === "request_data" ? "" : "success"}`}>{visible.value.message}</div>{visible.value.missing_fields.length > 0 && <div className="recommendation-missing">Не хватает: {visible.value.missing_fields.map((field) => missingLabels[field || ""] || field).join(", ")}. <button type="button" className="text-link" onClick={() => document.getElementById(targetFields[visible.value.missing_fields[0] || ""])?.focus()}>Перейти к полю</button></div>}{visible.value.actions.filter((action) => action.kind === "change_amount").map((action) => <p className="recommendation-hint" key={action.kind}><button type="button" className="text-link" onClick={() => document.getElementById("amount_kopecks")?.focus()}>{action.label}</button></p>)}{visible.value.items.length > 0 && <div className="recommendation-list">{visible.value.items.map((item) => <Item key={item.recommendation_id} item={item} apply={() => apply(item, visible.generation)} />)}</div>}</div>}</div>
  </section>;
}
