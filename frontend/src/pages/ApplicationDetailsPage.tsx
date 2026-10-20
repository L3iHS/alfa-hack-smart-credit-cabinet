import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import { useSession } from "../auth/session";
import ApplicationDocuments from "../components/ApplicationDocuments";
import SubmissionPanel from "../components/SubmissionPanel";
import type {
  Application,
  Catalog,
  HistoryEvent,
  PageResult,
  SubmissionPolicy,
} from "../api/types";
import {
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

export default function ApplicationDetailsPage() {
  const { id } = useParams();
  const { state } = useLocation();
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
      key={id}
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
  const [locked, setLocked] = useState(false);
  const [refreshError, setRefreshError] = useState("");
  const id = item.id;
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
        subtitle={`Заявка № ${item.id.slice(0, 8)} · ${dateTime(item.updated_at)}`}
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
            {saved && item.status === "draft" && (
              <div className="notice success" role="status">
                Черновик сохранён. Вы можете вернуться к нему в любой момент.
              </div>
            )}
            <div className="section-top">
              <h2>{staff ? "Данные заявки" : "Ваша заявка"}</h2>
              {!locked && item.available_actions.includes("edit_draft") && (
                <Link className="button secondary" to={`/applications/${id}/edit`}>
                  Редактировать
                </Link>
              )}
            </div>
            <dl className="details-grid">
              <div>
                <dt>Сумма кредита</dt>
                <dd className="summary-amount">{money(item.amount_kopecks)}</dd>
              </div>
              <div>
                <dt>Срок кредита</dt>
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
          <ApplicationDocuments
            application={item}
            required={product?.required_document_types || []}
            policy={policy}
            locked={locked}
            changed={refresh}
          />
        </div>
        <aside className="details-aside">
          {!!policyError && (
            <ErrorPanel error={policyError} retry={reloadPolicy} />
          )}
          <SubmissionPanel
            application={item}
            policy={policy}
            owner={user!.id}
            staff={staff}
            changed={refresh}
            lock={setLocked}
            submitted={(result) => {
              setItem((current) => ({
                ...current,
                status: result.status,
                version: result.version,
                available_actions: [],
              }));
            }}
          />
          <History id={id} version={item.version} />
        </aside>
      </div>
    </>
  );
}
function History({ id, version }: { id: string; version: number }) {
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
                    {{
                      draft_created: "Черновик создан",
                      draft_updated: "Черновик обновлён",
                      document_uploaded: "Документ добавлен",
                      document_deleted: "Документ удалён",
                      application_submitted: "Заявка отправлена",
                    }[item.event_type] || "Заявка обновлена"}
                  </strong>
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
