import { fileURLToPath } from 'node:url';
import { test, expect, type Page } from '@playwright/test';
const password = process.env.DEMO_PASSWORD || 'Demo-credit-2026!';
const evidence = fileURLToPath(new URL('../../.superpowers/sdd/plan/task-4-evidence', import.meta.url));
async function login(page: Page, staff = false) {
  await page.goto('/login'); await page.getByLabel('Электронная почта').fill(staff ? 'staff@example.test' : 'client1@example.test');
  await page.getByLabel('Пароль', { exact: true }).fill(password); await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page).toHaveURL(staff ? /\/staff\/applications$/ : /\/applications$/);
}
const intake = (code = 'equipment') => ({ suggested_fields: { product_code: code, amount_kopecks: 200000000, term_months: null, purpose: 'Купить две печи' }, evidence: { product_code: 'две печи', amount_kopecks: '2 млн', purpose: 'Купить две печи' }, questions: ['На какой срок нужен кредит?'], unsupported_need: false, model: 'test-fixture', catalog_version: 'demo-v2' });
const answer = (version: number | null = null) => ({ status: 'answered', answer: 'Для покупки печи подходит кредит на оборудование. <b>Текст ответа</b>', sources: [{ id: 'product:equipment', title: 'Кредит на оборудование', text: 'Нужен счёт на оборудование. <img src=x onerror=alert(1)>', version: 'demo-v2' }, { id: 'application:private:request', title: 'Данные заявки', version: '2', text: JSON.stringify({ product_code: 'equipment', amount_kopecks: 200000000, term_months: 24, probability: 0.12, revision_id: 'secret-uuid', terms_fingerprint: 'secret-fingerprint' }) }], model: 'test-fixture', knowledge_version: 'demo-v2', application_version: version });
async function openIntake(page: Page) { await page.goto('/applications/new'); await page.getByText('Опишите задачу', { exact: true }).click(); await page.getByLabel('Что нужно вашему бизнесу').fill('Купить две печи за 2 млн'); }
async function analyze(page: Page) { await page.getByRole('button', { name: 'Разобрать описание' }).click(); }
// Подмена HTTP проверяет поведение интерфейса, а не качество модели.
test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/assistant/**', route => route.fulfill({ status: 503, json: { code: 'assistant_unavailable', message: 'Помощник временно недоступен' } }));
  await page.route(/\/api\/v1\/applications\/[^/]+\/summary(?:\?|$)/, route => route.request().method() === 'GET' ? route.fulfill({ json: null }) : route.fulfill({ status: 503, json: { code: 'assistant_unavailable', message: 'Помощник временно недоступен' } }));
});
test('intake compares fields applies only on confirmation and preserves null', async ({ page }) => {
  await login(page); await page.route('**/api/v1/assistant/intake', route => route.fulfill({ json: intake() })); await openIntake(page);
  await page.locator('#amount_kopecks').fill('500000'); await page.locator('#term_months').fill('12'); await page.locator('#purpose').fill('Старая цель'); await analyze(page);
  await expect(page.locator('.intake-panel')).toContainText('Сейчас'); await expect(page.locator('.intake-panel')).toContainText('Предлагается'); await expect(page.locator('.intake-panel')).toContainText('Старая цель');
  await expect(page.locator('#amount_kopecks')).toHaveValue('500000'); await page.getByRole('button', { name: 'Применить к форме' }).click();
  await expect(page.locator('#amount_kopecks')).toHaveValue('2000000,00'); await expect(page.locator('#term_months')).toHaveValue('12'); await expect(page.locator('#purpose')).toHaveValue('Купить две печи'); await expect(page.locator('input[value="equipment"]')).toBeChecked(); await expect(page).toHaveURL(/\/new$/);
});
for (const code of ['working_capital', 'equipment', 'overdraft', 'credit_line', 'investment', 'tender_guarantee']) test(`intake catalog product ${code}`, async ({ page }) => {
  await login(page); await page.route('**/api/v1/assistant/intake', route => route.fulfill({ json: intake(code) })); await openIntake(page); await analyze(page); await page.getByRole('button', { name: 'Применить к форме' }).click(); await expect(page.locator(`input[value="${code}"]`)).toBeChecked();
});
test('intake clears product extras', async ({ page }) => {
  await login(page); await page.route('**/api/v1/assistant/intake', route => route.fulfill({ json: intake() })); await openIntake(page); await page.locator('input[value="investment"]').check(); await page.locator('#project_description').fill('Старый проект'); await analyze(page); await page.getByRole('button', { name: 'Применить к форме' }).click(); await page.locator('input[value="investment"]').check(); await expect(page.locator('#project_description')).toHaveValue('');
});
for (const changed of ['text', 'form']) test(`intake invalidates settled and in-flight response on ${changed}`, async ({ page }) => {
  await login(page); let release: (() => void) | undefined; let delayed = false;
  await page.route('**/api/v1/assistant/intake', async route => { if (delayed) await new Promise<void>(resolve => { release = resolve; }); await route.fulfill({ json: intake() }).catch(() => {}); });
  await openIntake(page); await analyze(page); await expect(page.getByRole('button', { name: 'Применить к форме' })).toBeVisible();
  if (changed === 'text') await page.getByLabel('Что нужно вашему бизнесу').fill('Изменённый запрос'); else await page.locator('#revenue_kopecks').fill('900000');
  await expect(page.getByRole('button', { name: 'Применить к форме' })).toHaveCount(0); delayed = true; await analyze(page); await expect.poll(() => Boolean(release)).toBe(true);
  if (changed === 'text') await page.getByLabel('Что нужно вашему бизнесу').fill('Ещё один запрос'); else await page.locator('#revenue_kopecks').fill('800000');
  release!(); await page.waitForTimeout(150); await expect(page.getByRole('button', { name: 'Применить к форме' })).toHaveCount(0); await expect(page.locator('#amount_kopecks')).toHaveValue('');
});
test('unavailable and malformed intake preserve normal saving', async ({ page }) => {
  await login(page); await page.route('**/api/v1/assistant/intake', route => route.fulfill({ status: 503, json: { code: 'assistant_unavailable', message: 'Помощник временно недоступен' } })); await openIntake(page); await analyze(page); await expect(page.locator('.intake-panel')).toContainText('Помощник временно недоступен');
  await page.route('**/api/v1/assistant/intake', route => route.fulfill({ json: { suggested_fields: { amount_kopecks: 'broken' } } })); await analyze(page); await expect(page.locator('.intake-panel')).toContainText('Не удалось прочитать ответ помощника');
  await page.getByRole('button', { name: 'Сохранить черновик' }).click(); await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/);
});
test('unsupported need cannot apply', async ({ page }) => {
  await login(page); await page.route('**/api/v1/assistant/intake', route => route.fulfill({ json: { ...intake(), unsupported_need: true } })); await openIntake(page); await analyze(page); await expect(page.locator('.intake-panel')).toContainText('не поддерживается'); await expect(page.getByRole('button', { name: 'Применить к форме' })).toHaveCount(0);
});
for (const width of [390, 1366]) test(`chat safe sources keyboard layout ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 }); await login(page); await page.route('**/api/v1/assistant/chat', route => route.fulfill({ json: answer() })); const panel = page.locator('.assistant-chat');
  await panel.getByText('Помощник', { exact: true }).focus(); await page.keyboard.press('Enter'); await page.keyboard.press('Tab');
  if (width > 640) { await expect(panel.getByRole('button', { name: 'Развернуть помощника' })).toBeFocused(); await page.keyboard.press('Tab'); }
  else await expect(panel.locator('.assistant-size-toggle')).toBeHidden();
  await expect(panel.getByRole('button', { name: 'Закрыть помощника' })).toBeFocused();
  await page.keyboard.press('Tab'); await expect(panel.locator('.assistant-examples button').first()).toBeFocused(); await page.keyboard.press('Tab'); await expect(panel.locator('.assistant-examples button').last()).toBeFocused(); await page.keyboard.press('Tab'); await expect(panel.getByLabel('Ваш вопрос')).toBeFocused(); expect(await panel.getByLabel('Ваш вопрос').evaluate(element => getComputedStyle(element).outlineStyle)).not.toBe('none');
  await panel.getByLabel('Ваш вопрос').fill('Какое оборудование?'); await panel.getByRole('button', { name: 'Спросить' }).click(); await expect(panel).toContainText('<b>Текст ответа</b>'); await panel.getByText('Источники (2)', { exact: true }).click();
  await expect(panel).toContainText('2 000 000 ₽'); await expect(panel).toContainText('12%'); await expect(panel).toContainText('Нужен счёт на оборудование. <img'); await expect(panel.locator('img, b')).toHaveCount(0); await expect(panel).not.toContainText('secret-uuid'); await expect(panel).not.toContainText('terms_fingerprint');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); await panel.getByRole('dialog').screenshot({ path: `${evidence}/chat-${width}.png` });
  await page.screenshot({ path: `${evidence}/chat-page-${width}.png` });
  await page.goto('/applications/new'); await page.getByText('Опишите задачу', { exact: true }).click(); await page.route('**/api/v1/assistant/intake', route => route.fulfill({ json: intake() })); await page.getByLabel('Что нужно вашему бизнесу').fill('Купить две печи за 2 млн'); await analyze(page); await expect(page.getByRole('button', { name: 'Применить к форме' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); await page.locator('.intake-panel').screenshot({ path: `${evidence}/intake-${width}.png` }); await page.screenshot({ path: `${evidence}/form-page-${width}.png`, fullPage: true });
});
test('client context and staff summary reset on polled version', async ({ page }) => {
  await login(page); await page.goto('/applications/new'); await page.getByRole('button', { name: 'Сохранить черновик' }).click(); await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/); const id = page.url().split('/').at(-1)!;
  const original = await (await page.request.get(`/api/v1/applications/${id}`)).json(); let version = original.version; let releaseSummary: (() => void) | undefined; let delaySummary = false;
  await page.route('**/api/v1/assistant/chat', async route => { expect(route.request().postDataJSON()).toMatchObject({ application_id: id, expected_version: version }); await route.fulfill({ json: answer(version) }); });
  const chat = page.locator('.assistant-chat'); await chat.getByText('Помощник', { exact: true }).click(); await chat.getByLabel('Ваш вопрос').fill('Какая сумма в заявке?'); await chat.getByRole('button', { name: 'Спросить' }).click(); await expect(chat).toContainText('подходит кредит'); await expect(page.locator('.staff-summary')).toHaveCount(0);
  await page.getByRole('button', { name: 'Выйти' }).click(); await login(page, true); await expect(page.locator('.assistant-chat')).toHaveCount(0);
  await page.route(`**/api/v1/applications/${id}`, route => route.fulfill({ json: { ...original, version, status: 'manual_review', available_actions: [] } }));
  await page.route(`**/api/v1/applications/${id}/assessment`, route => route.fulfill({ json: { application_id: id, revision_id: null, runs: [], risk_assessment: null } }));
  await page.route(`**/api/v1/applications/${id}/summary`, async route => { const response = { ...answer(version), revision_id: null, processing_run_id: null, generated_at: '2026-10-24T12:00:00Z' }; if (delaySummary) await new Promise<void>(resolve => { releaseSummary = resolve; }); await route.fulfill({ json: response }).catch(() => {}); });
  await page.goto(`/staff/applications/${id}`); await page.getByRole('button', { name: 'Сформировать сводку' }).click(); await expect(page.locator('.staff-summary')).toContainText('подходит кредит'); await page.locator('.staff-summary').screenshot({ path: `${evidence}/staff-summary.png` }); await page.setViewportSize({ width: 390, height: 900 }); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); await page.locator('.staff-summary').screenshot({ path: `${evidence}/staff-summary-390.png` }); version++;
  await expect(page.locator('.staff-summary')).not.toContainText('подходит кредит', { timeout: 7000 }); await expect(page.getByRole('button', { name: 'Сформировать сводку' })).toBeEnabled();
  delaySummary = true; await page.getByRole('button', { name: 'Сформировать сводку' }).click(); await expect.poll(() => Boolean(releaseSummary)).toBe(true); version++; await expect(page.getByRole('button', { name: 'Сформировать сводку' })).toBeEnabled({ timeout: 7000 }); releaseSummary!(); await page.waitForTimeout(100); await expect(page.locator('.staff-summary')).not.toContainText('подходит кредит');
});
test('identity change removes pending and completed intake suggestions', async ({ page }) => {
  await login(page); let release: (() => void) | undefined; let delayed = false;
  await page.route('**/api/v1/assistant/intake', async route => { if (delayed) await new Promise<void>(resolve => { release = resolve; }); await route.fulfill({ json: intake() }).catch(() => {}); });
  await openIntake(page); await analyze(page); await expect(page.getByRole('button', { name: 'Применить к форме' })).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new Event('credit-identity-changed'))); await expect(page.getByRole('button', { name: 'Применить к форме' })).toHaveCount(0);
  delayed = true; await analyze(page); await expect.poll(() => Boolean(release)).toBe(true); await page.evaluate(() => window.dispatchEvent(new Event('credit-identity-changed'))); release!(); await page.waitForTimeout(100); await expect(page.getByRole('button', { name: 'Применить к форме' })).toHaveCount(0);
});
test('chat unavailable retry malformed and insufficient context remain usable', async ({ page }) => {
  await login(page); const panel = page.locator('.assistant-chat'); await panel.getByText('Помощник', { exact: true }).click(); await panel.getByLabel('Ваш вопрос').fill('Что такое кредит?');
  // Ответ недоступного провайдера подменён: UI-проверка не расходует квоту модели.
  await panel.getByRole('button', { name: 'Спросить' }).click(); await expect(panel.getByRole('alert')).toBeVisible();
  await page.route('**/api/v1/assistant/chat', route => route.fulfill({ json: { ...answer(), sources: [null] } })); await panel.getByRole('button', { name: 'Повторить вопрос' }).click(); await expect(panel).toContainText('Не удалось прочитать ответ помощника');
  await page.route('**/api/v1/assistant/chat', route => route.fulfill({ json: { ...answer(), status: 'insufficient_context', sources: [], model: null, answer: 'В доступных сведениях нет ответа' } })); await panel.getByRole('button', { name: 'Повторить вопрос' }).click(); await expect(panel).toContainText('В доступных сведениях нет ответа'); await expect(panel.locator('.assistant-sources')).toHaveCount(0);
  await panel.getByLabel('Ваш вопрос').fill('Другой вопрос'); await expect(panel).toContainText('В доступных сведениях нет ответа');
});
test('structured sources show facts units missing data dates and no technical identifiers', async ({ page }) => {
  await login(page); const source = { id: 'application:private:summary', title: 'Сохранённые сведения', version: '4', text: JSON.stringify({ revision_id: 'secret-uuid', processing_run_id: 'secret-run', terms_fingerprint: 'secret-fingerprint', company: 'ignored', status: 'technical_failure', data: { probability: 0.125, terms: { amount_kopecks: 123456789, annual_rate_bps: 1750 }, available_flow_kopecks: '-10100', registered_at: '2026-01-15', document_types: ['financial_statement'], missing_document_types: ['equipment_invoice'], content_read: false, results: { registry: { liquidated: false }, tax: { expected_monthly_revenue_kopecks: null }, bki: { overdue_days: 12 } } } }) };
  await page.route('**/api/v1/assistant/chat', route => route.fulfill({ json: { ...answer(), sources: [source] } })); const panel = page.locator('.assistant-chat'); await panel.getByText('Помощник', { exact: true }).click(); await panel.getByLabel('Ваш вопрос').fill('Какие сведения?'); await panel.getByRole('button', { name: 'Спросить' }).click(); await panel.getByText('Источники (1)', { exact: true }).click();
  for (const value of ['Технический сбой', '12,5%', '1 234 567,89 ₽', '17,5%', '−101 ₽', '15.01.2026', 'Финансовая отчётность', 'Счёт на оборудование', 'Содержимое прочитано', 'Нет', 'Не указано', 'Дней просрочки']) await expect(panel).toContainText(value);
  for (const value of ['secret-uuid', 'secret-run', 'secret-fingerprint', 'probability', 'technical_failure', 'annual_rate_bps']) await expect(panel).not.toContainText(value);
});
test('chat keeps in-flight response while drafting and discards it after navigation', async ({ page }) => {
  await login(page); let release: (() => void) | undefined; await page.route('**/api/v1/assistant/chat', async route => { await new Promise<void>(resolve => { release = resolve; }); await route.fulfill({ json: answer() }).catch(() => {}); });
  const panel = page.locator('.assistant-chat'); await panel.getByText('Помощник', { exact: true }).click(); await panel.getByLabel('Ваш вопрос').fill('Старый вопрос'); await panel.getByRole('button', { name: 'Спросить' }).click(); await expect.poll(() => Boolean(release)).toBe(true); await panel.getByLabel('Ваш вопрос').fill('Новый вопрос'); release!(); await expect(panel).toContainText('подходит кредит'); await expect(panel.getByLabel('Ваш вопрос')).toHaveValue('Новый вопрос');
  release = undefined; await panel.getByRole('button', { name: 'Спросить' }).click(); await expect.poll(() => Boolean(release)).toBe(true); await page.goto('/applications/new'); release!(); await page.goto('/applications'); await expect(page.locator('.assistant-chat')).not.toContainText('подходит кредит');
});

for (const width of [390, 1366]) test(`floating assistant stays inside viewport and closes with Escape ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 800 }); await login(page);
  const panel = page.locator('.assistant-chat');
  expect(await panel.evaluate(element => getComputedStyle(element).position)).toBe('fixed');
  await panel.getByText('Помощник', { exact: true }).click();
  const dialog = panel.getByRole('dialog'); await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox(); expect(box).not.toBeNull();
  expect(box!.height).toBeLessThanOrEqual(600);
  expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(800);
  await panel.getByLabel('Ваш вопрос').fill('Как выбрать продукт?');
  await page.keyboard.press('Escape'); await expect(dialog).not.toBeVisible();
  await expect(panel.locator('.assistant-launcher')).toBeFocused();
  await page.keyboard.press('Enter'); await expect(dialog).toBeVisible();
  await expect(panel.getByLabel('Ваш вопрос')).toHaveValue('Как выбрать продукт?');
  await panel.getByRole('button', { name: 'Закрыть помощника' }).click(); await expect(dialog).not.toBeVisible();
});

