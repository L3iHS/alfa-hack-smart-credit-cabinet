# Правила рекомендации кредитных продуктов для МСБ

Документ описывает подбор кредитного продукта в «Умном кредитном кабинете»: слои правил, формат конфигов, примеры продуктов, структуру ответа и тесты. Все числа синтетические и подобраны для демонстрации, это не реальные параметры банка.

---

## 1. Принципы

1. **Правила в конфигах, а не в коде.** Продукт описывается YAML-файлом. Чтобы поменять порог, код не трогают.
2. **Детерминизм.** Одни и те же входные данные всегда дают один и тот же результат. Это упрощает тесты и защиту перед жюри.
3. **Подбор отделён от скоринга.** Подбор отвечает на вопрос «какие продукты вообще подходят под задачу». Скоринг и кредитное решение отвечают на вопрос «на каких условиях банк готов дать деньги». Подбор можно запускать с неполными данными, решение нужно только после подачи заявки.
4. **Исход небинарен.** Правило может не только отсечь продукт, но и предложить корректировку: уменьшить сумму, сменить срок, запросить документ, предложить другой продукт.
5. **У каждого правила два объяснения.** Клиентское (понятное и действенное) и служебное (с точными порогами и значениями). LLM только оформляет готовый текст и не принимает решений.
6. **Правила не раскрывают пороги клиенту.** Клиент видит «что сделать», сотрудник видит «какое правило и с каким значением сработало».

---

## 2. Конвейер подбора

```
Ввод клиента (форма или чат-помощник)
        │
        ▼
[L0] Нормализация и валидация входа
        │
        ▼
[L1] Eligibility: жёсткие фильтры допуска
        │
        ▼
[L2] Соответствие потребности (цель, сумма, срок, обеспечение)
        │
        ▼
[L3] Финансовая реалистичность (оценка по выручке и нагрузке)
        │
        ▼
[L4] Мягкие исходы: корректировка условий / запрос данных
        │
        ▼
[L5] Ранжирование оставшихся продуктов → топ 1–3
        │
        ▼
Ответ: список продуктов + причины + что можно улучшить
```

Каждый слой возвращает для каждого продукта одно из состояний:

| Состояние | Смысл |
|---|---|
| `PASS` | правило выполнено |
| `FAIL_HARD` | продукт исключён |
| `FAIL_ADJUSTABLE` | не выполнено, но есть корректировка (меньше сумма, другой срок) |
| `MISSING_DATA` | не хватает данных, чтобы проверить правило |

---

## 3. Входные данные

### 3.1. Анкета клиента (вводит пользователь)

| Поле | Пример | Обязательно для подбора |
|---|---|---|
| `purpose` | `working_capital`, `equipment`, `cash_gap`, `investment`, `tender_guarantee`, `real_estate` | да |
| `amount` | 1 500 000 | да |
| `term_months` | 12 | да |
| `has_collateral` | `true` / `false` | нет |
| `collateral_type` | `equipment`, `real_estate`, `none` | нет |
| `urgency` | `high` / `normal` | нет |

### 3.2. Профиль бизнеса (из анкеты и обогащения)

| Поле | Источник (мок) |
|---|---|
| `client_type` (`IP`/`OOO`), `tax_regime` | анкета |
| `inn`, `okved` | анкета + мок ЕГРЮЛ/ЕГРИП |
| `registration_date` → `business_age_months` | мок ЕГРЮЛ |
| `egrul_status` (`active`, `liquidating`, `bankrupt`) | мок ЕГРЮЛ |
| `mass_address_flag`, `director_disqualified_flag` | мок «Прозрачный бизнес» |
| `annual_revenue`, `avg_monthly_turnover`, `net_profit` | анкета или загруженная отчётность |
| `existing_debt_payments_monthly`, `overdue_flag`, `credit_history_score` | мок БКИ |

### 3.3. Производные показатели

