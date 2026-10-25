import RiskAssessmentPanel from "./RiskAssessmentPanel";
import type { Assessment } from "../api/types";
import { date, dateTime, ErrorPanel, Loading, money } from "./shared";
import PaymentTermsView from "./PaymentTermsView";

const runLabels = {
  pending: "Ожидает запуска",
  running: "Выполняется",
  succeeded: "Завершена",
  failed: "Технический сбой",
  interrupted: "Прервана",
};
// Средние передаются десятичными строками; округление здесь только для отображения.
function average(value: string) {
  return `${(Number(value) / 100).toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₽`;
}
export default function AssessmentPanel({
  data,
  error,
  reload,
}: {
  data: Assessment | null;
  error: unknown;
  reload: () => void;
}) {
  return (
    <section
      className="panel assessment-panel"
      aria-labelledby="assessment-title"
    >
      <h2 id="assessment-title">Проверки и расчёт</h2>
      {error ? (
        <ErrorPanel error={error} retry={reload} />
      ) : !data ? (
        <Loading />
      ) : !data.runs.length ? (
        <p>Обработка ещё не запускалась</p>
      ) : (
        data.runs.map((run, index) => (
          <details
            key={run.id}
            open={index === data.runs.length - 1}
            className="assessment-run"
          >
            <summary>
              {runLabels[run.status]} · {dateTime(run.created_at)}
            </summary>
            <p className="muted">{run.revision_id === data.revision_id ? "Текущее рассмотрение" : "Предыдущее рассмотрение"}</p>
            {run.decision && (
              <div className="assessment-decision">
                <h3>Результат рассмотрения</h3>
                <p className="multiline">{run.decision.internal_reason}</p>
              </div>
            )}
            {(run.risk_assessments || []).map((risk) => (
              <RiskAssessmentPanel key={risk.assessment_id} assessment={risk} />
            ))}
            {!run.risk_assessments?.length && (
              <p className="muted">
                {!run.scorer_version
                  ? run.catalog_version === "demo-v1" ? "Историческая политика без ML" : "Оценка риска для этого запуска пока не сохранена"
                  : run.status === "pending" || run.status === "running"
                    ? "Ожидается расчёт риска"
                    : run.status === "failed" || run.status === "interrupted"
                      ? "Оценка риска недоступна: обработка не завершена"
                      : "Оценка риска не сохранена"}
              </p>
            )}
            {run.error_code && (
              <div className="notice error">
                Обработка не завершена из-за технического сбоя. Кредитное решение не принято. Код ошибки доступен в технических сведениях.
              </div>
            )}
            <ul className="check-list">
              {run.checks.map((check) => (
                <li key={check.id}>
                  <strong>
                    {
                      {
                        registry: "Проверка компании",
                        tax: "Налоговые сведения",
                        bki: "Кредитная история",
                      }[check.kind]
                    }
                  </strong>
                  {"registered_at" in check.data ? (
                    <p>
                      {check.data.liquidated ? "В реестре указана ликвидация" : "Ликвидация не указана"}. Дата регистрации: {date(check.data.registered_at)}.
                    </p>
                  ) : "overdue_days" in check.data ? (
                    <p>{check.data.overdue_days === 0 ? "Просрочек не обнаружено" : `Просрочка: ${check.data.overdue_days} дн.`}</p>
                  ) : (
                    <p>
                      Месячная выручка источника:{" "}
                      {check.data.expected_monthly_revenue_kopecks === null
                        ? "Нет сведений"
                        : money(check.data.expected_monthly_revenue_kopecks)}
                    </p>
                  )}
                </li>
              ))}
            </ul>
            <h3 className="assessment-finances-title">Финансовый расчёт</h3>
            {run.calculation ? (
              <dl className="financial-details">
                <div>
                  <dt>Период расчёта</dt>
                  <dd>{run.calculation.months} мес.</dd>
                </div>
                <div>
                  <dt>Средняя месячная выручка</dt>
                  <dd>{average(run.calculation.monthly_revenue_kopecks)}</dd>
                </div>
                <div>
                  <dt>Средние операционные расходы</dt>
                  <dd>
                    {average(
                      run.calculation.monthly_operating_expenses_kopecks,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Текущие месячные платежи</dt>
                  <dd>{average(run.calculation.monthly_debt_kopecks)}</dd>
                </div>
                <div>
                  <dt>Доступный денежный поток</dt>
                  <dd>{average(run.calculation.available_flow_kopecks)}</dd>
                </div>
                {!run.calculation.payment_terms && <div>
                  <dt>Новый месячный платёж</dt>
                  <dd>{money(run.calculation.monthly_payment_kopecks)}</dd>
                </div>}
                {run.calculation.payment_terms?.payment_kind !== "guarantee" && <div>
                  <dt>Коэффициент покрытия</dt>
                  <dd>
                    {(run.calculation.financial_gate?.coverage_ratio ?? run.calculation.coverage_ratio) === null
                      ? "Не определён"
                      : Number(run.calculation.financial_gate?.coverage_ratio ?? run.calculation.coverage_ratio).toLocaleString(
                          "ru-RU",
                          { maximumFractionDigits: 4 },
                        )}
                  </dd>
                </div>}
              </dl>
            ) : (
              <p className="muted">Финансовый расчёт для этого запуска отсутствует</p>
            )}
            {run.calculation?.payment_terms && <>
              <PaymentTermsView terms={run.calculation.payment_terms} />
              {run.calculation.financial_gate?.guarantee_fee_affordable !== null && run.calculation.financial_gate?.guarantee_fee_affordable !== undefined && <p>Проверка комиссии: {run.calculation.financial_gate.guarantee_fee_affordable ? "пройдена" : "не пройдена"}. Проверка масштаба условного обязательства: {run.calculation.financial_gate.guarantee_liability_within_limit ? "пройдена" : "не пройдена"}.</p>}
            </>}
            <details className="assessment-technical">
              <summary>Технические сведения</summary>
              <dl className="financial-details">
                <div><dt>Версия правил</dt><dd>{run.policy_version}</dd></div>
                <div><dt>Версия источников</dt><dd>{run.source_version}</dd></div>
                <div><dt>Версия каталога</dt><dd>{run.catalog_version}</dd></div>
                <div><dt>Отправка</dt><dd>{run.revision_id}</dd></div>
                {run.error_code && <div><dt>Код ошибки</dt><dd>{run.error_code}</dd></div>}
              </dl>
            </details>
          </details>
        ))
      )}
    </section>
  );
}
