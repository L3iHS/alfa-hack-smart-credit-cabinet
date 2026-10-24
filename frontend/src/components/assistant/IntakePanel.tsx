import { useId, useState } from 'react';
import type { Catalog, FormValues } from '../../api/types';
import { analyzeIntake, useAssistantRequest, type IntakeOutput, type SuggestedFields } from '../../api/assistant';
import { money } from '../shared';

const labels: Record<keyof SuggestedFields, string> = { product_code: 'Продукт', amount_kopecks: 'Сумма', term_months: 'Срок', purpose: 'Цель финансирования' };
export default function IntakePanel({ catalog, values, owner, applicationKey, productLocked, onApply }: {
  catalog: Catalog; values: FormValues; owner: string; applicationKey: string; productLocked: boolean; onApply: (fields: SuggestedFields) => void;
}) {
  const [text, setText] = useState('');
  const id = useId();
  const request = useAssistantRequest<IntakeOutput>(JSON.stringify([owner, applicationKey, text, values, catalog.catalog_version]));
  const result = request.result;
  const keys = result && !result.unsupported_need ? (Object.keys(labels) as (keyof SuggestedFields)[]).filter(key => result.suggested_fields[key] !== null) : [];
  const incompatible = !!result && productLocked && result.suggested_fields.product_code !== null && result.suggested_fields.product_code !== values.product_code;
  function proposed(key: keyof SuggestedFields) {
    const value = result!.suggested_fields[key];
    if (key === 'product_code') return catalog.items.find(item => item.code === value)?.name;
    if (key === 'amount_kopecks') return money(value as number);
    if (key === 'term_months') return `${value} мес.`;
    return String(value);
  }
  function before(key: keyof SuggestedFields) {
    if (key === 'product_code') return catalog.items.find(item => item.code === values.product_code)?.name;
    if (key === 'amount_kopecks') return values[key] ? `${values[key]} ₽` : 'Не указана';
    if (key === 'term_months') return values[key] ? `${values[key]} мес.` : 'Не указан';
    return values[key] || 'Не указана';
  }
  return <details className="panel assistant-panel intake-panel">
    <summary>Опишите задачу</summary>
    <div className="assistant-body">
      <p className="muted">Расскажите, для чего нужно финансирование, укажите сумму и срок. Предложенные поля можно проверить перед подстановкой.</p>
      <label className="field" htmlFor={id}><span>Что нужно вашему бизнесу</span><textarea id={id} value={text} onChange={event => setText(event.target.value)} maxLength={6000} rows={3} placeholder="Например, купить две печи за 2 млн рублей" /></label>
      <div className="assistant-actions"><button type="button" className="button secondary" disabled={request.busy || !text.trim()} onClick={() => void request.run(signal => analyzeIntake(text, catalog, signal))}>{request.busy ? 'Разбираем описание…' : 'Разобрать описание'}</button></div>
      {request.busy && <p role="status" className="muted">Проверяем, какие поля можно предложить</p>}
      {request.error && <p className="notice error" role="alert">{request.error}. Вы можете заполнить форму самостоятельно.</p>}
      {result && <div className="assistant-result" aria-live="polite">
        {result.unsupported_need && <p>Эта потребность пока не поддерживается. Вы можете выбрать продукт и заполнить форму самостоятельно.</p>}
        {!!keys.length && <div className="intake-comparison" role="table" aria-label="Предлагаемые поля"><div className="intake-comparison-head" role="row"><span role="columnheader">Поле</span><span role="columnheader">Сейчас</span><span role="columnheader">Предлагается</span></div>{keys.map(key => <div className="intake-comparison-row" role="row" key={key}><strong role="rowheader">{labels[key]}</strong><span role="cell"><span className="intake-mobile-label">Сейчас: </span>{before(key)}</span><span role="cell"><span className="intake-mobile-label">Предлагается: </span>{proposed(key)}<small>Из описания: «{result.evidence[key]}»</small></span></div>)}</div>}
        {!!result.questions.length && <div><h3>Что нужно уточнить</h3><ul>{result.questions.map((question, index) => <li key={index}>{question}</li>)}</ul></div>}
        {incompatible && <p className="notice">Продукт отправленной заявки изменить нельзя. Уточните описание для выбранного продукта.</p>}
        {!!keys.length && !incompatible && <><p className="muted">Пустые предложения не изменят введённые данные. После подстановки проверьте форму и сохраните черновик.</p><div className="assistant-actions"><button type="button" className="button primary" onClick={() => onApply(result.suggested_fields)}>Применить к форме</button></div></>}
      </div>}
    </div>
  </details>;
}