```
amount_to_revenue   = amount / annual_revenue
monthly_payment     = annuity(amount, rate, term_months)
payment_to_turnover = monthly_payment / avg_monthly_turnover
dti                 = (existing_debt_payments_monthly + monthly_payment) / avg_monthly_turnover
```

Если для расчёта не хватает данных (нет выручки), правило получает `MISSING_DATA`, а не ложный `PASS`.

---

## 4. Слои правил

### L0. Валидация входа

- Сумма и срок положительные, срок в допустимых единицах.
- ИНН проходит контрольную сумму (10 цифр для ООО, 12 для ИП).
- Цель входит в справочник.
- Нормализация: срок в днях приводится к месяцам, сумма к рублям.

Ошибки L0 возвращаются в форму, до подбора дело не доходит.

### L1. Eligibility: жёсткие фильтры допуска

Отвечают на вопрос «имеет ли клиент право на продукт вообще». Не зависят от запрошенной суммы.

| Правило | Пример |
|---|---|
| Тип клиента | овердрафт доступен `IP` и `OOO` |
| Возраст бизнеса | `business_age_months >= 6` |
| Статус в реестре | `egrul_status == active` |
| Исключённые ОКВЭД | игорный бизнес, ломбарды, микрофинансы |
| Стоп-факторы | массовый адрес, дисквалификация руководителя, текущая просрочка более 30 дней |
| Налоговый режим | отдельные продукты только для УСН или ОСНО |

Все правила L1 по умолчанию `hard`: нарушение исключает продукт.

### L2. Соответствие потребности

Проверяет, подходит ли продукт под задачу.

**Цель → допустимые продукты (справочник):**

| Цель | Продукты |
|---|---|
| `working_capital` | кредит на оборотные средства, кредитная линия |
| `cash_gap` | овердрафт, кредитная линия |
| `equipment` | кредит на оборудование |
| `investment` / `real_estate` | инвестиционный кредит |
| `tender_guarantee` | банковская гарантия |

**Параметры:**

- Попадание суммы в диапазон продукта `[min, max]`.
- Попадание срока в диапазон продукта.
- Требование обеспечения: `required`, `optional`, `none`.
- Для целевого продукта нужен документ-основание (счёт, договор поставки). Если его нет, правило даёт `MISSING_DATA`.

Вне диапазона по сумме или сроку правило помечается `FAIL_ADJUSTABLE` и приводит к предложению в L4.

### L3. Финансовая реалистичность

Грубая оценка до полного скоринга: нет смысла предлагать клиенту то, что он явно не потянет.

- `amount_to_revenue <= лимит продукта` (например, 0.3 для овердрафта).
- `payment_to_turnover <= лимит` (например, 0.25).
- `dti <= лимит` (например, 0.5).
- Выручка положительная и стабильная (при наличии данных за несколько периодов: просадка не более X%).

### L4. Мягкие исходы

Если есть `FAIL_ADJUSTABLE` или `MISSING_DATA`, движок строит исход вместо отказа:

| Ситуация | Исход (`outcome`) |
|---|---|
| Сумма выше лимита по выручке | `COUNTER_OFFER`: «Можем предложить до {max_amount}» |
| Срок вне диапазона | `COUNTER_OFFER`: другой срок |
| Нужен залог, а его нет | `ALTERNATIVE_PRODUCT` без залога или `REQUEST_COLLATERAL` |
| Не хватает выручки или отчётности | `REQUEST_DATA`: список недостающих документов |
| Все продукты исключены | `NO_MATCH`: общая причина и что можно улучшить |

Контрпредложение пересчитывается и проходит L2–L3 повторно, чтобы не предложить то, что не пройдёт проверку.

### L5. Ранжирование

Для продуктов, прошедших проверки, считается взвешенный балл:

```
score = w_purpose   * purpose_match
      + w_fit       * amount_term_fit
      + w_cost      * cost_score
      + w_approval  * approval_likelihood
      + w_speed     * speed_score
```

