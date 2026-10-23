import { useEffect, type RefObject } from 'react';
import { isObservationOwner, observeEvent, ApiError } from '../api/client';
import type { AnalyticsEvent, FormStep, ProductCode } from '../api/types';
import { readStored, writeStored } from '../components/useReviewCommand';

type Queued = {event: AnalyticsEvent; attempts: number};
type Journey = {id: string; lastStep: FormStep | null};
const memory = new Map<string, unknown>();
function get<T>(key: string, fallback: T): T { return readStored<T>(key, memory.get(key) as T ?? fallback); }
function put(key: string, value: unknown) { memory.set(key, value); writeStored(key, value); }
const prefix = (owner: string) => `credit-observations:v1:${owner}`;
const running = new Set<string>();
const timers = new Map<string, ReturnType<typeof setTimeout>>();
const controllers = new Map<string, AbortController>();
export function cancelObservations() {
  timers.forEach(clearTimeout); timers.clear();
  controllers.forEach(controller => controller.abort()); controllers.clear();
}
window.addEventListener('credit-identity-changed', cancelObservations);
function queue(owner: string, event: AnalyticsEvent) {
  if (!isObservationOwner(owner)) return;
  const key = `${prefix(owner)}:queue`;
  put(key, [...get<Queued[]>(key, []), {event, attempts: 0}].slice(-80));
  void flush(owner);
}
export async function flush(owner: string) {
  if (running.has(owner) || !isObservationOwner(owner)) return;
  running.add(owner);
  const key = `${prefix(owner)}:queue`;
  const controller = new AbortController(); controllers.set(owner, controller);
  try {
    while (isObservationOwner(owner) && !controller.signal.aborted) {
      const entries = get<Queued[]>(key, []);
      const head = entries[0];
      if (!head) break;
      if (head.attempts >= 3) { put(key, entries.slice(1)); continue; }
      head.attempts++; put(key, entries);
      try {
        await observeEvent(owner, head.event, controller.signal);
        if (controller.signal.aborted || !isObservationOwner(owner)) break;
        put(key, get<Queued[]>(key, []).filter(item => item.event.event_id !== head.event.event_id));
      } catch (error) {
        if (controller.signal.aborted || !isObservationOwner(owner)) break;
        const terminal = error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 429;
        if (terminal || head.attempts >= 3) {
          put(key, get<Queued[]>(key, []).filter(item => item.event.event_id !== head.event.event_id));
          continue;
        }
        timers.set(owner, setTimeout(() => { timers.delete(owner); void flush(owner); }, head.attempts * 1500));
        break;
      }
    }
  } finally { running.delete(owner); if (controllers.get(owner) === controller) controllers.delete(owner); }
}
export function beginJourney(owner: string, product: ProductCode): string {
  const key = `${prefix(owner)}:active`;
  let journey = get<Journey | null>(key, null);
  if (!journey) {
    journey = {id: crypto.randomUUID(), lastStep: null}; put(key, journey);
    queue(owner, {kind: 'form_opened', event_id: crypto.randomUUID(), journey_id: journey.id, product_code: product});
  } else void flush(owner);
  return journey.id;
}
export function linkedJourney(owner: string, application: string): string | null {
  void flush(owner);
  return get<Record<string, Journey>>(`${prefix(owner)}:linked`, {})[application]?.id ?? null;
}
export function linkJourney(owner: string, journeyId: string, application: string) {
  const activeKey = `${prefix(owner)}:active`;
  const active = get<Journey | null>(activeKey, null);
  const key = `${prefix(owner)}:linked`;
  const linked = get<Record<string, Journey>>(key, {});
  linked[application] = active?.id === journeyId ? active : {id: journeyId, lastStep: null};
  put(key, linked); if (active?.id === journeyId) put(activeKey, null);
  queue(owner, {kind: 'draft_linked', event_id: crypto.randomUUID(), journey_id: journeyId, application_id: application});
}
export function viewStep(owner: string, id: string, step: FormStep) {
  const activeKey = `${prefix(owner)}:active`;
  const linkedKey = `${prefix(owner)}:linked`;
  const active = get<Journey | null>(activeKey, null);
  const linked = get<Record<string, Journey>>(linkedKey, {});
  const journey = active?.id === id ? active : Object.values(linked).find(item => item.id === id);
  if (!journey || journey.lastStep === step) return;
  journey.lastStep = step; put(activeKey, active); put(linkedKey, linked);
  queue(owner, {kind: 'form_step_viewed', event_id: crypto.randomUUID(), journey_id: id, step});
}
export function viewOffer(owner: string, id: string, version: number) {
  const key = `${prefix(owner)}:offers`;
  const seen = get<string[]>(key, []);
  if (seen.includes(id)) { void flush(owner); return; }
  put(key, [...seen, id]);
  queue(owner, {kind: 'offer_viewed', event_id: crypto.randomUUID(), offer_id: id, offer_version: version});
}
export function useVisibleObservation(ref: RefObject<HTMLElement | null>, observe: (() => void) | null, key: string) {
  useEffect(() => {
    if (!observe || !ref.current) return;
    let visible = false;
    const record = () => { if (visible && document.visibilityState === 'visible') observe(); };
    const observer = new IntersectionObserver(entries => {
      visible = entries.some(entry => entry.isIntersecting && entry.intersectionRatio >= 0.2 && entry.boundingClientRect.width > 0 && entry.boundingClientRect.height > 0); record();
    }, {threshold: [0, 0.2]});
    observer.observe(ref.current); document.addEventListener('visibilitychange', record);
    return () => { observer.disconnect(); document.removeEventListener('visibilitychange', record); };
  }, [ref, key]);
}
