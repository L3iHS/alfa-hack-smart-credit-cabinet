import { test, expect, type Page } from '@playwright/test';
const id = '00000000-0000-4000-8000-000000000049';
async function setup(page: Page, application = true) {
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    const data: Record<string, unknown> = {
      '/api/v1/me': { id: 'dialog-user', role: 'client', display_name: 'Анна' },
      '/api/v1/company': { id: 'company', name: 'Компания' },
      '/api/v1/products': { catalog_version: 'demo-v2', items: [] },
      '/api/v1/applications': { items: [], total: 0, limit: 20, offset: 0 },
      '/api/v1/auth/csrf': { csrf_token: 'csrf', user_id: 'dialog-user' },
      [`/api/v1/applications/${id}`]: { id, display_number: 'КЗ-49', version: 4, status: 'manual_review', product_code: 'equipment', purpose: 'Оборудование', description: null, amount_kopecks: 100000000, term_months: 12, period_start: null, period_end: null, revenue_kopecks: null, operating_expenses_kopecks: null, existing_debt_payments_kopecks: null, tender_number: null, beneficiary_name: null, project_description: null, updated_at: '2026-10-25T09:00:00Z', public_reasons: [], information_requests: [], offers: [], available_actions: [] },
    };
    return route.fulfill({ json: data[path] ?? { items: [], total: 0, limit: 10, offset: 0 } });
  });
  await page.goto(application ? `/applications/${id}` : '/applications');
  await page.getByRole('button', { name: 'Помощник', exact: true }).click();
  return page.getByRole('dialog', { name: 'Помощник по кредитам' });
}
const reply = (answer: string, version: number | null = 4, status = 'answered') => ({ status, answer, application_version: version, sources: status === 'answered' ? [{ id: answer, title: `Источник ${answer}`, text: answer, version: '4' }] : [] });
async function send(dialog: ReturnType<Page['getByRole']>, question: string) { await dialog.getByLabel('Ваш вопрос').fill(question); await dialog.getByRole('button', { name: 'Спросить', exact: true }).click(); }

test('transcript appends source-scoped answers and retries an older error with only its prior history', async ({ page }) => {
  const dialog = await setup(page); const bodies: { question: string; history?: unknown[] }[] = []; let failed = false;
  await page.route('**/api/v1/assistant/chat', route => {
    const body = route.request().postDataJSON(); bodies.push(body);
    if (body.question === 'Ошибка' && !failed) { failed = true; return route.fulfill({ status: 503, json: { code: 'assistant_unavailable' } }); }
    return route.fulfill({ json: reply(`Ответ ${body.question}`) });
  });
  await send(dialog, 'Первый'); await expect(dialog).toContainText('Ответ Первый');
  await send(dialog, 'Ошибка'); await expect(dialog.getByRole('alert')).toBeVisible();
  await send(dialog, 'Позже'); await expect(dialog).toContainText('Ответ Позже');
  await dialog.getByLabel('Ваш вопрос').fill('Следующий черновик');
  await dialog.getByRole('button', { name: 'Повторить вопрос' }).click(); await expect(dialog).toContainText('Ответ Ошибка');
  await expect(dialog.getByRole('group', { name: 'Ваше сообщение' })).toHaveCount(3);
  await expect(dialog.locator('.assistant-result')).toHaveCount(3);
  await expect(dialog.getByLabel('Ваш вопрос')).toHaveValue('Следующий черновик');
  expect(bodies.map(body => body.history)).toEqual([[], [{ question: 'Первый', answer: 'Ответ Первый' }], [{ question: 'Первый', answer: 'Ответ Первый' }], [{ question: 'Первый', answer: 'Ответ Первый' }]]);
  for (const [index, text] of ['Первый', 'Ошибка', 'Позже'].entries()) {
    const turn = dialog.locator('.assistant-turn').nth(index); await turn.getByText('Источники (1)', { exact: true }).click(); await expect(turn).toContainText(`Источник Ответ ${text}`);
  }
});

