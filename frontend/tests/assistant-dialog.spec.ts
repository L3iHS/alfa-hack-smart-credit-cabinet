import { test, expect, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
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

test('history retains whole recent completed pairs within six and total limits', async ({ page }) => {
  const dialog = await setup(page); const histories: { question: string; answer: string }[][] = [];
  await page.route('**/api/v1/assistant/chat', route => { const body = route.request().postDataJSON(); histories.push(body.history); const n = Number(body.question); return route.fulfill({ json: reply(n === 2 ? 'Недостаточно сведений' : n === 3 ? 'x'.repeat(6001) : n === 7 || n === 8 ? 'y'.repeat(5999) : `Ответ ${n}`, 4, n === 2 ? 'insufficient_context' : 'answered') }); });
  for (let n = 1; n <= 15; n++) { await send(dialog, String(n)); await expect(dialog.getByRole('button', { name: 'Спросить', exact: true })).toBeDisabled(); await expect(dialog.getByRole('status')).toHaveCount(0); }
  expect(histories[4].map(pair => pair.question)).toEqual(['1', '2', '4']);
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

for (const followup of ['А почему?', 'Что дальше?']) test(`insufficient context preserves the unrelated topic boundary for ${followup} and older retry`, async ({ page }) => {
  const dialog = await setup(page); const bodies: { question: string; history: unknown[] }[] = []; let failed = false;
  await page.route('**/api/v1/assistant/chat', route => {
    const body = route.request().postDataJSON(); bodies.push(body);
    if (body.question === 'Ошибка' && !failed) { failed = true; return route.fulfill({ status: 503, json: { code: 'assistant_unavailable' } }); }
    const insufficient = body.question === 'Почему Марс красный?' || body.question === followup;
    return route.fulfill({ json: reply(insufficient ? 'Недостаточно сведений' : `Ответ ${body.question}`, 4, insufficient ? 'insufficient_context' : 'answered') });
  });
  for (const question of ['Какую сумму я запросил по заявке?', 'Почему Марс красный?', 'Ошибка', followup, 'Какая сумма?']) {
    await send(dialog, question); await expect(dialog.getByRole('status')).toHaveCount(0);
  }
  const prefix = [{ question: 'Какую сумму я запросил по заявке?', answer: 'Ответ Какую сумму я запросил по заявке?' }, { question: 'Почему Марс красный?', answer: 'Недостаточно сведений', status: 'insufficient_context' }];
  expect(bodies[3].history).toEqual(prefix);
  expect(bodies[4].history).toEqual([...prefix, { question: followup, answer: 'Недостаточно сведений', status: 'insufficient_context' }]);
  await dialog.getByRole('button', { name: 'Повторить вопрос' }).click(); await expect(dialog).toContainText('Ответ Ошибка');
  expect(bodies.at(-1)!.history).toEqual(prefix);
});

for (const answerLength of [5999, 6000]) test(`Unicode codepoint history accepts ${answerLength} character answers and exact total budget`, async ({ page }) => {
  const dialog = await setup(page); const histories: { question: string; answer: string }[][] = [];
  const answer = 'а'.repeat(answerLength - 1) + '🙂';
  await page.route('**/api/v1/assistant/chat', route => { histories.push(route.request().postDataJSON().history); return route.fulfill({ json: reply(answer) }); });
  for (const question of ['A', 'B', 'C']) { await send(dialog, question); await expect(dialog.getByRole('status')).toHaveCount(0); }
  expect(histories[1]).toEqual([{ question: 'A', answer }]);
  expect(histories[2]).toEqual(answerLength === 5999 ? [{ question: 'A', answer }, { question: 'B', answer }] : [{ question: 'B', answer }]);
});

test('application source uses the authoritative product name once without code labels or kopecks', async ({ page }) => {
  const dialog = await setup(page);
  await page.route('**/api/v1/assistant/chat', route => route.fulfill({ json: { ...reply('Сведения заявки'), sources: [{ id: `application:${id}:request`, title: 'Данные заявки', version: '4', text: JSON.stringify({ product_code: 'working_capital', product_name: 'Оборотный кредит', amount_kopecks: 150000000, term_months: 24 }) }] } }));
  await send(dialog, 'Какой продукт?'); await expect(dialog).toContainText('Сведения заявки');
  await dialog.getByText('Источники (1)', { exact: true }).click();
  await expect(dialog.getByText('Оборотный кредит', { exact: true })).toHaveCount(1);
  await expect(dialog).toContainText('1 500 000 ₽');
  for (const raw of ['working_capital', 'product_name', 'Продукт не найден', '150000000', 'копеек']) await expect(dialog).not.toContainText(raw);
});

// Записанный настоящий ответ модели от25.10; replay не обращается к провайдеру.
const recordedSourceId = 'application:1a1f9163-6e12-4adb-851d-de926ff2911b:request';
const recordedFollowup = 'Вся информация основана на предоставленных источниках. В вашей заявке выбран продукт «Оборотный кредит» (product_name) на сумму 1 500 000 ₽ и срок 24 месяца. Это подтверждается источником «Данные заявки» (application:1a1f9163-6e12-4adb-851d-de926ff2911b:request).';
const humanDetails = '\n\nСтавка 24% (годовых), сумма 1 500 000 ₽ (по данным клиента). Период (01.07.2026–30.09.2026). Договор (1a1f9163-6e12-4adb-851d-de926ff2911b). Неизвестное обозначение (other_key) и условия (от 6 до 24 месяцев).';
const recordedSources = [{ id: recordedSourceId, title: 'Данные заявки', version: '4', text: JSON.stringify({ product_code: 'working_capital', product_name: 'Оборотный кредит', amount_kopecks: 150000000, term_months: 24, terms: { annual_rate_bps: 2400 } }) }];
const annotatedAnswer = recordedFollowup + ' Сумма (amount_rubles), ставка (annual_rate_percent). Источник: ' + recordedSourceId + '.' + humanDetails;
async function assertHumanAnswer(answer: ReturnType<Page['locator']>) {
  for (const raw of ['product_name', recordedSourceId, 'amount_rubles', 'annual_rate_percent']) await expect(answer).not.toContainText(raw);
  for (const human of ['Оборотный кредит', '1 500 000 ₽', '24 месяца', 'Источник: Данные заявки.', '(годовых)', '(по данным клиента)', '(01.07.2026–30.09.2026)', '(1a1f9163-6e12-4adb-851d-de926ff2911b)', '(other_key)', '(от 6 до 24 месяцев)']) await expect(answer).toContainText(human);
  await expect(answer.locator('p')).toHaveCount(2);
}

test('recorded model annotations disappear from chat and next history while human parentheses remain', async ({ page }, info) => {
  const dialog = await setup(page); const payloads: { history: { answer: string }[] }[] = [];
  await page.route('**/api/v1/assistant/chat', route => { payloads.push(route.request().postDataJSON()); return route.fulfill({ json: { ...reply(annotatedAnswer), sources: recordedSources } }); });
  await send(dialog, 'А почему ты так считаешь?'); await expect(dialog.locator('.assistant-answer')).toBeVisible(); await assertHumanAnswer(dialog.locator('.assistant-answer'));
  await dialog.getByRole('button', { name: 'Развернуть помощника' }).click(); await expect(dialog.getByLabel('Ваш вопрос')).toBeInViewport();
  await dialog.screenshot({ path: info.outputPath('recorded-response-presentation.png') });
  await send(dialog, 'Что дальше?'); await expect(dialog.locator('.assistant-result')).toHaveCount(2);
  const historyAnswer = payloads[1].history[0].answer;
  expect(historyAnswer).not.toContain('product_name'); expect(historyAnswer).not.toContain(recordedSourceId); expect(historyAnswer).toContain(humanDetails);
  // Идентификатор источника — часть контракта, форматирование его не меняет.
  const validated = await page.evaluate(async ({ sourceId, applicationId }) => {
    const api = await import('/src/api/assistant.ts');
    const answer = await api.askAssistant('Проверка источника', { id: applicationId, version: 4 }, new AbortController().signal);
    return { ids: answer.sources.map((source: { id: string }) => source.id), answer: answer.answer, sourceId };
  }, { sourceId: recordedSourceId, applicationId: id });
  expect(validated.ids).toEqual([recordedSourceId]); expect(validated.answer).not.toContain(recordedSourceId);
});

test('saved staff summary and Markdown export use the same human presentation without changing sources', async ({ page }) => {
  await setup(page);
  await page.route('**/api/v1/me', route => route.fulfill({ json: { id: 'dialog-user', role: 'staff', display_name: 'Сотрудник' } }));
  await page.route('**/api/v1/applications/*/assessment', route => route.fulfill({ json: { application_id: id, revision_id: null, runs: [], risk_assessment: null } }));
  await page.route(/\/api\/v1\/applications\/[^/]+\/summary(?:\?|$)/, route => route.fulfill({ json: { ...reply(annotatedAnswer), generated_at: '2026-10-25T12:00:00Z', sources: recordedSources } }));
  await page.goto(`/staff/applications/${id}`);
  const summary = page.getByRole('region', { name: 'Сводка помощника' }); await assertHumanAnswer(summary.locator('.assistant-answer'));
  const downloadEvent = page.waitForEvent('download'); await summary.getByRole('button', { name: 'Скачать сводку в Markdown' }).click(); const download = await downloadEvent;
  const text = await readFile((await download.path())!, 'utf8');
  for (const raw of ['product_name', recordedSourceId, 'amount_rubles', 'annual_rate_percent']) expect(text).not.toContain(raw);
  expect(text).toContain(humanDetails); expect(text).toContain('1 500 000 ₽'); expect(text).toContain('## Источники');
});

test('presentation preserves a model product mistake instead of changing its meaning', async ({ page }) => {
  const dialog = await setup(page);
  await page.route('**/api/v1/assistant/chat', route => route.fulfill({ json: { ...reply('Вы запросили «Кредитная линия» (product_name).'), sources: recordedSources } }));
  await send(dialog, 'Какой продукт?'); await expect(dialog.locator('.assistant-answer')).toHaveText('Вы запросили «Кредитная линия».');
  await expect(dialog.locator('.assistant-answer')).not.toContainText('Оборотный кредит');
});

test('recorded real two-answer dialog renders cleanly without a new model call', async ({ page }, info) => {
  const dialog = await setup(page); let count = 0;
  const answers = ['Вы запросили **Оборотный кредит** на сумму **1 500 000 ₽** сроком на **24 месяца**.', recordedFollowup];
  await page.route('**/api/v1/assistant/chat', route => route.fulfill({ json: { ...reply(answers[count++]), sources: recordedSources } }));
  await send(dialog, 'Какую сумму, на какой срок и какой продукт я запросил?'); await expect(dialog.locator('.assistant-result')).toHaveCount(1);
  await send(dialog, 'А почему ты так считаешь?'); await expect(dialog.locator('.assistant-result')).toHaveCount(2);
  await expect(dialog).not.toContainText('product_name'); await expect(dialog).not.toContainText(recordedSourceId);
  await dialog.getByRole('button', { name: 'Развернуть помощника' }).click(); await expect(dialog.getByLabel('Ваш вопрос')).toBeInViewport();
  await dialog.screenshot({ path: info.outputPath('recorded-real-dialog-presentation.png') }); expect(count).toBe(2);
});
