import { test, expect, type Page } from '@playwright/test';
const id = '00000000-0000-4000-8000-000000000050';
async function setup(page: Page, staff = false, conflict = false) {
  let withdrawn = false; const posts: unknown[] = [];
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    const item = { id, display_number: 'КЗ-50', version: withdrawn ? 5 : 4, status: withdrawn ? 'withdrawn' : 'needs_info', product_code: 'equipment', purpose: 'Оборудование', description: null, amount_kopecks: 100000000, term_months: 12, period_start: null, period_end: null, revenue_kopecks: null, operating_expenses_kopecks: null, existing_debt_payments_kopecks: null, tender_number: null, beneficiary_name: null, project_description: null, updated_at: '2026-10-25T09:00:00Z', public_reasons: withdrawn ? ['Заявка отозвана клиентом. Рассмотрение прекращено.'] : [], processing_status: withdrawn ? 'interrupted' : 'succeeded', information_requests: [{ id: 'request', status: 'open', message: 'Уточните выручку', requested_fields: [], requested_document_types: ['financial_statement'] }], offers: [], available_actions: withdrawn ? [] : staff ? [] : ['withdraw', 'respond_information'] };
    if (path.endsWith('/withdraw')) { posts.push(route.request().postDataJSON()); if (conflict) return route.fulfill({ status: 409, json: { code: 'version_conflict', message: 'Заявка изменилась' } }); withdrawn = true; return route.fulfill({ json: { ...item, status: 'withdrawn', version: 5, available_actions: [] } }); }
    const data: Record<string, unknown> = {
      '/api/v1/me': { id: staff ? 'staff' : 'client', role: staff ? 'staff' : 'client', display_name: 'Анна' }, '/api/v1/company': { id: 'company', name: 'Компания' },
      '/api/v1/products': { catalog_version: 'demo-v2', items: [] }, '/api/v1/auth/csrf': { csrf_token: 'csrf', user_id: staff ? 'staff' : 'client' },
      [`/api/v1/applications/${id}`]: item,
      [`/api/v1/applications/${id}/history`]: { items: withdrawn ? [{ id: 'event', event_type: 'application_withdrawn', actor_type: 'user', actor_id: 'client', application_version: 5, created_at: '2026-10-25T09:00:00Z' }] : [], total: withdrawn ? 1 : 0, limit: 10, offset: 0 },
      [`/api/v1/applications/${id}/assessment`]: { application_id: id, revision_id: 'revision', runs: withdrawn ? [{ id: 'run', revision_id: 'revision', status: 'interrupted', error_code: 'application_withdrawn', checks: [], risk_assessments: [], created_at: '2026-10-25T09:00:00Z' }] : [], risk_assessment: null },
    };
    return route.fulfill({ json: data[path] ?? { items: [], total: 0, limit: 20, offset: 0 } });
  });
  await page.goto(`${staff ? '/staff' : ''}/applications/${id}`);
  return { posts, withdraw: () => { withdrawn = true; } };
}

