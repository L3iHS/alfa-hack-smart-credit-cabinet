import { summarizeApplication, useAssistantRequest, type AnswerOutput } from '../../api/assistant';
import type { Application, Catalog } from '../../api/types';
import { dateTime } from '../shared';
import SourceDetails from './SourceDetails';
export default function StaffSummaryPanel({ owner, application, catalog }: { owner: string; application: Application; catalog: Catalog }) {
  const request = useAssistantRequest<AnswerOutput>(JSON.stringify([owner, application.id, application.version]));
  return <section className="panel assistant-panel staff-summary" aria-label="Сводка помощника"><h2>Сводка помощника</h2>
    <p className="muted">Краткий обзор текущего рассмотрения по сохранённым сведениям. Решение принимает сотрудник.</p>
    <div className="assistant-actions"><button type="button" className="button secondary" disabled={request.busy} onClick={() => void request.run(signal => summarizeApplication(application.id, application.version, signal))}>{request.busy ? 'Формируем сводку…' : 'Сформировать сводку'}</button></div>
    {request.busy && <p role="status" className="muted">Собираем сведения текущего рассмотрения</p>}
    {request.error && <p className="notice error" role="alert">{request.error}. Рассмотрение заявки доступно без сводки.</p>}
    {request.result && <div className="assistant-result" aria-live="polite"><p className="multiline">{request.result.answer}</p>{request.result.generated_at && <p className="muted">Сформировано {dateTime(request.result.generated_at)}</p>}<SourceDetails sources={request.result.sources} catalog={catalog} /></div>}
  </section>;
}
