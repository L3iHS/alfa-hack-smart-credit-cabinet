import { test, expect, type Page, type Browser } from '@playwright/test';
const password = process.env.DEMO_PASSWORD || 'AlfaDemo2026!';
async function login(page: Page, staff = true) {
  await page.goto('/login');
  await page.locator('#email').fill(staff ? 'staff@example.test' : 'demo-a@example.test');
  await page.locator('#password').fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page).toHaveURL(staff ? /\/staff\/applications$/ : /\/applications$/);
}
// Каждый потребитель таблицы сам готовит реальное непросмотренное предложение.
// API-запросы не создают клиентское событие просмотра и не подменяют отчёт аналитики.
async function prepareUnviewedOffer(browser: Browser) {
  const context = await browser.newContext({baseURL: process.env.BASE_URL || 'http://localhost:8080'});
  const api = context.request;
  try {
    async function authorize(email: string) {
      const initial = await (await api.get('/api/v1/auth/csrf')).json();
      const response = await api.post('/api/v1/auth/login', {
        headers: {'X-CSRF-Token': initial.csrf_token}, data: {email, password},
      });
      expect(response.status()).toBe(200);
      return (await response.json()).csrf_token as string;
    }
    let token = await authorize('demo-a@example.test');
    const today = new Date();
    const periodStart = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() - 3, 1)).toISOString().slice(0, 10);
    const periodEnd = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 0)).toISOString().slice(0, 10);
    const created = await api.post('/api/v1/applications', {
      headers: {'X-CSRF-Token': token},
      data: {product_code: 'overdraft', purpose: 'Проверка таблицы контрпредложений',
        amount_kopecks: 50000000, term_months: 2, period_start: periodStart, period_end: periodEnd,
        revenue_kopecks: 240000000, operating_expenses_kopecks: 90000000, existing_debt_payments_kopecks: 15000000},
    });
    expect(created.status()).toBe(201);
    const draft = await created.json();
    let version = draft.version;
    const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4b6gCAANXAUWe8DG4AAAAAElFTkSuQmCC', 'base64');
    for (const document of ['financial_statement', 'bank_statement']) {
      const uploaded = await api.post(`/api/v1/applications/${draft.id}/documents?document_type=${document}&expected_version=${version}&filename=analytics.png`, {
        headers: {'X-CSRF-Token': token, 'Content-Type': 'image/png'}, data: png,
      });
      expect(uploaded.status()).toBe(201);
      version = (await uploaded.json()).application_version;
    }
    const policy = await (await api.get('/api/v1/submission-policy')).json();
    const submitted = await api.post(`/api/v1/applications/${draft.id}/submit`, {
      headers: {'X-CSRF-Token': token, 'Idempotency-Key': crypto.randomUUID()},
      data: {expected_version: version, data_confirmed: true, bki_consent: true, consent_version: policy.consent_version},
    });
    expect(submitted.status()).toBe(202);
    await expect.poll(async () => (await (await api.get(`/api/v1/applications/${draft.id}`)).json()).status,
      {timeout: 15000}).toBe('manual_review');
    token = await authorize('staff@example.test');
    const current = await (await api.get(`/api/v1/applications/${draft.id}`)).json();
    const offered = await api.post(`/api/v1/applications/${draft.id}/offers`, {
      headers: {'X-CSRF-Token': token, 'Idempotency-Key': crypto.randomUUID()},
      data: {expected_version: current.version, amount_kopecks: 40000000, term_months: 2, reason: 'Условия для проверки таблицы'},
    });
    expect(offered.status()).toBe(201);
    return draft.id as string;
  } finally {
    await context.close();
  }
}