test('client cancels then confirms withdrawal and sees terminal state and history', async ({ page }, testInfo) => {
  const { posts } = await setup(page); const action = page.getByRole('button', { name: 'Отозвать заявку', exact: true });
  await expect(page.locator('.page-heading').getByRole('button', { name: 'Отозвать заявку', exact: true })).toBeVisible();
  await expect(action).toBeInViewport(); await page.screenshot({ path: testInfo.outputPath('withdrawal-top.png') }); await action.click();
  const dialog = page.getByRole('dialog', { name: 'Отозвать заявку?' }); await expect(dialog.getByRole('button', { name: 'Продолжить рассмотрение' })).toBeFocused();
  await page.keyboard.press('Tab'); await expect(dialog.getByRole('button', { name: 'Отозвать заявку', exact: true })).toBeFocused(); await page.keyboard.press('Tab'); await expect(dialog.getByRole('button', { name: 'Продолжить рассмотрение' })).toBeFocused();
  await page.keyboard.press('Escape'); await expect(dialog).toBeHidden(); expect(posts).toEqual([]); await expect(action).toBeFocused();
  await action.click(); await dialog.getByRole('button', { name: 'Продолжить рассмотрение' }).click(); await expect(dialog).toBeHidden(); expect(posts).toEqual([]);
  await action.click(); await dialog.getByRole('button', { name: 'Отозвать заявку', exact: true }).click();
  await expect(page.locator('.status-withdrawn')).toHaveText('Отозвана'); await expect(page.getByRole('button', { name: 'Отозвать заявку', exact: true })).toHaveCount(0);
  await expect(page.locator('.review-panel').getByText('Заявка отозвана клиентом. Рассмотрение прекращено.', { exact: true })).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Отправить ответ' })).toHaveCount(0); await expect(page.locator('main')).not.toContainText('Произошёл технический сбой'); await expect(page.locator('main')).not.toContainText('приложите новый файл');
  await expect(page.locator('.history')).toContainText('Заявка отозвана клиентом'); await expect(page.locator('main')).toContainText('Запрос уточнений до отзыва'); expect(posts).toEqual([{ expected_version: 4 }]);
});

