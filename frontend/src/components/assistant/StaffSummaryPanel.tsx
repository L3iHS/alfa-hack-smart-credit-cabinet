import { useEffect, useState } from 'react';
import { loadApplicationSummary, summarizeApplication, useAssistantRequest, type AnswerOutput } from '../../api/assistant';
import type { Application, Catalog } from '../../api/types';
import { dateTime } from '../shared';
import SourceDetails from './SourceDetails';
import AnswerContent from './AnswerContent';
import { downloadSummary } from './summaryDownload';
import './assistant-usability.css';
export default function StaffSummaryPanel({ owner, application, catalog }: { owner: string; application: Application; catalog: Catalog }) {
  const scope = JSON.stringify([owner, application.id, application.version]);
  const request = useAssistantRequest<AnswerOutput | null>(scope);
  const [generating, setGenerating] = useState<string | null>(null);
  const applicationNumber = (application as Application & { display_number?: string }).display_number;
  // Чтение сохранённой сводки не запускает модель. Хук отбрасывает ответ другого владельца или версии.
  useEffect(() => {
    void request.run(signal => loadApplicationSummary(application.id, application.version, signal));
  }, [scope]);
  const result = request.result;
  function generate(refresh: boolean) {
    setGenerating(scope);
    void request.run(signal => summarizeApplication(application.id, application.version, signal, refresh), true).finally(() => setGenerating(current => current === scope ? null : current));
  }
  return <section className="panel assistant-panel staff-summary" aria-label="Сводка помощника">
    <header className="assistant-summary-heading">
      <span className="assistant-summary-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7" /></svg></span>
      <div><h2>Сводка помощника</h2><p className="muted">Обзор текущего рассмотрения. Решение принимает сотрудник.</p></div>
      <div className="assistant-summary-actions">
        {result && <button type="button" className="assistant-download" aria-label="Скачать сводку в Markdown" title="Скачать Markdown" onClick={() => downloadSummary(result, applicationNumber, catalog)}><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" /></svg></button>}
        <button type="button" className="button secondary" disabled={request.busy} onClick={() => generate(Boolean(result))}>{request.busy ? generating === scope ? 'Формируем сводку…' : 'Загружаем сводку…' : result ? 'Обновить сводку' : 'Сформировать сводку'}</button>
      </div>
    </header>
    {request.busy && <p role="status" className="muted">{generating === scope ? 'Собираем сведения текущего рассмотрения' : 'Проверяем сохранённую сводку'}</p>}
    {request.error && <p className="notice error" role="alert">{request.error}. Рассмотрение заявки доступно без сводки.</p>}
    {result && <div className="assistant-result" aria-live="polite"><AnswerContent text={result.answer} />{result.generated_at && <p className="muted">Сформировано {dateTime(result.generated_at)}</p>}<SourceDetails sources={result.sources} catalog={catalog} /></div>}
  </section>;
}
