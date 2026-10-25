import { test, expect, type Page } from '@playwright/test';

// Подменяем только HTTP: настоящий интерфейс и управление запросами остаются в работе.
async function openCabinet(page: Page, staff = false) {
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    const responses: Record<string, unknown> = {
      '/api/v1/me': { id: 'messages-user', role: staff ? 'staff' : 'client', display_name: 'Анна', email: 'client@example.test' },
      '/api/v1/company': { id: 'messages-company', name: 'ООО «Пекарня»', inn: '7701234567', industry: 'Пищевое производство', registered_at: '2020-01-01' },
      '/api/v1/products': { catalog_version: 'demo-v2', items: [] },
      '/api/v1/applications': { items: [], total: 0, limit: 20, offset: 0 },
      '/api/v1/auth/csrf': { csrf_token: 'messages-csrf', user_id: 'messages-user' },
    };
    return path in responses ? route.fulfill({ json: responses[path] }) : route.fulfill({ status: 503, json: { code: 'assistant_unavailable', message: 'Помощник временно недоступен' } });
  });
  await page.goto(staff ? '/staff/applications' : '/applications');
}
const reply = (answer = 'Для покупки оборудования нужен счёт.', version: number | null = null) => ({ status: 'answered', answer, application_version: version, sources: [{ id: 'equipment', title: 'Кредит на оборудование', text: 'Нужен счёт на оборудование.', version: 'demo-v2' }] });
async function openAssistant(page: Page) {
  await page.getByRole('button', { name: 'Помощник', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Помощник по кредитам' });
  await expect(dialog).toBeVisible();
  await dialog.evaluate(element => Promise.all(element.getAnimations().map(animation => animation.finished)));
  return dialog;
}

test('sent question appears in chat and next draft survives the pending and completed answer', async ({ page }, testInfo) => {
  await openCabinet(page); let release: (() => void) | undefined; const questions: string[] = [];
  await page.route('**/api/v1/assistant/chat', async route => {
    questions.push(route.request().postDataJSON().question);
    await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({ json: reply() }).catch(() => {});
  });
  const dialog = await openAssistant(page); const input = dialog.getByLabel('Ваш вопрос');
  await input.fill('  Какие документы нужны?  '); await dialog.getByRole('button', { name: 'Спросить', exact: true }).click();
  await expect(dialog.getByRole('group', { name: 'Ваше сообщение' })).toContainText('Какие документы нужны?');
  await expect(input).toHaveValue(''); await expect(input).toBeFocused();
  await input.fill('Как выбрать срок?'); await expect(dialog.getByRole('button', { name: 'Готовим ответ…' })).toBeDisabled();
  await expect.poll(() => Boolean(release)).toBe(true); release!();
  await expect(dialog).toContainText('Для покупки оборудования нужен счёт.'); await expect(input).toHaveValue('Как выбрать срок?');
  expect(questions).toEqual(['Какие документы нужны?']);
  await page.keyboard.press('Escape'); await openAssistant(page);
  await expect(dialog.getByRole('group', { name: 'Ваше сообщение' })).toContainText('Какие документы нужны?');
  await expect(input).toHaveValue('Как выбрать срок?');
  await page.screenshot({ path: testInfo.outputPath('assistant-exchange.png') });
  release = undefined; await dialog.getByRole('button', { name: 'Спросить', exact: true }).click();
  await expect(dialog.getByRole('group', { name: 'Ваше сообщение' })).toContainText('Как выбрать срок?');
  await expect(dialog).not.toContainText('Для покупки оборудования нужен счёт.'); await expect(input).toHaveValue('');
  await expect.poll(() => Boolean(release)).toBe(true); release!(); await expect(dialog).toContainText('Для покупки оборудования нужен счёт.');
  expect(questions).toEqual(['Какие документы нужны?', 'Как выбрать срок?']);
});

test('retry resends the failed question and preserves a new draft without automatic requests', async ({ page }) => {
  await openCabinet(page); let release: (() => void) | undefined; const questions: string[] = [];
  await page.route('**/api/v1/assistant/chat', async route => {
    questions.push(route.request().postDataJSON().question);
    if (questions.length === 1) return route.fulfill({ status: 503, json: { code: 'assistant_unavailable', message: 'Помощник временно недоступен' } });
    await new Promise<void>(resolve => { release = resolve; }); await route.fulfill({ json: reply() }).catch(() => {});
  });
  const dialog = await openAssistant(page); const input = dialog.getByLabel('Ваш вопрос');
  await input.fill('Какие документы нужны?'); await dialog.getByRole('button', { name: 'Спросить', exact: true }).click();
  await expect(dialog.getByRole('alert')).toBeVisible(); await expect(input).toHaveValue('');
  await expect(dialog.getByRole('button', { name: 'Спросить', exact: true })).toBeDisabled();
  await input.fill('Мой следующий вопрос'); expect(questions).toEqual(['Какие документы нужны?']);
  await dialog.getByRole('button', { name: 'Повторить вопрос', exact: true }).click(); await expect.poll(() => Boolean(release)).toBe(true);
  await expect(dialog.getByRole('button', { name: 'Повторить вопрос', exact: true })).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Готовим ответ…' })).toBeDisabled();
  release!(); await expect(dialog).toContainText('Для покупки оборудования нужен счёт.'); await expect(input).toHaveValue('Мой следующий вопрос');
  expect(questions).toEqual(['Какие документы нужны?', 'Какие документы нужны?']);
});

test('pending dot breathes by size without blinking and respects reduced motion', async ({ page }, testInfo) => {
  await openCabinet(page); let release: (() => void) | undefined;
  await page.route('**/api/v1/assistant/chat', async route => { await new Promise<void>(resolve => { release = resolve; }); await route.fulfill({ json: reply() }).catch(() => {}); });
  const dialog = await openAssistant(page); await dialog.getByLabel('Ваш вопрос').fill('Какие документы нужны?'); await dialog.getByRole('button', { name: 'Спросить', exact: true }).click();
  const dot = dialog.getByRole('status').locator('span'); await expect(dot).not.toHaveCSS('animation-name', 'none');
  const frames = await dot.evaluate(element => {
    const animation = element.getAnimations()[0]; animation.pause(); const duration = Number(animation.effect!.getTiming().duration);
    animation.currentTime = 0; const start = getComputedStyle(element).transform;
    animation.currentTime = duration / 2; const middle = getComputedStyle(element).transform;
    return { start, middle, opacity: getComputedStyle(element).opacity };
  });
  expect(frames.start).not.toBe(frames.middle); expect(frames.opacity).toBe('1');
  await page.screenshot({ path: testInfo.outputPath('assistant-pending.png') });
  await page.emulateMedia({ reducedMotion: 'reduce' }); await expect(dot).toHaveCSS('animation-name', 'none'); await expect(dialog.getByRole('status')).toContainText('Ищем ответ');
  await expect.poll(() => Boolean(release)).toBe(true); release!(); await expect(dialog).toContainText('Для покупки оборудования нужен счёт.');
});

test('answers safely render headings lists paragraphs and emphasis while markup stays literal', async ({ page }, testInfo) => {
  await openCabinet(page);
  const structured = '### Документы\n\nДля покупки оборудования подготовьте **счёт**.\n\n- Счёт на оборудование\n- Финансовая отчётность\n\n1. Выберите продукт\n2. Заполните заявку\n\n<img src=x onerror=alert(1)> [Сайт](https://example.test)\nЕщё одна строка.';
  await page.route('**/api/v1/assistant/chat', route => route.fulfill({ json: reply(structured) }));
  const dialog = await openAssistant(page); await dialog.getByLabel('Ваш вопрос').fill('Какие документы нужны?'); await dialog.getByRole('button', { name: 'Спросить', exact: true }).click();
  const answer = dialog.locator('.assistant-answer'); await expect(answer.getByRole('heading', { name: 'Документы', level: 3 })).toBeVisible();
  await expect(answer.locator('strong')).toHaveText('счёт'); await expect(answer.locator('ul > li')).toHaveText(['Счёт на оборудование', 'Финансовая отчётность']);
  await expect(answer.locator('ol > li')).toHaveText(['Выберите продукт', 'Заполните заявку']);
  await expect(answer).toContainText('<img src=x onerror=alert(1)> [Сайт](https://example.test)'); await expect(answer.locator('img, a, script')).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('assistant-structured.png') });
});

