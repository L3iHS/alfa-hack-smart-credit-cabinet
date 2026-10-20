import { useState } from "react";
import { api } from "../api/client";
import type { Application, PageResult } from "../api/types";
import {
  ErrorPanel,
  Loading,
  PageHeading,
  Pagination,
  useResource,
} from "../components/shared";

export default function StaffApplicationsPage() {
  const [offset, setOffset] = useState(0);
  const { data, error, reload } = useResource(
    () =>
      api<PageResult<Application>>(`/applications?limit=20&offset=${offset}`),
    String(offset),
  );
  return (
    <>
      <PageHeading
        title="Заявки на рассмотрение"
        subtitle="Рабочая очередь сотрудника банка"
      />
      {error ? (
        <ErrorPanel error={error} retry={reload} />
      ) : !data ? (
        <Loading />
      ) : (
        <>
          <section className="panel empty-state">
            <div className="empty-icon" aria-hidden="true">
              ▤
            </div>
            <h2>Заявок на рассмотрение пока нет</h2>
            <p>
              Здесь появятся заявки, которые клиенты отправят в банк. Черновики
              остаются в кабинете компании.
            </p>
            <button className="button secondary" onClick={reload}>
              Обновить очередь
            </button>
          </section>
          <Pagination {...data} onChange={setOffset} />
        </>
      )}
      <div className="quiet-note">
        Приём и рассмотрение заявок будут доступны на следующем этапе
      </div>
    </>
  );
}
