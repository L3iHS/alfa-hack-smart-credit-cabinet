import { readFile } from 'node:fs/promises';
import { test, expect, type Page } from '@playwright/test';

const id = '00000000-0000-4000-8000-000000000052';
const application = (version = 4) => ({ id, display_number: 'КЗ-000052', version, status: 'manual_review', updated_at: '2026-10-25T09:00:00Z', catalog_version: 'demo-v2', product_code: 'equipment', purpose: 'Купить печь', description: null, amount_kopecks: 100000001, term_months: 12, period_start: null, period_end: null, revenue_kopecks: null, operating_expenses_kopecks: null, existing_debt_payments_kopecks: null, tender_number: null, beneficiary_name: null, project_description: null, public_reasons: [], processing_status: null, information_requests: [], offers: [], available_actions: [] });
const summary = (version = 4, answer = '### Запрос клиента\n\n- Купить печь.\n\n### Финансы\n\n- Выручка не указана.\n\n### Проверки и документы\n\n- Файл не прочитан.\n\n### Расчёт и риск\n\n- Нет оценки.\n\n### Результат и следующий шаг\n\n- На рассмотрении.') => ({ status: 'answered', answer, application_version: version, generated_at: '2026-10-25T09:00:00Z', sources: [
  { id: 'application:summary:units', title: 'Единицы величин и границы сведений', version: '4', text: '{"money":"100 копеек = 1 рубль"}' },
  { id: 'application:summary:checks', title: 'Проверки и условия', version: '4', text: JSON.stringify({ results: { registry: { liquidated: false }, tax: { expected_monthly_revenue_kopecks: 123456789 }, bki: { overdue_days: 0 } }, data: { terms: { amount_kopecks: 100000001, annual_rate_bps: 1750 }, available_flow_kopecks: -10101, total_cost_kopecks: Number.MAX_SAFE_INTEGER }, terms_fingerprint: 'secret-fingerprint' }) },
] });
async function setup(page: Page, staff = true) {
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    const responses: Record<string, unknown> = {
      '/api/v1/me': { id: 'usability-user', role: staff ? 'staff' : 'client', display_name: 'Анна', email: 'usability@example.test' },
      '/api/v1/company': { id: 'usability-company', name: 'ООО «Пекарня»', inn: '7701234567', industry: 'Производство', registered_at: '2020-01-01' },
      '/api/v1/products': { catalog_version: 'demo-v2', items: [] },
      '/api/v1/applications': { items: [], total: 0, limit: 20, offset: 0 },
      '/api/v1/auth/csrf': { csrf_token: 'usability-csrf', user_id: 'usability-user' },
      [`/api/v1/applications/${id}`]: application(),
      [`/api/v1/applications/${id}/assessment`]: { application_id: id, revision_id: null, runs: [], risk_assessment: null },
    };
    return path in responses ? route.fulfill({ json: responses[path] }) : route.fulfill({ status: 503, json: { code: 'assistant_unavailable', message: 'Помощник временно недоступен' } });
  });
}
const summaryRoute = /\/api\/v1\/applications\/[^/]+\/summary(?:\?|$)/;
async function openChat(page: Page) {
  await page.getByRole('button', { name: 'Помощник', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Помощник по кредитам' });
  await dialog.evaluate(element => Promise.all(element.getAnimations().map(animation => animation.finished)));
  return dialog;
}

for (const width of [390, 1366]) test(`saved summary restores without generation and exports readable safe Markdown ${width}`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 900 }); await setup(page);
  const methods: string[] = [];
  await page.route(summaryRoute, route => { methods.push(route.request().method()); expect(new URL(route.request().url()).searchParams.get('expected_version')).toBe('4'); return route.fulfill({ json: summary(4, summary().answer + '\n\n<script>alert(1)</script>') }); });
  await page.goto(`/staff/applications/${id}`);
  const panel = page.getByRole('region', { name: 'Сводка помощника' });
  await expect(panel.getByRole('heading', { name: 'Запрос клиента', exact: true })).toBeVisible();
  expect(methods.length).toBeGreaterThan(0); expect(methods.every(method => method === 'GET')).toBe(true);
  await expect(panel.getByRole('button', { name: 'Обновить сводку' })).toBeEnabled();
  await expect(panel.locator('.assistant-answer h3')).toHaveCount(5);
  await panel.getByText('Источники (1)', { exact: true }).click();
  for (const text of ['Реестр компаний', 'Налоговые сведения', 'Кредитная история', '1 234 567,89 ₽', '1 000 000,01 ₽', '−101,01 ₽', '90 071 992 547 409,91 ₽', '17,5%']) await expect(panel).toContainText(text);
  for (const text of ['Сохранённые сведения /', 'secret-fingerprint', 'копеек', 'базисных']) await expect(panel).not.toContainText(text);
  await expect(panel.locator('script, img, a')).toHaveCount(0);
  const downloadEvent = page.waitForEvent('download'); await panel.getByRole('button', { name: 'Скачать сводку в Markdown' }).click();
  const download = await downloadEvent; expect(download.suggestedFilename()).toBe('summary-КЗ-000052-2026-10-25.md');
  const content = await readFile((await download.path())!, 'utf8');
  for (const text of ['КЗ-000052', '25.10.2026', '### Запрос клиента', '## Источники', '1 000 000,01 ₽', '&lt;script&gt;']) expect(content).toContain(text);
  expect(content).not.toContain('<script>'); expect(content).not.toContain('копеек');
  const heading = await panel.locator('.assistant-summary-heading h2').boundingBox();
  const action = await panel.getByRole('button', { name: 'Обновить сводку' }).boundingBox();
  if (width > 640) expect(Math.abs(heading!.y - action!.y)).toBeLessThan(20);
  if (width > 640) {
    const count = methods.length;
    await page.waitForRequest(request => new URL(request.url()).pathname === `/api/v1/applications/${id}`);
    expect(methods).toHaveLength(count);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await panel.screenshot({ path: info.outputPath(`summary-${width}.png`) });
});