test('staff analytics has honest funnels and immutable conditions', async ({ page, browser }) => {
  await prepareUnviewedOffer(browser);
  await login(page);
  await page.getByRole('link', { name: 'Аналитика', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Оформление заявки', exact: true })).toBeVisible();
  await expect(page.locator('.analytics-funnel')).toHaveCount(2);
  await expect(page.getByText('Просмотр не зафиксирован', { exact: true }).first()).toBeVisible();
  await page.getByText('Как считаем', { exact: true }).click();
  await expect(page.getByText(/72 часов/).first()).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.analytics-table tbody tr').first()).toBeVisible();
});

for (const width of [320, 1366]) {
test(`analytics help is modal, preserves layout and returns keyboard focus at ${width}px`, async ({page}) => {
  await page.setViewportSize({width, height: 900});
  await login(page);
  await page.goto('/staff/analytics');
  await expect(page.locator('.analytics-funnel')).toHaveCount(2);
  const trigger = page.getByText('Как считаем', {exact: true});
  const before = await trigger.boundingBox();
  const funnels = await page.locator('.analytics-funnels').boundingBox();
  const overflow = await page.locator('body').evaluate(element => element.style.overflow);
  await trigger.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible({timeout: 1500});
  await expect(dialog.getByRole('heading', {name: 'Как считаем показатели'})).toBeVisible();
  await expect(dialog.getByRole('heading', {name: 'Как считаем показатели'})).toBeFocused({timeout: 1500});
  const box = await dialog.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(900);
  expect((await trigger.boundingBox())!.x).toBeCloseTo(before!.x, 0);
  expect((await trigger.boundingBox())!.y).toBeCloseTo(before!.y, 0);
  expect((await page.locator('.analytics-funnels').boundingBox())!.y).toBeCloseTo(funnels!.y, 0);
  await page.keyboard.press('Tab');
  const close = dialog.getByRole('button', {name: 'Закрыть пояснение'});
  await expect(close).toBeFocused();
  expect(await close.evaluate(element => element.matches(':focus-visible'))).toBe(true);
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', {name: 'Понятно'})).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(close).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  expect(await page.locator('body').evaluate(element => element.style.overflow)).toBe(overflow);
  await trigger.click();
  await page.mouse.click(4, 4);
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await screenshot(page, `help-closed-${width}`);
});
}

test('empty analytics explains missing data and offers contextual help', async ({page}) => {
  await login(page);
  await page.goto('/staff/analytics');
  await page.getByLabel('Период с', {exact: true}).fill('01.01.2000');
  await page.getByLabel('Период по', {exact: true}).fill('02.01.2000');
  await page.getByRole('button', {name: 'Применить', exact: true}).click();
  await expect(page.getByText('Нет незавершённых оформлений за выбранный период.', {exact: true})).toBeVisible({timeout: 1500});
  await expect(page.locator('.analytics-page')).not.toContainText(/0\s+из\s+0/);
  const info = page.getByRole('button', {name: 'О разделе «Где остановились»'});
  await info.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('ещё не отправлены');
  await expect(dialog).toContainText('3 из 10');
  await dialog.getByRole('button', {name: 'Закрыть пояснение'}).click();
  await expect(info).toBeFocused();
});

async function screenshot(page: Page, name: string) {
  if (process.env.SCREENSHOT_DIR) await page.screenshot({path: `${process.env.SCREENSHOT_DIR}/${name}.png`, fullPage: true});
}
const id = 'adab7d37-1f76-4801-bdab-e417916293d1';
const offerId = 'aaab7d37-1f76-4801-bdab-e417916293d1';
function offerApplication() {
  return {id, version: 7, status: 'counteroffer', product_code: 'working_capital', updated_at: new Date().toISOString(), catalog_version: 'demo-v2', purpose: 'Наблюдение', description: null, amount_kopecks: 100000000, term_months: 12, period_start: null, period_end: null, revenue_kopecks: null, operating_expenses_kopecks: null, existing_debt_payments_kopecks: null, tender_number: null, beneficiary_name: null, project_description: null, public_reasons: [], processing_status: 'succeeded', information_requests: [], available_actions: ['accept_offer', 'decline_offer'], offers: [{id: offerId, version: 1, status: 'active', revision_id: id, application_version: 7, product_code: 'working_capital', amount_kopecks: 80000000, term_months: 12, monthly_payment_kopecks: 8000000, total_payment_kopecks: 96000000, annual_rate_bps: 2000, created_at: new Date().toISOString(), reason: 'Предложены другие условия', payment_terms: {payment_kind: 'annuity', amount_kopecks: 80000000, term_months: 12, annual_rate_bps: 2000, annual_commission_bps: 0, monthly_payment_kopecks: 8000000, upfront_fee_kopecks: 0, principal_due_at_end_kopecks: 0, last_payment_kopecks: 8000000, total_payment_kopecks: 96000000, total_cost_kopecks: 16000000, assessment_monthly_burden_kopecks: 8000000, contingent_liability_kopecks: 0, assumptions: []}}]};
}
async function mockOffer(page: Page) {
  const item = offerApplication();
  await page.route(`**/api/v1/applications/${id}`, route => route.fulfill({json: item}));
  await page.route(`**/api/v1/applications/${id}/documents`, route => route.fulfill({json: {items: []}}));
  await page.route(`**/api/v1/applications/${id}/history?*`, route => route.fulfill({json: {items: [], total: 0, limit: 10, offset: 0}}));
  return item;
}

test('client role cannot open staff analytics or see navigation', async ({page}) => {
  await login(page, false);
  await expect(page.getByRole('link', {name: 'Аналитика', exact: true})).toHaveCount(0);
  expect((await page.request.get('/api/v1/analytics/summary')).status()).toBe(403);
  await page.goto('/staff/analytics'); await expect(page).toHaveURL(/\/applications$/);
});

test('real journey survives reload, links once, observes card steps and releases next new form', async ({page, browser}) => {
  await login(page, false);
  const context = await browser.newContext(); const staff = await context.newPage(); await login(staff);
  const baseline = await (await staff.request.get('/api/v1/analytics/summary')).json();
  const events: any[] = [];
  page.on('request', request => {if (request.url().endsWith('/analytics/events')) events.push(request.postDataJSON());});
  await page.goto('/applications/new');
  await expect.poll(() => events.filter(event => event.kind === 'form_opened').length).toBe(1);
  const journey = events.find(event => event.kind === 'form_opened').journey_id;
  await page.reload();
  await page.locator('#purpose').fill('Проверка сквозной воронки');
  await page.locator('#amount_kopecks').fill('200000'); await page.locator('#term_months').fill('3');
  await page.locator('#period_start').fill('2026-01'); await page.locator('#period_end').fill('2026-03');
  await page.locator('#revenue_kopecks').fill('9000000'); await page.locator('#operating_expenses_kopecks').fill('3000000'); await page.locator('#existing_debt_payments_kopecks').fill('0');
  await page.getByRole('button', {name: 'Сохранить черновик', exact: true}).click();
  await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/);
  const applicationId = page.url().split('/').at(-1)!;
  await expect.poll(() => events.filter(event => event.kind === 'draft_linked').length).toBe(1);
  expect(events.find(event => event.kind === 'draft_linked')).toMatchObject({journey_id: journey, application_id: applicationId});
  await page.locator('.documents-panel').scrollIntoViewIfNeeded();
  await expect.poll(() => events.filter(event => event.kind === 'form_step_viewed' && event.step === 'documents').length).toBe(1);
  await page.getByRole('button', {name: 'Отправить заявку', exact: true}).scrollIntoViewIfNeeded();
  await expect.poll(() => events.filter(event => event.kind === 'form_step_viewed' && event.step === 'review').length).toBe(1);
  await page.reload(); await page.waitForTimeout(3400);
  expect(events.filter(event => event.kind === 'form_opened')).toHaveLength(1);
  expect(events.filter(event => event.kind === 'draft_linked')).toHaveLength(1);
  for (const event of events) {
    const allowed = event.kind === 'form_opened' ? ['kind', 'event_id', 'journey_id', 'product_code'] : event.kind === 'draft_linked' ? ['kind', 'event_id', 'journey_id', 'application_id'] : ['kind', 'event_id', 'journey_id', 'step'];
    expect(Object.keys(event).sort()).toEqual(allowed.sort());
  }
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4b6gCAANXAUWe8DG4AAAAAElFTkSuQmCC', 'base64');
  await page.getByLabel('Файл: Финансовая отчётность').setInputFiles({name: 'analytics.png', mimeType: 'image/png', buffer: png});
  await page.getByRole('button', {name: 'Загрузить: Финансовая отчётность', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Скачать analytics.png', exact: true})).toBeVisible();
  await page.getByRole('checkbox', {name: /Подтверждаю, что проверил данные/}).check();
  await page.getByRole('checkbox', {name: /Согласен на проверку кредитной истории/}).check();
  const submitted = page.waitForResponse(response => response.url().includes(`/applications/${applicationId}/submit`) && response.request().method() === 'POST');
  await page.getByRole('button', {name: 'Отправить заявку', exact: true}).click(); expect((await submitted).status()).toBe(202);
  const summary = await (await staff.request.get('/api/v1/analytics/summary')).json();
  expect(summary.form_funnel[0].count).toBe(baseline.form_funnel[0].count + 1); expect(summary.form_funnel[1].count).toBe(baseline.form_funnel[1].count + 1); expect(summary.form_funnel[2].count).toBe(baseline.form_funnel[2].count + 1);
  await context.close();
  await page.goto('/applications/new');
  await expect.poll(() => events.filter(event => event.kind === 'form_opened').length).toBe(2);
  expect(events.filter(event => event.kind === 'form_opened')[1].journey_id).not.toBe(journey);
});

for (const width of [320, 390, 768, 901, 1366]) {
  test(`analytics and recommendation geometry at ${width}px`, async ({page}) => {
    await page.setViewportSize({width, height: 900}); await login(page);
    await page.goto('/staff/analytics'); await expect(page.locator('.analytics-funnel')).toHaveCount(2);
    const dateField = page.getByLabel('Период с', {exact: true});
    const productField = page.getByLabel('Продукт', {exact: true});
    const outcomeField = page.getByLabel('Исход', {exact: true});
    const radius = await dateField.evaluate(element => getComputedStyle(element).borderRadius);
    for (const control of [productField, outcomeField]) {
      expect(await control.evaluate(element => getComputedStyle(element).borderRadius)).toBe(radius);
      expect((await control.boundingBox())!.height).toBe((await dateField.boundingBox())!.height);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await screenshot(page, `analytics-${width}`);
    if (width < 700) await page.getByRole('button', {name: 'Аккаунт', exact: true}).click();
    await page.getByRole('button', {name: 'Выйти', exact: true}).click(); await expect(page).toHaveURL(/\/login$/);
    await login(page, false); await page.goto('/applications/new');
    await page.getByText('Помочь выбрать', {exact: true}).click();
    const panel = page.locator('.recommendation-panel'); await expect(panel).toBeVisible();
    const bounds = await panel.boundingBox(); const selection = await page.locator('.product-selection-help').boundingBox();
    expect(Math.abs(bounds!.x - selection!.x)).toBeLessThan(1); expect(Math.abs(bounds!.width - selection!.width)).toBeLessThan(1);
    const picker = panel.getByRole('combobox'); await picker.click();
    await page.getByRole('option', {name: 'Запуск или развитие проекта'}).click();
    const button = panel.locator('.recommendation-actions .primary');
    const pickerBox = await picker.boundingBox(); const actionBox = await button.boundingBox();
    expect(pickerBox!.height).toBe(48); expect(actionBox!.height).toBe(48);
    const overlap = pickerBox!.x < actionBox!.x + actionBox!.width && pickerBox!.x + pickerBox!.width > actionBox!.x && pickerBox!.y < actionBox!.y + actionBox!.height && pickerBox!.y + pickerBox!.height > actionBox!.y;
    expect(overlap).toBe(false);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await screenshot(page, `recommendation-width-${width}`);
  });
}

for (const mode of ['500', '401', '403', 'csrf-network'] as const) {
  test(`telemetry ${mode} never expires session or blocks draft save`, async ({page}) => {
    await login(page, false);
    let requests = 0;
    if (mode === 'csrf-network') {
      await page.reload();
      await page.route('**/api/v1/auth/csrf', async route => {
        if (requests === 0) {requests++; await route.abort('failed');} else await route.continue();
      });
    } else await page.route('**/api/v1/analytics/events', route => {requests++; return route.fulfill({status: Number(mode), json: {code: 'csrf_failed', message: 'Сбой наблюдений'}});});
    await page.goto('/applications/new'); await expect(page.locator('#purpose')).toBeVisible();
    await expect.poll(() => requests).toBeGreaterThan(0);
    await page.locator('#purpose').fill('Сохранение при сбое наблюдений');
    await page.getByRole('button', {name: 'Сохранить черновик', exact: true}).click();
    await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/);
    await expect(page.getByRole('button', {name: 'Выйти', exact: true})).toBeVisible();
    await expect(page.getByText('Сохранение при сбое наблюдений', {exact: true})).toBeVisible();
  });
}

test('pending link retries retain event identity while next form starts another journey', async ({page}) => {
  await login(page, false);
  const links: any[] = []; const opens: any[] = [];
  await page.route('**/api/v1/analytics/events', async route => {
    const event = route.request().postDataJSON();
    if (event.kind === 'form_opened') opens.push(event);
    if (event.kind === 'draft_linked') {links.push(event); if (links.length === 1) return route.fulfill({status: 503, json: {code: 'temporarily_unavailable'}});}
    await route.continue();
  });
  await page.goto('/applications/new'); await page.getByRole('button', {name: 'Сохранить черновик', exact: true}).click();
  await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/);
  await page.goto('/applications/new'); await expect.poll(() => opens.length).toBe(2);
  await expect.poll(() => links.length).toBe(2); expect(links[1]).toEqual(links[0]); expect(opens[1].journey_id).not.toBe(opens[0].journey_id);
});

test('owner switch cancels bounded queued observations', async ({page}) => {
  await login(page, false); const sent: any[] = [];
  await page.route('**/api/v1/analytics/events', route => {sent.push(route.request().postDataJSON()); return route.fulfill({status: 503, json: {code: 'unavailable'}});});
  await page.goto('/applications/new'); await expect.poll(() => sent.length).toBeGreaterThan(0);
  const firstJourney = sent[0].journey_id;
  await page.getByRole('button', {name: 'Выйти', exact: true}).click(); await expect(page).toHaveURL(/\/login$/); const afterLogout = sent.length;
  await page.locator('#email').fill('client1@example.test'); await page.locator('#password').fill(password); await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await expect(page).toHaveURL(/\/applications$/); await page.waitForTimeout(5000);
  expect(sent.length).toBe(afterLogout);
  await page.goto('/applications/new'); await expect.poll(() => sent.length).toBeGreaterThan(afterLogout);
  expect(sent.slice(afterLogout).every(event => event.journey_id !== firstJourney)).toBe(true);
});

test('offer observed only when genuinely intersecting and visible; polling does not repeat', async ({page}) => {
  await login(page, false); await mockOffer(page); const events: any[] = [];
  await page.addInitScript(() => {Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => (window as any).__tabHidden ? 'hidden' : 'visible'}); (window as any).__tabHidden = true;});
  await page.route('**/api/v1/analytics/events', route => {events.push(route.request().postDataJSON()); return route.fulfill({json: {recorded: true}});});
  await page.setViewportSize({width: 1366, height: 400});
  await page.goto(`/applications/${id}`);
  await expect(page.locator('.offer-comparison')).not.toBeInViewport();
  await page.evaluate(() => {(window as any).__tabHidden = false; document.dispatchEvent(new Event('visibilitychange'));});
  await page.waitForTimeout(250); expect(events.filter(event => event.kind === 'offer_viewed')).toHaveLength(0);
  await page.evaluate(() => {(window as any).__tabHidden = true; document.dispatchEvent(new Event('visibilitychange'));});
  await page.locator('.offer-comparison').scrollIntoViewIfNeeded(); await page.waitForTimeout(500);
  expect(events.filter(event => event.kind === 'offer_viewed')).toHaveLength(0);
  await page.evaluate(() => {(window as any).__tabHidden = false; document.dispatchEvent(new Event('visibilitychange'));});
  await expect.poll(() => events.filter(event => event.kind === 'offer_viewed').length).toBe(1);
  await page.waitForTimeout(3400); await page.reload(); await page.locator('.offer-comparison').scrollIntoViewIfNeeded();
  expect(events.filter(event => event.kind === 'offer_viewed')).toHaveLength(1);
});