| Компонент | Как считается |
|---|---|
| `purpose_match` | 1.0 — основная цель продукта, 0.6 — допустимая альтернатива |
| `amount_term_fit` | близость суммы и срока к «центру» диапазона продукта, от 0 до 1 |
| `cost_score` | 1 − нормированная годовая стоимость кредита (ставка + комиссии) |
| `approval_likelihood` | 1 − нормированный предварительный риск (лёгкая версия скоринга) |
| `speed_score` | 1.0 при высокой срочности и быстром продукте (овердрафт), иначе нейтрально |

Веса хранятся в конфиге и могут зависеть от `urgency`. Клиенту показываются 1–3 лучших продукта. Если разница баллов меньше порога, второй продукт тоже выводится как альтернатива.

---

## 5. Формат конфигов

Структура репозитория:

```
config/
  rules/
    products.yaml          # каталог продуктов
    purpose_map.yaml       # цель → продукты
    ranking.yaml           # веса ранжирования
    reasons.yaml           # reason codes и тексты
    stop_factors.yaml      # общие стоп-факторы и исключённые ОКВЭД
```

### 5.1. Общие стоп-факторы (`stop_factors.yaml`)

```yaml
global_stop_factors:
  - id: STOP_LIQUIDATION
    field: egrul_status
    op: eq
    value: active
    on_fail: reject_product
    reason_code: R_BUSINESS_NOT_ACTIVE

  - id: STOP_MASS_ADDRESS
    field: mass_address_flag
    op: eq
    value: false
    on_fail: reject_product
    reason_code: R_ADDRESS_CHECK

  - id: STOP_ACTIVE_OVERDUE
    field: max_overdue_days
    op: lte
    value: 30
    on_fail: reject_product
    reason_code: R_OVERDUE

excluded_okved_prefixes:
  - "92."    # азартные игры
  - "64.92"  # микрофинансовая деятельность
  - "64.99"  # прочие финансовые услуги
```

### 5.2. Каталог продуктов (`products.yaml`)

Общая схема описания продукта:

```yaml
- id: <уникальный идентификатор>
  name: <название для клиента>
  type: <loan | credit_line | overdraft | guarantee>
  purposes: [...]            # основные цели
  alt_purposes: [...]        # допустимые альтернативные цели
  eligibility: [...]         # L1
  needs: [...]               # L2
  financial_limits: [...]    # L3
  pricing: {...}             # условия для расчёта платежа и стоимости
  adjustments: [...]         # L4: что предлагать при частичном несоответствии
```

Каждое правило имеет единый вид:

```yaml
- id: <идентификатор>
  field: <поле профиля или производный показатель>
  op: <eq | ne | gte | lte | between | in | not_in | not_prefix>
  value: <значение или список>
  on_fail: <reject_product | adjust | request_data>
  reason_code: <ключ из reasons.yaml>
```

#### Овердрафт

```yaml
- id: overdraft_smb
  name: "Овердрафт"
  type: overdraft
  purposes: [cash_gap]
  alt_purposes: [working_capital]

  eligibility:
    - {id: OD_CLIENT_TYPE, field: client_type, op: in, value: [IP, OOO], on_fail: reject_product, reason_code: R_CLIENT_TYPE}
    - {id: OD_AGE, field: business_age_months, op: gte, value: 6, on_fail: reject_product, reason_code: R_BUSINESS_AGE}
    - {id: OD_OKVED, field: okved, op: not_prefix, value: ["92.", "64.92"], on_fail: reject_product, reason_code: R_OKVED_EXCLUDED}

  needs:
    - {id: OD_AMOUNT, field: amount, op: between, value: [100000, 3000000], on_fail: adjust, reason_code: R_AMOUNT_RANGE}
    - {id: OD_TERM, field: term_days, op: lte, value: 90, on_fail: adjust, reason_code: R_TERM_TOO_LONG}
    - {id: OD_COLLATERAL, field: has_collateral, op: in, value: [true, false], on_fail: reject_product, reason_code: R_COLLATERAL}

  financial_limits:
    - {id: OD_REV_RATIO, field: amount_to_revenue, op: lte, value: 0.30, on_fail: adjust, reason_code: R_AMOUNT_TO_REVENUE}
    - {id: OD_DTI, field: dti, op: lte, value: 0.50, on_fail: adjust, reason_code: R_DEBT_LOAD}
    - {id: OD_TURNOVER_DATA, field: avg_monthly_turnover, op: exists, on_fail: request_data, reason_code: R_NEED_TURNOVER}

  pricing:
    base_rate: 0.21          # годовая ставка
    fee_pct: 0.0
    approval_hours: 4

  adjustments:
    - when: OD_AMOUNT
      action: cap_amount
      to: max_allowed        # min(лимит продукта, лимит по выручке)
    - when: OD_TERM
      action: suggest_product
      product_id: credit_line_smb
```