test('empty cache needs explicit creation and explicit refresh preserves a saved answer on provider failure', async ({ page }) => {
  await setup(page); let saved: ReturnType<typeof summary> | null = null; const posts: unknown[] = []; let fail = false;
  await page.route(summaryRoute, route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: saved });
    posts.push(route.request().postDataJSON());
    if (fail) return route.fulfill({ status: 503, json: { code: 'assistant_unavailable' } });
    saved = summary(); return route.fulfill({ json: saved });
  });
  await page.goto(`/staff/applications/${id}`); const panel = page.locator('.staff-summary');
  await expect(panel.getByRole('button', { name: 'Сформировать сводку' })).toBeEnabled(); expect(posts).toEqual([]);
  await panel.getByRole('button', { name: 'Сформировать сводку' }).click();
  await expect(panel.getByRole('button', { name: 'Обновить сводку' })).toBeEnabled(); expect(posts).toEqual([{ expected_version: 4, refresh: false }]);
  fail = true; await panel.getByRole('button', { name: 'Обновить сводку' }).click();
  await expect(panel.getByRole('alert')).toBeVisible(); await expect(panel).toContainText('Купить печь.');
  expect(posts).toEqual([{ expected_version: 4, refresh: false }, { expected_version: 4, refresh: true }]);
  fail = false; await panel.getByRole('button', { name: 'Обновить сводку' }).click(); await expect(panel.getByRole('alert')).toHaveCount(0);
  expect(posts.at(-1)).toEqual({ expected_version: 4, refresh: true });
  await page.reload(); await expect(panel).toContainText('Купить печь.'); expect(posts).toHaveLength(3);
});

test('late cache and generated answers stay isolated by version and identity', async ({ page }) => {
  await setup(page); let version = 4; let release: (() => void) | undefined; let delay = true;
  await page.route(`**/api/v1/applications/${id}`, route => route.fulfill({ json: application(version) }));
  await page.route(summaryRoute, async route => {
    const v = route.request().method() === 'GET' ? Number(new URL(route.request().url()).searchParams.get('expected_version')) : route.request().postDataJSON().expected_version;
    if (delay) await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({ json: summary(v, `Сводка версии ${v}`) }).catch(() => {});
  });
  await page.goto(`/staff/applications/${id}`); const panel = page.locator('.staff-summary'); await expect.poll(() => Boolean(release)).toBe(true);
  const oldRelease = release!; version = 5; delay = false;
  await expect(panel).toContainText('Сводка версии 5', { timeout: 7000 }); oldRelease();
  await expect(panel).not.toContainText('Сводка версии 4');
  delay = true; release = undefined; await panel.getByRole('button', { name: 'Обновить сводку' }).click(); await expect.poll(() => Boolean(release)).toBe(true);
  await page.evaluate(() => window.dispatchEvent(new Event('credit-identity-changed'))); release!();
  await expect(panel).not.toContainText('Сводка версии 5'); await expect(panel.getByRole('button', { name: 'Скачать сводку в Markdown' })).toHaveCount(0);
});