test('staff viewing offer emits no client observation', async ({page}) => {
  await login(page); await mockOffer(page); let sent = 0;
  page.on('request', request => {if (request.url().endsWith('/analytics/events')) sent++;});
  await page.goto(`/staff/applications/${id}`); await page.locator('.offer-comparison').scrollIntoViewIfNeeded(); await page.waitForTimeout(500); expect(sent).toBe(0);
});

for (const reason of ['', 'high_payment']) {
  test(`optional decline reason '${reason || 'omitted'}' retains immutable command on unknown retry`, async ({page}) => {
    await login(page, false); await mockOffer(page);
    await page.route('**/api/v1/analytics/events', route => route.fulfill({json: {recorded: true}}));
    const commands: {key: string; body: any}[] = [];
    await page.route(`**/api/v1/offers/${offerId}/decline`, route => {
      commands.push({key: route.request().headers()['idempotency-key'], body: route.request().postDataJSON()});
      return commands.length === 1 ? route.abort('failed') : route.fulfill({json: {application_id: id, version: 8, status: 'manual_review', revision_id: id}});
    });
    await page.goto(`/applications/${id}`);
    if (reason) await page.getByLabel('Причина отказа').selectOption(reason);
    await page.getByRole('button', {name: 'Отклонить предложение', exact: true}).click();
    await expect(page.getByRole('button', {name: 'Повторить действие', exact: true})).toBeVisible();
    await page.reload(); await page.getByRole('button', {name: 'Повторить действие', exact: true}).click();
    await expect.poll(() => commands.length).toBe(2); expect(commands[1]).toEqual(commands[0]);
    expect(commands[0].body).toEqual({expected_version: 7, offer_version: 1, ...(reason ? {decline_reason: reason} : {})});
  });
}

