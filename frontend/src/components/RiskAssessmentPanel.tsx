import type { RiskAssessment, RiskFactor } from "../api/types";
import { money } from "./shared";

function probabilityText(value: number) {
  const percent = value * 100;
  const rounded = Number(percent.toFixed(2));
  // Округление не должно переносить прогноз через порог политики.
  if (value < 0.1 && rounded >= 10) return "< 10%";
  if (value < 0.3 && rounded >= 30) return "< 30%";
  if (value > 0 && rounded === 0) return "< 0,01%";
  return `${percent.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}
function Factors({
  factors,
  increasing,
}: {
  factors: RiskFactor[];
  increasing: boolean;
}) {
  return (
    <div>
      <h4>{increasing ? "Повышают оценку" : "Снижают оценку"}</h4>
      {factors.length ? (
        <ul>
          {factors.slice(0, 3).map((factor) => (
            <li key={factor.feature_name}>{factor.label}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">
          {increasing ? "Нет повышающих факторов" : "Нет снижающих факторов"}
        </p>
      )}
    </div>
  );
}
export default function RiskAssessmentPanel({
  assessment: risk,
}: {
  assessment: RiskAssessment;
}) {
  const successful = risk.status === "succeeded" && risk.probability !== null;
  const unsupported = risk.status === "not_applicable" && risk.reason_code === "unsupported_product";
  const band = risk.risk_band;
  const labels = {
    low: "Низкий риск",
    elevated: "Повышенный риск",
    high: "Высокий риск",
  };
  return (
    <article
      className="risk-assessment"
      aria-label={
        risk.prediction_scope === "requested_terms"
          ? "Риск исходных условий"
          : "Риск новых условий"
      }
    >
      <h3>
        {risk.prediction_scope === "requested_terms"
          ? "Риск исходных условий"
          : "Риск новых условий"}
      </h3>
      <p className="risk-terms">
        {money(risk.terms.amount_kopecks)} · {risk.terms.term_months} мес. ·{" "}
        {risk.terms.annual_rate_bps === null ? "Без кредитной ставки" : `${(risk.terms.annual_rate_bps / 100).toLocaleString("ru-RU")}% годовых`}
      </p>
      <p className="muted">
        {risk.prediction_scope === "requested_terms"
          ? "Исходный запрос"
          : risk.offer_version === null
            ? "Расчёт до создания предложения"
            : `Версия предложения ${risk.offer_version}`}
      </p>
      {!unsupported && <p className="risk-target">Просрочка 90+ дней в первые 12 месяцев</p>}
      {successful ? (
        <>
          <div className="risk-result">
            <strong className="risk-probability">
              {probabilityText(risk.probability!)}
            </strong>
            {band && (
              <span className={`risk-band risk-${band}`}>{labels[band]}</span>
            )}
          </div>
          <p className="muted">
            Расчёт выполнен. Вероятность события по оценке модели
          </p>
          <div className="risk-factors">
            <Factors factors={risk.top_increasing_factors} increasing />
            <Factors factors={risk.top_decreasing_factors} increasing={false} />
          </div>
          <p className="muted">
            Линейные вклады описывают прогноз модели, а не доказанные причины
            события. Основания кредитного решения указаны отдельно
          </p>
          {risk.explanation_method === "linear_contributions" &&
            risk.explanation_scale === "raw_log_odds" && (
              <details className="risk-contributions">
                <summary>Численные вклады</summary>
                <p>
                  Шкала log odds — логарифм отношения вероятности события к
                  вероятности его отсутствия. Вклады складываются с базовым
                  значением до преобразования в вероятность; это не процентные
                  пункты
                </p>
                <dl className="financial-details">
                  <div>
                    <dt>Базовое значение</dt>
                    <dd>
                      {risk.base_value?.toLocaleString("ru-RU", {
                        maximumFractionDigits: 4,
                      })}
                    </dd>
                  </div>
                  {(risk.contributions.length
                    ? risk.contributions
                    : [
                        ...risk.top_increasing_factors,
                        ...risk.top_decreasing_factors,
                      ]
                  ).map((factor) => (
                    <div key={factor.feature_name}>
                      <dt>{factor.label}</dt>
                      <dd>
                        {factor.contribution.toLocaleString("ru-RU", {
                          maximumFractionDigits: 4,
                          signDisplay: "exceptZero",
                        })}
                      </dd>
                    </div>
                  ))}
                  <div>
                    <dt>Итог до преобразования</dt>
                    <dd>
                      {risk.raw_prediction?.toLocaleString("ru-RU", {
                        maximumFractionDigits: 4,
                      })}
                    </dd>
                  </div>
                </dl>
              </details>
            )}
        </>
      ) : (
        <div className={risk.status === "failed" ? "notice error" : "notice"}>
          <strong>
            {risk.status === "failed"
              ? "Техническая ошибка оценки"
              : "Оценка неприменима"}
          </strong>
          <p>
            {risk.status === "failed"
              ? "Вероятность не рассчитана. Кредитное решение по этой оценке не принято; повторите действие после устранения сбоя"
              : unsupported ? "Модель риска для этого продукта пока не применяется. Заявку рассматривает сотрудник" : "Для этих условий оценка не рассчитывается. Изучите проверки и основания результата"}
          </p>
        </div>
      )}
      {!unsupported && <p className="muted risk-model">
        Модель: {risk.scorer_version || "Не определена"}
      </p>}
      {!unsupported && <p className="muted">
        Синтетические данные. Качество на них не подтверждает точность для
        реальных заёмщиков
      </p>}
    </article>
  );
}