test('new dialog aborts pending generation and late response cannot enter the fresh transcript', async ({ page }) => {
  const dialog = await setup(page); let release: (() => void) | undefined; const histories: unknown[] = [];
  await page.route('**/api/v1/assistant/chat', async route => { const body = route.request().postDataJSON(); histories.push(body.history); if (histories.length === 1) await new Promise<void>(resolve => { release = resolve; }); await route.fulfill({ json: reply(histories.length === 1 ? 'Старый ответ' : 'Новый ответ') }).catch(() => {}); });
  await send(dialog, 'Старый'); await expect.poll(() => Boolean(release)).toBe(true);
  await dialog.getByLabel('Ваш вопрос').fill('Старый черновик'); await dialog.getByRole('button', { name: 'Новый диалог', exact: true }).click();
  await expect(dialog.getByRole('group', { name: 'Ваше сообщение' })).toHaveCount(0); await expect(dialog.getByLabel('Ваш вопрос')).toHaveValue('');
  release!(); await send(dialog, 'Новый'); await expect(dialog).toContainText('Новый ответ'); await expect(dialog).not.toContainText('Старый ответ'); expect(histories).toEqual([[], []]);
});

test('history retains whole recent successful pairs within six and total limits', async ({ page }) => {
  const dialog = await setup(page); const histories: { question: string; answer: string }[][] = [];
  await page.route('**/api/v1/assistant/chat', route => { const body = route.request().postDataJSON(); histories.push(body.history); const n = Number(body.question); return route.fulfill({ json: reply(n === 2 ? 'Недостаточно сведений' : n === 3 ? 'x'.repeat(6001) : n === 7 || n === 8 ? 'y'.repeat(5999) : `Ответ ${n}`, 4, n === 2 ? 'insufficient_context' : 'answered') }); });
  for (let n = 1; n <= 15; n++) { await send(dialog, String(n)); await expect(dialog.getByRole('button', { name: 'Спросить', exact: true })).toBeDisabled(); await expect(dialog.getByRole('status')).toHaveCount(0); }
  expect(histories[4].map(pair => pair.question)).toEqual(['1', '4']);
  expect(histories[9].map(pair => pair.question)).toEqual(['8', '9']);
  expect(histories[14].map(pair => pair.question)).toEqual(['9', '10', '11', '12', '13', '14']);
  expect(histories.every(pairs => pairs.length <= 6 && pairs.reduce((sum, pair) => sum + pair.question.length + pair.answer.length, 0) <= 12000)).toBe(true);
});

test('reference chat never sends application history', async ({ page }) => {
  const dialog = await setup(page, false); const histories: unknown[] = [];
  await page.route('**/api/v1/assistant/chat', route => { histories.push(route.request().postDataJSON().history); return route.fulfill({ json: reply('Справочный ответ', null) }); });
  await send(dialog, 'Первый'); await expect(dialog).toContainText('Справочный ответ'); await send(dialog, 'Второй'); await expect(dialog.locator('.assistant-result')).toHaveCount(2); expect(histories).toEqual([[], []]);
});

for (const width of [390, 1366]) test(`appended messages scroll only the widget at width ${width}`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 700 }); const dialog = await setup(page);
  await page.route('**/api/v1/assistant/chat', route => route.fulfill({ json: reply('Подробный ответ. '.repeat(80)) }));
  const before = await page.evaluate(() => scrollY);
  await send(dialog, 'Первый длинный вопрос'); await expect(dialog.locator('.assistant-result')).toHaveCount(1);
  await send(dialog, 'Второй вопрос'); await expect(dialog.locator('.assistant-result')).toHaveCount(2);
  expect(await page.evaluate(() => scrollY)).toBe(before);
  const body = dialog.locator('.assistant-body'); expect(await body.evaluate(element => element.scrollTop > 0 && element.scrollHeight - element.scrollTop - element.clientHeight < 2)).toBe(true);
  await expect(dialog.getByLabel('Ваш вопрос')).toBeInViewport(); await expect(dialog.getByRole('button', { name: 'Новый диалог', exact: true })).toBeInViewport();
  await dialog.screenshot({ path: info.outputPath(`dialog-transcript-${width}.png`) });
});
