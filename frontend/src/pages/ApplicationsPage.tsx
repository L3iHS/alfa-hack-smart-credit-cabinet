import { useState } from "react";
import { Link } from "react-router-dom";
import AssistantPanel from "../components/assistant/AssistantPanel";
import { useSession } from "../auth/session";
import { api } from "../api/client";
import type { Application, Catalog, PageResult } from "../api/types";
import {
  ApplicationNumber,
  dateTime,
  ErrorPanel,
  Loading,
  money,
  PageHeading,
  Pagination,
  Status,
  useResource,
} from "../components/shared";

export default function ApplicationsPage() {
  const { user } = useSession();
  const [offset, setOffset] = useState(0);
  const { data, error, reload } = useResource(
    async () => {
      const [applications, catalog] = await Promise.all([
        api<PageResult<Application>>(`/applications?limit=20&offset=${offset}`),
        api<Catalog>("/products"),
      ]);
      return { applications, catalog };
    },
    String(offset),
    3000,
  );
  return (
    <>
      <PageHeading
        title="Мои заявки"
        subtitle="Здесь всё, что нужно для продолжения работы с кредитом"
      >
        <Link className="button primary" to="/applications/new">
          <span aria-hidden="true">＋</span> Новая заявка
        </Link>
      </PageHeading>
      {data && <AssistantPanel owner={user!.id} catalog={data.catalog} />}
      {error ? (
        <ErrorPanel error={error} retry={reload} />
      ) : !data ? (
        <Loading />
      ) : data.applications.items.length === 0 ? (
        <section className="panel empty-state">
          <div className="empty-icon" aria-hidden="true">
            ▤
          </div>
          <h2>Начнём с вашей первой заявки</h2>
          <p>
            Оборотные средства или новое оборудование — выберите финансирование
            под задачи бизнеса
          </p>
          <Link className="button primary" to="/applications/new">
            Новая заявка
          </Link>
          <span className="muted">
            Заполняйте в своём темпе: черновик можно сохранить
          </span>
        </section>
      ) : (
        <>
          <section className="panel applications-list">
            <div className="list-heading">
              <span>Продукт и заявка</span>
              <span>Сумма</span>
              <span>Статус</span>
              <span>Изменена</span>
            </div>
            {data.applications.items.map((item) => (
              <article
                className="application-row"
                key={item.id}
              >
                <div>
                  <Link className="application-title" to={`/applications/${item.id}`}><strong>
                    {data.catalog.items.find(
                      (p) => p.code === item.product_code,
                    )?.name || item.product_code}
                  </strong></Link>
                  <ApplicationNumber number={item.display_number} />
                </div>
                <span className="amount">{money(item.amount_kopecks)}</span>
                <Status status={item.status} />
                <time dateTime={item.updated_at}>
                  {dateTime(item.updated_at)}
                </time>

              </article>
            ))}
          </section>
          <Pagination {...data.applications} onChange={setOffset} />
        </>
      )}
      <div className="quiet-note">
        Черновики доступны только вашей компании. После отправки заявку увидит
        сотрудник банка.
      </div>
    </>
  );
}