test('staff summary error has its own full-width row and clear wording', async ({ page }) => {
  await login(page); await page.goto('/applications/new'); await page.getByRole('button', { name: 'Сохранить черновик' }).click();
  await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/); const id = page.url().split('/').at(-1)!;
  const original = await (await page.request.get(`/api/v1/applications/${id}`)).json();
  await page.getByRole('button', { name: 'Выйти' }).click(); await login(page, true);
  await page.route(`**/api/v1/applications/${id}`, route => route.fulfill({ json: { ...original, status: 'approved', available_actions: [] } }));
  await page.route(`**/api/v1/applications/${id}/assessment`, route => route.fulfill({ json: { application_id: id, revision_id: null, runs: [], risk_assessment: null } }));
  await page.goto(`/staff/applications/${id}`);
  const panel = page.locator('.staff-summary'); const button = panel.getByRole('button', { name: 'Сформировать сводку' });
  await button.click(); const alert = panel.getByRole('alert'); await expect(alert).toBeVisible();
  const actionBox = await button.boundingBox(); const errorBox = await alert.boundingBox();
  expect(errorBox!.y - actionBox!.y - actionBox!.height).toBeGreaterThanOrEqual(12);
  expect(errorBox!.x + errorBox!.width).toBeGreaterThanOrEqual(actionBox!.x + actionBox!.width - 1);
  await expect(page.getByText('Доступных команд сейчас нет', { exact: false })).toHaveCount(0);
  await expect(alert).not.toContainText('..'); await expect(alert).not.toContainText('заполнение формы');
  await panel.screenshot({ path: `${evidence}/staff-summary-error.png` });
});
