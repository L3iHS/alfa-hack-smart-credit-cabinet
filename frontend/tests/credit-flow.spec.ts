import { test, expect, type Browser, type Page } from "@playwright/test";

const password = process.env.DEMO_PASSWORD || "Demo-credit-2026!";
const baseURL = process.env.BASE_URL || "http://localhost:8080";
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4b6gCAANXAUWe8DG4AAAAAElFTkSuQmCC", "base64");
type Profile = "a" | "b" | "c" | "d" | "e";
const profiles = {
  a: { equipment: true, amount: "2000000", term: "24", revenue: "2400000", expenses: "300000", debt: "150000" },
  b: { equipment: false, amount: "5000000", term: "12", revenue: "2100000", expenses: "1500000", debt: "90000" },
  c: { equipment: true, amount: "2000000", term: "24", revenue: "2100000", expenses: "1500000", debt: "150000" },
  d: { equipment: false, amount: "500000", term: "12", revenue: "1200000", expenses: "900000", debt: "30000" },
  e: { equipment: true, amount: "2000000", term: "24", revenue: "2400000", expenses: "1500000", debt: "150000" },
};

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(email.startsWith("staff") ? /\/staff\/applications$/ : /\/applications$/);
}
async function status(page: Page, value: string) {
  await expect(page.locator(".page-heading .status")).toHaveText(value, { timeout: 15_000 });
}
async function upload(page: Page, label: string, filename = "credit-demo.png") {
  const count = await page.getByRole("button", { name: `Скачать ${filename}`, exact: true }).count();
  await page.getByLabel(`Файл: ${label}`, { exact: true }).setInputFiles({ name: filename, mimeType: "image/png", buffer: png });
  await page.getByRole("button", { name: `Загрузить: ${label}`, exact: true }).click();
  await expect(page.getByRole("button", { name: `Скачать ${filename}`, exact: true })).toHaveCount(count + 1);
  await expect(page.getByRole("button", { name: `Загрузить: ${label}`, exact: true })).toBeEnabled();
}
async function confirmations(page: Page) {
  await page.getByRole("checkbox", { name: /Подтверждаю, что проверил данные/ }).check();
  await page.getByRole("checkbox", { name: /Согласен на проверку кредитной истории/ }).check();
}
async function createAndSubmit(page: Page, letter: Profile) {
  const p = profiles[letter];
  await login(page, `demo-${letter}@example.test`);
  await page.getByRole("link", { name: "Новая заявка", exact: true }).first().click();
  await page.getByRole("radio", { name: p.equipment ? "Кредит на оборудование" : "Оборотный кредит" }).check();
  await page.getByLabel("Цель финансирования").fill(`Демонстрация ${letter.toUpperCase()} ${Date.now()}`);
  await page.locator("#amount_kopecks").fill(p.amount);
  await page.locator("#term_months").fill(p.term);
  // Берём три завершённых месяца относительно даты реального запуска.
  const now = new Date();
  const month = (offset: number) => {
    const d = new Date(now.getFullYear(), now.getMonth() + offset, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  };
  await page.locator("#period_start").fill(month(-3));
  await page.locator("#period_end").fill(month(-1));
  await page.getByLabel("Выручка за период, ₽", { exact: true }).fill(p.revenue);
  await page.getByLabel("Операционные расходы за период, ₽", { exact: true }).fill(p.expenses);
  await page.locator("#existing_debt_payments_kopecks").fill(p.debt);
  await page.getByRole("button", { name: "Сохранить черновик", exact: true }).click();
  await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/);
  const id = page.url().split("/").at(-1)!;
  await page.reload();
  await status(page, "Черновик");
  await upload(page, "Финансовая отчётность");
  if (p.equipment) await upload(page, "Счёт на оборудование", "invoice.png");
  await confirmations(page);
  const response = page.waitForResponse(r => r.url().endsWith(`/api/v1/applications/${id}/submit`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "Отправить заявку", exact: true }).click();
  const submitted = await response;
  expect(submitted.status()).toBe(202);
  return { id, submission: await submitted.json() as { revision_id: string; processing_run_id: string } };
}
async function staffPage(browser: Browser, id: string) {
  const context = await browser.newContext({ baseURL });
  const page = await context.newPage();
  await login(page, "staff@example.test");
  await page.goto(`/staff/applications/${id}`);
  await expect(page.getByRole("heading", { name: "Проверки и расчёт", exact: true })).toBeVisible();
  await expect(page.locator(".assessment-run").last().locator(".risk-assessment").first()).toBeVisible();
  return { page, context };
}
async function staffOffer(page: Page, amount: string, term: string) {
  await page.getByLabel("Основание решения или предложения").fill("Новые условия рассмотрены сотрудником");
  await page.getByText("Предложить другие условия", { exact: true }).click();
  await page.getByLabel("Предлагаемая сумма, ₽", { exact: true }).fill(amount);
  await page.getByLabel("Предлагаемый срок, месяцев", { exact: true }).fill(term);
  const response = page.waitForResponse(r => r.url().endsWith("/offers") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Отправить предложение", exact: true }).click();
  const result = await response;
  if (result.status() === 409) {
    expect((await result.json()).code).toBe("risk_acknowledgement_required");
    const score = page.locator(".review-form .risk-assessment");
    await expect(score).toContainText("Расчёт выполнен");
    await page.getByRole("checkbox", { name: "Изучена оценка риска новых условий", exact: true }).check();
    const confirmed = page.waitForResponse(r => r.url().endsWith("/offers") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Отправить предложение", exact: true }).click();
    expect((await confirmed).status()).toBe(201);
  } else expect(result.status()).toBe(201);
}
async function evidence(page: Page, id: string) {
  const response = await page.request.get(`/api/v1/applications/${id}`);
  expect(response.status()).toBe(200);
  return response.json();
}

// Здесь нет подмены API: ввод, файлы и все команды проходят через интерфейс.
test("profile_A_equipment_approves_and_staff_sees_calculation", async ({ page, browser }) => {
  const { id, submission } = await createAndSubmit(page, "a");
  await status(page, "Одобрена");
  const staff = await staffPage(browser, id);
  await status(staff.page, "Одобрена");
  await expect(staff.page.getByText("105 742,20 ₽", { exact: true })).toBeVisible();
  const assessment = await (await staff.page.request.get(`/api/v1/applications/${id}/assessment`)).json();
  expect(assessment.runs[0].revision_id).toBe(submission.revision_id);
  expect(assessment.runs[0].checks).toHaveLength(3);
  expect(assessment.risk_assessment.status).toBe("succeeded");
  expect(assessment.risk_assessment.risk_band).toBe("low");
  expect(assessment.risk_assessment.probability).toBeLessThan(.1);
  await staff.context.close();
});

test("profile_B_client_accepts_staff_offer_after_risk_review", async ({ page, browser }) => {
  const { id } = await createAndSubmit(page, "b");
  await status(page, "На рассмотрении сотрудника");
  const staff = await staffPage(browser, id);
  await staffOffer(staff.page, "2342000", "24");
  await status(page, "Предложены другие условия");
  await expect(page.getByRole("cell", { name: "2 342 000 ₽", exact: true })).toBeVisible();
  await expect(page.getByText("123 824,11 ₽", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Принять условия", exact: true }).click();
  await status(page, "Одобрена");
  const item = await evidence(page, id);
  expect(item.amount_kopecks).toBe(500000000);
  expect(item.offers.find((o: { status: string }) => o.status === "accepted").amount_kopecks).toBe(234200000);
  await staff.context.close();
});

test("profile_B_decline_returns_to_staff_then_staff_rejects", async ({ page, browser }) => {
  const { id } = await createAndSubmit(page, "b");
  await status(page, "На рассмотрении сотрудника");
  const offerStaff = await staffPage(browser, id);
  await staffOffer(offerStaff.page, "2342000", "24");
  await offerStaff.context.close();
  await status(page, "Предложены другие условия");
  await page.getByRole("button", { name: "Отклонить предложение", exact: true }).click();
  await status(page, "На рассмотрении сотрудника");
  const item = await evidence(page, id);
  expect(item.offers.some((o: { status: string }) => o.status === "declined")).toBe(true);
  const staff = await staffPage(browser, id);
  await staff.page.getByLabel("Основание решения или предложения").fill("Клиенту не подходят допустимые условия финансирования");
  await staff.page.getByRole("button", { name: "Отказать по заявке", exact: true }).click();
  await status(staff.page, "Отказ");
  await status(page, "Отказ");
  await expect(page.getByText("Клиенту не подходят допустимые условия финансирования", { exact: true }).first()).toBeVisible();
  await staff.context.close();
});

test("profile_C_correction_creates_new_revision_and_keeps_first_run", async ({ page, browser }) => {
  const { id, submission } = await createAndSubmit(page, "c");
  await status(page, "Нужны уточнения");
  await page.getByRole("link", { name: "Дополнить сведения", exact: true }).click();
  await page.getByLabel("Выручка за период, ₽", { exact: true }).fill("2400000");
  await page.getByRole("button", { name: "Сохранить дополнения", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/applications/${id}$`));
  await status(page, "Нужны уточнения");
  await page.getByLabel("Сообщение к ответу").fill("Выручка за период исправлена");
  await confirmations(page);
  const response = page.waitForResponse(r => r.url().endsWith(`/api/v1/applications/${id}/information-responses`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "Отправить ответ", exact: true }).click();
  const answered = await response;
  expect(answered.status()).toBe(202);
  const newSubmission = await answered.json();
  expect(newSubmission.revision_id).not.toBe(submission.revision_id);
  await status(page, "На рассмотрении сотрудника");
  const staff = await staffPage(browser, id);
  await page.getByText("Отправленные ответы", { exact: true }).click();
  await staff.page.getByText("Отправленные ответы", { exact: true }).click();
  await expect(page.getByText("Выручка за период исправлена", { exact: true }).first()).toBeVisible();
  await expect(staff.page.getByText("Выручка за период исправлена", { exact: true }).first()).toBeVisible();
  const item = await evidence(page, id);
  const answeredRequest = item.information_requests.find((r: { status: string }) => r.status === "answered");
  expect(answeredRequest.response_message).toBe("Выручка за период исправлена");
  expect(answeredRequest.response_revision_id).toBe(newSubmission.revision_id);
  expect(answeredRequest.responded_by).toBeTruthy();
  expect(answeredRequest.responded_at).toBeTruthy();
  const assessment = await (await staff.page.request.get(`/api/v1/applications/${id}/assessment`)).json();
  expect(assessment.runs).toHaveLength(2);
  expect(assessment.runs.map((r: { revision_id: string }) => r.revision_id)).toContain(submission.revision_id);
  expect(assessment.runs.map((r: { revision_id: string }) => r.revision_id)).toContain(newSubmission.revision_id);
  const history = await (await page.request.get(`/api/v1/applications/${id}/history?limit=100`)).json();
  expect(history.items.filter((e: { event_type: string }) => e.event_type === "information_responded")).toHaveLength(1);
  await staff.context.close();
});

test("profile_D_short_history_staff_approves", async ({ page, browser }) => {
  const { id } = await createAndSubmit(page, "d");
  await status(page, "На рассмотрении сотрудника");
  const staff = await staffPage(browser, id);
  await staff.page.getByLabel("Основание решения или предложения").fill("Синтетические данные нового бизнеса рассмотрены");
  await staff.page.getByRole("checkbox", { name: "Изучена оценка риска исходных условий", exact: true }).check();
  await staff.page.getByRole("button", { name: "Одобрить заявку", exact: true }).click();
  await status(staff.page, "Одобрена");
  await status(page, "Одобрена");
  await staff.context.close();
});

test("profile_D_staff_requests_document_and_client_explicitly_responds", async ({ page, browser }) => {
  const { id, submission } = await createAndSubmit(page, "d");
  await status(page, "На рассмотрении сотрудника");
  const staff = await staffPage(browser, id);
  await staff.page.getByText("Запросить уточнения", { exact: true }).click();
  await staff.page.getByLabel("Сообщение клиенту").fill("Приложите новые финансовые сведения");
  await staff.page.getByRole("checkbox", { name: "Финансовая отчётность", exact: true }).check();
  await staff.page.getByRole("button", { name: "Отправить запрос", exact: true }).click();
  await status(page, "Нужны уточнения");
  await upload(page, "Финансовая отчётность", "additional.png");
  await status(page, "Нужны уточнения");
  await page.getByLabel("Сообщение к ответу").fill("Дополнительные сведения приложены");
  await confirmations(page);
  await page.getByRole("button", { name: "Отправить ответ", exact: true }).click();
  await status(page, "На рассмотрении сотрудника");
  const item = await evidence(page, id);
  expect(item.information_requests[0].status).toBe("answered");
  const assessment = await (await staff.page.request.get(`/api/v1/applications/${id}/assessment`)).json();
  expect(assessment.runs).toHaveLength(2);
  expect(assessment.revision_id).not.toBe(submission.revision_id);
  await staff.context.close();
});

test("profile_D_staff_offer_is_accepted_by_client", async ({ page, browser }) => {
  const { id } = await createAndSubmit(page, "d");
  await status(page, "На рассмотрении сотрудника");
  const staff = await staffPage(browser, id);
  await staffOffer(staff.page, "400000", "12");
  await status(page, "Предложены другие условия");
  await page.getByRole("button", { name: "Принять условия", exact: true }).click();
  await status(page, "Одобрена");
  await status(staff.page, "Одобрена");
  await staff.context.close();
});

test("profile_E_overdue_is_rejected_and_other_company_has_no_access", async ({ page, browser }) => {
  const { id } = await createAndSubmit(page, "e");
  await status(page, "Отказ");
  await expect(page.locator(".public-reasons")).toContainText(/просроч/i);
  const staff = await staffPage(browser, id);
  await expect(staff.page.getByText("Просрочка: 100 дн.", { exact: true })).toBeVisible();
  await staff.context.close();
  const context = await browser.newContext({ baseURL });
  const other = await context.newPage();
  await login(other, "client2@example.test");
  await other.goto(`/applications/${id}`);
  await expect(other.getByRole("heading", { name: "Заявка не найдена", exact: true })).toBeVisible();
  expect((await other.request.get(`/api/v1/applications/${id}/assessment`)).status()).toBe(403);
  await context.close();
});