test('legacy plain answers preserve paragraphs newlines and incomplete formatting', async ({ page }) => {
  await openCabinet(page); await page.route('**/api/v1/assistant/chat', route => route.fulfill({ json: reply('Первый абзац.\nЕщё строка.\n\nВторой абзац с неизвестным # знаком и незакрытой **меткой.') }));
  const dialog = await openAssistant(page); await dialog.getByLabel('Ваш вопрос').fill('Что нужно?'); await dialog.getByRole('button', { name: 'Спросить', exact: true }).click();
  await expect(dialog.locator('.assistant-answer > p')).toHaveText(['Первый абзац.\nЕщё строка.', 'Второй абзац с неизвестным # знаком и незакрытой **меткой.']);
});

const application = (version: number) => ({ id: '00000000-0000-4000-8000-000000000048', version, status: 'manual_review', updated_at: '2026-10-24T12:00:00Z', catalog_version: 'demo-v2', product_code: 'equipment', purpose: 'Купить печь', description: null, amount_kopecks: 100000000, term_months: 12, period_start: null, period_end: null, revenue_kopecks: null, operating_expenses_kopecks: null, existing_debt_payments_kopecks: null, tender_number: null, beneficiary_name: null, project_description: null, public_reasons: [], processing_status: null, information_requests: [], offers: [], available_actions: [] });

