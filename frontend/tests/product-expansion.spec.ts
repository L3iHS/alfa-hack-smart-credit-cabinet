import { test, expect } from "@playwright/test";
import type { Browser, Page } from "@playwright/test";

const password = process.env.DEMO_PASSWORD || "Demo-credit-2026!";

async function login(page: Page, email = "demo-a@example.test") {
  await page.goto("/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(email.startsWith("staff") ? /\/staff\/applications$/ : /\/applications$/);
}

const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4b6gCAANXAUWe8DG4AAAAAElFTkSuQmCC", "base64");
async function upload(page: Page, label: string) {
  await page.getByLabel(`Файл: ${label}`).setInputFiles({ name: `${label}.png`, mimeType: "image/png", buffer: png });
  await page.getByRole("button", { name: `Загрузить: ${label}` }).click();
  await expect(page.getByRole("button", { name: `Скачать ${label}.png` })).toBeVisible();
}
for (const product of [
  { code: "overdraft", amount: "500000", offered: "400000", term: "2", document: "Выписка по счёту" },
  { code: "credit_line", amount: "1000000", offered: "800000", term: "12", document: "Выписка по счёту" },
  { code: "investment", amount: "4000000", offered: "3500000", term: "36", document: "Бизнес-план" },
  { code: "tender_guarantee", amount: "500000", offered: "400000", term: "12", document: "Документы по тендеру" },
] as const) {
  test(`${product.code} real manual offer can be accepted`, async ({ page, browser }: { page: Page; browser: Browser }) => {
    await login(page);
    await page.goto("/applications/new");
    await page.locator(`input[name="product_code"][value="${product.code}"]`).check();
    await page.locator("#amount_kopecks").fill(product.amount);
    await page.locator("#term_months").fill(product.term);
    await page.locator("#purpose").fill(`Ручное предложение ${product.code}`);
    await page.locator("#period_start").fill("2026-01");
    await page.locator("#period_end").fill("2026-03");
    await page.locator("#revenue_kopecks").fill("120000000");
    await page.locator("#operating_expenses_kopecks").fill("3000000");
    await page.locator("#existing_debt_payments_kopecks").fill("0");
    if (product.code === "investment") await page.locator("#project_description").fill("Новая линия");
    if (product.code === "tender_guarantee") {
      await page.locator("#tender_number").fill("T-2026-42");
      await page.locator("#beneficiary_name").fill("Заказчик");
    }
    await page.getByRole("button", { name: "Сохранить черновик" }).click();
    await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/);
    const id = page.url().split("/").at(-1)!;
    await upload(page, "Финансовая отчётность");
    await upload(page, product.document);
    await page.getByRole("checkbox", { name: /Подтверждаю, что проверил данные/ }).check();
    await page.getByRole("checkbox", { name: /Согласен на проверку кредитной истории/ }).check();
    await page.getByRole("button", { name: "Отправить заявку" }).click();
    await expect(page.locator(".page-heading .status")).toHaveText("На рассмотрении сотрудника", { timeout: 20000 });
    const context = await browser.newContext({ baseURL: process.env.BASE_URL || "http://127.0.0.1:8086" });
    const staff = await context.newPage();
    await login(staff, "staff@example.test");
    await staff.goto(`/staff/applications/${id}`);
    await expect(staff.getByText("Модель риска для этого продукта пока не применяется. Заявку рассматривает сотрудник").first()).toBeVisible();
    await staff.getByLabel("Основание решения или предложения").fill("Подходящие уточнённые условия");
    await staff.getByText("Предложить другие условия", { exact: true }).click();
    await staff.getByLabel("Предлагаемая сумма, ₽").fill(product.offered);
    await staff.getByLabel("Предлагаемый срок, месяцев").fill(product.term);
    await staff.getByRole("button", { name: "Отправить предложение" }).click();
    await expect(staff.locator(".page-heading .status")).toHaveText("Предложены другие условия", { timeout: 15000 });
    await expect(page.locator(".page-heading .status")).toHaveText("Предложены другие условия", { timeout: 15000 });
    if (product.code === "tender_guarantee") {
      await expect(page.locator(".offer-comparison")).toContainText("Условное обязательство возмещения");
      await expect(page.locator(".offer-comparison")).not.toContainText("Ежемесячный платёж");
      await expect(page.locator(".offer-comparison")).not.toContainText("0% годовых");
    } else if (product.code === "overdraft" || product.code === "credit_line") {
      await expect(page.locator(".offer-comparison")).toContainText("Проценты в месяц");
      await expect(page.locator(".offer-comparison")).toContainText("Возврат лимита в конце срока");
      await expect(page.locator(".offer-comparison")).toContainText("Расчётная нагрузка для оценки");
    } else {
      await expect(page.locator(".offer-comparison")).toContainText("Ежемесячный платёж");
    }
    await page.getByRole("button", { name: "Принять условия" }).click();
    await expect(page.locator(".page-heading .status")).toHaveText("Одобрена", { timeout: 15000 });
    const saved = await (await page.request.get(`/api/v1/applications/${id}`)).json();
    expect(saved.offers.find((offer: { status: string }) => offer.status === "accepted").amount_kopecks).toBe(Number(product.offered) * 100);
    await context.close();
  });
}

