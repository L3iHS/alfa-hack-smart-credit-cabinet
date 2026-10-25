import { useEffect, useId, useRef, useState } from 'react';
import { useAssistantDialog } from './useAssistantDialog';
import type { Catalog } from '../../api/types';
import AnswerContent from './AnswerContent';
import SourceDetails from './SourceDetails';
import { useAssistantSize } from './useAssistantSize';
import './assistant-usability.css';

export default function AssistantPanel({ owner, catalog, application }: { owner: string; catalog: Catalog; application?: { id: string; version: number; display_number?: string } }) {
  const sizing = useAssistantSize();
  const scope = JSON.stringify([owner, application?.id, application?.version]);
  const [draft, setDraft] = useState({ scope, text: '' });
  const question = draft.scope === scope ? draft.text : '';
  const [open, setOpen] = useState(false);
  const launcher = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(false);
  useEffect(() => {
    function clear() { setDraft({ scope, text: '' }); }
    clear();
    window.addEventListener('credit-identity-changed', clear);
    return () => window.removeEventListener('credit-identity-changed', clear);
  }, [scope]);
  useEffect(() => {
    if (open) heading.current?.focus({ preventScroll: true });
    else if (wasOpen.current) launcher.current?.focus({ preventScroll: true });
    wasOpen.current = open;
  }, [open]);
  function close() { setOpen(false); }
  const id = useId();
  const request = useAssistantDialog(scope, application);
  useEffect(() => { if (open && body.current) body.current.scrollTop = body.current.scrollHeight; }, [request.turns, open]);
  function setQuestion(text: string) { setDraft({ scope, text }); }
  function send(text: string, retryId?: number) {
    if (!text.trim() || request.busy) return;
    void request.send(text, retryId);
    if (retryId === undefined) setQuestion('');
    input.current?.focus();
  }
  function newDialog() { request.reset(); setQuestion(''); input.current?.focus(); }
  const examples = application ? ['Какую сумму я запросил?', 'Какие документы нужны?'] : ['Какие документы нужны для кредита на оборудование?', 'Что такое кредитная линия?'];
  return <div className="assistant-panel assistant-chat">
    <button type="button" className="assistant-launcher" ref={launcher} hidden={open} aria-expanded={open} aria-controls={`${id}-window`} onClick={() => setOpen(true)}><svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a9.5 9.5 0 0 1 19 0Z" /><path d="M7 10h10M7 14h6" /></svg>Помощник</button>
    {open && <div id={`${id}-window`} className="assistant-chat-window" style={sizing.style} role="dialog" aria-labelledby={`${id}-title`} onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); } }}>
      <div className="assistant-resize-handle" aria-hidden="true" title="Потяните уголок, чтобы изменить размер" {...sizing.pointer}><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M3 11 11 3M3 7l4-4" /></svg></div>
      <header className="assistant-chat-heading">
        <span className="assistant-chat-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M20 11a8 8 0 0 1-8 8H5l-3 3V11a9 9 0 0 1 18 0Z" /><path d="M7 9h8M7 13h5" /></svg></span>
        <div><h2 id={`${id}-title`} ref={heading} tabIndex={-1}>Помощник по кредитам</h2><p>{application ? application.display_number ? `По заявке № ${application.display_number}` : 'По текущей заявке' : 'По продуктам и документам'}</p></div>
        <button type="button" className="assistant-size-toggle assistant-close" aria-label={sizing.customized ? 'Вернуть обычный размер помощника' : 'Развернуть помощника'} title={sizing.customized ? 'Обычный размер' : 'Развернуть'} onClick={sizing.toggle}><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">{sizing.customized ? <path d="M9 3v6H3m18 6h-6v6M9 9 3 3m12 12 6 6" /> : <path d="M3 9V3h6m6 18h6v-6M3 3l6 6m6 6 6 6" />}</svg></button>
        <button type="button" className="assistant-close" aria-label="Закрыть помощника" onClick={close}><svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 6 12 12M18 6 6 18" /></svg></button>
      </header>
      <div className="assistant-body" ref={body}>
        {!request.turns.length && <div className="assistant-welcome"><p>{application ? 'Помогу разобраться в условиях и сохранённых сведениях заявки.' : 'Помогу разобраться в условиях. Для вопросов о своей заявке откройте её карточку.'}</p><div className="assistant-examples" aria-label="Примеры вопросов">{examples.map(example => <button type="button" key={example} onClick={() => { setQuestion(example); input.current?.focus(); }}>{example}<span aria-hidden="true">↗</span></button>)}</div></div>}
        {request.turns.map(turn => <article className="assistant-turn" key={turn.id}>
          <div className="assistant-question" role="group" aria-label="Ваше сообщение"><span>Вы</span><p>{turn.question}</p></div>
          {turn.pending && <p role="status" className="assistant-progress"><span aria-hidden="true" />Ищем ответ по доступным сведениям…</p>}
          {turn.error && <div className="assistant-chat-error"><p className="notice error" role="alert">{turn.error}.</p><button type="button" className="button secondary" disabled={request.busy} onClick={() => send(turn.question, turn.id)}>Повторить вопрос</button></div>}
          {turn.result && <div className="assistant-result" aria-live="polite"><AnswerContent text={turn.result.answer} /><SourceDetails sources={turn.result.sources} catalog={catalog} /></div>}
        </article>)}
      </div>
      <form className="assistant-composer" onSubmit={event => { event.preventDefault(); send(question); }}>
        <label className="field" htmlFor={id}><span className="assistant-visually-hidden">Ваш вопрос</span><textarea ref={input} id={id} rows={2} value={question} onChange={event => setQuestion(event.target.value)} maxLength={2000} placeholder="О чём хотите узнать?" aria-describedby={`${id}-hint`} /></label>
        <div className="assistant-composer-footer"><div><p id={`${id}-hint`} className="muted">{application ? 'В контексте этой заявки' : 'По справочнику продуктов'}</p><button type="button" className="assistant-new-dialog" onClick={newDialog}>Новый диалог</button></div><button type="submit" className="button primary" disabled={request.busy || !question.trim()}>{request.busy ? 'Готовим ответ…' : 'Спросить'}<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 19V5m-6 6 6-6 6 6" /></svg></button></div>
      </form>
    </div>}
  </div>;
}
