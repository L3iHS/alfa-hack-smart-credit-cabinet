import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './client';
import type { Catalog, ProductCode } from './types';

export interface SuggestedFields {
  product_code: ProductCode | null;
  amount_kopecks: number | null;
  term_months: number | null;
  purpose: string | null;
}
export interface IntakeOutput {
  suggested_fields: SuggestedFields;
  evidence: Partial<Record<keyof SuggestedFields, string>>;
  questions: string[];
  unsupported_need: boolean;
  catalog_version: string;
}
export interface Source { id: string; title: string; text: string; version: string }
export interface AnswerOutput {
  status: 'answered' | 'insufficient_context';
  answer: string;
  sources: Source[];
  application_version: number | null;
  generated_at?: string;
}
function invalid(): never {
  throw new ApiError(0, 'invalid_response', 'Не удалось прочитать ответ помощника. Попробуйте ещё раз');
}
function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === 'string');
}
export async function analyzeIntake(text: string, catalog: Catalog, signal: AbortSignal): Promise<IntakeOutput> {
  const value = await api<unknown>('/assistant/intake', { method: 'POST', body: { text, catalog_version: catalog.catalog_version }, signal });
  if (!object(value) || !object(value.suggested_fields) || !object(value.evidence) || !strings(value.questions) || typeof value.unsupported_need !== 'boolean' || value.catalog_version !== catalog.catalog_version) invalid();
  const fields = value.suggested_fields;
  if (fields.product_code !== null && !catalog.items.some(item => item.code === fields.product_code)) invalid();
  if (fields.amount_kopecks !== null && (typeof fields.amount_kopecks !== 'number' || !Number.isSafeInteger(fields.amount_kopecks) || fields.amount_kopecks < 0)) invalid();
  if (fields.term_months !== null && (typeof fields.term_months !== 'number' || !Number.isInteger(fields.term_months) || fields.term_months < 1 || fields.term_months > 120)) invalid();
  if (fields.purpose !== null && (typeof fields.purpose !== 'string' || !fields.purpose.trim() || fields.purpose.length > 2000)) invalid();
  for (const key of ['product_code', 'amount_kopecks', 'term_months', 'purpose'] as const) {
    if (fields[key] !== null && (typeof value.evidence[key] !== 'string' || !text.includes(value.evidence[key] as string) || !(value.evidence[key] as string).trim())) invalid();
  }
  return value as unknown as IntakeOutput;
}
async function answerRequest(path: string, body: unknown, version: number | null, signal: AbortSignal): Promise<AnswerOutput> {
  const value = await api<unknown>(path, { method: 'POST', body, signal });
  if (!object(value) || !['answered', 'insufficient_context'].includes(String(value.status)) || typeof value.answer !== 'string' || !value.answer.trim() || !Array.isArray(value.sources) || value.application_version !== version) invalid();
  if (!value.sources.every(source => object(source) && ['id', 'title', 'text', 'version'].every(key => typeof source[key] === 'string'))) invalid();
  if (value.status === 'answered' && !value.sources.length) invalid();
  if (value.generated_at !== undefined && (typeof value.generated_at !== 'string' || Number.isNaN(Date.parse(value.generated_at)))) invalid();
  return value as unknown as AnswerOutput;
}
export function askAssistant(question: string, application: { id: string; version: number } | undefined, signal: AbortSignal) {
  return answerRequest('/assistant/chat', { question, application_id: application?.id ?? null, expected_version: application?.version ?? null }, application?.version ?? null, signal);
}
export function summarizeApplication(id: string, version: number, signal: AbortSignal) {
  return answerRequest(`/applications/${id}/summary`, { expected_version: version }, version, signal);
}

// Ключ включает весь ввод и владельца. Даже ответ до выполнения cleanup не виден новому контексту.
export function useAssistantRequest<T>(scope: string) {
  const [state, setState] = useState<{ scope: string; result?: T; error?: string; busy: boolean } | null>(null);
  const current = useRef(scope);
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  current.current = scope;
  useEffect(() => {
    function invalidate() { sequence.current++; controller.current?.abort(); setState(null); }
    invalidate();
    window.addEventListener('credit-identity-changed', invalidate);
    return () => { sequence.current++; controller.current?.abort(); window.removeEventListener('credit-identity-changed', invalidate); };
  }, [scope]);
  async function run(request: (signal: AbortSignal) => Promise<T>) {
    controller.current?.abort();
    const abort = new AbortController(); controller.current = abort;
    const requestId = ++sequence.current;
    const valid = () => current.current === scope && sequence.current === requestId && !abort.signal.aborted;
    setState({ scope, busy: true });
    try {
      const result = await request(abort.signal);
      if (valid()) setState({ scope, result, busy: false });
    } catch (error) {
      if (valid()) setState({ scope, error: error instanceof ApiError && error.status === 409 ? 'Заявка изменилась. Дождитесь обновления данных и повторите запрос' : error instanceof ApiError && error.status === 503 ? 'Помощник временно недоступен. Попробуйте позже' : error instanceof Error ? error.message.replace(/[.!?…]+\s*$/u, '') : 'Помощник временно недоступен. Попробуйте позже', busy: false });
    }
  }
  return { busy: state?.scope === scope ? state.busy : false, result: state?.scope === scope ? state.result : undefined, error: state?.scope === scope ? state.error : undefined, run };
}