#### Кредит на оборотные средства

```yaml
- id: working_capital_loan
  name: "Кредит на оборотные средства"
  type: loan
  purposes: [working_capital]
  alt_purposes: [cash_gap]

  eligibility:
    - {id: WC_CLIENT_TYPE, field: client_type, op: in, value: [IP, OOO], on_fail: reject_product, reason_code: R_CLIENT_TYPE}
    - {id: WC_AGE, field: business_age_months, op: gte, value: 12, on_fail: reject_product, reason_code: R_BUSINESS_AGE}

  needs:
    - {id: WC_AMOUNT, field: amount, op: between, value: [300000, 10000000], on_fail: adjust, reason_code: R_AMOUNT_RANGE}
    - {id: WC_TERM, field: term_months, op: between, value: [6, 36], on_fail: adjust, reason_code: R_TERM_RANGE}
    - id: WC_UNSECURED_CAP
      field: amount
      op: lte
      value: 3000000
      when: {has_collateral: false}        # условное правило
      on_fail: adjust
      reason_code: R_NEED_COLLATERAL_FOR_AMOUNT

  financial_limits:
    - {id: WC_REV_RATIO, field: amount_to_revenue, op: lte, value: 0.40, on_fail: adjust, reason_code: R_AMOUNT_TO_REVENUE}
    - {id: WC_PAYMENT, field: payment_to_turnover, op: lte, value: 0.25, on_fail: adjust, reason_code: R_PAYMENT_BURDEN}
    - {id: WC_DTI, field: dti, op: lte, value: 0.50, on_fail: adjust, reason_code: R_DEBT_LOAD}
    - {id: WC_REVENUE_DATA, field: annual_revenue, op: exists, on_fail: request_data, reason_code: R_NEED_REVENUE}

  pricing:
    base_rate: 0.19
    rate_discount_if_collateral: 0.02
    fee_pct: 0.01
    approval_hours: 24

  adjustments:
    - {when: WC_UNSECURED_CAP, action: offer_two_options, options: [cap_amount_unsecured, request_collateral]}
    - {when: WC_REV_RATIO, action: cap_amount, to: max_allowed}
    - {when: WC_TERM, action: clamp_term}
```

#### Кредитная линия

```yaml
- id: credit_line_smb
  name: "Кредитная линия"
  type: credit_line
  purposes: [working_capital, cash_gap]
  alt_purposes: []

  eligibility:
    - {id: CL_CLIENT_TYPE, field: client_type, op: in, value: [IP, OOO], on_fail: reject_product, reason_code: R_CLIENT_TYPE}
    - {id: CL_AGE, field: business_age_months, op: gte, value: 12, on_fail: reject_product, reason_code: R_BUSINESS_AGE}
    - {id: CL_HISTORY, field: credit_history_score, op: gte, value: 400, on_fail: reject_product, reason_code: R_CREDIT_HISTORY}

  needs:
    - {id: CL_AMOUNT, field: amount, op: between, value: [500000, 15000000], on_fail: adjust, reason_code: R_AMOUNT_RANGE}
    - {id: CL_TERM, field: term_months, op: between, value: [6, 24], on_fail: adjust, reason_code: R_TERM_RANGE}

  financial_limits:
    - {id: CL_REV_RATIO, field: amount_to_revenue, op: lte, value: 0.35, on_fail: adjust, reason_code: R_AMOUNT_TO_REVENUE}
    - {id: CL_DTI, field: dti, op: lte, value: 0.50, on_fail: adjust, reason_code: R_DEBT_LOAD}

  pricing:
    base_rate: 0.20
    fee_pct: 0.005
    commitment_fee_on_unused: 0.01
    approval_hours: 48
```