test("all six products can be selected directly and show only their specific fields", async ({ page }) => {
  await login(page);
  await page.goto("/applications/new");
  for (const code of ["working_capital", "equipment", "overdraft", "credit_line", "investment", "tender_guarantee"]) {
    await page.locator(`input[name="product_code"][value="${code}"]`).check();
    await expect(page.locator(`input[name="product_code"][value="${code}"]`)).toBeChecked();
    await expect(page.locator("#project_description")).toHaveCount(code === "investment" ? 1 : 0);
    await expect(page.locator("#tender_number")).toHaveCount(code === "tender_guarantee" ? 1 : 0);
    await expect(page.locator("#beneficiary_name")).toHaveCount(code === "tender_guarantee" ? 1 : 0);
  }
});

for (const choice of [
  { code: "credit_line", basis: "от лимита" },
  { code: "investment", basis: "от суммы" },
] as const) {
  test(`${choice.code} direct choice shows catalog upfront fee and its basis`, async ({ page }) => {
    await login(page);
    const catalog = await (await page.request.get("/api/v1/products")).json();
    const product = catalog.items.find((item: { code: string }) => item.code === choice.code);
    expect(product.upfront_fee_bps).toBeGreaterThan(0);
    await page.goto("/applications/new");
    await page.locator(`input[name="product_code"][value="${choice.code}"]`).check();
    const row = page.locator(".terms-panel .terms > div").filter({ has: page.getByText("Разовая комиссия", { exact: true }) });
    await expect(row).toContainText(`${(product.upfront_fee_bps / 100).toLocaleString("ru-RU")}% ${choice.basis}`);
    await expect(row).not.toContainText("годовых");
  });
}

test("switching products clears incompatible fields and keeps financial input", async ({ page }) => {
  await login(page);
  await page.goto("/applications/new");
  await page.locator("#revenue_kopecks").fill("1234567");
  await page.locator('input[name="product_code"][value="tender_guarantee"]').check();
  await page.locator("#tender_number").fill("T-77");
  await page.locator("#beneficiary_name").fill("Заказчик");
  await page.locator('input[name="product_code"][value="investment"]').check();
  await expect(page.locator("#tender_number")).toHaveCount(0);
  await page.locator("#project_description").fill("Новый цех");
  await page.locator('input[name="product_code"][value="working_capital"]').check();
  await expect(page.locator("#project_description")).toHaveCount(0);
  await expect(page.locator("#revenue_kopecks")).toHaveValue("1234567");
  await page.locator('input[name="product_code"][value="tender_guarantee"]').check();
  await expect(page.locator("#tender_number")).toHaveValue("");
  await expect(page.locator("#beneficiary_name")).toHaveValue("");
});