test('empty period has null shares and filter races never paint stale data', async ({page}) => {
  await login(page);
  let saved: any;
  await page.route('**/api/v1/analytics/summary?*', async route => {
    const response = await route.fetch(); const body = await response.json(); saved = body;
    if (route.request().url().includes('product_code=equipment')) {await new Promise(resolve => setTimeout(resolve, 800)); body.form_funnel[0].count = 999;}
    if (route.request().url().includes('product_code=investment')) {
      body.form_funnel.forEach((stage: any) => {stage.count = 0; stage.base_from_first = 0; stage.base_from_previous = 0; stage.share_from_first = null; stage.share_from_previous = null;});
      body.offer_funnel.forEach((stage: any) => {stage.count = 0; stage.base_from_first = 0; stage.base_from_previous = 0; stage.share_from_first = null; stage.share_from_previous = null;});
    }
    await route.fulfill({json: body});
  });
  await page.goto('/staff/analytics'); await expect(page.locator('.analytics-funnel')).toHaveCount(2);
  await page.getByLabel('Продукт', {exact: true}).selectOption('equipment'); await page.getByRole('button', {name: 'Применить', exact: true}).click();
  await page.getByLabel('Продукт', {exact: true}).selectOption('investment'); await page.getByRole('button', {name: 'Применить', exact: true}).click();
  await expect(page.getByText('За этот период наблюдений и предложений нет. Выберите другой период или продукт.')).toBeVisible();
  await page.waitForTimeout(1000);
  await expect(page.locator('.funnel-label strong')).toHaveCount(0);
  await expect(page.locator('.analytics-funnel').first()).toContainText('За выбранный период новые оформления не начинались.');
  expect(saved.form_funnel[0].share_from_first).toBeNull();
});