#### Кредит на оборудование

```yaml
- id: equipment_loan
  name: "Кредит на оборудование"
  type: loan
  purposes: [equipment]
  alt_purposes: []

  eligibility:
    - {id: EQ_CLIENT_TYPE, field: client_type, op: in, value: [IP, OOO], on_fail: reject_product, reason_code: R_CLIENT_TYPE}
    - {id: EQ_AGE, field: business_age_months, op: gte, value: 12, on_fail: reject_product, reason_code: R_BUSINESS_AGE}

  needs:
    - {id: EQ_AMOUNT, field: amount, op: between, value: [500000, 30000000], on_fail: adjust, reason_code: R_AMOUNT_RANGE}
    - {id: EQ_TERM, field: term_months, op: between, value: [12, 60], on_fail: adjust, reason_code: R_TERM_RANGE}
    - {id: EQ_DOCS, field: supplier_invoice_attached, op: eq, value: true, on_fail: request_data, reason_code: R_NEED_INVOICE}
    - {id: EQ_DOWNPAYMENT, field: down_payment_pct, op: gte, value: 0.10, on_fail: adjust, reason_code: R_DOWN_PAYMENT}

  financial_limits:
    - {id: EQ_PAYMENT, field: payment_to_turnover, op: lte, value: 0.30, on_fail: adjust, reason_code: R_PAYMENT_BURDEN}
    - {id: EQ_DTI, field: dti, op: lte, value: 0.55, on_fail: adjust, reason_code: R_DEBT_LOAD}

  pricing:
    base_rate: 0.17
    collateral: purchased_equipment     # залог приобретаемого оборудования
    fee_pct: 0.01
    approval_hours: 48
```

#### Инвестиционный кредит

```yaml
- id: investment_loan
  name: "Инвестиционный кредит"
  type: loan
  purposes: [investment, real_estate]
  alt_purposes: [equipment]

  eligibility:
    - {id: INV_CLIENT_TYPE, field: client_type, op: in, value: [OOO], on_fail: reject_product, reason_code: R_CLIENT_TYPE_OOO_ONLY}
    - {id: INV_AGE, field: business_age_months, op: gte, value: 24, on_fail: reject_product, reason_code: R_BUSINESS_AGE}

  needs:
    - {id: INV_AMOUNT, field: amount, op: between, value: [3000000, 100000000], on_fail: adjust, reason_code: R_AMOUNT_RANGE}
    - {id: INV_TERM, field: term_months, op: between, value: [24, 120], on_fail: adjust, reason_code: R_TERM_RANGE}
    - {id: INV_COLLATERAL, field: has_collateral, op: eq, value: true, on_fail: request_data, reason_code: R_COLLATERAL_REQUIRED}
    - {id: INV_BUSINESS_PLAN, field: business_plan_attached, op: eq, value: true, on_fail: request_data, reason_code: R_NEED_BUSINESS_PLAN}

  financial_limits:
    - {id: INV_PAYMENT, field: payment_to_turnover, op: lte, value: 0.30, on_fail: adjust, reason_code: R_PAYMENT_BURDEN}
    - {id: INV_DTI, field: dti, op: lte, value: 0.55, on_fail: adjust, reason_code: R_DEBT_LOAD}
    - {id: INV_PROFIT, field: net_profit, op: gt, value: 0, on_fail: reject_product, reason_code: R_NEGATIVE_PROFIT}

  pricing:
    base_rate: 0.16
    fee_pct: 0.015
    approval_hours: 120
```

