import { useEffect, useId, useRef, useState } from 'react';
import { api, ApiError, errorMessage } from '../api/client';
import type { Application } from '../api/types';

export default function WithdrawalAction({ application, locked, lock, changed }: { application: Application; locked: boolean; lock: (value: boolean) => void; changed: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const active = useRef(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open) { dialog.current?.showModal(); cancel.current?.focus(); }
    else if (wasOpen.current) { dialog.current?.close(); trigger.current?.focus({ preventScroll: true }); }
    wasOpen.current = open;
  }, [open]);
  useEffect(() => () => lock(false), [lock]);
  if (!application.available_actions.includes('withdraw')) return null;
  function close() { if (!active.current) setOpen(false); }
  async function submit(refresh = false) {
    if (active.current || (!refresh && (conflict || saved))) return;
    active.current = true; setBusy(true); lock(true); setError('');
    try {
      if (!refresh) { await api<Application>(`/applications/${application.id}/withdraw`, { method: 'POST', body: { expected_version: application.version } }); setSaved(true); }
      await changed();
      if (refresh) { setConflict(false); if (saved) setOpen(false); }
      else setOpen(false);
    } catch (value) {
      setError(errorMessage(value));
      if (value instanceof ApiError && value.status === 409) setConflict(true);
    } finally { active.current = false; setBusy(false); lock(false); }
  }
  return <section className="withdrawal-action">
    <button ref={trigger} className="button secondary" disabled={locked} onClick={() => { setError(''); setOpen(true); }}>Отозвать заявку</button>
    <dialog ref={dialog} className="withdrawal-dialog" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} onCancel={event => { event.preventDefault(); close(); }} onKeyDown={event => {
      if (event.key !== 'Tab') return;
      const buttons = Array.from(dialog.current?.querySelectorAll<HTMLButtonElement>('button:not([disabled])') ?? []);
      const first = buttons[0], last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }}>
      <h2 id={`${id}-title`}>Отозвать заявку?</h2>
      <p id={`${id}-description`}>Банк прекратит рассмотрение. Документы и предыдущие результаты останутся в истории заявки.</p>
      {error && <p className="notice error" role="alert">{saved ? 'Отзыв сохранён. Не удалось обновить карточку. ' : ''}{error}{conflict ? '. Обновите сведения перед следующим действием.' : ''}</p>}
      {(conflict || saved) && <button className="button secondary" disabled={busy} onClick={() => void submit(true)}>Обновить сведения</button>}
      <div className="review-buttons">
        <button ref={cancel} className="button secondary" disabled={busy} onClick={close}>{saved ? 'Закрыть' : 'Продолжить рассмотрение'}</button>
        <button className="button primary" disabled={busy || conflict || saved} onClick={() => void submit()}>{busy ? 'Сохраняем…' : 'Отозвать заявку'}</button>
      </div>
    </dialog>
  </section>;
}