test('application version and identity changes hide messages and discard stale responses', async ({ page }) => {
  await openCabinet(page); let version = 1; let release: (() => void) | undefined; let delayed = false;
  await page.route('**/api/v1/applications/00000000-0000-4000-8000-000000000048', route => route.fulfill({ json: application(version) }));
  await page.route('**/api/v1/assistant/chat', async route => { const expectedVersion = route.request().postDataJSON().expected_version; if (delayed) await new Promise<void>(resolve => { release = resolve; }); await route.fulfill({ json: reply('Сведения сохранённой заявки.', expectedVersion) }).catch(() => {}); });
  await page.goto('/applications/00000000-0000-4000-8000-000000000048'); const dialog = await openAssistant(page); const input = dialog.getByLabel('Ваш вопрос');
  await input.fill('Какая сумма?'); await dialog.getByRole('button', { name: 'Спросить', exact: true }).click(); await expect(dialog).toContainText('Сведения сохранённой заявки.'); await expect(dialog.getByRole('group', { name: 'Ваше сообщение' })).toContainText('Какая сумма?');
  version++; await expect(dialog.getByRole('group', { name: 'Ваше сообщение' })).toHaveCount(0, { timeout: 7000 }); await expect(dialog).not.toContainText('Сведения сохранённой заявки.');
  delayed = true; await input.fill('Другой вопрос'); await dialog.getByRole('button', { name: 'Спросить', exact: true }).click(); await expect.poll(() => Boolean(release)).toBe(true); await expect(dialog.getByRole('group', { name: 'Ваше сообщение' })).toContainText('Другой вопрос');
  version++; await expect(dialog.getByRole('group', { name: 'Ваше сообщение' })).toHaveCount(0, { timeout: 7000 }); release!(); await expect(dialog).not.toContainText('Сведения сохранённой заявки.');
  delayed = false; await input.fill('Вопрос до смены пользователя'); await dialog.getByRole('button', { name: 'Спросить', exact: true }).click(); await expect(dialog).toContainText('Сведения сохранённой заявки.');
  await input.fill('Личный черновик'); await page.evaluate(() => window.dispatchEvent(new Event('credit-identity-changed')));
  await expect(dialog.getByRole('group', { name: 'Ваше сообщение' })).toHaveCount(0); await expect(dialog).not.toContainText('Сведения сохранённой заявки.'); await expect(input).toHaveValue('');
});

test('staff summary renders sections and preserves its generated time and sources', async ({ page }, testInfo) => {
  await openCabinet(page, true);
  await page.route('**/api/v1/applications/00000000-0000-4000-8000-000000000048', route => route.fulfill({ json: application(4) }));
  await page.route('**/api/v1/applications/*/assessment', route => route.fulfill({ json: { application_id: application(4).id, revision_id: null, runs: [], risk_assessment: null } }));
  await page.route(/\/api\/v1\/applications\/[^/]+\/summary(?:\?|$)/, route => route.fulfill({ json: route.request().method() === 'GET' ? null : { ...reply('### Запрос клиента\n\nКупить **печь**.\n\n### Финансы\n\n- Выручка не указана.\n- Расходы не указаны.\n\n### Результат и следующий шаг\n\nЗаявка на рассмотрении сотрудника.', 4), generated_at: '2026-10-24T12:00:00Z' } }));
  await page.goto('/staff/applications/00000000-0000-4000-8000-000000000048');
  const panel = page.getByRole('region', { name: 'Сводка помощника' }); await panel.getByRole('button', { name: 'Сформировать сводку' }).click();
  await expect(panel.getByRole('heading', { name: 'Запрос клиента', level: 3 })).toBeVisible(); await expect(panel.getByRole('heading', { name: 'Финансы', level: 3 })).toBeVisible();
  await expect(panel.locator('strong')).toHaveText('печь'); await expect(panel.locator('.assistant-answer li')).toHaveText(['Выручка не указана.', 'Расходы не указаны.']);
  await expect(panel).toContainText('Сформировано 24.10.2026'); await expect(panel.getByText('Источники (1)', { exact: true })).toBeVisible();
  await panel.screenshot({ path: testInfo.outputPath('staff-summary-structured.png') });
});
