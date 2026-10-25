import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import { useSession } from "../auth/session";
import AssistantPanel from "../components/assistant/AssistantPanel";
import StaffSummaryPanel from "../components/assistant/StaffSummaryPanel";
import ApplicationDocuments from "../components/ApplicationDocuments";
import ReviewActions from "../components/ReviewActions";
import AssessmentPanel from "../components/AssessmentPanel";
import SubmissionPanel from "../components/SubmissionPanel";
import type {
  Application,
  Assessment,
  Catalog,
  HistoryEvent,
  PageResult,
  SubmissionPolicy,
} from "../api/types";
import {
  ApplicationNumber,
  date,
  dateTime,
  ErrorPanel,
  Loading,
  money,
  PageHeading,
  Pagination,
  Status,
  useResource,
} from "../components/shared";
import { amountLabel } from "../components/PaymentTermsView";

import { linkedJourney, useVisibleObservation, viewStep } from "../analytics/observations";

export default function ApplicationDetailsPage() {
  const { id } = useParams();
  const { state } = useLocation();
  const { user } = useSession();
  const { data, error, reload } = useResource(async () => {
    const [application, catalog] = await Promise.all([
      api<Application>(`/applications/${id}`),
      api<Catalog>("/products"),
    ]);
    return { application, catalog };
  }, id!);
  if (error) return <ErrorPanel error={error} retry={reload} />;
  if (!data) return <Loading />;
  return (
    <Details
      key={`${user!.id}:${id}`}
      initial={data.application}
      catalog={data.catalog}
      saved={state?.saved === true}
    />
  );
}
function Details({
  initial,
  catalog,
  saved,
}: {
  initial: Application;
  catalog: Catalog;
  saved: boolean;
}) {
  const { user } = useSession();
  const staff = user!.role === "staff";
  const [item, setItem] = useState(initial);
  const [submissionLocked, setSubmissionLocked] = useState(false);
  const [reviewLocked, setReviewLocked] = useState(false);
  const locked = submissionLocked || reviewLocked;
  const [refreshError, setRefreshError] = useState("");
  const id = item.id;
  const documentsRef = useRef<HTMLDivElement>(null);
  const reviewRef = useRef<HTMLDivElement>(null);
  const [journey] = useState(() => staff ? null : linkedJourney(user!.id, id));
  useVisibleObservation(documentsRef, journey ? () => viewStep(user!.id, journey, 'documents') : null, `${journey}:documents`);
  useVisibleObservation(reviewRef, journey && item.status === 'draft' ? () => viewStep(user!.id, journey, 'review') : null, `${journey}:${item.status}:review`);
  const assessment = useResource(
    () =>
      staff
        ? api<Assessment>(`/applications/${id}/assessment`)
        : Promise.resolve(null),
    `${id}:${item.version}:${staff}`,
  );
  const {
    data: policy,
    error: policyError,
    reload: reloadPolicy,
  } = useResource(
    () =>
      staff
        ? Promise.resolve(null)
        : api<SubmissionPolicy>("/submission-policy"),
    user!.id,
  );
  async function refresh(version?: number) {
    if (version !== undefined)
      setItem((current) => ({
        ...current,
        version: Math.max(current.version, version),
      }));
    const current = await api<Application>(`/applications/${id}`);
    setItem((previous) =>
      current.version >= previous.version ? current : previous,
    );
    setRefreshError("");
  }
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const current = await api<Application>(`/applications/${id}`);
        if (active) {
          setItem((previous) =>
            current.version >= previous.version ? current : previous,
          );
          setRefreshError("");
        }
      } catch (error) {
        if (active) setRefreshError(errorMessage(error));
      } finally {
        if (active) timer = setTimeout(poll, 3000);
      }
    }
    timer = setTimeout(poll, 3000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [id]);
  const product = catalog.items.find(
    (product) => product.code === item.product_code,
  );
  return (
    <>
      <PageHeading
        title={product?.name || "Кредитная заявка"}
        metadata={<><ApplicationNumber number={item.display_number} /><time dateTime={item.updated_at}>Изменена {dateTime(item.updated_at)}</time></>}
      >
        <Status status={item.status} />
      </PageHeading>
      {refreshError && (
        <div className="notice error" role="status">
          Не удалось обновить статус. {refreshError}
        </div>
      )}
      <div className="details-layout">
        <div className="details-main">
          <section className="panel details-panel">
            {saved &&
              (item.status === "draft" || item.status === "needs_info") && (
                <div className="notice success" role="status">
                  {item.status === "needs_info"
                    ? "Дополнения сохранены. Отправьте ответ отдельно, чтобы продолжить рассмотрение."
                    : "Черновик сохранён. Вы можете вернуться к нему в любой момент."}
                </div>
              )}
            <div className="section-top">
              <h2>Запрошенные условия</h2>
              {!locked && item.available_actions.includes("edit_draft") && (
                <Link
                  className="button secondary edit-draft"
                  to={`/applications/${id}/edit`}
                  aria-label="Редактировать"
                >
                  <svg
                    className="edit-icon"
                    viewBox="0 0 24 24"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path
                      d="m15 5 4 4M4 20l5-1L20 8a2.8 2.8 0 0 0-4-4L5 15l-1 5Z"
                      stroke="currentColor"
                      strokeWidth="1.7"
                      strokeLinejoin="round"
                    />
                  </svg>
                  <span className="edit-label">Редактировать</span>
                </Link>
              )}
            </div>
            <dl className="details-grid">
              <div>
                <dt>{amountLabel(product?.payment_kind || "annuity")}</dt>
                <dd className="summary-amount">{money(item.amount_kopecks)}</dd>
              </div>
              <div>
                <dt>Срок</dt>
                <dd className="summary-amount">
                  {item.term_months ? `${item.term_months} мес.` : "Не указан"}
                </dd>
              </div>
              <div className="full-width">
                <dt>Цель финансирования</dt>
                <dd>{item.purpose || "Не указана"}</dd>
              </div>
              {item.description && (
                <div className="full-width">
                  <dt>Дополнительное описание</dt>
                  <dd className="multiline">{item.description}</dd>
                </div>
              )}
              {item.project_description && <div className="full-width"><dt>Описание проекта</dt><dd className="multiline">{item.project_description}</dd></div>}
              {item.tender_number && <div><dt>Номер тендера</dt><dd>{item.tender_number}</dd></div>}
              {item.beneficiary_name && <div><dt>Заказчик по тендеру</dt><dd>{item.beneficiary_name}</dd></div>}
            </dl>
            <div className="details-divider" />
            <h2>Финансы компании</h2>
            <dl className="financial-details">
              <div>
                <dt>Период</dt>
                <dd>
                  {item.period_start || item.period_end
                    ? `${date(item.period_start)} — ${date(item.period_end)}`
                    : "Не указан"}
                </dd>
              </div>
              <div>
                <dt>Выручка</dt>
                <dd>{money(item.revenue_kopecks)}</dd>
              </div>
              <div>
                <dt>Операционные расходы</dt>
                <dd>{money(item.operating_expenses_kopecks)}</dd>
              </div>
              <div>
                <dt>Платежи по кредитам</dt>
                <dd>{money(item.existing_debt_payments_kopecks)}</dd>
              </div>
            </dl>
          </section>
          {staff ? <StaffSummaryPanel owner={user!.id} application={item} catalog={catalog} /> : <AssistantPanel owner={user!.id} application={item} catalog={catalog} />}
          {staff && (
            <AssessmentPanel
              data={assessment.data}
              error={assessment.error}
              reload={assessment.reload}
            />
          )}
          <ReviewActions
            application={item}
            owner={user!.id}
            staff={staff}
            policy={policy}
            changed={refresh}
            assessment={assessment.error ? null : assessment.data}
            refreshAssessment={assessment.reload}
            lock={setReviewLocked}
          />
          <div ref={documentsRef}><ApplicationDocuments
            application={item}
            required={product?.required_document_types || []}
            policy={policy}
            locked={locked}
            changed={refresh}
          /></div>
        </div>
        <aside className="details-aside">
          {!!policyError && (
            <ErrorPanel error={policyError} retry={reloadPolicy} />
          )}
          <div ref={reviewRef}><SubmissionPanel
            application={item}
            policy={policy}
            owner={user!.id}
            staff={staff}
            changed={refresh}
            lock={setSubmissionLocked}
            submitted={(result) => {
              setItem((current) => ({
                ...current,
                status: result.status,
                version: result.version,
                available_actions: [],
              }));
            }}
          /></div>
          <History id={id} version={item.version} />
        </aside>
      </div>
    </>
  );
}
const staffHistoryEvents = new Set([
  "information_requested",
  "offer_created",
  "staff_approved",
  "staff_rejected",
  "processing_retried",
]);
const clientHistoryEvents = new Set([
  "draft_created",
  "draft_updated",
  "document_uploaded",
  "document_deleted",
  "application_submitted",
  "working_copy_updated",
  "information_responded",
  "offer_accepted",
  "offer_declined",
]);
function historyAuthor(event: HistoryEvent, owner: string) {
  if (event.actor_type === "system") return "Система";
  if (event.actor_id === owner) return "Вы";
  if (staffHistoryEvents.has(event.event_type)) return "Сотрудник банка";
  if (clientHistoryEvents.has(event.event_type)) return "Клиент компании";
  return "Участник заявки";
}
function History({ id, version }: { id: string; version: number }) {
  const { user } = useSession();
  const [offset, setOffset] = useState(0);
  const { data, error, reload } = useResource(
    () =>
      api<PageResult<HistoryEvent>>(
        `/applications/${id}/history?limit=10&offset=${offset}`,
      ),
    `${id}-${offset}-${version}`,
    3000,
  );
  return (
    <section className="history">
      <h2>История заявки</h2>
      {error ? (
        <ErrorPanel error={error} retry={reload} />
      ) : !data ? (
        <Loading />
      ) : (
        <>
          <ol>
            {data.items.map((item) => (
              <li key={item.id}>
                <span className="history-dot" />
                <div>
                  <strong>
                    {(
                      {
                        draft_created: "Черновик создан",
                        draft_updated: "Черновик обновлён",
                        document_uploaded: "Документ добавлен",
                        document_deleted: "Документ удалён",
                        application_submitted: "Заявка отправлена",
                        processing_started: "Проверка началась",
                        processing_completed: "Проверка завершена",
                        processing_failed: "Технический сбой обработки",
                        processing_interrupted: "Обработка прервана",
                        processing_retried: "Обработка запущена повторно",
                        information_requested: "Запрошены уточнения",
                        information_responded: "Отправлен ответ на запрос",
                        working_copy_updated: "Дополнения сохранены",
                        offer_created: "Предложены другие условия",
                        offer_accepted: "Предложение принято клиентом",
                        offer_declined: "Предложение отклонено клиентом",
                        staff_approved: "Заявка одобрена сотрудником",
                        staff_rejected: "Отказ по решению сотрудника",
                        auto_approved: "Заявка одобрена",
                        auto_rejected: "Отказ по правилам",
                      } as Record<string, string>
                    )[item.event_type] || "Заявка обновлена"}
                  </strong>
                  <small>
                    {historyAuthor(item, user!.id)} · версия{" "}
                    {item.application_version}
                  </small>
                  <time dateTime={item.created_at}>
                    {dateTime(item.created_at)}
                  </time>
                </div>
              </li>
            ))}
          </ol>
          <Pagination {...data} onChange={setOffset} />
        </>
      )}
    </section>
  );
}
