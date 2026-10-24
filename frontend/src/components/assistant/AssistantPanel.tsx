import { useId, useRef, useState } from 'react';
import { askAssistant, useAssistantRequest, type AnswerOutput } from '../../api/assistant';
import type { Catalog } from '../../api/types';
import SourceDetails from './SourceDetails';

export default function AssistantPanel({ owner, catalog, application }: { owner: string; catalog: Catalog; application?: { id: string; version: number } }) {
  const [question, setQuestion] = useState('');
  const [open, setOpen] = useState(false);
  const launcher = useRef<HTMLButtonElement>(null);
  function close() { setOpen(false); launcher.current?.focus(); }
  const id = useId();
  const request = useAssistantRequest<AnswerOutput>(JSON.stringify([owner, application?.id, application?.version, question]));
  const examples = application ? ['Какую сумму я запросил?', 'Какие документы нужны?'] : ['Какие документы нужны для кредита на оборудование?', 'Что такое кредитная линия?'];
  return <div className="assistant-panel assistant-chat">
    <button type="button" className="assistant-launcher" ref={launcher} aria-expanded={open} aria-controls={`${id}-window`} onClick={() => setOpen(value => !value)}><svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a9.5 9.5 0 0 1 19 0Z" /><path d="M7 10h10M7 14h6" /></svg>Помощник</button>
    {open && <div id={`${id}-window`} className="assistant-chat-window" role="dialog" aria-labelledby={`${id}-title`} onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); } }}>
    <header className="assistant-chat-heading"><h2 id={`${id}-title`}>Помощник по кредитам</h2><button type="button" className="assistant-close" aria-label="Закрыть помощника" onClick={close}><svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 6 12 12M18 6 6 18" /></svg></button></header>
    <div className="assistant-body">
    <label className="field" htmlFor={id}><span>Ваш вопрос</span><textarea id={id} rows={2} value={question} onChange={event => setQuestion(event.target.value)} maxLength={2000} placeholder="О продуктах, документах или вашей заявке" /></label>
    <div className="assistant-examples" aria-label="Примеры вопросов">{examples.map(example => <button type="button" key={example} onClick={() => setQuestion(example)}>{example}</button>)}</div>
    <p className="muted">Каждый вопрос рассматривается отдельно.</p>
    <div className="assistant-actions"><button type="button" className="button secondary" disabled={request.busy || !question.trim()} onClick={() => void request.run(signal => askAssistant(question, application, signal))}>{request.busy ? 'Готовим ответ…' : 'Спросить'}</button></div>
    {request.busy && <p role="status" className="muted">Ищем ответ по доступным сведениям</p>}
    {request.error && <p className="notice error" role="alert">{request.error}.</p>}
    {request.result && <div className="assistant-result" aria-live="polite"><p className="multiline">{request.result.answer}</p><SourceDetails sources={request.result.sources} catalog={catalog} /></div>}
  </div></div>}</div>;
}
