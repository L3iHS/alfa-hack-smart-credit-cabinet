import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Application, Catalog, PageResult } from "../api/types";
import {
  ApplicationNumber,
  ErrorPanel,
  Loading,
  PageHeading,
  Pagination,
  useResource,
  dateTime,
  money,
  Status,
} from "../components/shared";

export default function StaffApplicationsPage() {
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
        title="Заявки"
        subtitle="Рабочая очередь сотрудника банка"
      />
      {error ? (
        <ErrorPanel error={error} retry={reload} />
      ) : !data ? (
        <Loading />
      ) : (
        <>
          {data.applications.items.length ? (
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
                    <Link className="application-title" to={`/staff/applications/${item.id}`}><strong>
                      {data.catalog.items.find(
                        (product) => product.code === item.product_code,
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
          ) : (
            <section className="panel empty-state">
              <div className="empty-icon" aria-hidden="true">
                ▤
              </div>
              <h2>Заявок пока нет</h2>
              <p>
                Здесь появятся заявки, которые клиенты отправят в банк.
                Черновики остаются в кабинете компании.
              </p>
              <button className="button secondary" onClick={reload}>
                Обновить очередь
              </button>
            </section>
          )}
          <Pagination {...data.applications} onChange={setOffset} />
        </>
      )}
      <div className="quiet-note">
        В очереди отображаются отправленные заявки. Откройте карточку, чтобы посмотреть проверки и доступные действия.
      </div>
    </>
  );
}