test('observation retries stop after three attempts and keep one event id', async ({page}) => {
  await login(page, false); const opens: any[] = [];
  await page.route('**/api/v1/analytics/events', route => {
    const event = route.request().postDataJSON(); if (event.kind === 'form_opened') opens.push(event);
    return route.fulfill({status: 503, json: {code: 'unavailable'}});
  });
  await page.goto('/applications/new');
  await expect.poll(() => opens.length, {timeout: 10000}).toBe(3);
  expect(new Set(opens.map(event => event.event_id)).size).toBe(1);
  await page.reload(); await page.waitForTimeout(2000); expect(opens).toHaveLength(3);
});

test('returning to an earlier section updates last observed step without polling duplicates', async ({page}) => {
  await login(page, false); const steps: string[] = [];
  await page.setViewportSize({width: 390, height: 844});
  await page.route('**/api/v1/analytics/events', route => {
    const event = route.request().postDataJSON(); if (event.kind === 'form_step_viewed') steps.push(event.step);
    return route.fulfill({json: {recorded: true}});
  });
  await page.goto('/applications/new');
  await expect.poll(() => steps.at(-1)).toBe('terms');
  await page.locator('#revenue_kopecks').scrollIntoViewIfNeeded(); await expect.poll(() => steps.at(-1)).toBe('finances');
  await page.getByRole('heading', {name: 'Выбор продукта', exact: true}).scrollIntoViewIfNeeded(); await expect.poll(() => steps.at(-1)).toBe('terms');
  expect(steps.filter(step => step === 'terms')).toHaveLength(2);
});

