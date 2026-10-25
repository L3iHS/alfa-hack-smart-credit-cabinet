import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../api/client';
import { askAssistant, type AnswerOutput, type HistoryPair } from '../../api/assistant';

interface Turn { id: number; question: string; pending?: boolean; result?: AnswerOutput; error?: string }
export function dialogHistory(turns: Turn[]): HistoryPair[] {
  const pairs = turns.filter(turn => turn.result?.status === 'answered' && turn.question.trim() && turn.question.length <= 2000 && turn.result.answer.trim() && turn.result.answer.length <= 6000).slice(-6).map(turn => ({ question: turn.question, answer: turn.result!.answer }));
  let length = pairs.reduce((sum, pair) => sum + pair.question.length + pair.answer.length, 0);
  // Исключаем целые старые пары: усечение текста может менять смысл продолжения.
  while (length > 12000) { const pair = pairs.shift()!; length -= pair.question.length + pair.answer.length; }
  return pairs;
}
export function useAssistantDialog(scope: string, application?: { id: string; version: number }) {
  const [state, setState] = useState<{ scope: string; turns: Turn[] }>({ scope, turns: [] });
  const current = useRef(scope); current.current = scope;
  const turns = useRef<Turn[]>([]);
  const sequence = useRef(0);
  const nextId = useRef(0);
  const active = useRef<AbortController | null>(null);
  function publish(value: Turn[]) { turns.current = value; setState({ scope, turns: value }); }
  function reset() { sequence.current++; active.current?.abort(); active.current = null; publish([]); }
  useEffect(() => {
    reset();
    window.addEventListener('credit-identity-changed', reset);
    return () => { sequence.current++; active.current?.abort(); active.current = null; window.removeEventListener('credit-identity-changed', reset); };
  }, [scope]);
  async function send(question: string, retryId?: number) {
    if (active.current || !question.trim()) return;
    const previous = turns.current;
    const index = retryId === undefined ? previous.length : previous.findIndex(turn => turn.id === retryId && !!turn.error);
    if (index < 0) return;
    const id = retryId ?? ++nextId.current;
    const turn: Turn = { id, question: question.trim(), pending: true };
    const history = application ? dialogHistory(previous.slice(0, index)) : [];
    publish(retryId === undefined ? [...previous, turn] : previous.map(item => item.id === id ? turn : item));
    const abort = new AbortController(); active.current = abort;
    const request = ++sequence.current;
    const valid = () => current.current === scope && request === sequence.current && !abort.signal.aborted;
    try {
      const result = await askAssistant(turn.question, application, abort.signal, history);
      if (valid()) publish(turns.current.map(item => item.id === id ? { ...turn, pending: false, result } : item));
    } catch (value) {
      if (!valid()) return;
      const error = value instanceof ApiError && value.status === 409 ? 'Заявка изменилась. Дождитесь обновления данных и повторите запрос' : value instanceof ApiError && value.status === 503 ? 'Помощник временно недоступен. Попробуйте позже' : value instanceof Error ? value.message.replace(/[.!?…]+\s*$/u, '') : 'Помощник временно недоступен. Попробуйте позже';
      // Утрата доступа или версии скрывает прежние ответы до обновления области.
      const retained = value instanceof ApiError && [401, 403, 404, 409].includes(value.status) ? turns.current.filter(item => item.id === id) : turns.current;
      publish(retained.map(item => item.id === id ? { ...turn, pending: false, error } : item));
    } finally { if (valid()) active.current = null; }
  }
  const visible = state.scope === scope ? state.turns : [];
  return { turns: visible, busy: visible.some(turn => turn.pending), send, reset };
}
