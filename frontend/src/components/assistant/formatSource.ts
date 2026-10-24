import type { Catalog } from '../../api/types';
import { documentLabels } from '../ApplicationDocuments';
import { date, dateTime, money, statusLabels } from '../shared';

const labels: Record<string, string> = {
  product_code: 'Продукт', purpose: 'Цель финансирования', description: 'Дополнительное описание',
  amount_kopecks: 'Сумма', term_months: 'Срок, месяцев', period_start: 'Начало периода', period_end: 'Конец периода',
  revenue_kopecks: 'Выручка', operating_expenses_kopecks: 'Операционные расходы', existing_debt_payments_kopecks: 'Платежи по кредитам',
  tender_number: 'Номер тендера', beneficiary_name: 'Заказчик по тендеру', project_description: 'Описание проекта',
  status: 'Состояние', processing_status: 'Обработка', public_reasons: 'Основания', available_actions: 'Доступные действия',
  message: 'Сообщение', requested_fields: 'Запрошенные сведения', requested_document_types: 'Запрошенные документы',
  reason: 'Основание', version: 'Версия', annual_rate_bps: 'Ставка, % годовых', annual_commission_bps: 'Комиссия, % годовых',
  monthly_payment_kopecks: 'Ежемесячный платёж', total_payment_kopecks: 'Всего к выплате', payment_terms: 'Условия платежей',
  upfront_fee_kopecks: 'Разовая комиссия', principal_due_at_end_kopecks: 'Возврат в конце срока', last_payment_kopecks: 'Последний платёж',
  total_cost_kopecks: 'Стоимость финансирования', assessment_monthly_burden_kopecks: 'Нагрузка для оценки', contingent_liability_kopecks: 'Условное обязательство',
  payment_kind: 'Вид платежей', assumptions: 'Допущения расчёта', name: 'Название компании', inn: 'ИНН', industry: 'Отрасль', registered_at: 'Дата регистрации',
  application: 'Отправленные данные', note: 'Пояснение', document_types: 'Представленные документы', missing_document_types: 'Недостающие документы', content_read: 'Содержимое прочитано',
  data: 'Сохранённые сведения', results: 'Результаты проверок', registry: 'Реестр компаний', tax: 'Налоговые сведения', bki: 'Кредитная история', missing_checks: 'Отсутствующие проверки',
  liquidated: 'Компания ликвидирована', expected_monthly_revenue_kopecks: 'Ожидаемая месячная выручка', overdue_days: 'Дней просрочки',
  months: 'Месяцев в периоде', monthly_revenue_kopecks: 'Выручка в месяц', monthly_operating_expenses_kopecks: 'Расходы в месяц', monthly_debt_kopecks: 'Долговые платежи в месяц',
  available_flow_kopecks: 'Доступный денежный поток', coverage_ratio: 'Покрытие платежа', financial_gate: 'Финансовые условия', allowed: 'Условия соблюдены',
  guarantee_fee_affordable: 'Комиссия по силам компании', guarantee_liability_within_limit: 'Обязательство в пределах лимита', available_after_debt_kopecks: 'Остаток после долговых платежей', guarantee_liability_limit_kopecks: 'Лимит обязательства',
  outcome: 'Сохранённый результат', internal_reason: 'Основание сотруднику', probability: 'Вероятность просрочки', risk_band: 'Уровень риска',
  terms: 'Оценённые условия', top_increasing_factors: 'Повышают оценку', top_decreasing_factors: 'Снижают оценку', contributions: 'Линейные вклады', label: 'Фактор', contribution: 'Вклад в логарифм шансов',
  base_value: 'Базовое значение, логарифм шансов', raw_prediction: 'Прогноз до преобразования', horizon_months: 'Горизонт оценки, месяцев',
  created_at: 'Создано', started_at: 'Начало', finished_at: 'Завершено',
  money: 'Денежные величины', rates: 'Ставки', missing: 'Отсутствие сведений',
};
const values: Record<string, string> = {
  ...statusLabels, ...documentLabels, available: 'Доступно', missing: 'Сведений нет', technical_failure: 'Технический сбой',
  succeeded: 'Выполнено', failed: 'Технический сбой', interrupted: 'Прервано', pending: 'Ожидает обработки', running: 'Выполняется', not_applicable: 'Не применяется',
  active: 'Действует', accepted: 'Принято клиентом', declined: 'Отклонено клиентом', superseded: 'Заменено', open: 'Открыт', answered: 'Ответ получен',
  low: 'Низкий', elevated: 'Повышенный', high: 'Высокий', annuity: 'Аннуитет', revolving: 'Лимит с возвратом в конце срока', guarantee: 'Гарантия',
  upload_document: 'Добавить документ', respond_information: 'Ответить на запрос', make_offer: 'Предложить условия', edit_draft: 'Редактировать', submit: 'Отправить заявку', respond_to_information_request: 'Ответить на запрос', accept_offer: 'Принять условия', decline_offer: 'Отклонить условия',
  request_information: 'Запросить сведения', create_offer: 'Предложить условия', approve: 'Одобрить', reject: 'Отказать', retry_processing: 'Повторить обработку',
  registry: 'Реестр компаний', tax: 'Налоговые сведения', bki: 'Кредитная история',
};
const codeKeys = new Set(['status', 'processing_status', 'outcome', 'payment_kind', 'risk_band', 'available_actions', 'requested_fields', 'document_types', 'missing_document_types', 'requested_document_types', 'missing_checks']);
export interface SourceRow { label: string; value: string }
export function formatSource(text: string, catalog: Catalog): { text?: string; rows?: SourceRow[] } {
  let parsed: unknown;
  try { parsed = JSON.parse(text); } catch { return { text: /^[{\[]/.test(text.trim()) ? 'Не удалось прочитать сведения источника' : text }; }
  if (!parsed || typeof parsed !== 'object') return { text: 'Нет доступных сведений для отображения' };
  const rows: SourceRow[] = [];
  function visit(key: string, value: unknown, prefix: string, depth: number) {
    const label = labels[key];
    if (!label || depth > 8) return;
    const title = prefix ? `${prefix} / ${label}` : label;
    if (Array.isArray(value)) {
      if (!value.length) rows.push({ label: title, value: 'Нет' });
      else value.forEach(item => visit(key, item, prefix, depth + 1));
    } else if (value && typeof value === 'object') {
      Object.entries(value).forEach(([child, item]) => visit(child, item, title, depth + 1));
    } else {
      let formatted = value === null ? 'Не указано' : typeof value === 'boolean' ? value ? 'Да' : 'Нет' : String(value);
      if (value !== null) {
        if (key.endsWith('_kopecks')) {
          const amount = Number(value);
          formatted = Number.isSafeInteger(amount) ? `${amount < 0 ? "−" : ""}${money(Math.abs(amount))}` : Number.isFinite(amount) && Math.abs(amount) <= Number.MAX_SAFE_INTEGER ? `${(amount / 100).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} ₽` : 'Не удалось отобразить сумму';
        } else if (key.endsWith('_bps') && typeof value === 'number') formatted = `${(value / 100).toLocaleString('ru-RU')}%`;
        else if (key === 'probability' && typeof value === 'number') formatted = `${(value * 100).toLocaleString('ru-RU', { maximumFractionDigits: 4 })}%`;
        else if (key === 'product_code') formatted = catalog.items.find(item => item.code === value)?.name || 'Продукт не найден в каталоге';
        else if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) formatted = date(value);
        else if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value)) formatted = dateTime(value);
        else if (codeKeys.has(key)) formatted = values[String(value)] || labels[String(value)] || 'Нет доступного описания';
      }
      rows.push({ label: title, value: formatted });
    }
  }
  if (Array.isArray(parsed)) return { text: 'Нет доступных сведений для отображения' };
  Object.entries(parsed).forEach(([key, value]) => visit(key, value, '', 0));
  return rows.length ? { rows } : { text: 'Нет доступных сведений для отображения' };
}
