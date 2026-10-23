import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type {
  Application,
  Assessment,
  CreateOfferBody,
  DecisionBody,
  DocumentType,
  DraftFields,
  InformationRequestBody,
  InformationResponseBody,
  OfferActionBody,
  SubmissionPolicy,
} from "../api/types";
import RiskAssessmentPanel from "./RiskAssessmentPanel";
import PaymentTermsView, { amountLabel } from "./PaymentTermsView";
import { documentLabels } from "./ApplicationDocuments";
import { dateTime, money, statusLabels } from "./shared";
import { readStored, useReviewCommand, writeStored } from "./useReviewCommand";

type RequestedField = Exclude<keyof DraftFields, "product_code">;
export const fieldLabels: Record<RequestedField, string> = {
  purpose: "Цель финансирования",
  description: "Дополнительное описание",
  amount_kopecks: "Сумма кредита",
  term_months: "Срок кредита",
  period_start: "Начало периода",
  period_end: "Конец периода",
  revenue_kopecks: "Выручка",
  operating_expenses_kopecks: "Операционные расходы",
  existing_debt_payments_kopecks: "Платежи по кредитам",
  tender_number: "Номер тендера",
  beneficiary_name: "Заказчик по тендеру",
  project_description: "Описание проекта",
};
const nextStep = {
  draft: "Заполните данные, приложите документы и отправьте заявку",
  submitted:
    "Заявка принята и ожидает обработки. Статус обновляется автоматически",
  processing: "Проверяем данные. Дождитесь результата обработки",
  needs_info: "Дополните сведения по запросу и отдельно отправьте ответ",
  manual_review:
    "Сотрудник рассматривает заявку. Результат появится в кабинете",
  counteroffer: "Сравните условия и примите или отклоните предложение",
  approved:
    "Рассмотрение завершено. Одобрение не означает выдачу денег",
  rejected: "Рассмотрение завершено. Причина решения указана ниже",
};
type Draft = {
  reason: string;
  message: string;
  fields: RequestedField[];
  documents: DocumentType[];
  amount: string;
  term: string;
  confirmed: boolean;
  consent: boolean;
};
const emptyDraft: Draft = {
  reason: "",
  message: "",
  fields: [],
  documents: [],
  amount: "",
  term: "",
  confirmed: false,
  consent: false,
};
function parseAmount(value: string) {
  const normalized = value
    .trim()
    .replace(/[\s\u00a0\u202f]/g, "")
    .replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) return null;
  const [whole, decimal = ""] = normalized.split(".");
  const amount = BigInt(whole) * 100n + BigInt(decimal.padEnd(2, "0"));
  return amount <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(amount) : null;
}
export default function ReviewActions({
  application: item,
  owner,
  staff,
  policy,
  changed,
  assessment,
  refreshAssessment,
  lock,
}: {
  application: Application;
  owner: string;
  staff: boolean;
  policy: SubmissionPolicy | null;
  changed: () => Promise<void>;
  assessment: Assessment | null;
  refreshAssessment: () => void;
  lock: (locked: boolean) => void;
}) {
  const draftKey = `credit-review-form:v1:${owner}:${item.id}`;
  const [draft, setDraft] = useState<Draft>(() =>
    readStored(draftKey, emptyDraft),
  );
  const [validation, setValidation] = useState("");
  const command = useReviewCommand(owner, item.id, changed, refreshAssessment);
  const [requestedAck, setRequestedAck] = useState(false);
  const [offeredAck, setOfferedAck] = useState(false);
  const requestedRisk = assessment?.risk_assessment;
  const latestRun = assessment?.runs
    .filter((run) => run.revision_id === assessment.revision_id)
    .at(-1);
  const offeredRisk = latestRun?.risk_assessments
    ?.filter(
      (risk) =>
        risk.revision_id === assessment?.revision_id &&
        risk.processing_run_id === latestRun.id &&
        risk.prediction_scope === "offered_terms" &&
        risk.terms.product_code === item.product_code &&
        risk.terms.amount_kopecks === parseAmount(draft.amount) &&
        risk.terms.term_months === Number(draft.term),
    )
    .at(-1);
  const requestedNeedsAck =
    requestedRisk?.status === "succeeded" &&
    requestedRisk.probability !== null &&
    requestedRisk.probability >= 0.1;
  const offeredNeedsAck =
    offeredRisk?.status === "succeeded" &&
    offeredRisk.probability !== null &&
    offeredRisk.probability >= 0.1;
  useEffect(() => {
    setRequestedAck(false);
    setOfferedAck(false);
  }, [
    item.id,
    item.version,
    assessment?.revision_id,
    requestedRisk?.assessment_id,
  ]);
  useEffect(() => {
    setOfferedAck(false);
  }, [draft.amount, draft.term, offeredRisk?.assessment_id]);
  const disabled = command.busy || !!command.pending || command.conflict;
  const can = (action: Application["available_actions"][number]) =>
    item.available_actions.includes(action);
  const request = item.information_requests.find(
    (request) => request.status === "open",
  );
  const offer =
    item.offers.find((offer) => offer.status === "active") ||
    item.offers.find((offer) => offer.status === "accepted");
  const productFields: RequestedField[] = item.product_code === "investment" ? ["project_description"] : item.product_code === "tender_guarantee" ? ["tender_number", "beneficiary_name"] : [];
  const paymentKind = item.product_code === "tender_guarantee"
    ? "guarantee"
    : item.product_code === "overdraft" || item.product_code === "credit_line"
      ? "revolving"
      : "annuity";
  const itemFieldLabels = {
    ...fieldLabels,
    amount_kopecks: amountLabel(paymentKind),
    term_months: paymentKind === "annuity" ? "Срок кредита" : "Срок",
  };
  useEffect(() => {
    writeStored(draftKey, draft);
  }, [draftKey, draft]);
  useEffect(() => {
    lock(command.busy || !!command.pending);
  }, [command.busy, command.pending, lock]);
  function update<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
    if (key === "amount" || key === "term") {
      setRequestedAck(false);
      setOfferedAck(false);
    }
    setValidation("");
  }
  function toggle(key: "fields" | "documents", value: string) {
    if (key === "fields") {
      const field = value as RequestedField;
      setDraft((current) => ({
        ...current,
        fields: current.fields.includes(field)
          ? current.fields.filter((item) => item !== field)
          : [...current.fields, field],
      }));
    } else {
      const type = value as DocumentType;
      setDraft((current) => ({
        ...current,
        documents: current.documents.includes(type)
          ? current.documents.filter((item) => item !== type)
          : [...current.documents, type],
      }));
    }
    setValidation("");
  }
  function send(
    action:
      | "request_information"
      | "make_offer"
      | "approve"
      | "reject"
      | "respond_information"
      | "retry_processing"
      | "accept_offer"
      | "decline_offer",
  ) {
    if (!can(action) || disabled) return;
    const body: Record<string, unknown> = { expected_version: item.version };
    let path = `/applications/${item.id}/`;
    if (action === "request_information") {
      if (
        !draft.message.trim() ||
        (!draft.fields.length && !draft.documents.length)
      ) {
        setValidation("Напишите запрос и выберите поля или документы");
        return;
      }
      path += "information-requests";
      Object.assign(body, {
        message: draft.message.trim(),
        requested_fields: draft.fields,
        requested_document_types: draft.documents,
      } satisfies Omit<InformationRequestBody, "expected_version">);
    } else if (action === "respond_information") {
      if (!request || !policy || !draft.message.trim()) {
        setValidation("Добавьте сообщение к ответу");
        return;
      }
      path += "information-responses";
      Object.assign(body, {
        request_id: request.id,
        message: draft.message.trim(),
        data_confirmed: draft.confirmed,
        bki_consent: draft.consent,
        consent_version: policy.consent_version,
      } satisfies Omit<InformationResponseBody, "expected_version">);
    } else if (action === "make_offer") {
      const amount = parseAmount(draft.amount);
      const term = Number(draft.term);
      if (
        amount === null ||
        !/^\d+$/.test(draft.term) ||
        !Number.isSafeInteger(term) ||
        term < 1 ||
        term > 120 ||
        !draft.reason.trim()
      ) {
        setValidation(
          "Укажите сумму в рублях, срок от 1 до 120 месяцев и основание",
        );
        return;
      }
      if (offeredNeedsAck && !offeredAck) {
        setValidation("Подтвердите изучение оценки риска новых условий");
        return;
      }
      path += "offers";
      Object.assign(body, {
        risk_acknowledged: !!offeredNeedsAck && offeredAck,
        amount_kopecks: amount,
        term_months: term,
        reason: draft.reason.trim(),
      } satisfies Omit<CreateOfferBody, "expected_version">);
    } else if (action === "approve" || action === "reject") {
      if (!draft.reason.trim()) {
        setValidation("Укажите основание решения");
        return;
      }
      if (action === "approve" && requestedNeedsAck && !requestedAck) {
        setValidation("Подтвердите изучение оценки риска исходных условий");
        return;
      }
      path += "decisions";
      Object.assign(body, {
        risk_acknowledged:
          action === "approve" && !!requestedNeedsAck && requestedAck,
        outcome: action === "approve" ? "approved" : "rejected",
        reason: draft.reason.trim(),
      } satisfies Omit<DecisionBody, "expected_version">);
    } else if (action === "retry_processing") path += "processing-retries";
    else {
      if (!offer || offer.status !== "active") return;
      path = `/offers/${offer.id}/${action === "accept_offer" ? "accept" : "decline"}`;
      Object.assign(body, { offer_version: offer.version } satisfies Omit<
        OfferActionBody,
        "expected_version"
      >);
    }
    setValidation("");
    void command.send(path, body);
  }
  const technicalFailure =
    item.processing_status === "failed" ||
    item.processing_status === "interrupted";
  if (item.status === "draft" && !command.pending) return null;
  return (
    <section className="panel review-panel" aria-labelledby="review-title">
      <h2 id="review-title">
        {staff ? "Рассмотрение заявки" : "Следующий шаг"}
      </h2>
      <p>
        {technicalFailure
          ? "Требуется повтор обработки после устранения технического сбоя"
          : staff && item.status === "manual_review"
            ? "Изучите проверки и выберите доступное действие. Для решения укажите основание"
            : nextStep[item.status]}
      </p>
      {technicalFailure && (
        <div className="notice error" role="status">
          <strong>Обработка не завершена</strong>
          <p>
            Произошёл технический сбой. Кредитное решение не принято.{" "}
            {staff
              ? "Повторите обработку, когда причина сбоя устранена"
              : "Сотрудник банка может повторить обработку"}
          </p>
        </div>
      )}
      {item.public_reasons.length > 0 && (
        <ul className="public-reasons">
          {item.public_reasons.map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}
        </ul>
      )}
      {request && (
        <div className="information-request">
          <h3>Запрос уточнений</h3>
          <p className="multiline">{request.message}</p>
          <ul>
            {request.requested_fields.map((field) => (
              <li key={field}>
                {itemFieldLabels[field as RequestedField] || field}
              </li>
            ))}
            {request.requested_document_types.map((type) => (
              <li key={type}>{documentLabels[type]} — приложите новый файл</li>
            ))}
          </ul>
        </div>
      )}
      {item.information_requests.some(
        (request) => request.status === "answered",
      ) && (
        <details className="answered-requests">
          <summary>Отправленные ответы</summary>
          {item.information_requests
            .filter((request) => request.status === "answered")
            .map((request) => (
              <article key={request.id}>
                <h3>Запрос уточнений</h3>
                <p className="multiline">{request.message}</p>
                <ul>
                  {request.requested_fields.map((field) => (
                    <li key={field}>
                      {itemFieldLabels[field as RequestedField] || field}
                    </li>
                  ))}
                  {request.requested_document_types.map((type) => (
                    <li key={type}>{documentLabels[type]}</li>
                  ))}
                </ul>
                <h3>Ответ клиента</h3>
                <p className="multiline">
                  {request.response_message || "Текст ответа отсутствует"}
                </p>
                <p className="muted">
                  {request.responded_by === owner ? "Вы" : "Клиент компании"}
                  {request.responded_at
                    ? ` · ${dateTime(request.responded_at)}`
                    : ""}
                </p>
              </article>
            ))}
        </details>
      )}
      {offer && (
        <div className="offer-comparison">
          <h3>
            {offer.status === "accepted"
              ? "Принятые условия"
              : "Предложенные условия"}
          </h3>
          <p className="multiline">{offer.reason}</p>
          <table>
            <caption className="sr-only">Сравнение условий кредита</caption>
            <thead>
              <tr>
                <th scope="col">Условие</th>
                <th scope="col">Вы запросили</th>
                <th scope="col">
                  {offer.status === "accepted" ? "Принято" : "Предложено"}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">{amountLabel(offer.payment_terms.payment_kind)}</th>
                <td>{money(item.amount_kopecks)}</td>
                <td>{money(offer.amount_kopecks)}</td>
              </tr>
              <tr>
                <th scope="row">Срок</th>
                <td>{item.term_months} мес.</td>
                <td>{offer.term_months} мес.</td>
              </tr>
            </tbody>
          </table>
          <PaymentTermsView terms={offer.payment_terms} />
        </div>
      )}
      {!staff && can("respond_information") && (
        <div className="review-form">
          <p>
            Сохранение сведений и загрузка файлов не отправляют ответ в банк
          </p>
          <Link
            className={`button secondary${disabled ? " disabled" : ""}`}
            aria-disabled={disabled}
            onClick={(event) => {
              if (disabled) event.preventDefault();
            }}
            to={`/applications/${item.id}/edit`}
          >
            Дополнить сведения
          </Link>
          <label className="field">
            Сообщение к ответу
            <textarea
              rows={3}
              maxLength={4000}
              disabled={disabled}
              value={draft.message}
              onChange={(event) => update("message", event.target.value)}
            />
          </label>
          {policy && (
            <div className="consent-list">
              <label>
                <input
                  type="checkbox"
                  checked={draft.confirmed}
                  disabled={disabled}
                  onChange={(event) =>
                    update("confirmed", event.target.checked)
                  }
                />{" "}
                <span>{policy.data_confirmation_text}</span>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={draft.consent}
                  disabled={disabled}
                  onChange={(event) => update("consent", event.target.checked)}
                />{" "}
                <span>{policy.bki_consent_text}</span>
              </label>
            </div>
          )}
          <div className="review-buttons">
            <button
              className="button primary"
              disabled={disabled || !policy}
              onClick={() => send("respond_information")}
            >
              Отправить ответ
            </button>
          </div>
        </div>
      )}
      {!staff && (can("accept_offer") || can("decline_offer")) && (
        <div className="review-buttons">
          {can("decline_offer") && (
            <button
              className="button secondary"
              disabled={disabled}
              onClick={() => send("decline_offer")}
            >
              Отклонить предложение
            </button>
          )}
          {can("accept_offer") && (
            <button
              className="button primary"
              disabled={disabled}
              onClick={() => send("accept_offer")}
            >
              Принять условия
            </button>
          )}
        </div>
      )}
      {staff && can("request_information") && (
        <details className="review-form">
          <summary>Запросить уточнения</summary>
          <label className="field">
            Сообщение клиенту
            <textarea
              rows={3}
              maxLength={4000}
              disabled={disabled}
              value={draft.message}
              onChange={(event) => update("message", event.target.value)}
            />
          </label>
          <fieldset className="request-options" disabled={disabled}>
            <legend>Какие сведения нужны</legend>
            {Object.entries(itemFieldLabels).filter(([field]) => !(["tender_number", "beneficiary_name", "project_description"] as string[]).includes(field) || productFields.includes(field as RequestedField)).map(([field, label]) => (
              <label key={field}>
                <input
                  type="checkbox"
                  checked={draft.fields.includes(field as RequestedField)}
                  onChange={() => toggle("fields", field)}
                />{" "}
                {label}
              </label>
            ))}
          </fieldset>
          <fieldset className="request-options" disabled={disabled}>
            <legend>Новые документы</legend>
            {Object.entries(documentLabels).map(([type, label]) => (
              <label key={type}>
                <input
                  type="checkbox"
                  checked={draft.documents.includes(type as DocumentType)}
                  onChange={() => toggle("documents", type)}
                />{" "}
                {label}
              </label>
            ))}
          </fieldset>
          <div className="review-buttons">
            <button
              className="button primary"
              disabled={disabled}
              onClick={() => send("request_information")}
            >
              Отправить запрос
            </button>
          </div>
        </details>
      )}
      {staff && (can("make_offer") || can("approve") || can("reject")) && (
        <div className="review-form">
          <label className="field">
            Основание решения или предложения
            <textarea
              rows={3}
              maxLength={4000}
              disabled={disabled}
              value={draft.reason}
              onChange={(event) => update("reason", event.target.value)}
            />
            <small>Обязательно. Публичная причина будет видна клиенту</small>
          </label>
          {can("approve") && requestedNeedsAck && (
            <label className="risk-acknowledgement">
              <input
                type="checkbox"
                checked={requestedAck}
                disabled={disabled}
                onChange={(event) => setRequestedAck(event.target.checked)}
              />
              <span>Изучена оценка риска исходных условий</span>
            </label>
          )}
          {can("make_offer") && (
            <details>
              <summary>Предложить другие условия</summary>
              <div className="field-grid">
                <label className="field">
                  Предлагаемая сумма, ₽
                  <input
                    inputMode="decimal"
                    maxLength={24}
                    disabled={disabled}
                    value={draft.amount}
                    onChange={(event) => update("amount", event.target.value)}
                  />
                </label>
                <label className="field">
                  Предлагаемый срок, месяцев
                  <input
                    inputMode="numeric"
                    maxLength={3}
                    disabled={disabled}
                    value={draft.term}
                    onChange={(event) => update("term", event.target.value)}
                  />
                </label>
              </div>
              {offeredRisk && <RiskAssessmentPanel assessment={offeredRisk} />}
              {offeredNeedsAck && (
                <label className="risk-acknowledgement">
                  <input
                    type="checkbox"
                    checked={offeredAck}
                    disabled={disabled}
                    onChange={(event) => setOfferedAck(event.target.checked)}
                  />
                  <span>Изучена оценка риска новых условий</span>
                </label>
              )}
              <div className="review-buttons">
                <button
                  className="button secondary"
                  disabled={disabled}
                  onClick={() => send("make_offer")}
                >
                  Отправить предложение
                </button>
              </div>
            </details>
          )}
          <div className="review-buttons">
            {can("reject") && (
              <button
                className="button secondary"
                disabled={disabled}
                onClick={() => send("reject")}
              >
                Отказать по заявке
              </button>
            )}
            {can("approve") && (
              <button
                className="button primary"
                disabled={disabled}
                onClick={() => send("approve")}
              >
                Одобрить заявку
              </button>
            )}
          </div>
        </div>
      )}
      {staff && can("retry_processing") && (
        <div className="review-buttons">
          <button
            className="button primary"
            disabled={disabled}
            onClick={() => send("retry_processing")}
          >
            Повторить обработку
          </button>
        </div>
      )}
      {(validation || command.error) && (
        <div className="notice error" role="alert">
          <p>{validation || command.error}</p>
          {Object.entries(command.fields).map(([field, message]) => (
            <p key={field}>
              {itemFieldLabels[field as RequestedField] || field}: {message}
            </p>
          ))}
        </div>
      )}
      {command.pending && !command.busy && (
        <div className="notice" role="status">
          <p>
            Ответ не получен. Повтор сохранит исходные данные команды и не
            создаст второе действие
          </p>
          <button
            className="button primary"
            disabled={command.busy}
            onClick={() => void command.send()}
          >
            Повторить действие
          </button>
        </div>
      )}
      {command.conflict && (
        <div className="notice">
          <p>
            Заявка изменилась. Ваш ввод сохранён; проверьте актуальное состояние
            перед новым действием
          </p>
          <button
            className="button secondary"
            disabled={command.busy}
            onClick={() => void command.refresh()}
          >
            Загрузить актуальное состояние
          </button>
        </div>
      )}
      {command.busy && <p role="status">Выполняем действие…</p>}
      {item.offers.some(
        (offer) => offer.status === "declined" || offer.status === "superseded",
      ) && (
        <details className="past-offers">
          <summary>Предыдущие предложения</summary>
          {item.offers
            .filter(
              (offer) =>
                offer.status === "declined" || offer.status === "superseded",
            )
            .map((offer) => (
              <p key={offer.id}>
                {money(offer.amount_kopecks)}, {offer.term_months} мес. —{" "}
                {offer.status === "declined"
                  ? "Отклонено клиентом"
                  : "Заменено новым предложением"}
              </p>
            ))}
        </details>
      )}
      {staff && item.available_actions.length === 0 && (
        <p className="muted">
          {statusLabels[item.status]}. Доступных команд сейчас нет
        </p>
      )}
    </section>
  );
}