test('dates stay Russian independent of browser locale and query uses Moscow calendar ISO', async ({page}) => {
  await login(page); await page.goto('/staff/analytics'); await expect(page.locator('.analytics-funnel')).toHaveCount(2);
  await expect(page.getByLabel('Период с', {exact: true})).toHaveValue(/^\d{2}\.\d{2}\.\d{4}$/);
  const previousCount = await page.locator('.funnel-label strong').first().textContent();
  await page.getByLabel('Период с', {exact: true}).fill('31.02.2026'); await page.getByRole('button', {name: 'Применить', exact: true}).click();
  await expect(page.getByRole('alert')).toContainText('Укажите существующие даты');
  await expect(page.locator('.analytics-funnel')).toHaveCount(2); await expect(page.locator('.funnel-label strong').first()).toHaveText(previousCount!);
  await page.getByLabel('Период с', {exact: true}).fill('01.10.2026'); await page.getByLabel('Период по', {exact: true}).fill('24.10.2026');
  const request = page.waitForRequest(request => request.url().includes('/analytics/summary?') && request.url().includes('date_from=2026-10-01') && request.url().includes('date_to=2026-10-24'));
  await page.getByRole('button', {name: 'Применить', exact: true}).click(); await request;
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('all four offer stages and all five columns fit normal laptop', async ({page, browser}) => {
  await prepareUnviewedOffer(browser);
  await page.setViewportSize({width: 1265, height: 712}); await login(page); await page.goto('/staff/analytics');
  await expect(page.locator('.analytics-funnel')).toHaveCount(2);
  const caption = await page.locator('.analytics-funnel').last().locator('.funnel-caption').last().boundingBox();
  expect(caption!.y + caption!.height).toBeLessThanOrEqual(712);
  const overflow = await page.locator('.analytics-table-scroll').evaluate(element => element.scrollWidth - element.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1); await screenshot(page, 'analytics-laptop-1265');
});

for (const status of [503, 429]) {
  test(`background CSRF ${status} retries original event and preserves business session`, async ({page}) => {
    await login(page, false);
    const owner = (await (await page.request.get('/api/v1/me')).json()).id;
    const csrfEvents: {event_id: string; attempts: number}[] = [];
    const observed: any[] = [];
    const acknowledgements = new Map<string, number>();
    page.on('response', response => {
      if (response.url().endsWith('/analytics/events')) {
        const event = response.request().postDataJSON();
        acknowledgements.set(event.event_id, response.status());
      }
    });
    await page.route('**/api/v1/auth/csrf', async route => {
      const queued = await page.evaluate(ownerId => {
        const entries = JSON.parse(sessionStorage.getItem(`credit-observations:v1:${ownerId}:queue`) || '[]');
        return entries[0] ? {event_id: entries[0].event.event_id, attempts: entries[0].attempts} : null;
      }, owner);
      if (queued) csrfEvents.push(queued);
      if (csrfEvents.length === 1) return route.fulfill({status, json: {code: 'temporarily_unavailable', message: 'Попробуйте позже'}});
      await route.continue();
    });
    page.on('request', request => {if (request.url().endsWith('/analytics/events')) observed.push(request.postDataJSON());});
    await page.goto('/applications/new');
    await expect.poll(() => observed.filter(event => event.kind === 'form_opened').length, {timeout: 5000}).toBe(1);
    expect(csrfEvents.slice(0, 2)).toEqual([
      {event_id: csrfEvents[0].event_id, attempts: 1},
      {event_id: csrfEvents[0].event_id, attempts: 2},
    ]);
    expect(observed.find(event => event.kind === 'form_opened').event_id).toBe(csrfEvents[0].event_id);
    await expect.poll(() => acknowledgements.get(csrfEvents[0].event_id)).toBe(200);
    expect((await (await page.request.get('/api/v1/me')).json()).id).toBe(owner);
    await expect(page.getByRole('button', {name: 'Выйти', exact: true})).toBeVisible();
    await page.locator('#purpose').fill(`Сохранение после CSRF ${status}`);
    await page.getByRole('button', {name: 'Сохранить черновик', exact: true}).click();
    await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/);
    await expect(page.getByText(`Сохранение после CSRF ${status}`, {exact: true})).toBeVisible();
  });
}

for (const width of [390, 1366]) test(`counteroffer count shares heading row ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 850 }); await login(page); await page.goto('/staff/analytics');
  const section = page.locator('.analytics-offers');
  const count = section.locator('.analytics-total'); await expect(count).toBeVisible();
  const title = section.getByRole('heading', { name: 'Контрпредложения', exact: true });
  const a = await title.boundingBox(); const b = await count.boundingBox();
  expect(Math.abs(a!.y + a!.height / 2 - b!.y - b!.height / 2)).toBeLessThan(6);
  await expect(section).not.toContainText('Запрошенные и предложенные условия');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