#### Банковская гарантия

```yaml
- id: tender_guarantee
  name: "Банковская гарантия для тендера"
  type: guarantee
  purposes: [tender_guarantee]
  alt_purposes: []

  eligibility:
    - {id: BG_CLIENT_TYPE, field: client_type, op: in, value: [IP, OOO], on_fail: reject_product, reason_code: R_CLIENT_TYPE}
    - {id: BG_AGE, field: business_age_months, op: gte, value: 3, on_fail: reject_product, reason_code: R_BUSINESS_AGE}

  needs:
    - {id: BG_AMOUNT, field: amount, op: between, value: [100000, 20000000], on_fail: adjust, reason_code: R_AMOUNT_RANGE}
    - {id: BG_TERM, field: term_months, op: between, value: [1, 36], on_fail: adjust, reason_code: R_TERM_RANGE}
    - {id: BG_TENDER_NUMBER, field: tender_number, op: exists, on_fail: request_data, reason_code: R_NEED_TENDER_NUMBER}

  financial_limits:
    - {id: BG_REV_RATIO, field: amount_to_revenue, op: lte, value: 0.50, on_fail: adjust, reason_code: R_AMOUNT_TO_REVENUE}

  pricing:
    commission_year_pct: 0.03
    approval_hours: 8
```

### 5.3. Справочник «цель → продукты» (`purpose_map.yaml`)

```yaml
purposes:
  working_capital:
    label: "Пополнение оборотных средств"
    primary: [working_capital_loan, credit_line_smb]
    secondary: [overdraft_smb]
  cash_gap:
    label: "Кассовый разрыв"
    primary: [overdraft_smb]
    secondary: [credit_line_smb]
  equipment:
    label: "Покупка оборудования"
    primary: [equipment_loan]
    secondary: [investment_loan]
  investment:
    label: "Запуск или развитие проекта"
    primary: [investment_loan]
    secondary: []
  real_estate:
    label: "Недвижимость"
    primary: [investment_loan]
    secondary: []
  tender_guarantee:
    label: "Участие в тендере"
    primary: [tender_guarantee]
    secondary: []
```

### 5.4. Веса ранжирования (`ranking.yaml`)

```yaml
default_weights:
  purpose_match: 0.35
  amount_term_fit: 0.20
  cost_score: 0.20
  approval_likelihood: 0.20
  speed_score: 0.05

urgency_overrides:
  high:
    speed_score: 0.20
    cost_score: 0.10
    purpose_match: 0.30
    amount_term_fit: 0.20
    approval_likelihood: 0.20

show_top_n: 3
close_score_delta: 0.05    # если разница меньше, показываем оба продукта как равноценные
```

### 5.5. Reason codes (`reasons.yaml`)

У каждого кода есть клиентский текст, служебный текст (с подстановкой значений) и подсказка, что делать:

```yaml
R_BUSINESS_AGE:
  client: "Для этого продукта бизнес должен работать дольше. Попробуйте другой продукт или вернитесь позже."
  staff: "business_age_months={actual} < {threshold}"
  hint: "suggest_alternative"

R_AMOUNT_TO_REVENUE:
  client: "Запрошенная сумма велика относительно выручки. Мы можем предложить меньшую сумму."
  staff: "amount/annual_revenue={actual:.2f} > {threshold:.2f}"
  hint: "cap_amount"

R_DEBT_LOAD:
  client: "Текущие обязательства уже занимают значительную часть оборота. Уменьшение суммы или срока может помочь."
  staff: "DTI={actual:.2f} > {threshold:.2f}"
  hint: "reduce_amount_or_extend_term"

R_PAYMENT_BURDEN:
  client: "Ежемесячный платёж получается слишком высоким для вашего оборота. Попробуйте увеличить срок."
  staff: "payment/turnover={actual:.2f} > {threshold:.2f}"
  hint: "extend_term"

R_COLLATERAL_REQUIRED:
  client: "Для этого продукта нужно обеспечение. Добавьте залог или выберите продукт без залога."
  staff: "has_collateral=false, required=true"
  hint: "add_collateral"

R_NEED_REVENUE:
  client: "Укажите выручку за последний год или загрузите отчётность, чтобы мы проверили условия."
  staff: "annual_revenue missing"
  hint: "request_documents"

R_OVERDUE:
  client: "По кредитной истории есть неурегулированная просрочка. Закройте её и подайте заявку снова."
  staff: "max_overdue_days={actual} > {threshold}"
  hint: "none"
```