test("recommendation purpose supports keyboard, escape, tab and outside click", async ({ page }) => {
  await login(page);
  const options = await (await page.request.get("/api/v1/product-recommendations/options")).json();
  await page.goto("/applications/new");
  const picker = page.getByRole("combobox", { name: "Что планируете финансировать" });
  await expect(picker).toBeEnabled();
  await picker.focus();
  await expect(picker).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(picker).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("listbox", { name: "Что планируете финансировать" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(picker).toHaveAttribute("aria-expanded", "false");
  await expect(picker).toBeFocused();

  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(picker).toContainText(options.purposes[1].label);

  await picker.click();
  await page.getByRole("option", { name: "Покупка оборудования" }).click();
  await expect(picker).toContainText("Покупка оборудования");
  await picker.click();
  await page.keyboard.press("Tab");
  await expect(picker).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("button", { name: "Подобрать продукт" })).toBeFocused();

  await picker.click();
  await page.getByRole("heading", { name: "Подбор кредитного продукта" }).click();
  await expect(picker).toHaveAttribute("aria-expanded", "false");

  await picker.click();
  await page.locator("#amount_kopecks").focus();
  await expect(picker).toHaveAttribute("aria-expanded", "false");
});

test("editing an input invalidates recommendation cards", async ({ page }) => {
  await login(page);
  await page.goto("/applications/new");
  await page.locator("#amount_kopecks").fill("2000000");
  await page.locator("#term_months").fill("24");
  await page.locator("#period_start").fill("2026-01");
  await page.locator("#period_end").fill("2026-03");
  await page.locator("#revenue_kopecks").fill("9000000");
  await page.locator("#operating_expenses_kopecks").fill("3000000");
  await page.locator("#existing_debt_payments_kopecks").fill("0");
  const panel = page.locator(".recommendation-panel");
  await panel.getByRole("button", { name: "Подобрать продукт" }).click();
  await expect(panel.locator(".recommendation-card").first()).toBeVisible();
  await page.locator("#amount_kopecks").fill("2100000");
  await expect(panel.locator(".recommendation-apply")).toHaveCount(0);
  await expect(panel).toContainText("Данные изменились. Подберите продукт заново");
  await page.locator("#amount_kopecks").fill("2000000");
  await expect(panel.locator(".recommendation-apply")).toHaveCount(0);
});

test("late recommendation A cannot replace B or clear B loading state", async ({ page }) => {
  await login(page);
  await page.goto("/applications/new");
  await page.locator("#amount_kopecks").fill("2000000");
  await page.locator("#term_months").fill("24");
  await page.locator("#period_start").fill("2026-01");
  await page.locator("#period_end").fill("2026-03");
  await page.locator("#revenue_kopecks").fill("9000000");
  await page.locator("#operating_expenses_kopecks").fill("3000000");
  await page.locator("#existing_debt_payments_kopecks").fill("0");
  let releaseA!: () => void;
  let releaseB!: () => void;
  const holdA = new Promise<void>((resolve) => { releaseA = resolve; });
  const holdB = new Promise<void>((resolve) => { releaseB = resolve; });
  let received = 0;
  await page.route("**/api/v1/product-recommendations", async (route) => {
    received++;
    const sequence = received;
    await (sequence === 1 ? holdA : holdB);
    try { await route.continue(); } catch { /* Отменённый запрос уже закрыт браузером. */ }
  });
  const panel = page.locator(".recommendation-panel");
  await panel.getByRole("button", { name: "Подобрать продукт" }).click();
  await expect.poll(() => received).toBe(1);
  await page.locator("#amount_kopecks").fill("2100000");
  await panel.getByRole("button", { name: "Подобрать продукт" }).click();
  await expect.poll(() => received).toBe(2);
  releaseA();
  await expect(panel.getByRole("button", { name: "Подбираем…" })).toBeDisabled();
  releaseB();
  await expect(panel.locator(".recommendation-card").first()).toBeVisible();
  await expect(panel.locator(".recommendation-card").first()).toContainText("2 100 000 ₽");
});

for (const product of [
  { code: "tender_guarantee", amount: "500000", revised: "450000", term: "12", document: "Документы по тендеру", amountLabel: "Сумма гарантии", termLabel: "Срок" },
  { code: "credit_line", amount: "1000000", revised: "900000", term: "12", document: "Выписка по счёту", amountLabel: "Лимит", termLabel: "Срок" },
] as const) {
  test(`${product.code} request and response use product amount and term labels`, async ({ page, browser }) => {
    await login(page);
    await page.goto("/applications/new");
    await page.locator(`input[name="product_code"][value="${product.code}"]`).check();
    await page.locator("#amount_kopecks").fill(product.amount);
    await page.locator("#term_months").fill(product.term);
    await page.locator("#purpose").fill(`Уточнение ${product.code}`);
    await page.locator("#period_start").fill("2026-01");
    await page.locator("#period_end").fill("2026-03");
    await page.locator("#revenue_kopecks").fill("120000000");
    await page.locator("#operating_expenses_kopecks").fill("3000000");
    await page.locator("#existing_debt_payments_kopecks").fill("0");
    if (product.code === "tender_guarantee") {
      await page.locator("#tender_number").fill("T-2026-42");
      await page.locator("#beneficiary_name").fill("Заказчик");
    }
    await page.getByRole("button", { name: "Сохранить черновик" }).click();
    await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/);
    const id = page.url().split("/").at(-1)!;
    await upload(page, "Финансовая отчётность");
    await upload(page, product.document);
    await page.getByRole("checkbox", { name: /Подтверждаю, что проверил данные/ }).check();
    await page.getByRole("checkbox", { name: /Согласен на проверку кредитной истории/ }).check();
    await page.getByRole("button", { name: "Отправить заявку" }).click();
    await expect(page.locator(".page-heading .status")).toHaveText("На рассмотрении сотрудника", { timeout: 20000 });

    const context = await browser.newContext({ baseURL: process.env.BASE_URL || "http://127.0.0.1:8086" });
    const staff = await context.newPage();
    try {
      await login(staff, "staff@example.test");
      await staff.goto(`/staff/applications/${id}`);
      await staff.getByText("Запросить уточнения", { exact: true }).click();
      const choices = staff.getByRole("group", { name: "Какие сведения нужны" });
      await expect(choices.getByRole("checkbox", { name: product.amountLabel, exact: true })).toBeVisible();
      await expect(choices.getByRole("checkbox", { name: product.termLabel, exact: true })).toBeVisible();
      await choices.getByRole("checkbox", { name: product.amountLabel, exact: true }).check();
      await choices.getByRole("checkbox", { name: product.termLabel, exact: true }).check();
      await staff.getByLabel("Сообщение клиенту").fill("Уточните сумму и срок");
      await staff.getByRole("button", { name: "Отправить запрос" }).click();
      await expect(page.locator(".page-heading .status")).toHaveText("Нужны уточнения", { timeout: 15000 });
      const request = page.locator(".information-request");
      await expect(request).toContainText(product.amountLabel);
      await expect(request).toContainText(product.termLabel);
      await expect(request).not.toContainText("Сумма кредита");

      await page.getByRole("link", { name: "Дополнить сведения" }).click();
      await page.locator("#amount_kopecks").fill(product.revised);
      await page.getByRole("button", { name: "Сохранить дополнения" }).click();
      await expect(page).toHaveURL(new RegExp(`/applications/${id}$`));
      await page.getByLabel("Сообщение к ответу").fill("Сумма и срок уточнены");
      await page.getByRole("checkbox", { name: /Подтверждаю, что проверил данные/ }).check();
      await page.getByRole("checkbox", { name: /Согласен на проверку кредитной истории/ }).check();
      const response = page.waitForResponse((item) => item.url().endsWith(`/api/v1/applications/${id}/information-responses`));
      await page.getByRole("button", { name: "Отправить ответ" }).click();
      expect((await response).status()).toBe(202);
      await page.getByText("Отправленные ответы", { exact: true }).click();
      const answered = page.locator(".answered-requests");
      await expect(answered).toContainText(product.amountLabel);
      await expect(answered).toContainText(product.termLabel);
      await expect(answered).not.toContainText("Сумма кредита");
    } finally {
      await context.close();
    }
  });
}

