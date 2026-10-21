import RiskAssessmentPanel from "./RiskAssessmentPanel";
import type { Assessment } from "../api/types";
import { date, dateTime, ErrorPanel, Loading, money } from "./shared";

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
      <p className="muted">
        Синтетические источники и демонстрационные правила
      </p>
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
            <p className="muted">
              {run.revision_id === data.revision_id
                ? "Текущая отправка"
                : "Предыдущая отправка"}{" "}
              {run.revision_id.slice(0, 8)} · Правила {run.policy_version} ·
              Источник {run.source_version}
            </p>
            {(run.risk_assessments || []).map((risk) => (
              <RiskAssessmentPanel key={risk.assessment_id} assessment={risk} />
            ))}
            {!run.risk_assessments?.length && (
              <p className="muted">
                {!run.scorer_version
                  ? "Историческая политика без ML"
                  : run.status === "pending" || run.status === "running"
                    ? "Ожидается расчёт риска"
                    : run.status === "failed" || run.status === "interrupted"
                      ? "Оценка риска недоступна: обработка не завершена"
                      : "Оценка риска не сохранена"}
              </p>
            )}
            {run.error_code && (
              <div className="notice error">
                Обработка не завершена: {run.error_code}. Это технический сбой,
                кредитное решение не принято.
              </div>
            )}
            <ul className="check-list">
              {run.checks.map((check) => (
                <li key={check.id}>
                  <strong>
                    {
                      {
                        registry: "Реестр компаний",
                        tax: "Налоговые сведения",
                        bki: "БКИ",
                      }[check.kind]
                    }
                  </strong>
                  <span>Проверка выполнена</span>
                  {"registered_at" in check.data ? (
                    <p>
                      Дата регистрации: {date(check.data.registered_at)}.
                      Ликвидация: {check.data.liquidated ? "да" : "нет"}
                    </p>
                  ) : "overdue_days" in check.data ? (
                    <p>Просрочка: {check.data.overdue_days} дн.</p>
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
                <div>
                  <dt>Новый месячный платёж</dt>
                  <dd>{money(run.calculation.monthly_payment_kopecks)}</dd>
                </div>
                <div>
                  <dt>Коэффициент покрытия</dt>
                  <dd>
                    {run.calculation.coverage_ratio === null
                      ? "Не определён"
                      : Number(run.calculation.coverage_ratio).toLocaleString(
                          "ru-RU",
                          { maximumFractionDigits: 4 },
                        )}
                  </dd>
                </div>
              </dl>
            ) : (
              <p className="muted">Финансовый расчёт для этого запуска отсутствует</p>
            )}
            {run.decision && (
              <div className="assessment-decision">
                <strong>Основание результата</strong>
                <p className="multiline">{run.decision.internal_reason}</p>
              </div>
            )}
          </details>
        ))
      )}
    </section>
  );
}
