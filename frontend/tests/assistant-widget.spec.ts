import { test, expect, type Page } from '@playwright/test';

// HTTP-подмены изолируют оформление виджета от базы и внешней модели.
async function openCabinet(page: Page) {
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    const responses: Record<string, unknown> = {
      '/api/v1/me': { id: 'widget-client', role: 'client', display_name: 'Анна', email: 'client@example.test' },
      '/api/v1/company': { id: 'widget-company', name: 'ООО «Пекарня»', inn: '7701234567', industry: 'Пищевое производство', registered_at: '2020-01-01' },
      '/api/v1/products': { catalog_version: 'demo-v2', items: [] },
      '/api/v1/applications': { items: [], total: 0, limit: 20, offset: 0 },
      '/api/v1/auth/csrf': { csrf_token: 'widget-csrf', user_id: 'widget-client' },
    };
    return path in responses ? route.fulfill({ json: responses[path] }) : route.fulfill({ status: 503, json: { code: 'assistant_unavailable', message: 'Помощник временно недоступен' } });
  });
  await page.goto('/applications');
  await expect(page.getByRole('button', { name: 'Помощник', exact: true })).toBeVisible();
}

for (const width of [390, 1366]) test(`assistant exchanges launcher for compact window and restores keyboard focus ${width}`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 800 });
  await openCabinet(page);
  const launcher = page.getByRole('button', { name: 'Помощник', exact: true });
  await launcher.focus(); await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog', { name: 'Помощник по кредитам' });
  await expect(dialog).toBeVisible();
  await dialog.evaluate(element => Promise.all(element.getAnimations().map(animation => animation.finished)));
  await expect(launcher).toBeHidden();
  await expect(dialog.getByRole('heading')).toBeFocused();
  await page.keyboard.press('Tab'); await expect(dialog.getByRole('button', { name: 'Закрыть помощника' })).toBeFocused();
  const input = dialog.getByLabel('Ваш вопрос');
  await input.fill('Как выбрать финансирование?');
  expect(await input.evaluate(element => getComputedStyle(element).resize)).toBe('none');
  const box = await dialog.boundingBox();
  expect(box!.height).toBeLessThanOrEqual(600);
  expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(800);
  await page.screenshot({ path: testInfo.outputPath(`assistant-open-${width}.png`) });
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden(); await expect(launcher).toBeVisible(); await expect(launcher).toBeFocused();
  await page.keyboard.press('Enter'); await expect(input).toHaveValue('Как выбрать финансирование?');
  await dialog.getByRole('button', { name: 'Закрыть помощника' }).click();
  await expect(dialog).toBeHidden(); await expect(launcher).toBeFocused();
});

test('assistant keeps composer available with long answer and sources on a short mobile screen', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 360, height: 540 }); await openCabinet(page);
  await page.route('**/api/v1/assistant/chat', route => route.fulfill({ json: { status: 'answered', answer: 'Для покупки оборудования можно выбрать кредит на оборудование.\n\n' + 'Сумма и срок зависят от потребности вашего бизнеса. '.repeat(35), application_version: null, sources: [{ id: 'equipment', title: 'Кредит на оборудование', text: 'Нужен счёт на оборудование. <img src=x>', version: 'demo-v2' }] } }));
  await page.getByRole('button', { name: 'Помощник', exact: true }).click();
  const dialog = page.getByRole('dialog'); const input = dialog.getByLabel('Ваш вопрос');
  await input.fill('Какие документы нужны?'); await dialog.getByRole('button', { name: 'Спросить', exact: true }).click();
  await expect(dialog).toContainText('Для покупки оборудования');
  await dialog.getByText('Источники (1)', { exact: true }).click();
  await expect(dialog).toContainText('Нужен счёт на оборудование. <img src=x>'); await expect(dialog.locator('img')).toHaveCount(0);
  const submit = dialog.getByRole('button', { name: 'Спросить', exact: true });
  const inputBox = await input.boundingBox(); const submitBox = await submit.boundingBox();
  expect(inputBox!.y).toBeGreaterThanOrEqual(0); expect(submitBox!.y + submitBox!.height).toBeLessThanOrEqual(540);
  await expect(input).toBeInViewport(); await expect(submit).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await dialog.getByText('Нужен счёт на оборудование. <img src=x>', { exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('assistant-long-mobile.png') });
  await dialog.getByRole('button', { name: 'Закрыть помощника' }).click();
  await page.getByRole('button', { name: 'Помощник', exact: true }).click();
  await expect(dialog).toContainText('Для покупки оборудования');
  await input.fill('Длинный вопрос\n'.repeat(100));
  expect(await input.evaluate(element => element.clientHeight)).toBeLessThanOrEqual(80);
  expect(await input.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);
  await input.fill('Новый вопрос'); await expect(dialog).not.toContainText('Для покупки оборудования');
});

test('assistant reduced motion preserves open close and error retry', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' }); await openCabinet(page);
  await page.getByRole('button', { name: 'Помощник', exact: true }).click(); const dialog = page.getByRole('dialog');
  expect(await dialog.evaluate(element => getComputedStyle(element).animationName)).toBe('none');
  await dialog.getByLabel('Ваш вопрос').fill('Что такое кредитная линия?');
  await dialog.getByRole('button', { name: 'Спросить', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('Помощник временно недоступен');
  await page.route('**/api/v1/assistant/chat', route => route.fulfill({ json: { status: 'insufficient_context', answer: 'В доступных сведениях нет ответа', sources: [], application_version: null } }));
  await dialog.getByRole('button', { name: 'Спросить', exact: true }).click(); await expect(dialog).toContainText('В доступных сведениях нет ответа');
  await expect(dialog.getByRole('alert')).toHaveCount(0);
  await page.keyboard.press('Escape'); await expect(page.getByRole('button', { name: 'Помощник', exact: true })).toBeFocused();
});
