import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../api/client';
import type { AnalyticsSummary, Catalog, CounterofferPage, FunnelStage, ObservationCount, OfferOutcome } from '../api/types';
import { money, useResource } from '../components/shared';

import { reasonLabels } from "../analytics/labels";
import { AnalyticsHelpDialog, AnalyticsSectionHeading, type AnalyticsHelpTopic } from "../components/AnalyticsHelp";
const reportTimestamp = new Intl.DateTimeFormat('ru-RU', {timeZone: 'Europe/Moscow', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false});
function reportDateTime(value: string) { return reportTimestamp.format(new Date(value)); }
const outcomes: Record<OfferOutcome, string> = {
  accepted: 'Принято', declined: 'Отклонено', superseded: 'Заменено', no_response: 'Без ответа 3 дня',
  awaiting_response: 'Ожидает ответа', not_viewed: 'Просмотр не зафиксирован',
};
const stages: Record<FunnelStage['key'], string> = {opened: 'Открыли форму', draft_saved: 'Сохранили черновик', submitted: 'Отправили заявку', issued: 'Выставлены', viewed: 'Просмотрены', responded: 'Ответили', accepted: 'Приняты'};
const steps = {terms: 'Условия', finances: 'Финансы', documents: 'Документы', review: 'Проверка', not_observed: 'Раздел не зафиксирован'};
const changes = {amount_only: 'Только сумма', term_only: 'Только срок', amount_and_term: 'Сумма и срок', unchanged: 'Без изменений'};
const percent = (value: number | null) => value === null ? '—' : `${(value * 100).toLocaleString('ru-RU', {maximumFractionDigits: 1})}%`;
function Fraction({value}: {value: ObservationCount}) { if (!value.base) return <span className="analytics-empty-fraction">Нет данных</span>; return <span className="analytics-fraction">{value.count} из {value.base} <span>· {percent(value.share)}</span></span>; }
function Funnel({title, data, note, topic, onHelp}: {title: string; data: FunnelStage[]; note: string; topic: AnalyticsHelpTopic; onHelp: (topic: AnalyticsHelpTopic) => void}) {
  return <section className="panel analytics-funnel"><AnalyticsSectionHeading title={title} topic={topic} onHelp={onHelp} /><p className="analytics-unit">{note}</p>
    {!data[0]?.count ? <p className="analytics-empty">{topic === "form" ? "За выбранный период новые оформления не начинались." : "За выбранный период предложения не выставлялись."}</p> : <ol>{data.map((stage, index) => <li key={stage.key}>
      <div className="funnel-label"><span>{stages[stage.key]}</span><strong>{stage.count.toLocaleString('ru-RU')}</strong></div>
      <div className="funnel-track" aria-hidden="true"><span style={{width: `${Math.max(0, Math.min(100, (stage.share_from_first ?? 0) * 100))}%`}} /></div>
      <div className="funnel-caption"><span>{stage.count} из {stage.base_from_first} · {percent(stage.share_from_first)}</span>{index > 0 && <span>{stage.base_from_previous ? `От предыдущего: ${stage.count} из ${stage.base_from_previous} · ${percent(stage.share_from_previous)}` : "Для перехода пока нет данных"}</span>}</div>
    </li>)}</ol>}
  </section>;
}
function initialDates() {
  const now = new Date();
  const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit'}).format(now);
  const start = new Date(`${today}T12:00:00Z`); start.setUTCDate(start.getUTCDate() - 29);
  return {date_from: start.toISOString().slice(0, 10), date_to: today, product_code: ''};
}
function displayDate(iso: string) { return iso.split('-').reverse().join('.'); }
function filterDate(value: string): string | null {
  const match = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(value);
  if (!match) return null;
  const iso = `${match[3]}-${match[2]}-${match[1]}`;
  const parsed = new Date(`${iso}T12:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === iso ? iso : null;
}
export default function StaffAnalyticsPage() {
  const [help, setHelp] = useState<AnalyticsHelpTopic | null>(null);
  const [draft, setDraft] = useState(() => { const dates = initialDates(); return {...dates, date_from: displayDate(dates.date_from), date_to: displayDate(dates.date_to)}; });
  const [filterError, setFilterError] = useState('');
  const [filters, setFilters] = useState(initialDates);
  const [outcome, setOutcome] = useState(''); const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [rows, setRows] = useState<CounterofferPage | null>(null);
  const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const [tableLoading, setTableLoading] = useState(true); const [tableError, setTableError] = useState('');
  const summaryRequest = useRef(0); const rowsRequest = useRef(0);
  const previousSummaryQuery = useRef(''); const previousRowsQuery = useRef('');
  const catalog = useResource(() => api<Catalog>('/products'), 'analytics-products');
  const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value)).toString();
  useEffect(() => {
    const request = ++summaryRequest.current; const controller = new AbortController();
    setLoading(true); setError('');
    if (previousSummaryQuery.current !== query) setSummary(null);
    previousSummaryQuery.current = query;
    api<AnalyticsSummary>(`/analytics/summary?${query}`, {signal: controller.signal})
      .then(value => { if (request === summaryRequest.current) setSummary(value); })
      .catch(value => { if (!controller.signal.aborted && request === summaryRequest.current) setError(errorMessage(value)); })
      .finally(() => { if (request === summaryRequest.current) setLoading(false); });
    return () => { controller.abort(); summaryRequest.current++; };
  }, [query, revision]);
  useEffect(() => {
    const request = ++rowsRequest.current; const controller = new AbortController();
    setTableLoading(true); setTableError('');
    const selection = `${query}:${outcome}:${page}`;
    if (previousRowsQuery.current !== selection) setRows(null);
    previousRowsQuery.current = selection;
    api<CounterofferPage>(`/analytics/counteroffers?${query}&page=${page}&page_size=20${outcome ? `&outcome=${outcome}` : ''}`, {signal: controller.signal})
      .then(value => { if (request === rowsRequest.current) setRows(value); })
      .catch(value => { if (!controller.signal.aborted && request === rowsRequest.current) setTableError(errorMessage(value)); })
      .finally(() => { if (request === rowsRequest.current) setTableLoading(false); });
    return () => { controller.abort(); rowsRequest.current++; };
  }, [query, outcome, page, revision]);
  function apply(event: FormEvent) {
    event.preventDefault();
    const from = filterDate(draft.date_from); const to = filterDate(draft.date_to);
    if (!from || !to) { setFilterError('Укажите существующие даты в формате ДД.ММ.ГГГГ'); return; }
    const days = (new Date(`${to}T12:00:00Z`).getTime() - new Date(`${from}T12:00:00Z`).getTime()) / 86400000 + 1;
    if (days < 1 || days > 366) { setFilterError('Выберите период от 1 до 366 дней'); return; }
    setFilterError(''); setPage(1);
    const next = {...draft, date_from: from, date_to: to};
    setFilters(next); if (JSON.stringify(next) === JSON.stringify(filters)) setRevision(value => value + 1);
  }
  const productName = (code: string) => catalog.data?.items.find(item => item.code === code)?.name || code;
  return <div className="analytics-page">
    <div className="analytics-heading"><div><h1>Аналитика</h1><p>Оформление заявок и ответы на предложения</p></div><button className="button secondary" onClick={() => setRevision(value => value + 1)} disabled={loading || tableLoading}>Обновить</button></div>
    <form className="panel analytics-filters" onSubmit={apply} noValidate>
      <label className="field"><span>Период с</span><input aria-label="Период с" placeholder="ДД.ММ.ГГГГ" inputMode="numeric" maxLength={10} aria-invalid={!!filterError} aria-describedby={filterError ? "analytics-filter-error" : undefined} value={draft.date_from} onChange={event => setDraft({...draft, date_from: event.target.value})} /></label>
      <label className="field"><span>Период по</span><input aria-label="Период по" placeholder="ДД.ММ.ГГГГ" inputMode="numeric" maxLength={10} aria-invalid={!!filterError} aria-describedby={filterError ? "analytics-filter-error" : undefined} value={draft.date_to} onChange={event => setDraft({...draft, date_to: event.target.value})} /></label>
      <label className="field analytics-product"><span>Продукт</span><select aria-label="Продукт" value={draft.product_code} onChange={event => setDraft({...draft, product_code: event.target.value})}><option value="">Все продукты</option>{catalog.data?.items.map(item => <option key={item.code} value={item.code}>{item.name}</option>)}</select></label>
      <button className="button primary">Применить</button>
    </form>
    {filterError && <p className="notice error" id="analytics-filter-error" role="alert">{filterError}</p>}
    <div className="analytics-context"><p>Начало: {displayDate(summary?.metadata.date_from || filters.date_from)} — {displayDate(summary?.metadata.date_to || filters.date_to)} · результаты на {summary ? reportDateTime(summary.metadata.outcomes_as_of) : "момент отчёта"} · Москва</p><button type="button" className="analytics-help-trigger" aria-haspopup="dialog" onClick={() => setHelp('overview')}>Как считаем</button></div>
    {loading && <p className="analytics-loading" role="status">Обновляем воронки…</p>}
    {error && <div className="notice error" role="alert"><p>{error}</p><button className="button secondary" onClick={() => setRevision(value => value + 1)}>Повторить</button></div>}
    {summary && <>
      {summary.form_funnel[0]?.count === 0 && summary.offer_funnel[0]?.count === 0 && <div className="notice" role="status">За этот период наблюдений и предложений нет. Выберите другой период или продукт.</div>}
      <div className="analytics-funnels"><Funnel title="Оформление заявки" note="Уникальные попытки оформления" data={summary.form_funnel} topic="form" onHelp={setHelp} /><Funnel title="Предложения клиентам" note="Уникальные предложения · просмотр до ответа" data={summary.offer_funnel} topic="offers" onHelp={setHelp} /></div>
      <div className="analytics-breakdowns">
        <section className="panel analytics-breakdown"><AnalyticsSectionHeading title="Где остановились" topic="last_steps" onHelp={setHelp} /><p className="analytics-unit">Последний видимый раздел в неотправленных формах</p>{summary.last_steps[0]?.base ? <dl>{summary.last_steps.map(value => <div key={value.step}><dt>{steps[value.step]}</dt><dd><Fraction value={value} /></dd></div>)}</dl> : <p className="analytics-empty">Нет незавершённых оформлений за выбранный период.</p>}</section>
        <section className="panel analytics-breakdown"><AnalyticsSectionHeading title="Результаты предложений" topic="outcomes" onHelp={setHelp} /><p className="analytics-unit">Все предложения, включая ответы без записи просмотра</p>{summary.offer_funnel[0]?.count ? <><dl>{summary.offer_outcomes.map(value => <div key={value.outcome}><dt>{outcomes[value.outcome]}</dt><dd><Fraction value={value} /></dd></div>)}</dl><p className="analytics-footnote">Отказы после просмотра: <Fraction value={summary.declined_after_view} /></p></> : <p className="analytics-empty">Предложений для расчёта пока нет.</p>}</section>
      </div>
      <section className="panel analytics-coverage"><AnalyticsSectionHeading title="Полнота наблюдений" topic="coverage" onHelp={setHelp} /><p>Ответы вне воронки: <strong>{summary.response_coverage.responses_without_prior_view}</strong></p><div className="analytics-coverage-items"><span>Без зарегистрированного просмотра <strong>{summary.response_coverage.response_without_registered_view}</strong></span><span>Просмотр после ответа <strong>{summary.response_coverage.response_viewed_after_response}</strong></span><span>Время ответа неизвестно <strong>{summary.response_coverage.response_time_unknown}</strong></span></div></section>
      <div className="analytics-breakdowns">
        <section className="panel analytics-breakdown"><AnalyticsSectionHeading title="Изменения условий" topic="changes" onHelp={setHelp} /><p className="analytics-unit">Сколько принято в каждой группе предложений</p>{summary.offer_funnel[0]?.count ? <dl>{summary.condition_changes.map(value => <div key={value.change}><dt>{changes[value.change]}</dt><dd><Fraction value={{count: value.accepted, base: value.count, share: value.acceptance_share}} /></dd></div>)}</dl> : <p className="analytics-empty">Предложений для сравнения пока нет.</p>}</section>
        <section className="panel analytics-breakdown"><AnalyticsSectionHeading title="Причины отказа" topic="reasons" onHelp={setHelp} /><p className="analytics-unit">Причину выбирает клиент · доля среди всех отказов</p>{summary.decline_reasons[0]?.base ? <dl>{summary.decline_reasons.map(value => <div key={value.reason || 'none'}><dt>{value.reason ? reasonLabels[value.reason] : 'Без причины'}</dt><dd><Fraction value={value} /></dd></div>)}</dl> : <p className="analytics-empty">За выбранный период отказов нет.</p>}</section>
      </div>
    </>}
    <section className="panel analytics-offers"><div className="analytics-table-heading"><div><AnalyticsSectionHeading title="Контрпредложения" topic="counteroffers" onHelp={setHelp} /><p className="analytics-unit">Запрошенные и предложенные условия</p></div><label className="field analytics-outcome-filter"><select aria-label="Исход" value={outcome} onChange={event => {setOutcome(event.target.value); setPage(1);}}><option value="">Все исходы</option>{Object.entries(outcomes).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
      {tableLoading && <p role="status">Обновляем предложения…</p>}{tableError && <div className="notice error" role="alert">{tableError} <button className="button secondary" onClick={() => setRevision(value => value + 1)}>Повторить</button></div>}
      {rows && <><p className="analytics-total">Найдено: <strong>{rows.total}</strong></p>{!rows.items.length ? <p className="analytics-empty">Предложений с такими фильтрами нет</p> : <div className="analytics-table-scroll" role="region" aria-label="Условия контрпредложений" tabIndex={0}><table className="analytics-table"><thead><tr><th scope="col">Компания и продукт</th><th scope="col">Запрос → предложение</th><th scope="col">Платёж / комиссия</th><th scope="col">Результат</th><th scope="col">Даты</th></tr></thead><tbody>{rows.items.map(row => <tr key={row.id}>
        <td><Link to={`/staff/applications/${row.application_id}`}>{row.company_name}</Link><span>{productName(row.product_code)}</span><small>Заявка {row.application_id.slice(0, 8)}</small></td>
        <td><strong>{money(row.original_amount_kopecks)} → {money(row.amount_kopecks)}</strong><span>{row.original_term_months} → {row.term_months} мес.</span><small>Изменение суммы: {row.amount_delta_kopecks > 0 ? '+' : ''}{money(row.amount_delta_kopecks)}{row.amount_delta_percent === null ? '' : ` (${row.amount_delta_percent > 0 ? '+' : ''}${row.amount_delta_percent.toLocaleString('ru-RU', {maximumFractionDigits: 1})}%)`}</small><small>Изменение срока: {row.term_delta_months > 0 ? '+' : ''}{row.term_delta_months} мес.</small></td>
        <td>{row.payment_terms.payment_kind === 'guarantee' ? <><strong>Гарантия</strong><span>Комиссия {money(row.payment_terms.upfront_fee_kopecks)}</span><small>Расходы {money(row.payment_terms.total_cost_kopecks)}</small></> : <><strong>{row.payment_terms.payment_kind === 'revolving' ? 'Проценты в месяц' : 'Ежемесячный платёж'}</strong><span>{row.original_monthly_payment_kopecks === null ? '—' : money(row.original_monthly_payment_kopecks)} → {money(row.payment_terms.monthly_payment_kopecks)}</span>{row.payment_terms.payment_kind === 'revolving' && <small>Возврат лимита {money(row.payment_terms.principal_due_at_end_kopecks)}</small>}</>}</td>
        <td><span className={`analytics-outcome outcome-${row.outcome}`}>{outcomes[row.outcome]}</span>{row.outcome === 'declined' && <small>{row.decline_reason ? reasonLabels[row.decline_reason] : 'Без причины'}</small>}</td>
        <td><span>Выставлено {reportDateTime(row.created_at)}</span><small>Просмотр: {row.first_viewed_at ? reportDateTime(row.first_viewed_at) : 'не зафиксирован'}</small><small>Ответ: {row.responded_at ? reportDateTime(row.responded_at) : row.outcome === 'accepted' || row.outcome === 'declined' ? 'время неизвестно' : '—'}</small></td>
      </tr>)}</tbody></table></div>}
      <div className="analytics-pagination"><span>Страница {rows.page} из {Math.max(1, Math.ceil(rows.total / rows.page_size))}</span><div><button className="button secondary" disabled={page <= 1 || tableLoading} onClick={() => setPage(value => value - 1)}>Назад</button><button className="button secondary" disabled={page * rows.page_size >= rows.total || tableLoading} onClick={() => setPage(value => value + 1)}>Далее</button></div></div></>}
    </section>
    <AnalyticsHelpDialog topic={help} onClose={() => setHelp(null)} />
  </div>;
}