Принцип: клиентский текст не содержит точных порогов и названий внутренних проверок (например, «массовый адрес» выводится нейтрально как «не удалось подтвердить данные организации»). Сотрудник видит полный вариант.

---

## 6. Реализация движка

### 6.1. Операторы

| Оператор | Смысл |
|---|---|
| `eq`, `ne` | равно, не равно |
| `gte`, `lte`, `gt`, `lt` | сравнение |
| `between` | `min <= x <= max` |
| `in`, `not_in` | принадлежность списку |
| `not_prefix` | значение не начинается ни с одного из префиксов (ОКВЭД) |
| `exists` | поле заполнено |
| `when` | условие применимости правила (условные правила) |

### 6.2. Псевдокод

```python
def evaluate_product(product, ctx):
    results = []
    for layer in ("eligibility", "needs", "financial_limits"):
        for rule in product[layer]:
            if not applies(rule.get("when"), ctx):
                continue
            actual = ctx.get(rule["field"])
            if actual is None:
                status = "MISSING_DATA"
            elif check(rule["op"], actual, rule["value"]):
                status = "PASS"
            else:
                status = FAIL_BY_ACTION[rule["on_fail"]]   # reject -> FAIL_HARD, adjust -> FAIL_ADJUSTABLE
            results.append(RuleResult(rule["id"], status, actual, rule["value"], rule["reason_code"]))
    return results


def recommend(ctx, products, purpose_map, ranking):
    candidates = purpose_map.products_for(ctx["purpose"])      # primary + secondary
    evaluated = {p.id: evaluate_product(p, ctx) for p in candidates}

    eligible = []
    for p in candidates:
        res = evaluated[p.id]
        if any(r.status == "FAIL_HARD" for r in res):
            continue                                            # продукт исключён
        outcome = build_outcome(p, res, ctx)                    # OK / COUNTER_OFFER / REQUEST_DATA
        eligible.append((p, res, outcome))

    ranked = sorted(eligible, key=lambda x: score(x, ctx, ranking), reverse=True)
    return build_response(ranked[:ranking.show_top_n], evaluated)
```

### 6.3. Контрпредложение (`cap_amount`)

```python
def max_allowed(product, ctx):
    caps = [product.needs.amount.max]
    caps.append(product.limits.amount_to_revenue_max * ctx.annual_revenue)
    caps.append(amount_from_payment_limit(product, ctx))   # по ограничению платежа к обороту
    cap = min(caps)
    return cap if cap >= product.needs.amount.min else None   # None -> продукт не подходит
```

После пересчёта контрпредложение повторно проходит `evaluate_product`.

---

## 7. Формат ответа API

```json
{
  "request_id": "a1f3-...",
  "status": "OK",
  "recommendations": [
    {
      "product_id": "working_capital_loan",
      "name": "Кредит на оборотные средства",
      "rank": 1,
      "score": 0.81,
      "outcome": "COUNTER_OFFER",
      "terms": {
        "requested_amount": 2500000,
        "offered_amount": 1800000,
        "term_months": 12,
        "indicative_rate": 0.19,
        "monthly_payment": 164000
      },
      "client_messages": [
        "Запрошенная сумма велика относительно выручки. Мы можем предложить 1,8 млн ₽."
      ],
      "next_actions": ["accept_counter_offer", "change_amount", "add_collateral"]
    }
  ],
  "excluded": [
    {
      "product_id": "investment_loan",
      "client_reason": "Для этого продукта бизнес должен работать дольше."
    }
  ],
  "staff_trace": {
    "rules_applied": [
      {"rule": "WC_REV_RATIO", "status": "FAIL_ADJUSTABLE", "actual": 0.52, "threshold": 0.40, "code": "R_AMOUNT_TO_REVENUE"},
      {"rule": "WC_AGE", "status": "PASS", "actual": 18, "threshold": 12}
    ],
    "config_version": "rules-2026.10.1"
  }
}
```

