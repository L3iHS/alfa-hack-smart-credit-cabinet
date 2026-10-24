import { useEffect, useId, useRef, useState } from 'react';
import { askAssistant, useAssistantRequest, type AnswerOutput } from '../../api/assistant';
import type { Catalog } from '../../api/types';
import SourceDetails from './SourceDetails';

export default function AssistantPanel({ owner, catalog, application }: { owner: string; catalog: Catalog; application?: { id: string; version: number } }) {
  const [question, setQuestion] = useState('');
  const [open, setOpen] = useState(false);
  const launcher = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open) heading.current?.focus({ preventScroll: true });
    else if (wasOpen.current) launcher.current?.focus({ preventScroll: true });
    wasOpen.current = open;
  }, [open]);
  function close() { setOpen(false); }
  const id = useId();
  const request = useAssistantRequest<AnswerOutput>(JSON.stringify([owner, application?.id, application?.version, question]));
  const examples = application ? ['Какую сумму я запросил?', 'Какие документы нужны?'] : ['Какие документы нужны для кредита на оборудование?', 'Что такое кредитная линия?'];
  return <div className="assistant-panel assistant-chat">
    <button type="button" className="assistant-launcher" ref={launcher} hidden={open} aria-expanded={open} aria-controls={`${id}-window`} onClick={() => setOpen(true)}><svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a9.5 9.5 0 0 1 19 0Z" /><path d="M7 10h10M7 14h6" /></svg>Помощник</button>
    {open && <div id={`${id}-window`} className="assistant-chat-window" role="dialog" aria-labelledby={`${id}-title`} onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); } }}>
      <header className="assistant-chat-heading">
        <span className="assistant-chat-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M20 11a8 8 0 0 1-8 8H5l-3 3V11a9 9 0 0 1 18 0Z" /><path d="M7 9h8M7 13h5" /></svg></span>
        <div><h2 id={`${id}-title`} ref={heading} tabIndex={-1}>Помощник по кредитам</h2><p>Продукты, документы и ваша заявка</p></div>
        <button type="button" className="assistant-close" aria-label="Закрыть помощника" onClick={close}><svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 6 12 12M18 6 6 18" /></svg></button>
      </header>
      <div className="assistant-body">
        {!request.result && !request.busy && !request.error && <div className="assistant-welcome"><p>Помогу разобраться в условиях и найти нужные сведения.</p><div className="assistant-examples" aria-label="Примеры вопросов">{examples.map(example => <button type="button" key={example} onClick={() => { setQuestion(example); input.current?.focus(); }}>{example}<span aria-hidden="true">↗</span></button>)}</div></div>}
        {request.busy && <p role="status" className="assistant-progress"><span aria-hidden="true" />Ищем ответ по доступным сведениям…</p>}
        {request.error && <p className="notice error" role="alert">{request.error}.</p>}
        {request.result && <div className="assistant-result" aria-live="polite"><p className="multiline">{request.result.answer}</p><SourceDetails sources={request.result.sources} catalog={catalog} /></div>}
      </div>
      <form className="assistant-composer" onSubmit={event => { event.preventDefault(); if (!request.busy && question.trim()) { void request.run(signal => askAssistant(question, application, signal)); input.current?.focus(); } }}>
        <label className="field" htmlFor={id}><span>Ваш вопрос</span><textarea ref={input} id={id} rows={2} value={question} onChange={event => setQuestion(event.target.value)} maxLength={2000} placeholder="О чём хотите узнать?" aria-describedby={`${id}-hint`} /></label>
        <div className="assistant-composer-footer"><p id={`${id}-hint`} className="muted">Каждый вопрос<br />рассматривается отдельно</p><button type="submit" className="button primary" disabled={request.busy || !question.trim()}>{request.busy ? 'Готовим ответ…' : 'Спросить'}<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 19V5m-6 6 6-6 6 6" /></svg></button></div>
      </form>
    </div>}
  </div>;
}