test("no-match change-amount action focuses the amount field", async ({ page }) => {
  await login(page);
  await page.goto("/applications/new");
  await page.locator("#amount_kopecks").fill("2000000");
  await page.locator("#term_months").fill("24");
  await page.route("**/api/v1/product-recommendations", (route) => route.fulfill({ json: {
    status: "no_match", message: "Измените сумму", items: [], missing_fields: [],
    actions: [{ kind: "change_amount", label: "Изменить сумму", field: "amount_kopecks", product_code: null, recommendation_id: null }],
    config_version: "test", trace_id: "test", catalog_version: "demo-v2", staff_trace: null,
  } }));
  await page.getByRole("button", { name: "Подобрать продукт" }).click();
  await page.getByRole("button", { name: "Изменить сумму" }).click();
  await expect(page.locator("#amount_kopecks")).toBeFocused();
});

for (const product of [
  { code: "working_capital", amount: "500000", term: "12" },
  { code: "equipment", amount: "1000000", term: "12" },
  { code: "overdraft", amount: "500000", term: "2" },
  { code: "credit_line", amount: "1000000", term: "12" },
  { code: "investment", amount: "3000000", term: "36" },
  { code: "tender_guarantee", amount: "500000", term: "12" },
] as const) {
  test(`${product.code} draft roundtrip uses real API`, async ({ page }) => {
    await login(page);
    await page.goto("/applications/new");
    await page.locator(`input[name="product_code"][value="${product.code}"]`).check();
    await page.locator("#amount_kopecks").fill(product.amount);
    await page.locator("#term_months").fill(product.term);
    await page.locator("#purpose").fill(`Проверка ${product.code}`);
    await page.locator("#period_start").fill("2026-01");
    await page.locator("#period_end").fill("2026-03");
    await page.locator("#revenue_kopecks").fill("12000000");
    await page.locator("#operating_expenses_kopecks").fill("3000000");
    await page.locator("#existing_debt_payments_kopecks").fill("0");
    if (product.code === "investment") await page.locator("#project_description").fill("Расширение производственной линии");
    if (product.code === "tender_guarantee") {
      await page.locator("#tender_number").fill("T-2026-17");
      await page.locator("#beneficiary_name").fill("Заказчик демонстрации");
    }
    await page.getByRole("button", { name: "Сохранить черновик" }).click();
    await expect(page).toHaveURL(/\/applications\/[a-f0-9-]+$/);
    await page.reload();
    const id = page.url().split("/").at(-1)!;
    const saved = await (await page.request.get(`/api/v1/applications/${id}`)).json();
    expect(saved.product_code).toBe(product.code);
    expect(saved.amount_kopecks).toBe(Number(product.amount) * 100);
    expect(saved.term_months).toBe(Number(product.term));
    expect(saved.revenue_kopecks).toBe(1200000000);
    expect(saved.existing_debt_payments_kopecks).toBe(0);
    if (product.code === "investment") expect(saved.project_description).toBe("Расширение производственной линии");
    if (product.code === "tender_guarantee") expect(saved.tender_number).toBe("T-2026-17");
    await page.goto(`/applications/${id}/edit`);
    await expect(page.locator(`input[name="product_code"][value="${product.code}"]`)).toBeChecked();
    await expect(page.locator("#amount_kopecks")).toHaveValue(`${product.amount},00`);
  });
}
