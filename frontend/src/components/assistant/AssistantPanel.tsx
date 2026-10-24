import { useId, useState } from 'react';
import { askAssistant, useAssistantRequest, type AnswerOutput } from '../../api/assistant';
import type { Catalog } from '../../api/types';
import SourceDetails from './SourceDetails';

export default function AssistantPanel({ owner, catalog, application }: { owner: string; catalog: Catalog; application?: { id: string; version: number } }) {
  const [question, setQuestion] = useState('');
  const id = useId();
  const request = useAssistantRequest<AnswerOutput>(JSON.stringify([owner, application?.id, application?.version, question]));
  const examples = application ? ['Какую сумму я запросил?', 'Какие документы нужны?'] : ['Какие документы нужны для кредита на оборудование?', 'Что такое кредитная линия?'];
  return <details className="panel assistant-panel assistant-chat"><summary>Помощник</summary><div className="assistant-body">
    <label className="field" htmlFor={id}><span>Ваш вопрос</span><textarea id={id} rows={2} value={question} onChange={event => setQuestion(event.target.value)} maxLength={2000} placeholder="О продуктах, документах или вашей заявке" /></label>
    <div className="assistant-examples" aria-label="Примеры вопросов">{examples.map(example => <button type="button" key={example} onClick={() => setQuestion(example)}>{example}</button>)}</div>
    <p className="muted">Каждый вопрос рассматривается отдельно.</p>
    <div className="assistant-actions"><button type="button" className="button secondary" disabled={request.busy || !question.trim()} onClick={() => void request.run(signal => askAssistant(question, application, signal))}>{request.busy ? 'Готовим ответ…' : 'Спросить'}</button></div>
    {request.busy && <p role="status" className="muted">Ищем ответ по доступным сведениям</p>}
    {request.error && <p className="notice error" role="alert">{request.error}. Попробуйте повторить вопрос позже.</p>}
    {request.result && <div className="assistant-result" aria-live="polite"><p className="multiline">{request.result.answer}</p><SourceDetails sources={request.result.sources} catalog={catalog} /></div>}
  </div></details>;
}