test('malformed saved summary is rejected and lost access removes exportable content', async ({ page }) => {
  await setup(page); let valid = false; let posts = 0;
  await page.route(summaryRoute, route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: valid ? summary() : { ...summary(), generated_at: undefined } });
    posts++; return route.fulfill({ status: 403, json: { code: 'operation_forbidden', message: 'Доступ к ответу изменился' } });
  });
  await page.goto(`/staff/applications/${id}`); const panel = page.locator('.staff-summary');
  await expect(panel.getByRole('alert')).toContainText('Не удалось прочитать ответ помощника');
  await expect(panel.getByRole('button', { name: 'Скачать сводку в Markdown' })).toHaveCount(0); expect(posts).toBe(0);
  valid = true; await page.reload(); await expect(panel).toContainText('Купить печь.');
  await panel.getByRole('button', { name: 'Обновить сводку' }).click(); await expect(panel.getByRole('alert')).toBeVisible();
  await expect(panel).not.toContainText('Купить печь.'); await expect(panel.getByRole('button', { name: 'Скачать сводку в Markdown' })).toHaveCount(0); expect(posts).toBe(1);
});

test('chat explains list context, shows application number, resizes up left and offers keyboard reset', async ({ page }, info) => {
  await setup(page, false); await page.goto('/applications'); const dialog = await openChat(page);
  await expect(dialog).toContainText('По продуктам и документам'); await expect(dialog).toContainText('откройте её карточку');
  const input = dialog.getByLabel('Ваш вопрос'); await expect(input).toBeVisible();
  await expect(input).toHaveCSS('height', '56px');
  expect(await dialog.getByText('Ваш вопрос', { exact: true }).evaluate(element => element.getBoundingClientRect().width)).toBe(1);
  await input.fill('Черновик'); const initial = (await dialog.boundingBox())!;
  const handle = (await dialog.locator('.assistant-resize-handle').boundingBox())!;
  expect(handle.width).toBeGreaterThanOrEqual(36);
  expect(handle.height).toBeGreaterThanOrEqual(36);
  expect(handle.x).toBeGreaterThan(initial.x + 5);
  expect(handle.y).toBeGreaterThan(initial.y + 5);
  await page.mouse.move(handle.x + 18, handle.y + 18); await page.mouse.down(); await page.mouse.move(handle.x - 260, handle.y - 130, { steps: 8 }); await page.mouse.up();
  const resized = (await dialog.boundingBox())!; expect(resized.width).toBeGreaterThan(initial.width + 200); expect(resized.height).toBeGreaterThan(initial.height + 100);
  expect(Math.abs(resized.x + resized.width - initial.x - initial.width)).toBeLessThan(2);
  expect(Math.abs(resized.y + resized.height - initial.y - initial.height)).toBeLessThan(2);
  await expect(input).toHaveValue('Черновик');
  const reset = dialog.getByRole('button', { name: 'Вернуть обычный размер помощника' }); await reset.focus(); await page.keyboard.press('Enter');
  expect((await dialog.boundingBox())!.width).toBe(initial.width);
  await dialog.getByRole('button', { name: 'Развернуть помощника' }).focus(); await page.keyboard.press('Enter');
  const expanded = (await dialog.boundingBox())!; expect(expanded.x).toBeGreaterThanOrEqual(0); expect(expanded.y).toBeGreaterThanOrEqual(0);
  await page.setViewportSize({ width: 390, height: 540 });
  const mobile = (await dialog.boundingBox())!; expect(mobile.width).toBeLessThanOrEqual(390); expect(mobile.x).toBeGreaterThanOrEqual(0); expect(mobile.y).toBeGreaterThanOrEqual(0);
  await expect(input).toBeInViewport(); await expect(dialog.getByRole('button', { name: 'Спросить', exact: true })).toBeInViewport();
  await page.screenshot({ path: info.outputPath('assistant-resized-mobile.png') });
  await page.goto(`/applications/${id}`); const contextual = await openChat(page); await expect(contextual).toContainText('По заявке № КЗ-000052');
});