test('version conflict prevents blind repeat and requires refreshing details', async ({ page }) => {
  const { posts } = await setup(page, false, true); await page.getByRole('button', { name: 'Отозвать заявку', exact: true }).click(); const dialog = page.getByRole('dialog', { name: 'Отозвать заявку?' }); await dialog.getByRole('button', { name: 'Отозвать заявку', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('Заявка изменилась'); await expect(dialog.getByRole('button', { name: 'Отозвать заявку', exact: true })).toBeDisabled(); await dialog.getByRole('button', { name: 'Обновить сведения' }).click(); await expect(dialog.getByRole('alert')).toHaveCount(0); expect(posts).toHaveLength(1);
});

for (const width of [320, 390]) test(`withdrawal is visible in the card heading ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 800 }); await setup(page);
  await expect(page.locator('.page-heading').getByRole('button', { name: 'Отозвать заявку', exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('staff sees withdrawal history and neutral interrupted processing without client commands', async ({ page }) => {
  const state = await setup(page, true); state.withdraw(); await page.reload(); await expect(page.locator('.status-withdrawn')).toHaveText('Отозвана');
  await expect(page.getByRole('button', { name: 'Отозвать заявку', exact: true })).toHaveCount(0); await expect(page.locator('main')).not.toContainText('из-за технического сбоя'); await expect(page.locator('main')).not.toContainText('Повторить обработку'); await expect(page.locator('.history')).toContainText('Клиент компании'); await expect(page.locator('main')).toContainText('Рассмотрение прекращено по отзыву клиента');
});

test('latest withdrawal event remains available on the last history page', async ({ page }) => {
  await setup(page);
  const events = Array.from({ length: 11 }, (_, index) => ({ id: `event-${index}`, event_type: index === 10 ? 'application_withdrawn' : 'draft_updated', actor_type: 'user', actor_id: 'client', application_version: index + 1, created_at: '2026-10-25T09:00:00Z' }));
  await page.route(`**/api/v1/applications/${id}/history?*`, route => { const offset = Number(new URL(route.request().url()).searchParams.get('offset')); return route.fulfill({ json: { items: events.slice(offset, offset + 10), total: 11, offset, limit: 10 } }); });
  await page.getByRole('button', { name: 'Отозвать заявку', exact: true }).click(); await page.getByRole('dialog', { name: 'Отозвать заявку?' }).getByRole('button', { name: 'Отозвать заявку', exact: true }).click();
  const history = page.locator('.history'); await history.getByRole('button', { name: 'Далее' }).click(); await expect(history).toContainText('Заявка отозвана клиентом'); await expect(history).toContainText('версия 11');
});

test('active application retains real processing failure wording', async ({ page }) => {
  await setup(page, true);
  await page.route(`**/api/v1/applications/${id}/assessment`, route => route.fulfill({ json: { application_id: id, revision_id: 'revision', runs: [{ id: 'failed-run', revision_id: 'revision', status: 'interrupted', error_code: 'worker_interrupted', checks: [], risk_assessments: [], created_at: '2026-10-25T09:00:00Z' }], risk_assessment: null } }));
  await page.reload(); await expect(page.locator('.assessment-panel')).toContainText('Обработка не завершена из-за технического сбоя');
});

for (const staff of [false, true]) test(`withdrawn status is available in ${staff ? 'staff' : 'client'} list filters`, async ({ page }) => {
  await setup(page, staff);
  await page.route('**/api/v1/applications?*', route => {
    const query = new URL(route.request().url()).searchParams; const filtered = query.has('status');
    return route.fulfill({ json: { items: filtered ? [] : [{ id, display_number: 'КЗ-50', status: 'withdrawn', product_code: 'equipment', amount_kopecks: 100000000, updated_at: '2026-10-25T09:00:00Z' }], total: filtered ? 0 : 21, limit: 20, offset: Number(query.get('offset')) } });
  });
  await page.goto(staff ? '/staff/applications' : '/applications'); await expect(page.locator('.application-row .status-withdrawn')).toHaveText('Отозвана');
  await page.getByRole('button', { name: 'Далее', exact: true }).click(); await expect(page.getByText('21–21 из 21', { exact: true })).toBeVisible();
  const select = page.getByRole('combobox', { name: 'Статус', exact: true }); await select.click();
  const menu = page.getByRole('listbox', { name: 'Статус', exact: true });
  await expect(menu.getByRole('option', { name: 'Отозвана', exact: true })).toHaveCount(1);
  await expect(menu.getByRole('option', { name: 'Черновик', exact: true })).toHaveCount(staff ? 0 : 1);
  const filtered = page.waitForRequest(request => { const url = new URL(request.url()); return url.pathname === '/api/v1/applications' && url.searchParams.get('status') === 'withdrawn' && url.searchParams.get('offset') === '0'; });
  await menu.getByRole('option', { name: 'Отозвана', exact: true }).click(); await filtered;
  await expect(page.getByRole('heading', { name: 'Заявок с таким статусом нет' })).toBeVisible();
  await page.getByRole('button', { name: 'Сбросить фильтр' }).click(); await expect(select).toHaveText('Все статусы');
});

for (const width of [320, 390, 1366]) test(`status picker shares heading actions and supports keyboard ${width}`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 800 }); await setup(page);
  await page.goto('/applications');
  const picker = page.getByRole('combobox', { name: 'Статус', exact: true });
  const create = page.locator('.page-heading').getByRole('link', { name: 'Новая заявка' });
  await expect(picker).toBeVisible();
  const filterBox = await picker.boundingBox(), createBox = await create.boundingBox();
  expect(Math.abs(filterBox!.y - createBox!.y)).toBeLessThan(3);
  expect(filterBox!.x + filterBox!.width).toBeLessThanOrEqual(createBox!.x);
  await picker.focus(); await page.keyboard.press('Enter');
  await expect(page.getByRole('option', { name: 'Все статусы', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.keyboard.press('End'); await page.keyboard.press('Enter'); await expect(picker).toHaveText('Отозвана');
  await picker.click(); await page.keyboard.press('Escape'); await expect(page.getByRole('listbox')).toHaveCount(0); await expect(picker).toBeFocused();
  await picker.click(); await page.getByRole('heading', { name: 'Мои заявки', exact: true }).click(); await expect(page.getByRole('listbox')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await picker.click();
  const check = page.getByRole('option', { name: 'Отозвана', exact: true }).locator('.status-option-check');
  const checkBox = await check.boundingBox(), tickBox = await check.locator('svg').boundingBox();
  expect(tickBox!.width).toBeLessThan(checkBox!.width);
  expect(tickBox!.height).toBeLessThan(checkBox!.height);
  await page.screenshot({ path: testInfo.outputPath(`status-picker-${width}.png`) });
});