`staff_trace` доступен только роли сотрудника. В нём всегда указывается версия конфигурации правил, чтобы результат можно было воспроизвести.

---

## 8. Как это используют LLM и чат-помощник

- Правила подбора **не** выполняет LLM. Она получает готовые `client_messages` и `next_actions` и формулирует их связным текстом.
- Чат-помощник собирает недостающие поля анкеты (`purpose`, `amount`, `term_months`, `has_collateral`) и возвращает JSON, который клиент подтверждает в форме. Дальше работает тот же движок.
- Промпт для объяснителя: «Перепиши сообщения простым языком. Не добавляй чисел, продуктов и условий, которых нет во входных данных. Не обещай одобрение».
- Если LLM недоступна, показываются шаблонные тексты из `reasons.yaml`.

---

## 9. Тестовые сценарии

| № | Вход | Ожидаемый результат |
|---|---|---|
| 1 | ООО, 24 мес., выручка 20 млн, цель `working_capital`, 2 млн, 12 мес. | Кредит на оборотные: `OK`; кредитная линия: вторая в списке |
| 2 | ИП, 4 мес., цель `cash_gap`, 300 тыс., 30 дн. | Овердрафт исключён (`R_BUSINESS_AGE`), результат `NO_MATCH` с подсказкой |
| 3 | ООО, выручка 3 млн, `working_capital`, 5 млн, 24 мес. | `COUNTER_OFFER`: сумма урезана по выручке |
| 4 | ООО, 18 мес., `equipment`, 4 млн, без счёта от поставщика | `REQUEST_DATA`: нужен счёт; продукт остаётся в списке |
| 5 | ИП, цель `investment`, 10 млн | Инвестиционный кредит исключён (только ООО); предложение альтернативы |
| 6 | ООО, массовый адрес, любая цель | Все продукты исключены; клиент получает нейтральную причину, сотрудник видит `STOP_MASS_ADDRESS` |
| 7 | ООО с просрочкой 45 дней | Исключены все продукты (`R_OVERDUE`) |
| 8 | Нет данных о выручке | `REQUEST_DATA` для продуктов с ограничением по выручке |
| 9 | Одинаковый вход дважды | Идентичный результат (детерминизм) |
| 10 | Смена порога в конфиге | Результат меняется без правки кода |

Для каждого сценария в репозитории хранится JSON с входом и ожидаемым выходом, их удобно запускать как автотесты и как коллекцию запросов.

---

## 10. Допущения и ограничения

- Пороги и ставки синтетические и нужны для демонстрации логики, они не отражают реальные политики банка.
- Данные ЕГРЮЛ, «Прозрачного бизнеса» и БКИ моделируются локальными моками.
- Подбор даёт ориентировочные условия. Итоговое решение принимает кредитный модуль (скоринг и кредитная логика) после подачи заявки.
- Ранжирование на правилах и весах выбрано сознательно: на синтетических данных RecSys-модель обучилась бы на том, что сгенерировали сами авторы, а продуктов в каталоге мало.

### Возможное развитие

- Подстановка весов ранжирования из A/B-экспериментов на реальных данных.
- Персонализация порядка и акцентов по поведению клиента (RecSys поверх правил, а не вместо них).
- Конфиги правил с версионированием и согласованием изменений (review → публикация).
- Симулятор «что, если»: клиент меняет сумму или срок и сразу видит, как меняется набор продуктов.