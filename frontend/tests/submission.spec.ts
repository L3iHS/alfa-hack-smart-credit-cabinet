import { test, expect, type Page } from "@playwright/test";
const password = process.env.DEMO_PASSWORD || "Demo-credit-2026!";
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4b6gCAANXAUWe8DG4AAAAAElFTkSuQmCC",
  "base64",
);
async function login(page: Page, email = "client1@example.test") {
  await page.goto("/login");
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(
    email.startsWith("staff") ? /\/staff\/applications$/ : /\/applications$/,
  );
}
async function draft(page: Page, product = "working_capital", complete = true) {
  const token = (await (await page.request.get("/api/v1/auth/csrf")).json())
    .csrf_token;
  const response = await page.request.post("/api/v1/applications", {
    headers: { "X-CSRF-Token": token },
    data: {
      product_code: product,
      ...(complete
        ? {
            purpose: `Закупка для проверки отправки ${Date.now()}`,
            amount_kopecks: 100000000,
            term_months: 12,
            period_start: "2025-01-01",
            period_end: "2025-03-31",
            revenue_kopecks: 300000000,
            operating_expenses_kopecks: 100000000,
            existing_debt_payments_kopecks: 0,
          }
        : {}),
    },
  });
  expect(response.status()).toBe(201);
  const value = await response.json();
  await page.goto(`/applications/${value.id}`);
  return value.id as string;
}
async function upload(page: Page, label = "Финансовая отчётность") {
  const previousCount = await page
    .getByRole("link", { name: "Скачать report.png" })
    .count();
  await page
    .getByLabel(`Файл: ${label}`, { exact: true })
    .setInputFiles({ name: "report.png", mimeType: "image/png", buffer: png });
  await page
    .getByRole("button", { name: `Загрузить: ${label}`, exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: "Скачать report.png" }),
  ).toHaveCount(previousCount + 1);
  await expect(
    page.getByRole("button", { name: `Загрузить: ${label}`, exact: true }),
  ).toBeEnabled();
}
async function confirm(page: Page) {
  await page.locator("#data-confirmed").check();
  await page.locator("#bki-consent").check();
}
for (const product of ["working_capital", "equipment"]) {
  test(`submits_${product}_and_staff_reads_same_application`, async ({
    page,
    browser,
  }) => {
    if (product === "equipment")
      await page.setViewportSize({ width: 390, height: 844 });
    await login(page);
    const id = await draft(page, product);
    await upload(page);
    if (product === "equipment") await upload(page, "Счёт на оборудование");
    await confirm(page);
    const staffContext = await browser.newContext();
    const staff = await staffContext.newPage();
    await login(staff, "staff@example.test");
    if (process.env.SCREENSHOT_DIR)
      await page.screenshot({
        path: `${process.env.SCREENSHOT_DIR}/submission-${product}.png`,
        fullPage: true,
      });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page
      .getByRole("button", { name: "Отправить заявку", exact: true })
      .click();
    await expect(page.locator(".page-heading .status")).toHaveText(
      "Отправлена",
    );
    await expect(
      page.getByRole("link", { name: "Редактировать", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByText("Заявка отправлена", { exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(page.locator(".page-heading .status")).toHaveText(
      "Отправлена",
    );
    const download = await page.request.get(
      (await page
        .getByRole("link", { name: "Скачать report.png" })
        .first()
        .getAttribute("href")) as string,
    );
    expect(download.status()).toBe(200);
    expect(await download.body()).toEqual(png);
    await page.goto(`/applications/${id}/edit`);
    await expect(
      page.getByRole("heading", { name: "Редактирование недоступно" }),
    ).toBeVisible();
    await staff
      .getByRole("link")
      .filter({ hasText: id.slice(0, 8) })
      .click();
    await expect(staff).toHaveURL(new RegExp(`/staff/applications/${id}$`));
    await expect(staff.locator(".page-heading .status")).toHaveText(
      "Отправлена",
    );
    await expect(
      staff.getByRole("button", { name: /Загрузить|Удалить|Отправить/ }),
    ).toHaveCount(0);
    await staffContext.close();
  });
}
test("incomplete_application_displays_errors_and_document_can_be_deleted", async ({
  page,
}) => {
  await login(page);
  const id = await draft(page, "working_capital", false);
  await page
    .getByRole("button", { name: "Отправить заявку", exact: true })
    .click();
  await expect(page.locator(".submission-errors")).toBeVisible();
  expect(
    (await (await page.request.get(`/api/v1/applications/${id}`)).json())
      .status,
  ).toBe("draft");
  await upload(page);
  await page.getByRole("button", { name: "Удалить report.png" }).click();
  await expect(
    page.getByRole("link", { name: "Скачать report.png" }),
  ).toHaveCount(0);
});
test("lost_submit_response_reuses_key_and_body", async ({ page }) => {
  await login(page);
  const id = await draft(page);
  await upload(page);
  await confirm(page);
  const commands: { key: string | undefined; body: string | null }[] = [];
  let intercepted = false;
  await page.route(`**/api/v1/applications/${id}/submit`, async (route) => {
    commands.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postData(),
    });
    if (!intercepted) {
      intercepted = true;
      const response = await route.fetch();
      expect(response.status()).toBe(202);
      await route.abort("failed");
    } else await route.continue();
  });
  // На время повтора подавляем опрос: результат отправки проверяет повтор команды.
  await page.route(`**/api/v1/applications/${id}`, async (route) => {
    if (intercepted) await route.abort("failed");
    else await route.continue();
  });
  await page
    .getByRole("button", { name: "Отправить заявку", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Повторить отправку" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Повторить отправку" }).click();
  await expect(page.locator(".page-heading .status")).toHaveText("Отправлена");
  expect(commands).toHaveLength(2);
  expect(commands[0].key).toMatch(/^[a-f0-9-]{36}$/);
  expect(commands[1]).toEqual(commands[0]);
  const history = await (
    await page.request.get(`/api/v1/applications/${id}/history`)
  ).json();
  expect(
    history.items.filter(
      (event: { event_type: string }) =>
        event.event_type === "application_submitted",
    ),
  ).toHaveLength(1);
});
test("upload_rejects_changed_account_and_other_company_cannot_download", async ({
  page,
  context,
  browser,
}) => {
  await login(page);
  const id = await draft(page);
  await upload(page);
  const fileUrl = await page
    .getByRole("link", { name: "Скачать report.png" })
    .getAttribute("href");
  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  await login(other, "client2@example.test");
  expect((await other.request.get(fileUrl!)).status()).toBe(404);
  await otherContext.close();
  const tab = await context.newPage();
  await tab.goto("/applications");
  await tab.getByRole("button", { name: "Выйти" }).click();
  await expect(tab).toHaveURL(/\/login$/);
  await login(tab, "client2@example.test");
  await page
    .getByLabel("Файл: Финансовая отчётность", { exact: true })
    .setInputFiles({ name: "private.png", mimeType: "image/png", buffer: png });
  await page
    .getByRole("button", { name: "Загрузить: Финансовая отчётность" })
    .click();
  await expect(page).toHaveURL(/\/login$/);
  await tab.close();
});

test("equipment_needs_invoice_and_open_card_polls_submission", async ({
  page,
}) => {
  await login(page);
  const id = await draft(page, "equipment");
  await upload(page);
  await confirm(page);
  await page
    .getByRole("button", { name: "Отправить заявку", exact: true })
    .click();
  await expect(page.locator(".submission-errors")).toContainText("Документы");
  await upload(page, "Счёт на оборудование");
  const current = await (
    await page.request.get(`/api/v1/applications/${id}`)
  ).json();
  const token = (await (await page.request.get("/api/v1/auth/csrf")).json())
    .csrf_token;
  const policy = await (
    await page.request.get("/api/v1/submission-policy")
  ).json();
  const result = await page.request.post(`/api/v1/applications/${id}/submit`, {
    headers: { "X-CSRF-Token": token, "Idempotency-Key": crypto.randomUUID() },
    data: {
      expected_version: current.version,
      data_confirmed: true,
      bki_consent: true,
      consent_version: policy.consent_version,
    },
  });
  expect(result.status()).toBe(202);
  await expect(page.locator(".page-heading .status")).toHaveText("Отправлена", {
    timeout: 8000,
  });
  await expect(
    page.getByRole("link", { name: "Редактировать", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Заявка отправлена", { exact: true }),
  ).toBeVisible();
});

test("stale_editor_locks_after_reloading_submitted_application", async ({
  page,
}) => {
  await login(page);
  const id = await draft(page);
  await upload(page);
  await page.getByRole("link", { name: "Редактировать", exact: true }).click();
  await page
    .getByLabel("Цель финансирования")
    .fill("Несохранённое изменение после отправки");
  const current = await (
    await page.request.get(`/api/v1/applications/${id}`)
  ).json();
  const token = (await (await page.request.get("/api/v1/auth/csrf")).json())
    .csrf_token;
  const policy = await (
    await page.request.get("/api/v1/submission-policy")
  ).json();
  const result = await page.request.post(`/api/v1/applications/${id}/submit`, {
    headers: { "X-CSRF-Token": token, "Idempotency-Key": crypto.randomUUID() },
    data: {
      expected_version: current.version,
      data_confirmed: true,
      bki_consent: true,
      consent_version: policy.consent_version,
    },
  });
  expect(result.status()).toBe(202);
  await page.getByRole("button", { name: "Сохранить черновик" }).click();
  await expect(page.getByLabel("Цель финансирования")).toHaveValue(
    "Несохранённое изменение после отправки",
  );
  await page
    .getByRole("button", { name: "Загрузить новую версию", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Редактирование недоступно" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Сохранить черновик" }),
  ).toHaveCount(0);
});
