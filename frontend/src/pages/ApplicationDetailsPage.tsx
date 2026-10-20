import { useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  Application,
  Catalog,
  HistoryEvent,
  PageResult,
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
  const item = data.application;
  const product = data.catalog.items.find(
    (product) => product.code === item.product_code,
  );
  return (
    <>
      <Link className="back-link" to="/applications">
        ‹ Мои заявки
      </Link>
      <PageHeading
        title={product?.name || "Кредитная заявка"}
        subtitle={`Заявка № ${item.id.slice(0, 8)} · ${dateTime(item.updated_at)}`}
      >
        <Status />
      </PageHeading>
      {state?.saved && (
        <div className="notice success" role="status">
          Черновик сохранён. Вы можете вернуться к нему в любой момент.
        </div>
      )}
      <div className="details-layout">
        <section className="panel details-panel">
          <div className="section-top">
            <h2>Ваша заявка</h2>
            {item.available_actions.includes("edit_draft") && (
              <Link className="text-link" to={`/applications/${id}/edit`}>
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
        <aside className="details-aside">
          <section className="panel next-step">
            <h2>Что дальше</h2>
            <p>
              Дополните цель, условия кредита и финансовые сведения. Пока заявка
              остаётся черновиком.
            </p>
            {item.available_actions.includes("edit_draft") && (
              <Link className="button primary" to={`/applications/${id}/edit`}>
                Продолжить заполнение
              </Link>
            )}
            <small>Отправка на рассмотрение появится на следующем этапе</small>
          </section>
          <History id={id!} />
        </aside>
      </div>
    </>
  );
}
function History({ id }: { id: string }) {
  const [offset, setOffset] = useState(0);
  const { data, error, reload } = useResource(
    () =>
      api<PageResult<HistoryEvent>>(
        `/applications/${id}/history?limit=10&offset=${offset}`,
      ),
    `${id}-${offset}`,
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
                    {item.event_type === "draft_created"
                      ? "Черновик создан"
                      : "Черновик обновлён"}
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
