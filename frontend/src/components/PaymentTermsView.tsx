import type { PaymentTerms } from "../api/types";
import { money } from "./shared";

export function amountLabel(kind: PaymentTerms["payment_kind"]) {
  return kind === "guarantee" ? "Сумма гарантии" : kind === "revolving" ? "Лимит" : "Сумма кредита";
}

export default function PaymentTermsView({ terms }: { terms: PaymentTerms }) {
  const guarantee = terms.payment_kind === "guarantee";
  const revolving = terms.payment_kind === "revolving";
  return (
    <div className="payment-terms">
      <dl className="financial-details">
        <div><dt>{amountLabel(terms.payment_kind)}</dt><dd>{money(terms.amount_kopecks)}</dd></div>
        <div><dt>Срок</dt><dd>{terms.term_months} мес.</dd></div>
        {terms.annual_rate_bps !== null && <div><dt>Ставка</dt><dd>{(terms.annual_rate_bps / 100).toLocaleString("ru-RU")}% годовых</dd></div>}
        {guarantee && <div><dt>Комиссия, % годовых</dt><dd>{(terms.annual_commission_bps / 100).toLocaleString("ru-RU")}%</dd></div>}
        {!guarantee && <div><dt>{revolving ? "Проценты в месяц" : "Ежемесячный платёж"}</dt><dd>{money(terms.monthly_payment_kopecks)}</dd></div>}
        {revolving && <>
          <div><dt>Возврат лимита в конце срока</dt><dd>{money(terms.principal_due_at_end_kopecks)}</dd></div>
          <div><dt>Последний платёж</dt><dd>{money(terms.last_payment_kopecks)}</dd></div>
          <div><dt>Расчётная нагрузка для оценки</dt><dd>{money(terms.assessment_monthly_burden_kopecks)}</dd></div>
        </>}
        <div><dt>{guarantee ? "Разовая комиссия за весь срок" : "Разовая комиссия"}</dt><dd>{money(terms.upfront_fee_kopecks)}</dd></div>
        {!guarantee && <div><dt>Всего к выплате</dt><dd>{money(terms.total_payment_kopecks)}</dd></div>}
        <div><dt>{guarantee ? "Расходы на гарантию" : "Стоимость финансирования"}</dt><dd>{money(terms.total_cost_kopecks)}</dd></div>
        {guarantee && <div><dt>Условное обязательство возмещения</dt><dd>{money(terms.contingent_liability_kopecks)}</dd></div>}
      </dl>
      {revolving && <p className="muted">Расчётная нагрузка включает резерв возврата лимита для оценки заявки. Это не ежемесячный платёж.</p>}
      {guarantee && <p className="muted">При выплате по гарантии может возникнуть обязанность возместить её сумму.</p>}
      {terms.assumptions.length > 0 && <ul className="payment-assumptions">{terms.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>}
    </div>
  );
}
